"""jfox moc add-member / remove-member 端到端集成测试（真实 KB 文件 + mock embedding）。"""

from __future__ import annotations

from datetime import datetime as dt
from pathlib import Path

import numpy as np
import pytest

from jfox.moc.cli import _add_member_impl, _remove_member_impl
from jfox.models import Note, NoteType
from jfox.note import _atomic_write, load_note_by_id
from jfox.note_index import get_note_index

MEMBER_ONE = "20260820000001"
MEMBER_TWO = "20260820000002"
MOC_ID = "20260821000001"


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
    """最小 KB：2 条 permanent + 1 条 structure MOC + mock embedding 后端。

    与 tests/unit/test_moc_generate.py 的 seeded_kb 同模式：原地修改全局
    config 单例属性并 _reset_singletons，让 get_note_index / vector_store
    重建到临时目录。
    """
    from jfox import config as config_module
    from jfox.config import ZKConfig

    cfg = ZKConfig(base_dir=tmp_path)
    cfg.ensure_dirs()

    def _write(note: Note, slug: str) -> None:
        note.set_filepath(cfg.notes_dir / note.type.value / f"{note.id}-{slug}.md")
        _atomic_write(note.filepath, note.to_markdown())

    _write(
        Note(
            id=MEMBER_ONE,
            title="Zima One",
            content="content of Zima One",
            type=NoteType.PERMANENT,
            created=dt(2026, 8, 20),
            updated=dt(2026, 8, 20),
            tags=["zima"],
        ),
        "zima-one",
    )
    _write(
        Note(
            id=MEMBER_TWO,
            title="Zima Two",
            content="content of Zima Two",
            type=NoteType.PERMANENT,
            created=dt(2026, 8, 20),
            updated=dt(2026, 8, 20),
            tags=["zima"],
        ),
        "zima-two",
    )
    moc_content = "## zima\n\n- [[20260820000001|Zima One]] — 3 links\n\n## 近期活动\n"
    _write(
        Note(
            id=MOC_ID,
            title="Zima MOC",
            content=moc_content,
            type=NoteType.STRUCTURE,
            created=dt(2026, 8, 21),
            updated=dt(2026, 8, 21),
            tags=["moc"],
            links=[MEMBER_ONE],
        ),
        "zima-moc",
    )
    # member one 的 backlinks 已含 MOC（模拟 create 后回填完成）
    member_one = Note(
        id=MEMBER_ONE,
        title="Zima One",
        content="content of Zima One",
        type=NoteType.PERMANENT,
        created=dt(2026, 8, 20),
        updated=dt(2026, 8, 20),
        tags=["zima"],
        backlinks=[MOC_ID],
    )
    _write(member_one, "zima-one")

    singleton = config_module.config
    monkeypatch.setattr(singleton, "base_dir", tmp_path)
    monkeypatch.setattr(singleton, "notes_dir", cfg.notes_dir)
    monkeypatch.setattr(singleton, "zk_dir", cfg.zk_dir)
    monkeypatch.setattr(singleton, "chroma_dir", cfg.chroma_dir)
    config_module._reset_singletons()
    monkeypatch.setattr("jfox.embedding_backend.get_backend", lambda: _MockBackend())

    yield cfg

    config_module._reset_singletons()


def _moc_file(cfg) -> Path:
    return cfg.notes_dir / "structure" / f"{MOC_ID}-zima-moc.md"


def _reload(cfg) -> Note:
    get_note_index(cfg).rebuild()
    return load_note_by_id(MOC_ID, cfg)


def test_add_member_end_to_end_three_way_consistency(seeded_kb):
    payload = _add_member_impl(seeded_kb, MOC_ID, MEMBER_TWO, None)

    assert payload["success"] is True
    assert payload["applied"] is True
    assert payload["already_member"] is False
    assert payload["group"] == "zima"  # tags=["zima"] 命中既有普通组

    moc = _reload(seeded_kb)
    # 正文：ID canonical 行插入 zima 组、位于近期活动之前
    assert "[[20260820000002|Zima Two]]" in moc.content
    assert moc.content.index("[[20260820000002|Zima Two]]") < moc.content.index("## 近期活动")
    # frontmatter links 合并去重
    assert sorted(moc.links) == [MEMBER_ONE, MEMBER_TWO]
    # 成员 backlinks 回填
    member_two = load_note_by_id(MEMBER_TWO, seeded_kb)
    assert MOC_ID in member_two.backlinks


def test_add_member_is_idempotent_on_second_run(seeded_kb):
    _add_member_impl(seeded_kb, MOC_ID, MEMBER_TWO, None)
    first_content = _moc_file(seeded_kb).read_text(encoding="utf-8")

    payload = _add_member_impl(seeded_kb, MOC_ID, MEMBER_TWO, None)

    assert payload["already_member"] is True
    assert payload["applied"] is False
    assert payload["partial"] is False
    assert _moc_file(seeded_kb).read_text(encoding="utf-8") == first_content


def test_add_member_repairs_body_when_links_only(seeded_kb):
    """links 已有但正文缺行：补正文行并回填 backlink。"""
    moc = _reload(seeded_kb)
    moc.links = sorted(set(moc.links + [MEMBER_TWO]))
    moc.content = "## zima\n\n- [[20260820000001|Zima One]] — 3 links\n\n## 近期活动\n"
    _atomic_write(moc.filepath, moc.to_markdown())

    payload = _add_member_impl(seeded_kb, MOC_ID, MEMBER_TWO, None)

    assert payload["already_member"] is True
    assert payload["applied"] is True
    moc = _reload(seeded_kb)
    assert "[[20260820000002|Zima Two]]" in moc.content


def test_add_member_non_permanent_warns_but_applies(seeded_kb):
    lit = Note(
        id="20260820000009",
        title="Zima Literature",
        content="literature note",
        type=NoteType.LITERATURE,
        created=dt(2026, 8, 20),
        updated=dt(2026, 8, 20),
        tags=["zima"],
    )
    lit.set_filepath(seeded_kb.notes_dir / "literature" / f"{lit.id}-zima-literature.md")
    _atomic_write(lit.filepath, lit.to_markdown())

    payload = _add_member_impl(seeded_kb, MOC_ID, lit.id, None)

    assert payload["success"] is True
    assert payload["applied"] is True
    assert any("not permanent" in w for w in payload["warnings"])


def test_add_member_invalid_ids_rejected(seeded_kb):
    with pytest.raises(ValueError, match="Invalid note id"):
        _add_member_impl(seeded_kb, MOC_ID, "bad/id", None)
    with pytest.raises(ValueError, match="Invalid note id"):
        _add_member_impl(seeded_kb, "x*y", MEMBER_TWO, None)


def test_add_member_self_link_rejected(seeded_kb):
    with pytest.raises(ValueError, match="self-link"):
        _add_member_impl(seeded_kb, MOC_ID, MOC_ID, None)


def test_add_member_missing_member_rejected(seeded_kb):
    with pytest.raises(ValueError, match="Member note not found"):
        _add_member_impl(seeded_kb, MOC_ID, "99999999999999", None)


def test_remove_member_end_to_end_cleans_all_three(seeded_kb):
    _add_member_impl(seeded_kb, MOC_ID, MEMBER_TWO, None)

    payload = _remove_member_impl(seeded_kb, MOC_ID, MEMBER_TWO)

    assert payload["success"] is True
    assert payload["removed"] is True
    assert payload["not_member"] is False
    assert payload["applied"] is True
    assert payload["partial"] is False
    assert payload["removed_rows"] >= 1
    assert payload["removed_groups"] == ["zima"]

    moc = _reload(seeded_kb)
    assert "[[20260820000002|Zima Two]]" not in moc.content
    # zima 组仍有 member one，不删组标题
    assert "## zima" in moc.content
    assert moc.links == [MEMBER_ONE]
    member_two = load_note_by_id(MEMBER_TWO, seeded_kb)
    assert MOC_ID not in member_two.backlinks


def test_remove_member_second_run_not_member(seeded_kb):
    _add_member_impl(seeded_kb, MOC_ID, MEMBER_TWO, None)

    payload = _remove_member_impl(seeded_kb, MOC_ID, MEMBER_TWO)
    assert payload["removed"] is True

    payload2 = _remove_member_impl(seeded_kb, MOC_ID, MEMBER_TWO)

    assert payload2["removed"] is False
    assert payload2["not_member"] is True
    assert payload2["applied"] is False


def test_remove_member_missing_target_cleans_links_by_id(seeded_kb):
    """成员文件不存在：按 ID 清理 links 与 canonical ID 行，不调 backlink helper。"""
    _add_member_impl(seeded_kb, MOC_ID, MEMBER_TWO, None)
    member_two_file = seeded_kb.notes_dir / "permanent" / f"{MEMBER_TWO}-zima-two.md"
    member_two_file.unlink()

    payload = _remove_member_impl(seeded_kb, MOC_ID, MEMBER_TWO)

    assert payload["success"] is True
    assert payload["title"] is None
    assert payload["removed"] is True
    # 目标不存在：canonical ID 行仍按 ID 清理（spec §3.3 步骤 3）
    assert payload["removed_rows"] == 1
    moc = _reload(seeded_kb)
    assert "[[20260820000002" not in moc.content
    assert moc.links == [MEMBER_ONE]


def test_remove_last_member_deletes_empty_group(seeded_kb):
    payload = _remove_member_impl(seeded_kb, MOC_ID, MEMBER_ONE)

    assert payload["success"] is True
    moc = _reload(seeded_kb)
    assert "## zima" not in moc.content  # 删行后组体只剩空白 → 连标题删除
    assert "## 近期活动" in moc.content
    assert moc.links == []
