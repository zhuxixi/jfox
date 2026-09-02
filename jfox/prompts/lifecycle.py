"""candidate 直接 promote/reject 时同步 prompt judgment 记账。

candidate 笔记带 source_prompts（#399 新溯源字段）时，用户绕过 `jfox prompts`
直接 `jfox candidates promote/reject` 也能让对应 judgment 的 disposition 保持一致。
旧 candidate（无 source_prompts）完全不受影响。
"""

import logging
from typing import Optional

from .store import PromptStore

logger = logging.getLogger(__name__)


def _current_kb_name() -> str:
    from ..config import get_config

    cfg = get_config()
    return cfg.kb_name if hasattr(cfg, "kb_name") else cfg.name


def on_post_promote(
    note_id: str,
    note_type: str,
    source_prompts: Optional[list] = None,
    kb_name: Optional[str] = None,
    store: Optional[PromptStore] = None,
) -> None:
    """candidate promote 后：对应 judgment disposition → promoted。"""
    _sync_disposition(note_id, "promoted", source_prompts, kb_name, store)


def on_post_reject(
    note_id: str,
    note_type: str,
    source_prompts: Optional[list] = None,
    kb_name: Optional[str] = None,
    store: Optional[PromptStore] = None,
) -> None:
    """candidate reject 后：对应 judgment disposition → rejected。"""
    _sync_disposition(note_id, "rejected", source_prompts, kb_name, store)


def _sync_disposition(
    note_id: str,
    disposition: str,
    source_prompts: Optional[list],
    kb_name: Optional[str],
    store: Optional[PromptStore],
) -> None:
    if not source_prompts:
        return  # 旧 candidate 无溯源 → 不处理
    store = store or PromptStore()
    kb = kb_name or _current_kb_name()
    for pid in source_prompts:
        j = store.get_judgment(kb, pid)
        if j is None:
            continue
        if j.get("candidate_note_id") != note_id:
            continue  # judgment 指向别的 candidate，不动
        if j["disposition"] != "pending":
            continue  # 已有人工处置，不覆盖
        if not store.update_disposition(kb, pid, disposition):
            logger.warning("lifecycle sync: 更新 disposition 失败 kb=%s prompt=%s", kb, pid)


def register_hooks() -> None:
    """注册到 note 生命周期广播（幂等）。"""
    from ..note import register_lifecycle_hook

    register_lifecycle_hook("post_promote", _on_post_promote_dispatch)
    register_lifecycle_hook("post_reject", _on_post_reject_dispatch)


def _on_post_promote_dispatch(note_id: str, note_type=None, **kw) -> None:
    """广播入口：从 note 对象取 source_prompts（广播 payload 不含该字段时加载）。"""
    source_prompts = kw.get("source_prompts")
    if source_prompts is None:
        source_prompts = _load_source_prompts(note_id)
    on_post_promote(
        note_id=note_id,
        note_type=note_type or "candidate",
        source_prompts=source_prompts,
        kb_name=kw.get("kb_name"),
    )


def _on_post_reject_dispatch(note_id: str, note_type=None, **kw) -> None:
    source_prompts = kw.get("source_prompts")
    if source_prompts is None:
        source_prompts = _load_source_prompts(note_id)
    on_post_reject(
        note_id=note_id,
        note_type=note_type or "candidate",
        source_prompts=source_prompts,
        kb_name=kw.get("kb_name"),
    )


def _load_source_prompts(note_id: str) -> list:
    try:
        from ..note import load_note_by_id

        n = load_note_by_id(note_id)
        return list(n.source_prompts) if n and n.source_prompts else []
    except Exception:
        return []


__all__ = ["on_post_promote", "on_post_reject", "register_hooks"]
