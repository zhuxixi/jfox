"""MOC 写盘与 backlinks 回填测试（进程内，mock embedding）。"""

from __future__ import annotations

import numpy as np
import pytest

from jfox.moc.cluster import ClusterMember, ClusterSummary
from jfox.moc.draft import build_moc_draft
from jfox.moc.generate import MOC_TAG, remove_moc_backlinks, write_moc
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
