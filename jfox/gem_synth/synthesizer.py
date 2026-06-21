"""合成编排：单个锚点 → transcript 上下文 → grounding → LLM → candidate 笔记 + 记账。

单个锚点的完整 L3 合成流水线。daemon 循环（Phase F）会对每个未处理锚点调用
synthesize_anchor；本模块只负责"一个锚点 -> 一条 candidate"的单步编排，
不涉及循环、限速、调度。
"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

from ..config import use_kb
from ..global_config import GemSynthesisConfig
from ..models import GemLevel, Note, NoteType
from ..note import save_note
from .grounding import fetch_grounding
from .llm import synthesize_with_llm
from .transcript import extract_turn_around

logger = logging.getLogger(__name__)


def _save_candidate_note(
    llm_result: Dict[str, Any], anchor: Dict[str, Any], kb: Optional[str]
) -> Optional[str]:
    """把 LLM 结果存成 candidate 笔记，返回 note id。失败返回 None。

    笔记落盘路径：<kb>/notes/candidate/<id>-<slug>.md（由 Note.filepath 根据
    NoteType.CANDIDATE + 全局 config.notes_dir 推导）。多 KB 支持通过 use_kb(kb)
    上下文切换全局 config 实现。
    """
    now = datetime.now()
    note_id = now.strftime("%Y%m%d%H%M%S")
    title = llm_result.get("title") or "未命名候选宝石"
    content = llm_result.get("content") or ""

    # 追加来源 / 基准 / 置信度元信息（便于 L5 审阅与溯源）
    source_section = (
        f"\n\n## 来源\n- 碎片 #{anchor['fragment_id']} @ {anchor['timestamp']}\n"
        f"- session `{anchor['session_id']}`\n"
    )
    grounding_section = ""
    if llm_result.get("grounded_by"):
        links = ", ".join(f"[[{g}]]" for g in llm_result["grounded_by"])
        grounding_section = f"\n## 参考的永久笔记\n{links}\n"
    conf_section = f"\n## 置信度\n{llm_result.get('confidence', '?')}\n"

    note = Note(
        id=note_id,
        title=title,
        content=content + source_section + grounding_section + conf_section,
        type=NoteType.CANDIDATE,
        created=now,
        updated=now,
        gem_level=GemLevel.FLAWED.value,
        confidence=float(llm_result.get("confidence") or 0),
        source_fragments=[anchor["fragment_id"]],
        grounded_by=list(llm_result.get("grounded_by") or []),
        knowledge_type=llm_result.get("knowledge_type"),
        status="pending",
    )
    try:
        _persist_note(note, kb)
        return note_id
    except Exception as e:
        logger.exception("保存 candidate 笔记失败: %s", e)
        return None


def _persist_note(note: Note, kb: Optional[str]) -> None:
    """实际落盘。封装一层适配 note.py 的 save API。

    note.save_note(note, add_to_index=True) 依赖全局 config.notes_dir 决定写入目录，
    且 add_to_index=True 会触发 vector_store/bm25 单例——daemon 进程内这些单例
    可能绑定到别的 KB 或未初始化。故：
      1. 用 use_kb(kb) 上下文切换全局 config，使 filepath 指向目标 KB；
      2. add_to_index=False，只落盘不建索引（candidate 是待审草稿，索引可由
         Phase G/H 或显式 reindex 补上）。
    """
    with use_kb(kb):
        # add_to_index=False：避免在 daemon 进程里意外触发向量/BM25 索引
        ok = save_note(note, add_to_index=False)
    if not ok:
        raise RuntimeError(f"save_note 返回 False（note_id={note.id}）")


def synthesize_anchor(
    anchor: Dict[str, Any], log, cfg: GemSynthesisConfig, kb: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    """合成单个锚点。成功返回 {candidate_note_id, title, confidence}，跳过/失败返回 None。

    流程：
      1. 无 transcript_path → 跳过
      2. extract_turn_around 抽不到上下文 → 跳过
      3. fetch_grounding 检索 permanent 基准
      4. synthesize_with_llm 调 LLM；None → 跳过（不记账，下轮重试）
      5. _save_candidate_note 落盘 + log.mark_processed 记账
    """
    transcript_path = anchor.get("transcript_path")
    if not transcript_path:
        logger.info("锚点 #%s 无 transcript_path，跳过", anchor["fragment_id"])
        return None

    turn = extract_turn_around(Path(transcript_path), anchor.get("content") or "")
    if not turn.strip():
        logger.info("锚点 #%s 提取不到上下文，跳过", anchor["fragment_id"])
        return None

    grounding = fetch_grounding(anchor.get("content") or "", top_k=cfg.grounding_top_k, kb=kb)

    llm_result = synthesize_with_llm(turn_context=turn, grounding=grounding, cfg=cfg)
    if llm_result is None:
        logger.info(
            "锚点 #%s LLM 合成失败/无效，跳过（不记账，下轮重试）",
            anchor["fragment_id"],
        )
        return None

    note_id = _save_candidate_note(llm_result, anchor, kb)
    if note_id is None:
        return None

    log.mark_processed(anchor_fragment_id=anchor["fragment_id"], candidate_note_id=note_id)
    return {
        "candidate_note_id": note_id,
        "title": llm_result.get("title"),
        "confidence": llm_result.get("confidence"),
    }


__all__ = ["synthesize_anchor"]
