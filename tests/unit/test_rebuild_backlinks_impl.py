"""
测试类型: 单元测试
目标功能: _rebuild_backlinks_impl 内部函数
预估耗时: 1-2秒

测试 backlinks 重新计算逻辑，不依赖真实知识库和 embedding
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import List
from unittest.mock import MagicMock, patch


@dataclass
class _FakeNote:
    """用于单元测试的轻量 Note 替身"""

    id: str
    title: str
    content: str
    type: str = "permanent"
    links: List[str] = field(default_factory=list)
    backlinks: List[str] = field(default_factory=list)
    filepath: Path = field(default_factory=lambda: Path("/tmp/fake.md"))


def _make_fake_meta(note: _FakeNote):
    """构造 NoteIndex 需要的 meta 对象"""
    meta = MagicMock()
    meta.id = note.id
    meta.title = note.title
    meta.type.value = note.type
    return meta


def _make_index(notes):
    """构造 mock NoteIndex"""

    def _find_by_id(nid):
        for n in notes:
            if n.id == nid:
                return _make_fake_meta(n)
        return None

    def _find_by_title(title):
        title_lower = title.lower()
        for n in notes:
            if n.title.lower() == title_lower:
                return _make_fake_meta(n)
        return None

    idx = MagicMock()
    idx.find_by_id.side_effect = _find_by_id
    idx.find_by_title.side_effect = _find_by_title
    idx.get_all_meta.return_value = [_make_fake_meta(n) for n in notes]
    return idx


class TestRebuildBacklinksImpl:
    """_rebuild_backlinks_impl 单元测试"""

    @patch("jfox.note.apply_backlinks")
    @patch("jfox.note_index.get_note_index")
    @patch("jfox.note.list_notes")
    def test_rebuild_updates_changed_links_and_backlinks(
        self, mock_list_notes, mock_get_index, mock_apply
    ):
        """links/backlinks 变化时，应调用 apply_backlinks 窄写回；forward links 与解析结果合并"""
        import jfox.cli  # noqa: F401
        from jfox.cli import _rebuild_backlinks_impl

        note_a = _FakeNote(id="202601010000000001", title="Note A", content="Content A")
        note_b = _FakeNote(
            id="202601010000000002", title="Note B", content="Note B references [[Note A]]"
        )

        mock_list_notes.return_value = [note_a, note_b]
        mock_get_index.return_value = _make_index([note_a, note_b])
        mock_apply.return_value = "updated"

        result = _rebuild_backlinks_impl(output_format="json")

        assert result["backlinks_rebuilt"] is True
        assert result["backlinks_total"] == 2
        # A 的 backlinks 从 [] 变为 [B]，B 的 links 从 [] 变为 [A]
        assert result["backlinks_updated"] == 2
        assert result["backlinks_failed"] == 0
        assert result["unresolved_links"] == []

        # 验证 apply_backlinks 被调用两次，位置参数为 (笔记对象, 合并后 links, 重算 backlinks)
        assert mock_apply.call_count == 2
        calls_by_id = {call.args[0].id: call for call in mock_apply.call_args_list}
        assert calls_by_id[note_a.id].args[0] is note_a
        assert calls_by_id[note_a.id].args[1] == []
        assert calls_by_id[note_a.id].args[2] == [note_b.id]
        assert calls_by_id[note_b.id].args[0] is note_b
        assert calls_by_id[note_b.id].args[1] == [note_a.id]
        assert calls_by_id[note_b.id].args[2] == []

    @patch("jfox.note.apply_backlinks")
    @patch("jfox.note_index.get_note_index")
    @patch("jfox.note.list_notes")
    def test_rebuild_skips_unchanged_notes(self, mock_list_notes, mock_get_index, mock_apply):
        """backlinks 未变化时，不应调用 apply_backlinks"""
        import jfox.cli  # noqa: F401
        from jfox.cli import _rebuild_backlinks_impl

        note_a = _FakeNote(
            id="202601010000000001",
            title="Note A",
            content="Content A",
            backlinks=["202601010000000002"],
        )
        note_b = _FakeNote(
            id="202601010000000002",
            title="Note B",
            content="Note B references [[Note A]]",
            links=["202601010000000001"],
        )

        mock_list_notes.return_value = [note_a, note_b]
        mock_get_index.return_value = _make_index([note_a, note_b])

        result = _rebuild_backlinks_impl(output_format="json")

        assert result["backlinks_rebuilt"] is True
        assert result["backlinks_total"] == 2
        assert result["backlinks_updated"] == 0
        assert result["backlinks_failed"] == 0
        assert result["unresolved_links"] == []
        mock_apply.assert_not_called()

    @patch("jfox.note.apply_backlinks")
    @patch("jfox.note_index.get_note_index")
    @patch("jfox.note.list_notes")
    def test_rebuild_reports_unresolved_links(self, mock_list_notes, mock_get_index, mock_apply):
        """无法解析的 wiki 链接应被报告"""
        import jfox.cli  # noqa: F401
        from jfox.cli import _rebuild_backlinks_impl

        note_a = _FakeNote(id="202601010000000001", title="Note A", content="Content A")
        note_b = _FakeNote(
            id="202601010000000002",
            title="Note B",
            content="Note B references [[Missing Note]]",
        )

        mock_list_notes.return_value = [note_a, note_b]
        mock_get_index.return_value = _make_index([note_a, note_b])

        result = _rebuild_backlinks_impl(output_format="json")

        assert result["backlinks_rebuilt"] is True
        assert "Missing Note" in result["unresolved_links"]
        assert result["backlinks_updated"] == 0
        assert result["backlinks_failed"] == 0

    @patch("jfox.note.apply_backlinks")
    @patch("jfox.note_index.get_note_index")
    @patch("jfox.note.list_notes")
    def test_rebuild_empty_notes(self, mock_list_notes, mock_get_index, mock_apply):
        """空知识库时应返回零值且不报错"""
        import jfox.cli  # noqa: F401
        from jfox.cli import _rebuild_backlinks_impl

        mock_list_notes.return_value = []

        result = _rebuild_backlinks_impl(output_format="json")

        assert result["backlinks_rebuilt"] is True
        assert result["backlinks_total"] == 0
        assert result["backlinks_updated"] == 0
        assert result["backlinks_failed"] == 0
        assert result["backlinks_skipped"] == 0
        assert result["unresolved_links"] == []
        mock_apply.assert_not_called()

    @patch("jfox.note.apply_backlinks")
    @patch("jfox.note_index.get_note_index")
    @patch("jfox.note.list_notes")
    def test_rebuild_filters_self_links(self, mock_list_notes, mock_get_index, mock_apply):
        """自链接 [[Note A]] 不应产生自指边"""
        import jfox.cli  # noqa: F401
        from jfox.cli import _rebuild_backlinks_impl

        note_a = _FakeNote(id="202601010000000001", title="Note A", content="See also [[Note A]]")

        mock_list_notes.return_value = [note_a]
        mock_get_index.return_value = _make_index([note_a])

        result = _rebuild_backlinks_impl(output_format="json")

        assert result["backlinks_total"] == 1
        assert result["backlinks_updated"] == 0
        assert result["unresolved_links"] == []
        mock_apply.assert_not_called()

    @patch("jfox.note.apply_backlinks")
    @patch("jfox.note_index.get_note_index")
    @patch("jfox.note.list_notes")
    def test_rebuild_includes_failed_count(self, mock_list_notes, mock_get_index, mock_apply):
        """apply_backlinks 返回 error 时，backlinks_failed 应被统计并包含在 JSON 输出中"""
        import jfox.cli  # noqa: F401
        from jfox.cli import _rebuild_backlinks_impl

        note_a = _FakeNote(id="202601010000000001", title="Note A", content="Content A")
        note_b = _FakeNote(
            id="202601010000000002", title="Note B", content="Note B references [[Note A]]"
        )

        mock_list_notes.return_value = [note_a, note_b]
        mock_get_index.return_value = _make_index([note_a, note_b])
        mock_apply.return_value = "error"

        result = _rebuild_backlinks_impl(output_format="json")

        assert result["backlinks_total"] == 2
        assert result["backlinks_updated"] == 0
        assert result["backlinks_failed"] == 2

    @patch("jfox.note.apply_backlinks")
    @patch("jfox.note_index.get_note_index")
    @patch("jfox.note.list_notes")
    def test_rebuild_failed_count_on_apply_exception(
        self, mock_list_notes, mock_get_index, mock_apply
    ):
        """apply_backlinks 抛异常时应计入 backlinks_failed 且不向外抛出（对齐旧 save_note 兜底语义）"""
        import jfox.cli  # noqa: F401
        from jfox.cli import _rebuild_backlinks_impl

        note_a = _FakeNote(id="202601010000000001", title="Note A", content="Content A")
        note_b = _FakeNote(
            id="202601010000000002", title="Note B", content="Note B references [[Note A]]"
        )

        mock_list_notes.return_value = [note_a, note_b]
        mock_get_index.return_value = _make_index([note_a, note_b])
        mock_apply.side_effect = Exception("boom")

        result = _rebuild_backlinks_impl(output_format="json")

        assert result["backlinks_total"] == 2
        assert result["backlinks_updated"] == 0
        assert result["backlinks_failed"] == 2

    @patch("jfox.note.apply_backlinks")
    @patch("jfox.note_index.get_note_index")
    @patch("jfox.note.list_notes")
    def test_rebuild_dispatches_skipped_and_updated(
        self, mock_list_notes, mock_get_index, mock_apply
    ):
        """A5：updated/skipped 分派到 backlinks_updated / backlinks_skipped，互不混淆"""
        import jfox.cli  # noqa: F401
        from jfox.cli import _rebuild_backlinks_impl

        note_a = _FakeNote(id="202601010000000001", title="Note A", content="Content A")
        note_b = _FakeNote(
            id="202601010000000002", title="Note B", content="Note B references [[Note A]]"
        )
        mock_list_notes.return_value = [note_a, note_b]
        mock_get_index.return_value = _make_index([note_a, note_b])
        mock_apply.side_effect = ["updated", "skipped"]

        result = _rebuild_backlinks_impl(output_format="json")

        assert result["backlinks_updated"] == 1
        assert result["backlinks_skipped"] == 1
        assert result["backlinks_failed"] == 0

    @patch("jfox.note.apply_backlinks")
    @patch("jfox.note_index.get_note_index")
    @patch("jfox.note.list_notes")
    def test_rebuild_no_skipped_line_when_zero(
        self, mock_list_notes, mock_get_index, mock_apply, capsys
    ):
        """Review Focus 5：skipped=0 时 table 输出不出现 skipped 提示行"""
        import jfox.cli  # noqa: F401
        from jfox.cli import _rebuild_backlinks_impl

        note_a = _FakeNote(id="202601010000000001", title="Note A", content="Content A")
        note_b = _FakeNote(
            id="202601010000000002", title="Note B", content="Note B references [[Note A]]"
        )
        mock_list_notes.return_value = [note_a, note_b]
        mock_get_index.return_value = _make_index([note_a, note_b])
        mock_apply.return_value = "updated"

        _rebuild_backlinks_impl(output_format="table")

        out = capsys.readouterr().out
        assert "Skipped" not in out
