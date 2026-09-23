"""测试 _read_content_file 对含 frontmatter 文件的处理"""

import io
import tempfile

import pytest

from jfox.cli import _read_content_file, _strip_frontmatter, _strip_leading_h1


class TestReadContentFile:
    """_read_content_file 的单元测试"""

    def test_plain_content_unchanged(self):
        """纯文本内容应原样返回"""
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write("Hello world")
            f.flush()
            result = _read_content_file(f.name)
        assert result == "Hello world"

    def test_content_with_frontmatter_stripped(self):
        """含 frontmatter 的文件应只返回正文"""
        raw = "---\nid: '123'\ntitle: test\n---\n\n# test\n\nBody text\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write(raw)
            f.flush()
            result = _read_content_file(f.name)
        assert "---" not in result
        assert "Body text" in result

    def test_content_with_frontmatter_no_title(self):
        """含 frontmatter 但无标题行的文件"""
        raw = "---\nid: '123'\ntitle: test\n---\n\nJust body text\n"
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".md", delete=False, encoding="utf-8"
        ) as f:
            f.write(raw)
            f.flush()
            result = _read_content_file(f.name)
        assert "---" not in result
        assert "Just body text" in result

    def test_stdin_frontmatter_and_h1_stripped(self):
        """stdin 与文件路径同语义（#541 D1）：frontmatter + H1 剥离"""
        import sys

        old_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO("---\nid: x\n---\n\n# 标题\n\n正文\n")
            result = _read_content_file("-")
        finally:
            sys.stdin = old_stdin
        assert result == "正文"

    def test_stdin_h1_only_stripped(self):
        """stdin：无 frontmatter 的 H1 开头同样剥离"""
        import sys

        old_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO("# 标题\n\n正文\n")
            result = _read_content_file("-")
        finally:
            sys.stdin = old_stdin
        assert result == "正文\n"

    def test_stdin_plain_passthrough(self):
        """stdin：纯正文原样放行"""
        import sys

        old_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO("Hello world")
            result = _read_content_file("-")
        finally:
            sys.stdin = old_stdin
        assert result == "Hello world"

    def test_file_not_found(self):
        """不存在的文件应抛异常"""
        with pytest.raises(ValueError, match="文件不存在"):
            _read_content_file("/nonexistent/file.md")

    def test_bom_file_stripped(self):
        """含 UTF-8 BOM 的 frontmatter 文件应正确剥离"""
        raw = "---\nid: '123'\ntitle: test\n---\n\nBody with BOM\n"
        with tempfile.NamedTemporaryFile(mode="wb", suffix=".md", delete=False) as f:
            f.write(raw.encode("utf-8-sig"))
            f.flush()
            result = _read_content_file(f.name)
        assert "---" not in result
        assert "Body with BOM" in result


class TestStripLeadingH1:
    """_strip_leading_h1 纯函数（#541）"""

    def test_strips_single_h1(self):
        assert _strip_leading_h1("# 标题\n正文") == "正文"

    def test_strips_h1_after_leading_blank_lines(self):
        assert _strip_leading_h1("\n\n# 标题\n正文") == "正文"

    def test_keeps_h2_heading(self):
        assert _strip_leading_h1("## 小节\n正文") == "## 小节\n正文"

    def test_keeps_hashtag_line(self):
        assert _strip_leading_h1("#标签\n正文") == "#标签\n正文"

    def test_plain_text_passthrough(self):
        assert _strip_leading_h1("Hello world") == "Hello world"


class TestStripFrontmatterH1Only:
    """无 frontmatter 时 H1 剥离（#541 主诉，spec 形态 4）"""

    def test_h1_only_no_frontmatter_stripped(self):
        raw = "# 回灌测试笔记\n\nB 原始正文。\n追加 B。\n"
        assert _strip_frontmatter(raw) == "B 原始正文。\n追加 B。\n"

    def test_h1_after_leading_blank_lines_stripped(self):
        assert _strip_frontmatter("\n\n# 标题\n正文") == "正文"


class TestStripFrontmatterDoubleH1:
    """开头连续双 H1 报错（#541 spec 形态 6，决策 D2）"""

    def test_double_h1_no_frontmatter_raises(self):
        with pytest.raises(ValueError, match="多个 H1"):
            _strip_frontmatter("# 标题一\n# 标题二\n正文")

    def test_double_h1_with_frontmatter_raises(self):
        raw = "---\nid: '1'\n---\n\n# 标题一\n\n# 标题二\n\n正文\n"
        with pytest.raises(ValueError, match="--content"):
            _strip_frontmatter(raw)


class TestStripFrontmatterEmpty:
    """剥后为空报错（#541 spec 形态 8，决策 D4）"""

    def test_single_h1_line_raises_empty(self):
        with pytest.raises(ValueError, match="正文为空"):
            _strip_frontmatter("# 只有标题没有正文")

    def test_empty_string_passthrough(self):
        assert _strip_frontmatter("") == ""

    def test_blank_lines_only_passthrough(self):
        assert _strip_frontmatter("\n\n") == "\n\n"
