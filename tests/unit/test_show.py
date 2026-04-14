"""Unit tests for show command"""

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from jfox.cli import app

pytestmark = [pytest.mark.unit, pytest.mark.fast]

runner = CliRunner()


class TestShowCommand:
    """测试 show 命令"""

    @patch("jfox.cli._show_impl")
    def test_show_calls_impl(self, mock_impl):
        """测试 show 命令调用 _show_impl"""
        result = runner.invoke(app, ["show", "202604141200001234"])
        assert result.exit_code == 0
        mock_impl.assert_called_once_with("202604141200001234")

    @patch("jfox.cli._show_impl", side_effect=ValueError("笔记不存在: xxx"))
    def test_show_not_found(self, mock_impl):
        """测试笔记不存在时的错误处理"""
        result = runner.invoke(app, ["show", "xxx"])
        assert result.exit_code != 0

    @patch("jfox.cli._show_impl")
    def test_show_with_kb(self, mock_impl):
        """测试 --kb 参数传递"""
        # use_kb 在 show 函数内部通过 `from .config import use_kb` 导入，
        # 因此需要在 jfox.config 模块上打补丁
        with patch("jfox.config.use_kb") as mock_use_kb:
            mock_use_kb.return_value.__enter__ = MagicMock()
            mock_use_kb.return_value.__exit__ = MagicMock(return_value=False)
            result = runner.invoke(app, ["show", "test-note", "--kb", "mykb"])
            assert result.exit_code == 0
            mock_use_kb.assert_called_once_with("mykb")

    @patch("jfox.cli.note.load_note_by_id")
    @patch("jfox.cli.find_note_id_by_title_or_id")
    def test_show_impl_reads_file(self, mock_find, mock_load):
        """测试 _show_impl 读取并输出文件内容"""
        mock_find.return_value = "202604141200001234"
        mock_note = MagicMock()
        mock_note.filepath.read_text.return_value = "---\nid: test\n---\n笔记内容"
        mock_load.return_value = mock_note

        from jfox.cli import _show_impl

        import io
        import sys

        captured = io.StringIO()
        sys.stdout = captured
        try:
            _show_impl("测试笔记")
        finally:
            sys.stdout = sys.__stdout__

        assert "笔记内容" in captured.getvalue()
        mock_note.filepath.read_text.assert_called_once_with(encoding="utf-8")

    @patch("jfox.cli.find_note_id_by_title_or_id", return_value=None)
    def test_show_impl_not_found(self, mock_find):
        """测试 _show_impl 笔记不存在时抛出异常"""
        from jfox.cli import _show_impl

        with pytest.raises(ValueError, match="nonexistent"):
            _show_impl("nonexistent")
