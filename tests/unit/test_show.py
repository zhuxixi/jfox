"""测试类型: 单元测试 / 目标模块: jfox.cli (show 命令)"""

import json as json_module
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
        mock_impl.assert_called_once_with("202604141200001234", "markdown")

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

        import io
        import sys

        from jfox.cli import _show_impl

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

    def test_to_show_dict_basic_fields(self):
        """测试 to_show_dict 基础字段 + content_body 剥 frontmatter"""
        from datetime import datetime
        from pathlib import Path

        from jfox.models import Note, NoteType

        raw = (
            "---\nid: '202604141200001234'\ntitle: 测试\n"
            "type: permanent\ncreated: '2026-04-14T12:00:00'\n"
            "updated: '2026-04-14T12:00:00'\ntags: []\n---\n\n# 测试\n\n正文内容"
        )
        n = Note(
            id="202604141200001234",
            title="测试",
            content="# 测试\n\n正文内容",
            type=NoteType.PERMANENT,
            created=datetime(2026, 4, 14, 12, 0, 0),
            updated=datetime(2026, 4, 14, 12, 0, 0),
            source_fragments=[1, 2],  # 跨类型溯源
            grounded_by=["202604141200009999"],  # 跨类型溯源
        )
        n.set_filepath(Path("/tmp/202604141200001234.md"))  # 固定路径，避免 config 依赖
        d = n.to_show_dict(raw_markdown=raw)
        assert d["id"] == "202604141200001234"
        assert d["title"] == "测试"
        assert d["type"] == "permanent"
        assert d["content"] == raw
        assert d["content_body"] == "# 测试\n\n正文内容"
        assert d["filepath"] == str(Path("/tmp/202604141200001234.md"))
        # 溯源字段跨类型输出（permanent 也输出，与 to_dict 一致）
        assert d["source_fragments"] == [1, 2]
        assert d["grounded_by"] == ["202604141200009999"]
        # source 为 None / archived 为 False 时不输出
        assert "source" not in d
        assert "archived" not in d

    def test_to_show_dict_candidate_fields(self):
        """测试 candidate 笔记含专属字段"""
        from datetime import datetime
        from pathlib import Path

        from jfox.models import GemLevel, Note, NoteType

        n = Note(
            id="202604141200001234",
            title="候选笔记",
            content="内容",
            type=NoteType.CANDIDATE,
            created=datetime(2026, 4, 14, 12, 0, 0),
            updated=datetime(2026, 4, 14, 12, 0, 0),
            confidence=0.8,
            knowledge_type="factual",
            status="pending",
            reject_reason="证据不足",
        )
        n.set_filepath(Path("/tmp/candidate.md"))  # 固定路径，避免 config 依赖
        d = n.to_show_dict()
        assert d["gem_level"] == GemLevel.FLAWED.value  # 默认 FLAWED
        assert d["confidence"] == 0.8
        assert d["knowledge_type"] == "factual"
        assert d["status"] == "pending"
        assert d["reject_reason"] == "证据不足"

    @patch("jfox.cli.note.load_note_by_id")
    @patch("jfox.cli.find_note_id_by_title_or_id")
    def test_show_impl_json_output(self, mock_find, mock_load):
        """测试 _show_impl JSON 模式输出结构化 JSON"""
        mock_find.return_value = "202604141200001234"
        raw_md = (
            "---\nid: '202604141200001234'\ntitle: 测试标题\ntype: permanent\n"
            "created: '2026-04-14T12:00:00'\nupdated: '2026-04-14T12:00:00'\n"
            "tags: [t1]\nlinks: []\nbacklinks: []\n---\n\n# 测试标题\n\n正文内容"
        )
        mock_note = MagicMock()
        mock_note.filepath.read_text.return_value = raw_md
        mock_note.to_show_dict.return_value = {
            "id": "202604141200001234",
            "title": "测试标题",
            "type": "permanent",
            "content": raw_md,
            "content_body": "# 测试标题\n\n正文内容",
        }
        mock_load.return_value = mock_note

        import io
        import sys

        from jfox.cli import _show_impl

        captured = io.StringIO()
        sys.stdout = captured
        try:
            _show_impl("测试笔记", output_format="json")
        finally:
            sys.stdout = sys.__stdout__

        data = json_module.loads(captured.getvalue())
        assert data["id"] == "202604141200001234"
        assert data["title"] == "测试标题"
        assert data["content_body"] == "# 测试标题\n\n正文内容"
        mock_note.to_show_dict.assert_called_once_with(raw_markdown=raw_md)

    @patch("jfox.cli._show_impl")
    def test_show_json_flag(self, mock_impl):
        """测试 --json 参数传递给 _show_impl"""
        result = runner.invoke(app, ["show", "202604141200001234", "--json"])
        assert result.exit_code == 0
        mock_impl.assert_called_once_with("202604141200001234", "json")

    @patch("jfox.cli._show_impl")
    def test_show_format_json(self, mock_impl):
        """测试 --format json 参数传递给 _show_impl"""
        result = runner.invoke(app, ["show", "202604141200001234", "--format", "json"])
        assert result.exit_code == 0
        mock_impl.assert_called_once_with("202604141200001234", "json")

    @patch("jfox.cli._show_impl", side_effect=ValueError("笔记不存在: xxx"))
    def test_show_json_error_output(self, mock_impl):
        """测试 JSON 模式下错误返回结构化 JSON"""
        result = runner.invoke(app, ["show", "xxx", "--json"])
        assert result.exit_code != 0
        data = json_module.loads(result.output)
        assert data["success"] is False
        assert "笔记不存在" in data["error"]
