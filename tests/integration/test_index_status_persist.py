"""#539 index status 持久化集成测试（in-process runner，模式同 test_index_kb_param）。"""

import json

from typer.testing import CliRunner

from jfox.cli import app

runner = CliRunner()


class TestIndexStatusFields:
    """A3：status 输出字段集合与 table 模式。"""

    @staticmethod
    def _reset_global_config_cache():
        from jfox import global_config as gc
        from jfox import kb_manager as km

        km._kb_manager = None
        if gc._global_config_manager is not None:
            gc._global_config_manager._config = None
        gc._global_config_manager = None

    def test_status_json_fields_no_dead_fields(self, cli):
        self._reset_global_config_cache()
        result = runner.invoke(app, ["index", "status", "--kb", cli.kb_name, "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["success"] is True
        assert set(data) == {"success", "vector_store", "bm25_indexed", "last_rebuild"}
        assert "total_indexed" not in data
        assert "pending_changes" not in data
        assert "last_indexed" not in data
        # 全新临时库无 rebuild 记录
        assert data["last_rebuild"] is None

    def test_status_table_mode_renders(self, cli):
        self._reset_global_config_cache()
        result = runner.invoke(app, ["index", "status", "--kb", cli.kb_name])
        assert result.exit_code == 0, result.output
        assert "Last Rebuild" in result.output
        assert "Total Indexed" not in result.output
