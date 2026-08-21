"""MOC 写盘与 backlinks 回填/摘除。

写盘复用 note.create_note + note.save_note（落 structure/ 目录 + 进向量/BM25 索引）；
回填模式与 note.promote_note 的增量回填一致：单成员失败只 warning 不中断，
不对称时可用 `jfox index rebuild --backlinks` 全量重算兜底。
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Sequence

from ..models import Note, NoteType
from .draft import MocCreateDraft, render_moc_content

logger = logging.getLogger(__name__)

MOC_TAG = "moc"


def write_moc(draft: MocCreateDraft) -> Note:
    """创建 structure 类型的 MOC 笔记并回填成员 backlinks。"""
    from ..note import create_note, save_note
    from ..note_index import get_note_index

    content = render_moc_content(draft)
    member_ids = sorted({m.id for group in draft.groups for m in group.members})
    moc = create_note(
        content,
        title=draft.title,
        note_type=NoteType.STRUCTURE,
        tags=[MOC_TAG],
        links=member_ids,
    )
    # create_note 只构造对象不落盘；save_note 才写文件 + 进索引（与 CLI add 一致）。
    # 检查返回值：写盘失败时不继续回填 backlinks，避免成员笔记指向不存在的 MOC（#413 final review）。
    if not save_note(moc):
        raise OSError(f"Failed to save MOC note {moc.id}")
    # save_note 不更新 NoteIndex；补一次 update_note_meta 让 list_notes 能发现新 MOC。
    get_note_index().update_note_meta(moc)
    backfill_moc_backlinks(moc, member_ids)
    return moc


def backfill_moc_backlinks(moc_note: Note, member_ids: Sequence[str]) -> None:
    """把 MOC id 增量加进每个成员笔记的 backlinks。"""
    from ..note import _atomic_write, load_note_by_id
    from ..note_index import get_note_index

    now = datetime.now()
    index = get_note_index()
    for mid in member_ids:
        target = load_note_by_id(mid)
        if target is None or moc_note.id in target.backlinks:
            continue
        target.updated = now
        target.backlinks = sorted(set(target.backlinks + [moc_note.id]))
        try:
            _atomic_write(target.filepath, target.to_markdown())
            index.update_note_meta(target)
        except Exception as exc:  # 单成员失败不中断（与 promote 一致）
            logger.warning(f"Failed to backfill backlinks for MOC member {mid}: {exc}")


def remove_moc_backlinks(moc_id: str, member_ids: Sequence[str]) -> None:
    """把 MOC id 从成员笔记的 backlinks 摘除（update 摘除死链时用）。"""
    from ..note import _atomic_write, load_note_by_id
    from ..note_index import get_note_index

    now = datetime.now()
    index = get_note_index()
    for mid in member_ids:
        target = load_note_by_id(mid)
        if target is None or moc_id not in target.backlinks:
            continue
        target.updated = now
        target.backlinks = [b for b in target.backlinks if b != moc_id]
        try:
            _atomic_write(target.filepath, target.to_markdown())
            index.update_note_meta(target)
        except Exception as exc:
            logger.warning(f"Failed to remove MOC backlink for member {mid}: {exc}")
