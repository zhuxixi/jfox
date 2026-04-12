"""Tests for jfox index --kb parameter support (issue #104)"""

import json

import pytest
from typer.testing import CliRunner

from jfox.cli import app

runner = CliRunner()


class TestIndexKbParamErrors:
    """验证 --kb 参数错误处理"""

    def test_status_with_nonexistent_kb_returns_error(self):
        """--kb 指向不存在的知识库时应报错"""
        result = runner.invoke(app, ["index", "status", "--kb", "nonexistent_kb_104"])
        assert result.exit_code != 0
        output_lower = result.output.lower()
        assert "nonexistent_kb_104" in output_lower or "not found" in output_lower

    def test_verify_with_nonexistent_kb_returns_error(self):
        """index verify --kb <不存在的知识库> 应报错"""
        result = runner.invoke(app, ["index", "verify", "--kb", "nonexistent_kb_104"])
        assert result.exit_code != 0
        output_lower = result.output.lower()
        assert "nonexistent_kb_104" in output_lower or "not found" in output_lower

    def test_rebuild_with_nonexistent_kb_returns_error(self):
        """index rebuild --kb <不存在的知识库> 应报错"""
        result = runner.invoke(app, ["index", "rebuild", "--kb", "nonexistent_kb_104"])
        assert result.exit_code != 0
        output_lower = result.output.lower()
        assert "nonexistent_kb_104" in output_lower or "not found" in output_lower

    def test_rebuild_bm25_with_nonexistent_kb_returns_error(self):
        """index rebuild-bm25 --kb <不存在的知识库> 应报错"""
        result = runner.invoke(app, ["index", "rebuild-bm25", "--kb", "nonexistent_kb_104"])
        assert result.exit_code != 0
        output_lower = result.output.lower()
        assert "nonexistent_kb_104" in output_lower or "not found" in output_lower

    def test_bm25_status_with_nonexistent_kb_returns_error(self):
        """index bm25-status --kb <不存在的知识库> 应报错"""
        result = runner.invoke(app, ["index", "bm25-status", "--kb", "nonexistent_kb_104"])
        assert result.exit_code != 0
        output_lower = result.output.lower()
        assert "nonexistent_kb_104" in output_lower or "not found" in output_lower


@pytest.mark.embedding
class TestIndexKbParamSuccess:
    """验证 --kb 参数正常功能"""

    @staticmethod
    def _reset_global_config_cache():
        """清除全局配置缓存，使 subprocess 注册的 KB 可被 runner.invoke 看到。

        cli fixture 通过 subprocess 调用 jfox init 注册 KB，但 runner.invoke
        在同一进程内运行，GlobalConfigManager 的缓存可能不包含新注册的 KB。
        需要同时清除 kb_manager 和 global_config_manager 的缓存实例。
        """
        from jfox import global_config as gc
        from jfox import kb_manager as km

        km._kb_manager = None
        if gc._global_config_manager is not None:
            gc._global_config_manager._config = None
        gc._global_config_manager = None

    def test_status_with_valid_kb(self, cli):
        """index status --kb <存在的知识库> 应正常执行"""
        self._reset_global_config_cache()
        result = runner.invoke(app, ["index", "status", "--kb", cli.kb_name, "--json"])
        assert result.exit_code == 0, f"Expected success but got: {result.output}"
        data = json.loads(result.output.strip())
        assert "total_indexed" in data

    def test_verify_with_valid_kb(self, cli):
        """index verify --kb <存在的知识库> 应正常执行"""
        self._reset_global_config_cache()
        result = runner.invoke(app, ["index", "verify", "--kb", cli.kb_name, "--json"])
        assert result.exit_code == 0, f"Expected success but got: {result.output}"
        data = json.loads(result.output.strip())
        assert "healthy" in data

    def test_default_kb_not_affected(self, cli):
        """不传 --kb 时行为与修改前一致"""
        self._reset_global_config_cache()
        result = runner.invoke(app, ["index", "status", "--json"])
        assert result.exit_code == 0
