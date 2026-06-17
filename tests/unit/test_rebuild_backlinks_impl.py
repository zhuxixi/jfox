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


class TestRebuildBacklinksImpl:
    """_rebuild_backlinks_impl 单元测试"""

    @patch("jfox.note.save_note")
    @patch("jfox.note_index.get_note_index")
    @patch("jfox.note.list_notes")
    def test_rebuild_updates_changed_backlinks(
        self, mock_list_notes, mock_get_index, mock_save_note
    ):
        """backlinks 变化时，应调用 save_note 写回"""
        import jfox.cli  # noqa: F401
        from jfox.cli import _rebuild_backlinks_impl

        note_a = _FakeNote(id="202601010000000001", title="Note A", content="Content A")
        note_b = _FakeNote(
            id="202601010000000002", title="Note B", content="Note B references [[Note A]]"
        )

        mock_list_notes.return_value = [note_a, note_b]

        # 构造 mock NoteIndex
        def _find_by_id(nid):
            for n in [note_a, note_b]:
                if n.id == nid:
                    return _make_fake_meta(n)
            return None

        def _find_by_title(title):
            title_lower = title.lower()
            for n in [note_a, note_b]:
                if n.title.lower() == title_lower:
                    return _make_fake_meta(n)
            return None

        idx = MagicMock()
        idx.find_by_id.side_effect = _find_by_id
        idx.find_by_title.side_effect = _find_by_title
        idx.get_all_meta.return_value = [_make_fake_meta(n) for n in [note_a, note_b]]
        mock_get_index.return_value = idx

        result = _rebuild_backlinks_impl(output_format="json")

        assert result["backlinks_rebuilt"] is True
        assert result["backlinks_total"] == 2
        # A 的 backlinks 从 [] 变为 [B]，B 的 links 从 [] 变为 [A]
        assert result["backlinks_updated"] == 2
        assert result["unresolved_links"] == []

        # 验证 save_note 被调用且未重新加入索引
        assert mock_save_note.call_count == 2
        for call in mock_save_note.call_args_list:
            assert call.kwargs.get("add_to_index") is False

    @patch("jfox.note.save_note")
    @patch("jfox.note_index.get_note_index")
    @patch("jfox.note.list_notes")
    def test_rebuild_skips_unchanged_notes(self, mock_list_notes, mock_get_index, mock_save_note):
        """backlinks 未变化时，不应调用 save_note"""
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

        def _find_by_id(nid):
            for n in [note_a, note_b]:
                if n.id == nid:
                    return _make_fake_meta(n)
            return None

        def _find_by_title(title):
            title_lower = title.lower()
            for n in [note_a, note_b]:
                if n.title.lower() == title_lower:
                    return _make_fake_meta(n)
            return None

        idx = MagicMock()
        idx.find_by_id.side_effect = _find_by_id
        idx.find_by_title.side_effect = _find_by_title
        idx.get_all_meta.return_value = [_make_fake_meta(n) for n in [note_a, note_b]]
        mock_get_index.return_value = idx

        result = _rebuild_backlinks_impl(output_format="json")

        assert result["backlinks_rebuilt"] is True
        assert result["backlinks_total"] == 2
        assert result["backlinks_updated"] == 0
        assert result["unresolved_links"] == []
        mock_save_note.assert_not_called()

    @patch("jfox.note.save_note")
    @patch("jfox.note_index.get_note_index")
    @patch("jfox.note.list_notes")
    def test_rebuild_reports_unresolved_links(
        self, mock_list_notes, mock_get_index, mock_save_note
    ):
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

        idx = MagicMock()
        idx.find_by_id.return_value = None
        idx.find_by_title.return_value = None
        idx.get_all_meta.return_value = [_make_fake_meta(n) for n in [note_a, note_b]]
        mock_get_index.return_value = idx

        result = _rebuild_backlinks_impl(output_format="json")

        assert result["backlinks_rebuilt"] is True
        assert "Missing Note" in result["unresolved_links"]
        # B 的 links 为空，A 的 backlinks 为空，没有变化
        assert result["backlinks_updated"] == 0

    @patch("jfox.note.save_note")
    @patch("jfox.note_index.get_note_index")
    @patch("jfox.note.list_notes")
    def test_rebuild_empty_notes(self, mock_list_notes, mock_get_index, mock_save_note):
        """空知识库时应返回零值且不报错"""
        import jfox.cli  # noqa: F401
        from jfox.cli import _rebuild_backlinks_impl

        mock_list_notes.return_value = []

        result = _rebuild_backlinks_impl(output_format="json")

        assert result["backlinks_rebuilt"] is True
        assert result["backlinks_total"] == 0
        assert result["backlinks_updated"] == 0
        assert result["unresolved_links"] == []
        mock_save_note.assert_not_called()
