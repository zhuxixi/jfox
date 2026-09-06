"""MOC 写盘与 backlinks 回填测试（进程内，mock embedding）。"""

from __future__ import annotations

import numpy as np
import pytest

from jfox.moc.cluster import ClusterMember, ClusterSummary
from jfox.moc.draft import build_moc_draft
from jfox.moc.generate import (
    MOC_TAG,
    backfill_moc_backlinks,
    remove_moc_backlinks,
    verify_members_on_disk,
    write_moc,
)
from jfox.models import NoteType
from jfox.note import list_notes, load_note_by_id

MEMBER_IDS = ["20260820000001", "20260820000002"]


class _MockBackend:
    """返回随机向量的 mock embedding 后端（避免加载真实模型）。"""

    def __init__(self) -> None:
        self.dimension = 384

    def encode(self, texts, **kwargs):
        if isinstance(texts, str):
            texts = [texts]
        return np.random.rand(len(texts), self.dimension).astype("float32")

    def encode_single(self, text: str) -> np.ndarray:
        return np.random.rand(self.dimension).astype("float32")


@pytest.fixture
def seeded_kb(tmp_path, monkeypatch):
    """初始化最小 KB：2 条 permanent + mock embedding 后端。"""
    from datetime import datetime as dt

    from jfox import config as config_module
    from jfox.config import ZKConfig
    from jfox.models import Note
    from jfox.note import _atomic_write
    from jfox.note_index import get_note_index

    cfg = ZKConfig(base_dir=tmp_path)
    cfg.ensure_dirs()
    for nid, title, tag in [
        ("20260820000001", "Zima One", "zima"),
        ("20260820000002", "Zima Two", "zima"),
    ]:
        note = Note(
            id=nid,
            title=title,
            content=f"content of {title}",
            type=NoteType.PERMANENT,
            created=dt(2026, 8, 20, 0, 0, 0),
            updated=dt(2026, 8, 20, 0, 0, 0),
            tags=[tag],
        )
        slug = title.lower().replace(" ", "-")
        note.set_filepath(cfg.notes_dir / "permanent" / f"{nid}-{slug}.md")
        _atomic_write(note.filepath, note.to_markdown())

    # 把全局 config 单例原地指向临时 KB（与 use_kb 一致；import-time 绑定可见）。
    # 不能用 monkeypatch.setattr("jfox.config.config", cfg)：note.py/vector_store.py
    # 在 import 时 `from .config import config` 绑定了原对象，替换对象不会传播。
    singleton = config_module.config
    monkeypatch.setattr(singleton, "base_dir", tmp_path)
    monkeypatch.setattr(singleton, "notes_dir", cfg.notes_dir)
    monkeypatch.setattr(singleton, "zk_dir", cfg.zk_dir)
    monkeypatch.setattr(singleton, "chroma_dir", cfg.chroma_dir)
    config_module._reset_singletons()

    # mock embedding 后端（save_note → vector_store.add_note → backend.encode_single）
    monkeypatch.setattr("jfox.embedding_backend.get_backend", lambda: _MockBackend())

    get_note_index(cfg)

    yield cfg

    config_module._reset_singletons()


def _draft(seeded_kb):
    members = [
        ClusterMember(id="20260820000001", title="Zima One", link_degree=1, mean_similarity=0.9),
        ClusterMember(id="20260820000002", title="Zima Two", link_degree=1, mean_similarity=0.8),
    ]
    cluster = ClusterSummary(size=2, members=members, hub=members[0])
    return build_moc_draft(
        cluster, {"20260820000001": ["zima"], "20260820000002": ["zima"]}, max_size=50
    )


def test_write_moc_creates_structure_note_with_links(seeded_kb):
    draft = _draft(seeded_kb)
    moc = write_moc(draft)

    assert moc.type == NoteType.STRUCTURE
    assert moc.tags == [MOC_TAG]
    assert moc.links == ["20260820000001", "20260820000002"]
    assert moc.filepath.exists()

    structure_notes = list_notes(note_type=NoteType.STRUCTURE, cfg=seeded_kb)
    assert len(structure_notes) == 1


def test_write_moc_backfills_member_backlinks(seeded_kb):
    draft = _draft(seeded_kb)
    moc = write_moc(draft)

    for mid in MEMBER_IDS:
        member = load_note_by_id(mid)
        assert moc.id in member.backlinks


def test_remove_moc_backlinks_strips_moc_id(seeded_kb):
    draft = _draft(seeded_kb)
    moc = write_moc(draft)
    remove_moc_backlinks(moc.id, MEMBER_IDS)

    for mid in MEMBER_IDS:
        member = load_note_by_id(mid)
        assert moc.id not in member.backlinks


def test_backfill_returns_changed_ids(seeded_kb):
    moc = write_moc(_draft(seeded_kb))
    remove_moc_backlinks(moc.id, MEMBER_IDS, cfg=seeded_kb)

    result = backfill_moc_backlinks(moc, MEMBER_IDS, cfg=seeded_kb)

    assert result.changed_ids == tuple(MEMBER_IDS)
    assert result.failed_ids == ()


def test_remove_returns_failed_ids_and_continues(seeded_kb, monkeypatch):
    moc = write_moc(_draft(seeded_kb))
    failing_id = MEMBER_IDS[1]
    from jfox import note as note_module

    original_atomic_write = note_module._atomic_write

    def fail_one(path, content):
        if failing_id in str(path):
            raise OSError("test write failure")
        return original_atomic_write(path, content)

    monkeypatch.setattr(note_module, "_atomic_write", fail_one)
    result = remove_moc_backlinks(moc.id, MEMBER_IDS, cfg=seeded_kb)

    assert MEMBER_IDS[0] in result.changed_ids
    assert failing_id in result.failed_ids


def test_backfill_skips_missing_targets(seeded_kb):
    moc = write_moc(_draft(seeded_kb))

    result = backfill_moc_backlinks(moc, ["99999999999999"], cfg=seeded_kb)

    assert result.changed_ids == ()
    assert result.failed_ids == ()


def test_backfill_skips_already_clean_backlinks(seeded_kb):
    moc = write_moc(_draft(seeded_kb))

    result = backfill_moc_backlinks(moc, MEMBER_IDS, cfg=seeded_kb)

    assert result.changed_ids == ()
    assert result.failed_ids == ()


def test_remove_skips_already_clean_backlinks(seeded_kb):
    moc = write_moc(_draft(seeded_kb))
    remove_moc_backlinks(moc.id, MEMBER_IDS, cfg=seeded_kb)

    result = remove_moc_backlinks(moc.id, MEMBER_IDS, cfg=seeded_kb)

    assert result.changed_ids == ()
    assert result.failed_ids == ()


def test_write_moc_raises_when_save_fails(seeded_kb, monkeypatch):
    """save_note 写盘失败时 write_moc 应 raise，不回填 backlinks。"""
    # save_note 在 write_moc 函数内部 lazy import（from ..note import save_note），
    # 因此 patch jfox.note.save_note 才能拦截。
    draft = _draft(seeded_kb)
    monkeypatch.setattr("jfox.note.save_note", lambda note: False)
    with pytest.raises(OSError, match="Failed to save MOC note"):
        write_moc(draft)

    # 确认没有回填 backlinks（成员 backlinks 不含 MOC id）
    structure_notes = list_notes(note_type=NoteType.STRUCTURE, cfg=seeded_kb)
    assert len(structure_notes) == 0


def test_verify_members_on_disk_returns_existing_and_missing_warnings(seeded_kb):
    """存在的成员进 existing_ids；不存在的成员进 missing_warnings。"""
    ids = ["20260820000001", "20260820000002", "99999999999999"]
    existing, warnings = verify_members_on_disk(ids)

    assert existing == {"20260820000001", "20260820000002"}
    assert len(warnings) == 1
    assert "skipped ghost member 99999999999999" in warnings[0]


def test_verify_members_on_disk_treats_deleted_file_as_missing(seeded_kb, monkeypatch):
    """文件已被删除但 index 残留：load_note_by_id 可能返回 note 但 filepath 不存在 → missing。"""
    import os

    member_file = seeded_kb.notes_dir / "permanent" / "20260820000001-zima-one.md"
    os.unlink(member_file)

    existing, warnings = verify_members_on_disk(["20260820000001"])
    assert "20260820000001" not in existing
    assert any("20260820000001" in w for w in warnings)
