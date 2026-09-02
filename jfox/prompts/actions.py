"""prompt 人工动作：promote/unresolved/resolve/ignore/retry 的前置条件与记账。

设计原则（spec D8/D10/D14/D18）：
- 每个动作只做"前置条件检查 → 核心操作 → 记账"，不做自动 dedup/merge；
- unresolved 写入需用户显式命令（本模块只在被调用时写）；
- --force --reason 允许覆盖分类建议，留痕 manual_override/manual_reason；
- 核心操作失败时 disposition 不记账（可重试）。
"""

import logging
import re
import threading
from typing import Optional

from .store import PromptStore

logger = logging.getLogger(__name__)

UNRESOLVED_NOTE_TITLE = "JFox 待解决问题清单"
UNRESOLVED_NOTE_TAG = "unresolved-problems"

_MARKER_START = "jfox:unresolved:{pid}:start"
_MARKER_END = "jfox:unresolved:{pid}:end"

# per-KB 文件锁（写 unresolved 清单期间独占）
_note_locks: dict = {}
_note_locks_guard = threading.Lock()


def _kb_lock(kb_name: str) -> threading.Lock:
    with _note_locks_guard:
        if kb_name not in _note_locks:
            _note_locks[kb_name] = threading.Lock()
        return _note_locks[kb_name]


# ---------------------------------------------------------------------------
# candidate 生命周期操作包装（便于测试 mock）
# ---------------------------------------------------------------------------


def _promote_candidate(note_id: str) -> bool:
    from ..note import promote_note

    return promote_note(note_id)


def _reject_candidate(note_id: str, reason: Optional[str] = None) -> bool:
    from ..note import reject_note

    return reject_note(note_id, reason)


def _get_pending_judgment(store: PromptStore, kb_name: str, prompt_id: int) -> Optional[dict]:
    """取 succeeded/pending 的 judgment，否则 None。"""
    j = store.get_judgment(kb_name, prompt_id)
    if j is None:
        return None
    if j["judgment_state"] != "succeeded" or j["disposition"] != "pending":
        return None
    return j


# ---------------------------------------------------------------------------
# 动作实现
# ---------------------------------------------------------------------------


def promote_prompt(kb_name: str, prompt_id: int, store: Optional[PromptStore] = None) -> bool:
    """promote candidate：仅 new/pending 且有 candidate。"""
    store = store or PromptStore()
    j = _get_pending_judgment(store, kb_name, prompt_id)
    if j is None:
        logger.warning("promote_prompt: prompt %s 无 pending judgment", prompt_id)
        return False
    if j["classification"] != "new":
        logger.warning("promote_prompt: classification=%s 非 new，拒绝", j["classification"])
        return False
    candidate_id = j.get("candidate_note_id")
    if not candidate_id:
        logger.warning("promote_prompt: 无 candidate_note_id，拒绝")
        return False

    if not _promote_candidate(candidate_id):
        logger.warning("promote_prompt: promote_note(%s) 失败", candidate_id)
        return False

    ok = store.update_disposition(kb_name, prompt_id, "promoted")
    if not ok:
        logger.error("promote_prompt: 记账失败（prompt %s）", prompt_id)
    return ok


def unresolved_prompt(
    kb_name: str,
    prompt_id: int,
    store: Optional[PromptStore] = None,
    force: bool = False,
    reason: Optional[str] = None,
) -> bool:
    """标记 unresolved：仅 repeated/pending（force 可覆盖分类）。"""
    store = store or PromptStore()
    j = _get_pending_judgment(store, kb_name, prompt_id)
    if j is None:
        logger.warning("unresolved_prompt: prompt %s 无 pending judgment", prompt_id)
        return False

    if j["classification"] != "repeated":
        if not force:
            logger.warning(
                "unresolved_prompt: classification=%s 非 repeated，拒绝（--force 可覆盖）",
                j["classification"],
            )
            return False
        if not reason:
            logger.warning("unresolved_prompt: --force 必须提供 --reason")
            return False

    # 先写聚合笔记（失败则整体回滚）
    try:
        _update_unresolved_note(kb_name, prompt_id, store)
    except Exception as e:
        logger.exception("unresolved_prompt: 更新清单笔记失败: %s", e)
        return False

    store.upsert_unresolved(kb_name, prompt_id, note_id="")
    ok = store.update_disposition(
        kb_name,
        prompt_id,
        "unresolved",
        manual_override=bool(force),
        manual_reason=reason,
    )
    return ok


def resolve_unresolved_prompt(
    kb_name: str,
    prompt_id: int,
    reason: Optional[str] = None,
    store: Optional[PromptStore] = None,
) -> bool:
    """解决 unresolved：移除清单标记 + 索引 resolved + disposition=resolved。"""
    store = store or PromptStore()
    # 必须已有 active unresolved
    active = [i for i in store.list_unresolved(kb_name) if i["prompt_id"] == prompt_id]
    if not active:
        logger.warning("resolve_unresolved_prompt: prompt %s 无 active unresolved", prompt_id)
        return False

    if not store.resolve_unresolved(kb_name, prompt_id, reason):
        return False

    try:
        _remove_unresolved_marker(kb_name, prompt_id, reason, store)
    except Exception as e:
        logger.exception("resolve_unresolved_prompt: 移除标记失败: %s", e)
        # 索引已 resolved，标记残留由 reconcile 清理
    return store.update_disposition(kb_name, prompt_id, "resolved")


def ignore_prompt(
    kb_name: str,
    prompt_id: int,
    store: Optional[PromptStore] = None,
    reject_candidate: bool = False,
) -> bool:
    """忽略：仅 succeeded/pending；有 candidate 时必须显式 --reject-candidate。"""
    store = store or PromptStore()
    j = _get_pending_judgment(store, kb_name, prompt_id)
    if j is None:
        logger.warning("ignore_prompt: prompt %s 无 pending judgment", prompt_id)
        return False

    candidate_id = j.get("candidate_note_id")
    if candidate_id:
        if not reject_candidate:
            logger.warning(
                "ignore_prompt: 存在 candidate %s，需 --reject-candidate 才能忽略",
                candidate_id,
            )
            return False
        if not _reject_candidate(candidate_id, reason="ignored via prompts CLI"):
            logger.warning("ignore_prompt: reject candidate 失败")
            return False

    return store.update_disposition(kb_name, prompt_id, "ignored")


def retry_prompt(kb_name: str, prompt_id: int, store: Optional[PromptStore] = None) -> bool:
    """重试：仅 failed judgment 或 needs_review 分类可重置。"""
    store = store or PromptStore()
    j = store.get_judgment(kb_name, prompt_id)
    if j is None:
        logger.warning("retry_prompt: prompt %s 无 judgment", prompt_id)
        return False

    if j["judgment_state"] == "failed":
        # 删除 judgment 行，让下次 judge 重新选择
        return store.reset_judgment(kb_name, prompt_id)
    if (
        j["judgment_state"] == "succeeded"
        and j["classification"] == "needs_review"
        and j["disposition"] == "pending"
    ):
        return store.reset_judgment(kb_name, prompt_id)

    logger.warning(
        "retry_prompt: state=%s classification=%s 不允许 retry",
        j["judgment_state"],
        j.get("classification"),
    )
    return False


# ---------------------------------------------------------------------------
# unresolved 聚合笔记
# ---------------------------------------------------------------------------


def _find_unresolved_note() -> Optional[object]:
    """在当前 KB 中查找唯一的清单笔记。"""
    from ..note import list_notes

    for n in list_notes():
        if n.title == UNRESOLVED_NOTE_TITLE and UNRESOLVED_NOTE_TAG in (n.tags or []):
            return n
    return None


def _create_unresolved_note():
    """创建清单笔记（permanent + unresolved-problems 标签）。"""
    from datetime import datetime

    from ..models import Note, NoteType
    from ..note import save_note

    now = datetime.now()
    note = Note(
        id=now.strftime("%Y%m%d%H%M%S") + f"{now.microsecond // 1000:03d}",
        title=UNRESOLVED_NOTE_TITLE,
        content=(
            "# JFox 待解决问题清单\n\n"
            "由 `jfox prompts unresolved` 维护的机器聚合笔记。\n"
            "每条问题以 `jfox:unresolved:<prompt_id>` 标记包裹，请勿手工编辑标记块。\n"
        ),
        type=NoteType.PERMANENT,
        created=now,
        updated=now,
        tags=[UNRESOLVED_NOTE_TAG],
    )
    if not save_note(note, add_to_index=True):
        raise RuntimeError("创建 unresolved 清单笔记失败")
    return note


def _escape_preview(text: str, max_len: int = 80) -> str:
    """转义用户文本预览：去 Markdown 语义 + 截断。"""
    s = text.replace("[", "［").replace("]", "］").replace("\n", " ")
    if len(s) > max_len:
        s = s[: max_len - 1] + "…"
    return s


def _update_unresolved_note(kb_name: str, prompt_id: int, store: Optional[PromptStore]) -> str:
    """在清单笔记中追加/更新该 prompt 的标记块，返回 note id。"""
    with _kb_lock(kb_name):
        note = _find_unresolved_note() or _create_unresolved_note()

        prompt_text = ""
        if store is not None:
            p = store.get_prompt(prompt_id)
            if p:
                prompt_text = p.get("prompt", "")

        start = f"<!-- {_MARKER_START.format(pid=prompt_id)} -->"
        end = f"<!-- {_MARKER_END.format(pid=prompt_id)} -->"
        block = (
            f"\n{start}\n"
            f"- **prompt #{prompt_id}**: {_escape_preview(prompt_text)}\n"
            f"- 状态: 未解决\n"
            f"{end}\n"
        )

        if start in note.content:
            # 已有标记块 → 替换
            pattern = re.compile(re.escape(start) + r".*?" + re.escape(end), re.DOTALL)
            note.content = pattern.sub(block.strip("\n"), note.content)
        else:
            note.content = note.content.rstrip("\n") + "\n" + block

        from ..note import update_note

        if not update_note(note):
            raise RuntimeError("更新 unresolved 清单笔记失败")
        return note.id


def _remove_unresolved_marker(
    kb_name: str,
    prompt_id: int,
    reason: Optional[str],
    store: Optional[PromptStore],
) -> None:
    """从清单笔记移除该 prompt 的标记块。"""
    with _kb_lock(kb_name):
        note = _find_unresolved_note()
        if note is None:
            return
        start = f"<!-- {_MARKER_START.format(pid=prompt_id)} -->"
        end = f"<!-- {_MARKER_END.format(pid=prompt_id)} -->"
        if start not in note.content:
            return
        pattern = re.compile(
            re.escape(start) + r"[^\n]*\n.*?" + re.escape(end) + r"[^\n]*\n?",
            re.DOTALL,
        )
        note.content = pattern.sub("", note.content).rstrip("\n") + "\n"
        from ..note import update_note

        if not update_note(note):
            raise RuntimeError("移除 unresolved 标记失败")


__all__ = [
    "promote_prompt",
    "unresolved_prompt",
    "resolve_unresolved_prompt",
    "ignore_prompt",
    "retry_prompt",
    "UNRESOLVED_NOTE_TITLE",
    "UNRESOLVED_NOTE_TAG",
]
