"""candidate 数据访问层：list/show 的过滤与组装（从 gem_synth/cli.py 迁移）。"""

from typing import Any, Dict, List, Optional

from ..models import Note, NoteType
from ..note import list_notes, load_note_by_id


def list_candidates(
    status: str = "pending",
    min_confidence: float = 0.0,
    limit: int = 50,
) -> List[Dict[str, Any]]:
    """列出 candidate 行（内存过滤 status/confidence，与迁移前行为一致）。

    - rejected 已 archived，仅 status in (rejected, all) 时包含；
    - limit 非正（0/负）回退默认 50。
    """
    if limit < 1:
        limit = 50
    notes = list_notes(
        note_type=NoteType.CANDIDATE,
        limit=limit * 3,
        include_archived=status in ("rejected", "all"),
    )
    rows: List[Dict[str, Any]] = []
    for n in notes:
        nstatus = getattr(n, "status", None) or ""
        if status != "all" and nstatus != status:
            continue
        conf = getattr(n, "confidence", None) or 0.0
        if conf < min_confidence:
            continue
        rows.append(
            {
                "id": n.id,
                "title": n.title,
                "confidence": conf,
                "knowledge_type": getattr(n, "knowledge_type", "") or "",
                "status": nstatus,
                "gem_level": getattr(n, "gem_level", "") or "",
            }
        )
        if len(rows) >= limit:
            break
    return rows


def get_candidate(note_id: str) -> Optional[Note]:
    """加载 candidate 笔记（任何 note 类型都会返回，由调用方校验）。"""
    return load_note_by_id(note_id)


__all__ = ["list_candidates", "get_candidate"]
