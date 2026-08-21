"""MOC create/update 端到端集成测试（真实 KB 文件 + mock 诊断）。"""

from __future__ import annotations

from datetime import datetime as dt
from unittest.mock import patch

import numpy as np
import pytest

from jfox.moc.cli import _create_impl, _update_impl
from jfox.moc.cluster import (
    ClusterMember,
    ClusterSummary,
    CoverageReport,
    MocDiagnoseReport,
    OrphanSummary,
    SuggestedReport,
    ThresholdSummary,
)
from jfox.models import Note, NoteType
from jfox.note import _atomic_write, list_notes, update_note
from jfox.note_index import get_note_index


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
    """初始化最小 KB：2 条 permanent + mock embedding 后端。

    与 test_moc_generate.py 的 seeded_kb 同模式：原地修改全局 config 单例
    （note.py / vector_store.py 在 import 时绑定 config，不能替换对象只能改属性），
    再 _reset_singletons 让 get_vector_store / get_note_index 重建到临时目录。
    """
    from jfox import config as config_module
    from jfox.config import ZKConfig

    cfg = ZKConfig(base_dir=tmp_path)
    cfg.ensure_dirs()
    for nid, title in [
        ("20260820000001", "Zima One"),
        ("20260820000002", "Zima Two"),
    ]:
        note = Note(
            id=nid,
            title=title,
            content=f"content of {title}",
            type=NoteType.PERMANENT,
            created=dt(2026, 8, 20, 0, 0, 0),
            updated=dt(2026, 8, 20, 0, 0, 0),
            tags=["zima"],
        )
        slug = title.lower().replace(" ", "-")
        note.set_filepath(cfg.notes_dir / "permanent" / f"{nid}-{slug}.md")
        _atomic_write(note.filepath, note.to_markdown())

    # 原地修改单例属性（与 use_kb 一致；import-time 绑定可见）
    singleton = config_module.config
    monkeypatch.setattr(singleton, "base_dir", tmp_path)
    monkeypatch.setattr(singleton, "notes_dir", cfg.notes_dir)
    monkeypatch.setattr(singleton, "zk_dir", cfg.zk_dir)
    monkeypatch.setattr(singleton, "chroma_dir", cfg.chroma_dir)
    config_module._reset_singletons()

    # mock embedding 后端（save_note / update_note → vector_store.add_note → encode_single）
    monkeypatch.setattr("jfox.embedding_backend.get_backend", lambda: _MockBackend())

    get_note_index(cfg)

    yield cfg

    config_module._reset_singletons()


def _report(member_ids):
    """构造包含指定成员的固定诊断报告（mock diagnose 用）。"""
    members = [
        ClusterMember(id=nid, title=f"Note {nid}", link_degree=1, mean_similarity=0.9)
        for nid in member_ids
    ]
    cluster = ClusterSummary(size=len(members), members=members, hub=members[0])
    return MocDiagnoseReport(
        coverage=CoverageReport(filesystem=2, vector=2, vector_orphans=0, bm25=2),
        threshold_sweep=[ThresholdSummary(0.65, 1, len(members), 0)],
        suggest=SuggestedReport(threshold=0.65, clusters=[cluster]),
        orphans=OrphanSummary(count=0),
        warnings=[],
    )


def test_create_then_update_end_to_end(seeded_kb):
    # --- create ---
    with patch(
        "jfox.moc.cli.diagnose_moc_density",
        return_value=_report(["20260820000001", "20260820000002"]),
    ):
        payload, moc, _draft_obj, _cluster_obj = _create_impl(
            seeded_kb, 0.65, 0, 50, None, False, True
        )

    assert moc is not None
    assert moc.type == NoteType.STRUCTURE
    assert moc.filepath.exists()
    assert sorted(moc.links) == ["20260820000001", "20260820000002"]
    assert len(list_notes(note_type=NoteType.STRUCTURE, cfg=seeded_kb)) == 1

    # --- 新增第三条 permanent + 注入一条死链 ---
    third = Note(
        id="20260820000003",
        title="Zima Three",
        content="content of Zima Three",
        type=NoteType.PERMANENT,
        created=dt(2026, 8, 21, 0, 0, 0),
        updated=dt(2026, 8, 21, 0, 0, 0),
        tags=["zima"],
    )
    third.set_filepath(seeded_kb.notes_dir / "permanent" / "20260820000003-zima-three.md")
    _atomic_write(third.filepath, third.to_markdown())
    moc.links = sorted(moc.links + ["20260820999999"])  # 死链
    update_note(moc)
    get_note_index(seeded_kb).rebuild()

    # --- update ---
    with patch(
        "jfox.moc.cli.diagnose_moc_density",
        return_value=_report(["20260820000001", "20260820000002", "20260820000003"]),
    ):
        payloads, changed = _update_impl(seeded_kb, moc.id, 0.65, True)

    assert len(payloads) == 1
    assert [m["id"] for m in payloads[0]["add"]] == ["20260820000003"]
    assert payloads[0]["remove"] == ["20260820999999"]

    updated_moc = list_notes(note_type=NoteType.STRUCTURE, cfg=seeded_kb)[0]
    assert "20260820000003" in updated_moc.links
    assert "20260820999999" not in updated_moc.links
