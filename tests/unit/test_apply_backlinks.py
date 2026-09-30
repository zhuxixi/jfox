"""
测试类型: 单元测试
目标功能: note.backlinks_write_needed / note.apply_backlinks（#561 分歧即跳过窄写）
预估耗时: 1-2秒

不依赖真实知识库与 embedding：文件用 tmp_path，find_note_file 与索引走 patch。
"""

from pathlib import Path
from unittest.mock import patch

from jfox import note as note_module
from jfox.models import Note, NoteType


class TestBacklinksWriteNeeded:
    """backlinks_write_needed 纯函数：目标值与现值（各自排序去重后）是否不同"""

    def test_equal_ignoring_order_and_duplicates(self):
        assert (
            note_module.backlinks_write_needed(["b", "a", "a"], ["x"], ["a", "b"], ["x"]) is False
        )

    def test_both_empty_equal(self):
        assert note_module.backlinks_write_needed([], [], [], []) is False

    def test_links_differ(self):
        assert note_module.backlinks_write_needed(["a"], [], ["a", "b"], []) is True

    def test_backlinks_differ(self):
        assert note_module.backlinks_write_needed([], [], [], ["c"]) is True

    def test_empty_to_nonempty(self):
        assert note_module.backlinks_write_needed([], [], ["a"], []) is True


def _make_note(
    note_id: str = "202601010000000001",
    title: str = "Note A",
    content: str = "Content A",
    links=None,
    backlinks=None,
    tags=None,
) -> Note:
    """构造最小 Note 对象"""
    from datetime import datetime

    return Note(
        id=note_id,
        title=title,
        content=content,
        type=NoteType.PERMANENT,
        created=datetime(2026, 1, 1),
        updated=datetime(2026, 1, 1),
        tags=tags or [],
        links=links or [],
        backlinks=backlinks or [],
    )


def _roundtrip_to_disk(n: Note, path: Path) -> Note:
    """落盘并重新 load，返回钉住真实路径的快照对象"""
    path.write_text(n.to_markdown(), encoding="utf-8")
    snapshot = note_module.load_note(path)
    assert snapshot is not None
    return snapshot


class TestApplyBacklinks:
    """apply_backlinks：重读 → 分歧检测 → 原子写（#561）"""

    def test_writes_recomputed_values_when_no_divergence(self, tmp_path):
        """A3：无分歧 → updated，links/backlinks 写重算值，其余字段原样，索引 meta 刷新"""
        path = tmp_path / "202601010000000001-note-a.md"
        snapshot = _roundtrip_to_disk(_make_note(tags=["keep"]), path)

        with patch("jfox.note_index.get_note_index") as mock_idx:
            status = note_module.apply_backlinks(
                snapshot, ["202601010000000002"], ["202601010000000003"]
            )

        assert status == "updated"
        fresh = note_module.load_note(path)
        assert fresh.links == ["202601010000000002"]
        assert fresh.backlinks == ["202601010000000003"]
        assert fresh.tags == ["keep"]  # 其余字段原样
        assert fresh.content == "Content A"
        mock_idx.return_value.update_note_meta.assert_called_once()

    def test_unchanged_when_targets_already_on_disk(self, tmp_path):
        """A3：目标值已在盘上 → unchanged 且零写入（mtime 不变）"""
        path = tmp_path / "202601010000000001-note-a.md"
        snapshot = _roundtrip_to_disk(
            _make_note(links=["202601010000000002"], backlinks=["202601010000000003"]),
            path,
        )
        mtime_before = path.stat().st_mtime_ns

        with patch("jfox.note_index.get_note_index") as mock_idx:
            status = note_module.apply_backlinks(
                snapshot, ["202601010000000002"], ["202601010000000003"]
            )

        assert status == "unchanged"
        assert path.stat().st_mtime_ns == mtime_before
        mock_idx.return_value.update_note_meta.assert_not_called()

    def test_skips_when_concurrent_modification_detected(self, tmp_path):
        """A2：快照后并发方改正文/标签 → skipped、零写入，并发方内容逐字节保留"""
        path = tmp_path / "202601010000000001-note-a.md"
        snapshot = _roundtrip_to_disk(_make_note(), path)

        # 并发方写入 v2（模拟另一会话的 jfox edit）
        concurrent = note_module.load_note(path)
        concurrent.content = "edited by another session"
        concurrent.tags = ["concurrent-tag"]
        path.write_text(concurrent.to_markdown(), encoding="utf-8")

        with patch("jfox.note_index.get_note_index") as mock_idx:
            status = note_module.apply_backlinks(
                snapshot, ["202601010000000002"], ["202601010000000003"]
            )

        assert status == "skipped"
        on_disk = note_module.load_note(path)
        assert on_disk.content == "edited by another session"
        assert on_disk.tags == ["concurrent-tag"]
        assert on_disk.links == []  # 重算值没有落盘
        assert on_disk.backlinks == []
        mock_idx.return_value.update_note_meta.assert_not_called()

    def test_updated_only_change_counts_as_divergence(self, tmp_path):
        """Review Focus 2：并发方只动 updated 时间戳也保守判分歧（可接受，pin 住）"""
        from datetime import datetime

        path = tmp_path / "202601010000000001-note-a.md"
        snapshot = _roundtrip_to_disk(_make_note(), path)

        concurrent = note_module.load_note(path)
        concurrent.updated = datetime(2026, 6, 6)
        path.write_text(concurrent.to_markdown(), encoding="utf-8")

        with patch("jfox.note_index.get_note_index"):
            status = note_module.apply_backlinks(snapshot, ["x"], [])

        assert status == "skipped"

    def test_hand_formatted_file_is_not_false_divergence(self, tmp_path):
        """Review Focus 1：手改格式（字段顺序/空行）的文件经 to_markdown 归一化后不误判分歧"""
        path = tmp_path / "202601010000000001-note-a.md"
        path.write_text(
            "---\n"
            "title: Note A\n"
            "id: '202601010000000001'\n"
            "type: permanent\n"
            "created: '2026-01-01T00:00:00'\n"
            "updated: '2026-01-01T00:00:00'\n"
            "\n"
            "tags: []\n"
            "links: []\n"
            "backlinks: []\n"
            "---\n"
            "\n"
            "# Note A\n"
            "\n"
            "Content A\n",
            encoding="utf-8",
        )
        snapshot = note_module.load_note(path)
        assert snapshot is not None

        with patch("jfox.note_index.get_note_index"):
            status = note_module.apply_backlinks(snapshot, ["202601010000000002"], [])

        # 未被误判分歧跳过：正常写入（文件格式被归一化是可接受的既有行为）
        assert status == "updated"
        assert note_module.load_note(path).links == ["202601010000000002"]

    def test_falls_back_to_find_note_file_when_pinned_path_missing(self, tmp_path):
        """A4①：快照钉住的路径失效（并发 edit --title 改名）→ find_note_file 兜底成功"""
        old_path = tmp_path / "202601010000000001-note-a.md"
        new_path = tmp_path / "202601010000000001-renamed.md"
        snapshot = _roundtrip_to_disk(_make_note(), old_path)
        old_path.rename(new_path)  # 模拟并发 rename

        with (
            patch("jfox.note.find_note_file", return_value=new_path),
            patch("jfox.note_index.get_note_index"),
        ):
            status = note_module.apply_backlinks(snapshot, ["202601010000000002"], [])

        assert status == "updated"
        assert note_module.load_note(new_path).links == ["202601010000000002"]

    def test_id_mismatch_on_pinned_path_is_not_written(self, tmp_path):
        """A4②：钉住路径被别的 id 的文件占用且兜底找不到 → skipped，占位文件不动"""
        path = tmp_path / "202601010000000001-note-a.md"
        snapshot = _roundtrip_to_disk(_make_note(), path)
        # 并发方把别的笔记写到了这个路径（极端路径复用）
        occupant_bytes = _make_note(note_id="999999999999999999", title="Occupant").to_markdown()
        path.write_text(occupant_bytes, encoding="utf-8")

        with (
            patch("jfox.note.find_note_file", return_value=None),
            patch("jfox.note_index.get_note_index"),
        ):
            status = note_module.apply_backlinks(snapshot, ["202601010000000002"], [])

        assert status == "skipped"
        assert path.read_text(encoding="utf-8") == occupant_bytes  # 占位文件逐字节未动

    def test_missing_returns_skipped_without_exception(self, tmp_path):
        """A4③：路径失效且 find_note_file 找不到（并发 delete）→ skipped，不写盘不抛异常"""
        path = tmp_path / "202601010000000001-note-a.md"
        snapshot = _roundtrip_to_disk(_make_note(), path)
        path.unlink()

        with (
            patch("jfox.note.find_note_file", return_value=None),
            patch("jfox.note._atomic_write") as mock_write,
            patch("jfox.note_index.get_note_index"),
        ):
            status = note_module.apply_backlinks(snapshot, ["202601010000000002"], [])

        assert status == "skipped"
        mock_write.assert_not_called()

    def test_write_error_returns_error(self, tmp_path):
        """A4：写盘异常 → error（捕获不向上抛），索引 meta 不刷新"""
        path = tmp_path / "202601010000000001-note-a.md"
        snapshot = _roundtrip_to_disk(_make_note(), path)

        with (
            patch("jfox.note._atomic_write", side_effect=OSError("disk full")),
            patch("jfox.note_index.get_note_index") as mock_idx,
        ):
            status = note_module.apply_backlinks(snapshot, ["202601010000000002"], [])

        assert status == "error"
        mock_idx.return_value.update_note_meta.assert_not_called()
