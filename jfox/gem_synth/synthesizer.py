"""合成编排：单个锚点 → transcript 上下文 → grounding → LLM → candidate 笔记 + 记账。

单个锚点的完整 L3 合成流水线。daemon 循环（Phase F）会对每个未处理锚点调用
synthesize_anchor；本模块只负责"一个锚点 -> 一条 candidate"的单步编排，
不涉及循环、限速、调度。
"""

import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from ..global_config import GemSynthesisConfig
from ..models import GemLevel, Note, NoteType
from ..note import save_note
from .dedup import _resolve_kb_name, dedup_check, upsert_dedup
from .grounding import fetch_grounding
from .llm import synthesize_with_llm
from .transcript import extract_turn_around

logger = logging.getLogger(__name__)


def _safe_float(value, default: float = 0.0) -> float:
    """安全转 float：LLM 可能返回 "high" 等非数值字符串，直接 float() 会抛 ValueError。"""
    try:
        return float(value) if value is not None else default
    except (TypeError, ValueError):
        return default


def _coerce_grounded_by(value) -> list:
    """grounded_by 类型安全：LLM 偶发返回字符串（如 "笔记A"），list() 会拆成字符。
    统一成 list；非 list/非空 字符串包成单元素列表。"""
    if isinstance(value, list):
        return value
    if value:
        return [value]
    return []


# content 开头冗余 H1 的正则：串首 \A + 可能有前导空白行 + `# 文本` + 紧随换行（含空行）。
# 复用 Note.from_markdown（models.py:179 `re.sub(r"^# .+\n+", ..., count=1)`）剥首个
# H1 的语义，保持合成写入与解析读写的对称。
_LEADING_H1_RE = re.compile(r"\A\s*# .+\n+")


def _strip_leading_h1(content: str) -> str:
    """剥掉 content 开头首个冗余 H1 行，消除 candidate 双 H1（#320）。

    title 已单独存 frontmatter、to_markdown 会前置 `# title`，故 LLM content 若以
    `# 标题` 开头即为冗余（双 H1 根因）。仅剥**首个** leading H1；正文内的 H1 分节
    （3+H1 场景，LLM 误用 H1 当分节）超出 #320 范围、留给 #319。

    保护：剥后若 content 为空（整段只是一个 H1），回退原值，避免产出空正文笔记。
    """
    stripped = _LEADING_H1_RE.sub("", content, count=1)
    return stripped if stripped.strip() else content


def _save_candidate_note(llm_result: Dict[str, Any], anchor: Dict[str, Any]) -> Optional[str]:
    """把 LLM 结果存成 candidate 笔记，返回 note id。失败返回 None。

    笔记落盘路径：<kb>/notes/candidate/<id>-<slug>.md（由 Note.filepath 根据
    NoteType.CANDIDATE + 全局 config.notes_dir 推导）。KB 上下文由调用方
    （daemon loop 外层 use_kb）提供，本函数不再内部 use_kb。

    整个构造 + 落盘都包在 try 内：anchor 字段缺失（KeyError）或 Note 构造异常
    都转成"跳过该锚点"（返回 None），不抛穿到循环导致整轮失败。
    """
    try:
        now = datetime.now()
        # 时间戳 + 微秒，避免同秒碰撞（candidate 不进 note_index，14 位约定不适用）
        note_id = now.strftime("%Y%m%d%H%M%S") + "-" + now.strftime("%f")
        title = llm_result.get("title") or "未命名候选宝石"
        # 剥掉 LLM content 开头冗余 H1（title 已在 frontmatter、to_markdown 会前置），
        # 消除 candidate 双 H1（#320）。dedup 仍用 synthesize_anchor 里的原始 content，
        # 不受影响。
        content = _strip_leading_h1(llm_result.get("content") or "")

        # 追加来源 / 基准 / 置信度元信息（便于 L5 审阅与溯源）
        # anchor['fragment_id']/['timestamp']/['session_id'] 在 try 内访问：
        # 缺键时 KeyError 被捕获 → 返回 None 跳过该锚点，而非抛穿循环
        source_section = (
            f"\n\n## 来源\n- 碎片 #{anchor['fragment_id']} @ {anchor['timestamp']}\n"
            f"- session `{anchor['session_id']}`\n"
        )
        grounding_section = ""
        grounded_by = _coerce_grounded_by(llm_result.get("grounded_by"))
        if grounded_by:
            links = ", ".join(f"[[{g}]]" for g in grounded_by)
            grounding_section = f"\n## 参考的永久笔记\n{links}\n"
        conf_section = f"\n## 置信度\n{llm_result.get('confidence', '?')}\n"

        # Note() 构造也在 try 内：任何字段异常（如类型/格式）都应转成"跳过"而非抛穿
        note = Note(
            id=note_id,
            title=title,
            content=content + source_section + grounding_section + conf_section,
            type=NoteType.CANDIDATE,
            created=now,
            updated=now,
            gem_level=GemLevel.FLAWED.value,
            confidence=_safe_float(llm_result.get("confidence"), 0.0),
            source_fragments=[anchor["fragment_id"]],
            grounded_by=grounded_by,
            knowledge_type=llm_result.get("knowledge_type"),
            status="pending",
        )
        _persist_note(note)
        return note_id
    except Exception as e:
        logger.exception("保存 candidate 笔记失败: %s", e)
        return None


def _persist_note(note: Note) -> None:
    """实际落盘。封装一层适配 note.py 的 save API。

    不再 use_kb(kb)：调用方（daemon loop 的 _tick_once 外层 use_kb(cfg.target_kb)）
    已切到目标 KB，内部再 use_kb 会每锚点 _reset_singletons（重载 embedding 模型）。
    add_to_index=False：避免在 daemon 进程里意外触发向量/BM25 索引（candidate 是
    待审草稿，索引可由 Phase G/H 或显式 reindex 补上）。
    """
    ok = save_note(note, add_to_index=False)
    if not ok:
        raise RuntimeError(f"save_note 返回 False（note_id={note.id}）")


def synthesize_anchor(
    anchor: Dict[str, Any],
    log,
    cfg: GemSynthesisConfig,
    stop_event: Optional[threading.Event] = None,
) -> Optional[Dict[str, Any]]:
    """合成单个锚点。成功返回 {candidate_note_id, title, confidence}，跳过/失败返回 None。

    流程：
      1. 无 transcript_path → mark_failed 记账（不重试）
      2. extract_turn_around 抽不到上下文 → mark_failed 记账（不重试）
      3. fetch_grounding 检索 permanent 基准
      4. synthesize_with_llm 调 LLM；None → mark_failed 记账（不重试）
      5. _save_candidate_note 落盘 + log.mark_processed 记账

    每条失败路径都调 log.mark_failed，使 daemon 过夜跑不会对坏锚点无限重试。
    stop_event 透传给 synthesize_with_llm → _invoke_claude，使 daemon shutdown /
    任务中断能在 claude 调用进行中触发（而非等满 timeout）。
    """
    transcript_path = anchor.get("transcript_path")
    if not transcript_path:
        logger.info("锚点 #%s 无 transcript_path，mark_failed", anchor["fragment_id"])
        log.mark_failed(anchor["fragment_id"], "no transcript_path")
        return None

    turn = extract_turn_around(Path(transcript_path), anchor.get("content") or "")
    if not turn.strip():
        logger.info("锚点 #%s 提取不到上下文，mark_failed", anchor["fragment_id"])
        log.mark_failed(anchor["fragment_id"], "empty transcript context")
        return None

    grounding = fetch_grounding(anchor.get("content") or "", top_k=cfg.grounding_top_k)

    llm_result = synthesize_with_llm(
        turn_context=turn, grounding=grounding, cfg=cfg, stop_event=stop_event
    )
    if llm_result is None:
        logger.info(
            "锚点 #%s LLM 合成失败/无效，mark_failed（不重试）",
            anchor["fragment_id"],
        )
        log.mark_failed(anchor["fragment_id"], "llm synthesis failed")
        return None

    # 存盘前去重：命中则不存盘、记 duplicate，锚点算处理完（不重试）
    # target_kb=None 表示用 default；解析成具体 KB 名（dedup_embeddings.kb 是
    # NOT NULL，且 None 会让 dedup_check 的 WHERE kb=? 匹配 0 行→永远检不到重复）
    kb_name = _resolve_kb_name(cfg.target_kb)
    if getattr(cfg, "dedup_enabled", True):
        dup_of = dedup_check(
            kb_name,
            llm_result.get("content") or "",
            threshold=getattr(cfg, "dedup_threshold", 0.88),
        )
        if dup_of:
            logger.info("锚点 #%s 命中重复（dup_of=%s），跳过存盘", anchor["fragment_id"], dup_of)
            log.mark_duplicate(anchor["fragment_id"], dup_of)
            return None

    note_id = _save_candidate_note(llm_result, anchor)
    if note_id is None:
        log.mark_failed(anchor["fragment_id"], "save candidate note failed")
        return None

    # 存盘成功 → 入 dedup 库（供后续锚点查重）；dedup 关闭时跳过
    # （spec §11：dedup_enabled=False 完全关闭回到原行为，不为每条 candidate 算 embedding 灌库）
    if getattr(cfg, "dedup_enabled", True):
        upsert_dedup(kb_name, note_id, "candidate", llm_result.get("content") or "")

    log.mark_processed(anchor_fragment_id=anchor["fragment_id"], candidate_note_id=note_id)
    return {
        "candidate_note_id": note_id,
        "title": llm_result.get("title"),
        "confidence": llm_result.get("confidence"),
    }


__all__ = ["synthesize_anchor"]
