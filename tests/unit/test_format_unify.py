"""
单元测试：CLI 命令 --format 统一迁移

测试 init, add, delete, edit 命令的 --format/--json 参数支持
"""

import json
from unittest.mock import patch

import pytest

from jfox.config import ZKConfig
from jfox.models import NoteType

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


class TestDeleteFormat:
    """测试 delete 命令的 --format 支持"""

    def _make_config(self, tmp_path):
        cfg = ZKConfig(base_dir=tmp_path)
        cfg.ensure_dirs()
        return cfg

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    @patch("jfox.note.get_vector_store")
    def test_delete_output_format_json(
        self, mock_vs, mock_global_config, mock_note_config, tmp_path, capsys
    ):
        """delete 命令 output_format='json' 应输出 JSON"""
        from jfox.cli import _delete_impl
        from jfox.note import create_note, save_note

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        n = create_note("to delete", title="DeleteMe", note_type=NoteType.PERMANENT)
        save_note(n, add_to_index=False)

        _delete_impl(n.id, force=True, output_format="json")

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["success"] is True
        assert data["deleted"] == n.id

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    @patch("jfox.note.get_vector_store")
    def test_delete_output_format_table(
        self, mock_vs, mock_global_config, mock_note_config, tmp_path, capsys
    ):
        """delete 命令 output_format='table' 应输出紧凑表格"""
        from jfox.cli import _delete_impl
        from jfox.note import create_note, save_note

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        n = create_note("to delete", title="TableDel", note_type=NoteType.PERMANENT)
        save_note(n, add_to_index=False)

        _delete_impl(n.id, force=True, output_format="table")

        captured = capsys.readouterr()
        assert not captured.out.strip().startswith("{")
        assert "TableDel" in captured.out

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_delete_cli_signature_has_format(self, mock_global_config, mock_note_config, tmp_path):
        """delete CLI 函数应接受 --format 参数"""
        import inspect

        from jfox.cli import delete

        sig = inspect.signature(delete)
        assert "output_format" in sig.parameters
        param = sig.parameters["output_format"]
        if hasattr(param.default, "default"):
            assert param.default.default == "table"
        else:
            assert param.default == "table"


class TestEditFormat:
    """测试 edit 命令的 --format 支持"""

    def _make_config(self, tmp_path):
        cfg = ZKConfig(base_dir=tmp_path)
        cfg.ensure_dirs()
        return cfg

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    @patch("jfox.note.get_vector_store")
    def test_edit_output_format_json(
        self, mock_vs, mock_global_config, mock_note_config, tmp_path, capsys
    ):
        """edit 命令 output_format='json' 应输出 JSON"""
        from jfox.cli import _edit_impl
        from jfox.note import create_note, save_note

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        n = create_note("original", title="EditMe", note_type=NoteType.PERMANENT)
        save_note(n, add_to_index=False)

        _edit_impl(
            note_id=n.id,
            content="updated",
            content_file=None,
            title=None,
            tags=None,
            note_type=None,
            source=None,
            output_format="json",
        )

        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["success"] is True
        assert data["note"]["title"] == "EditMe"

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    @patch("jfox.note.get_vector_store")
    def test_edit_output_format_table(
        self, mock_vs, mock_global_config, mock_note_config, tmp_path, capsys
    ):
        """edit 命令 output_format='table' 应输出紧凑表格"""
        from jfox.cli import _edit_impl
        from jfox.note import create_note, save_note

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        n = create_note("original", title="TableEdit", note_type=NoteType.PERMANENT)
        save_note(n, add_to_index=False)

        _edit_impl(
            note_id=n.id,
            content="new content",
            content_file=None,
            title="NewTitle",
            tags=None,
            note_type=None,
            source=None,
            output_format="table",
        )

        captured = capsys.readouterr()
        assert not captured.out.strip().startswith("{")
        assert "NewTitle" in captured.out

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_edit_cli_signature_has_format(self, mock_global_config, mock_note_config, tmp_path):
        """edit CLI 函数应接受 --format 参数"""
        import inspect

        from jfox.cli import edit

        sig = inspect.signature(edit)
        assert "output_format" in sig.parameters
        param = sig.parameters["output_format"]
        if hasattr(param.default, "default"):
            assert param.default.default == "table"
        else:
            assert param.default == "table"


class TestInitFormat:
    """测试 init 命令的 --format 支持"""

    def test_init_cli_signature_has_format(self):
        """init CLI 函数应接受 --format 参数"""
        import inspect

        from jfox.cli import init

        sig = inspect.signature(init)
        assert "output_format" in sig.parameters
        param = sig.parameters["output_format"]
        if hasattr(param.default, "default"):
            assert param.default.default == "table"
        else:
            assert param.default == "table"

    def test_init_cli_signature_json_backward_compat(self):
        """init CLI 函数应保留 --json 向后兼容"""
        import inspect

        from jfox.cli import init

        sig = inspect.signature(init)
        assert "json_output" in sig.parameters
        param = sig.parameters["json_output"]
        if hasattr(param.default, "default"):
            assert param.default.default is False
        else:
            assert param.default is False
