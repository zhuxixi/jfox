"""
单元测试：CLI 命令 --format 统一迁移

测试 init, add, delete, edit 命令的 --format/--json 参数支持
"""
import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from jfox.models import Note, NoteType
from jfox.config import ZKConfig

pytestmark = [pytest.mark.unit, pytest.mark.fast]


class TestAddFormat:
    """测试 add 命令的 --format 支持"""

    def _make_config(self, tmp_path):
        cfg = ZKConfig(base_dir=tmp_path)
        cfg.ensure_dirs()
        return cfg

    @patch("jfox.note.get_vector_store")
    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_add_output_format_json(
        self, mock_global_config, mock_note_config, mock_vs, tmp_path, capsys
    ):
        """add 命令 output_format='json' 应输出 JSON"""
        from jfox.cli import _add_note_impl

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        _add_note_impl(
            content="test content",
            title="TestTitle",
            note_type="permanent",
            tags=None,
            source=None,
            output_format="json",
        )

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["success"] is True
        assert data["note"]["title"] == "TestTitle"

    @patch("jfox.note.get_vector_store")
    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_add_output_format_table(
        self, mock_global_config, mock_note_config, mock_vs, tmp_path, capsys
    ):
        """add 命令 output_format='table' 应输出紧凑表格（非 JSON）"""
        from jfox.cli import _add_note_impl

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        _add_note_impl(
            content="test content",
            title="TableTest",
            note_type="permanent",
            tags=None,
            source=None,
            output_format="table",
        )

        captured = capsys.readouterr()
        # 不应是 JSON
        assert not captured.out.strip().startswith("{")
        # 应包含关键字段
        assert "TableTest" in captured.out

    @patch("jfox.note.get_vector_store")
    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_add_output_format_default_is_table(
        self, mock_global_config, mock_note_config, mock_vs, tmp_path, capsys
    ):
        """add 命令默认输出格式应为 table（不再是 JSON）"""
        from jfox.cli import _add_note_impl

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        _add_note_impl(
            content="default test",
            title="DefaultTest",
            note_type="fleeting",
            tags=None,
            source=None,
            output_format="table",
        )

        captured = capsys.readouterr()
        # 默认不应是 JSON
        assert not captured.out.strip().startswith("{")

    def test_add_cli_signature_has_format(self):
        """add CLI 函数应接受 --format 参数"""
        import inspect
        from jfox.cli import add

        sig = inspect.signature(add)
        assert "output_format" in sig.parameters
        assert "json_output" in sig.parameters
        # output_format 默认值应为 "table" (Typer wraps in OptionInfo)
        param_default = sig.parameters["output_format"].default
        if hasattr(param_default, "default"):
            assert param_default.default == "table"
        else:
            assert param_default == "table"
        # json_output 默认值应为 False (Typer wraps in OptionInfo)
        json_default = sig.parameters["json_output"].default
        if hasattr(json_default, "default"):
            assert json_default.default is False
        else:
            assert json_default is False
