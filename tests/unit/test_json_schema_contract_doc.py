"""#539 schema 文档与 index status 实现的静态防漂移测试。"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "json-schemas.md"


def test_index_status_fields_documented():
    text = DOC.read_text(encoding="utf-8")
    assert "`status`：`success, vector_store, bm25_indexed, last_rebuild`" in text


def test_index_status_dead_fields_removed_from_doc():
    text = DOC.read_text(encoding="utf-8")
    assert "success, total_indexed, last_indexed, pending_changes, vector_store" not in text


def test_edit_link_fields_documented():
    text = DOC.read_text(encoding="utf-8")
    assert "note{id,title,type,filepath,links,backlinks}" in text
    assert "`links_added[], links_removed[]`（恒有，可为空数组）" in text
