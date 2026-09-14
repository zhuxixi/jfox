"""
测试类型: 单元测试
目标功能: resolve_wiki_links 纯函数 + _strip_wiki_link_exclusions 增强（issue #511）
预估耗时: 1-2秒

不依赖真实知识库与 embedding；NoteIndex 用 MagicMock 替身
（沿用 tests/unit/test_rebuild_backlinks_impl.py 模式）。
"""

from unittest.mock import MagicMock, patch

from jfox.note_index import _strip_wiki_link_exclusions


def _make_meta(note_id: str, title: str):
    """构造 NoteIndex 需要的 meta 对象"""
    meta = MagicMock()
    meta.id = note_id
    meta.title = title
    return meta


def _make_index(notes):
    """notes: List[Tuple[id, title]]，构造 mock NoteIndex"""

    def _find_by_id(nid):
        for nid_, title in notes:
            if nid_ == nid:
                return _make_meta(nid_, title)
        return None

    def _find_by_title(title):
        tl = title.lower()
        for nid_, t in notes:
            if t.lower() == tl:
                return _make_meta(nid_, t)
        return None

    idx = MagicMock()
    idx.find_by_id.side_effect = _find_by_id
    idx.find_by_title.side_effect = _find_by_title
    idx.get_all_meta.return_value = [_make_meta(i, t) for i, t in notes]
    return idx


class TestStripWikiLinkExclusions:
    """_strip_wiki_link_exclusions 剥离行为"""

    def test_strip_inline_code(self):
        """A4：反引号 span 内的 [[...]] 被剥离"""
        out = _strip_wiki_link_exclusions("示例 `[[ID|标题]]` 文字")
        assert "[[" not in out

    def test_strip_fenced_block_kept(self):
        """回归：fenced code block 剥离行为保持"""
        out = _strip_wiki_link_exclusions("```\n[[X]]\n```\n[[Y]]")
        assert "[[X]]" not in out
        assert "[[Y]]" in out

    def test_plain_text_untouched(self):
        """非剥离区域的 [[...]] 不受影响"""
        out = _strip_wiki_link_exclusions("普通 [[链接]] 内容")
        assert "[[链接]]" in out


class TestResolveWikiLinks:
    """resolve_wiki_links 统一解析规则（issue #511）"""

    def test_self_link_filtered(self):
        """A1：标题包含匹配命中自身时，resolved 不含 self_id"""
        from jfox.cli import resolve_wiki_links

        notes = [("20260914000000", "某机制与 ID canonical 说明")]
        with patch("jfox.note_index.get_note_index", return_value=_make_index(notes)):
            resolved, _unresolved = resolve_wiki_links(
                "说明文字 [[ID|标题]] 示例", self_id="20260914000000"
            )
        assert "20260914000000" not in resolved
        assert resolved == []

    def test_dedup(self):
        """A2：正文两次引用同一目标只解析一次"""
        from jfox.cli import resolve_wiki_links

        notes = [("20260101000001", "目标笔记")]
        with patch("jfox.note_index.get_note_index", return_value=_make_index(notes)):
            resolved, _ = resolve_wiki_links(
                "见 [[目标笔记]] 与 [[目标笔记]]", self_id="20260999999999"
            )
        assert resolved == ["20260101000001"]

    def test_unresolved_collected(self):
        """A3：找不到目标的链接进 unresolved，不影响 resolved"""
        from jfox.cli import resolve_wiki_links

        notes = [("20260101000001", "存在的笔记")]
        with patch("jfox.note_index.get_note_index", return_value=_make_index(notes)):
            resolved, unresolved = resolve_wiki_links(
                "见 [[存在的笔记]] 和 [[不存在的标题xyz]]", self_id="20260999999999"
            )
        assert resolved == ["20260101000001"]
        assert unresolved == ["不存在的标题xyz"]

    def test_inline_code_literal_not_resolved(self):
        """A4 端到端：反引号内字面量不参与解析（经 Task 1 剥离）"""
        from jfox.cli import resolve_wiki_links

        notes = [("20260101000001", "无关的 --commit-id 笔记")]
        with patch("jfox.note_index.get_note_index", return_value=_make_index(notes)):
            resolved, unresolved = resolve_wiki_links(
                "示例 `[[ID]]` 文字", self_id="20260999999999"
            )
        assert resolved == []
        assert unresolved == []
