"""
测试 indexer.verify_index 以 frontmatter 真实 ID 对账

Issue #407: legacy 文件名（14位时间戳-6位微秒-slug）无法从文件名解析 ID，
导致 candidate/legacy permanent 全部误报 orphaned。
"""

import pytest

from jfox.config import ZKConfig
from jfox.indexer import Indexer
from jfox.vector_store import VectorStore


class FakeVectorStore(VectorStore):
    """verify_index 只调用 get_all_ids()；假对象避开 ChromaDB/embedding 依赖"""

    def __init__(self, ids):
        self._ids = list(ids)

    def get_all_ids(self):
        return list(self._ids)


@pytest.fixture
def indexer(tmp_path):
    """构造 notes 目录 + FakeVectorStore + Indexer"""
    cfg = ZKConfig(base_dir=tmp_path)
    cfg.ensure_dirs()
    return Indexer(cfg, FakeVectorStore([]))


def write_note(notes_dir, relpath, note_id, title="Test"):
    """手写含 frontmatter 的 md 文件，返回路径"""
    p = notes_dir / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f"---\nid: {note_id}\ntitle: {title}\ntype: permanent\n"
        "created: '2026-01-01T00:00:00'\n---\n\n# {title}\n\nbody\n",
        encoding="utf-8",
    )
    return p


class TestLegacyFilenameReconciliation:
    """legacy 14位-6位-slug 文件名不再误报（#407 核心）"""

    def test_legacy_candidate_filename(self, indexer):
        notes_dir = indexer.config.notes_dir
        nid = "20260628004828-286060"
        write_note(notes_dir, f"candidate/{nid}-jfox-embedding-daemon.md", nid)
        indexer.vector_store = FakeVectorStore([nid])

        result = indexer.verify_index()
        assert result["missing_from_index"] == []
        assert result["orphaned_in_index"] == []
        assert result["healthy"] is True

    def test_legacy_permanent_filename(self, indexer):
        notes_dir = indexer.config.notes_dir
        nid = "20260708002136-108471"
        write_note(notes_dir, f"permanent/{nid}-cc-plugin-版本号.md", nid)
        indexer.vector_store = FakeVectorStore([nid])

        result = indexer.verify_index()
        assert result["healthy"] is True
        assert result["unique_ids"] == 1
        assert result["valid_files"] == 1

    def test_current_formats_still_reconcile(self, indexer):
        """18位-slug / fleeting 8-10 / session 18位 回归"""
        notes_dir = indexer.config.notes_dir
        write_note(notes_dir, "permanent/202604120150293323-some-slug.md", "202604120150293323")
        write_note(notes_dir, "fleeting/20260412-0150293323.md", "202604120150293323")
        write_note(notes_dir, "session/202604120150293399-session-a.md", "202604120150293399")
        indexer.vector_store = FakeVectorStore(["202604120150293323", "202604120150293399"])

        result = indexer.verify_index()
        assert result["healthy"] is True
        assert result["unique_ids"] == 2
        assert result["total_files"] == 3


class TestUnreadableAndDuplicate:
    """unreadable / duplicate 单独报告，不混入 missing/orphaned"""

    def test_unreadable_file_reported_separately(self, indexer):
        notes_dir = indexer.config.notes_dir
        good_id = "202604120150293323"
        write_note(notes_dir, "permanent/good.md", good_id)
        broken = notes_dir / "permanent" / "broken.md"
        broken.parent.mkdir(parents=True, exist_ok=True)
        broken.write_text("# no frontmatter here\n\njust body\n", encoding="utf-8")
        indexer.vector_store = FakeVectorStore([good_id])

        result = indexer.verify_index()
        assert result["unreadable_files"] == [str(broken)]
        assert result["missing_from_index"] == []
        assert result["orphaned_in_index"] == []
        assert result["total_files"] == 2
        assert result["valid_files"] == 1

    def test_frontmatter_without_id_is_unreadable(self, indexer):
        notes_dir = indexer.config.notes_dir
        p = notes_dir / "permanent" / "no-id.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("---\ntitle: No Id\ntype: permanent\n---\n\nbody\n", encoding="utf-8")

        result = indexer.verify_index()
        assert result["unreadable_files"] == [str(p)]
        assert result["healthy"] is True  # 对账无差集

    def test_duplicate_id_reported(self, indexer):
        notes_dir = indexer.config.notes_dir
        nid = "20260711104217-263635"
        f1 = write_note(notes_dir, f"permanent/{nid}-没爆就别修.md", nid, title="A")
        f2 = write_note(notes_dir, f"permanent/{nid}-代码审查务实原则.md", nid, title="B")
        indexer.vector_store = FakeVectorStore([nid])

        result = indexer.verify_index()
        assert len(result["duplicate_ids"]) == 1
        assert result["duplicate_ids"][0]["id"] == nid
        assert set(result["duplicate_ids"][0]["files"]) == {str(f1), str(f2)}
        assert result["missing_from_index"] == []
        assert result["orphaned_in_index"] == []
        assert result["unique_ids"] == 1
        assert result["valid_files"] == 2


class TestTrueDiff:
    """missing / orphaned 真值判定"""

    def test_missing_and_orphaned(self, indexer):
        notes_dir = indexer.config.notes_dir
        file_only = "202604120150293323"
        index_only = "202604120150293999"
        write_note(notes_dir, "permanent/file-only.md", file_only)
        indexer.vector_store = FakeVectorStore([index_only])

        result = indexer.verify_index()
        assert result["missing_from_index"] == [file_only]
        assert result["orphaned_in_index"] == [index_only]
        assert result["healthy"] is False
        assert result["checked"] == "vector_store"

    def test_empty_notes_dir(self, indexer):
        result = indexer.verify_index()
        assert result["total_files"] == 0
        assert result["healthy"] is True

    def test_missing_notes_dir(self, tmp_path):
        import shutil

        cfg = ZKConfig(base_dir=tmp_path)
        cfg.ensure_dirs()
        shutil.rmtree(cfg.notes_dir)
        idx = Indexer(cfg, FakeVectorStore([]))
        result = idx.verify_index()
        assert result == {"error": "Notes directory not found"}
