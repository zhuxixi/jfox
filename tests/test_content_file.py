"""测试 _read_content_file 对含 frontmatter 文件的处理"""

import tempfile
from pathlib import Path

from jfox.cli import _read_content_file


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

    def test_stdin_passthrough(self):
        """stdin 模式（'-'）不应做处理"""
        import io
        import sys

        old_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO("---\nid: x\n---\nbody")
            result = _read_content_file("-")
        finally:
            sys.stdin = old_stdin
        assert "---" in result

    def test_file_not_found(self):
        """不存在的文件应抛异常"""
        import pytest

        with pytest.raises(ValueError, match="文件不存在"):
            _read_content_file("/nonexistent/file.md")
