"""#363 status 的 backend 接线：daemon 值优先、三格式同源（A2/A3/A4）。"""

import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from jfox.cli import app
from jfox.embedding_backend import reset_backend

runner = CliRunner()

DAEMON = {
    "pid": 19793,
    "host": "127.0.0.1",
    "port": 18700,
    "model": "BAAI/bge-m3",
    "dimension": 1024,
    "device": "cuda",
    "started_at": None,
}


@pytest.fixture
def no_daemon():
    # 进程内 get_backend() 单例可能被前序用例加载过模型（顺序性）：重置以还原未加载态
    reset_backend()
    with (
        patch("jfox.daemon.process.get_daemon_status", return_value=None),
        patch("jfox.daemon.process.is_daemon_running", return_value=False),
    ):
        yield


@pytest.fixture
def running_daemon():
    with (
        patch("jfox.daemon.process.get_daemon_status", return_value=DAEMON),
        patch("jfox.daemon.process.is_daemon_running", return_value=True),
    ):
        yield


def _reset_global_config_cache():
    """进程内 runner 复用全局配置缓存：清掉以读到本用例刚注册的临时 KB。"""
    from jfox import global_config as gc
    from jfox import kb_manager as km

    km._kb_manager = None
    if gc._global_config_manager is not None:
        gc._global_config_manager._config = None
    gc._global_config_manager = None


def _invoke(cli, *args):
    result = runner.invoke(app, ["status", "--kb", cli.kb_name, *args])
    assert result.exit_code == 0, result.output
    return result


class TestDaemonRunning:
    """A2/A4：daemon 在跑时三格式都用 daemon 值。"""

    def test_json_backend_block(self, cli, running_daemon):
        _reset_global_config_cache()
        data = json.loads(_invoke(cli, "--json").output)

        assert data["backend"] == {
            "type": "cuda",
            "model": "BAAI/bge-m3",
            "dimension": 1024,
            "source": "daemon",
        }

    def test_daemon_model_not_shadowed_by_local_fallback(self, cli, running_daemon):
        _reset_global_config_cache()
        data = json.loads(_invoke(cli, "--json").output)

        assert data["backend"]["model"] != "auto (未加载)"

    def test_yaml_backend_block(self, cli, running_daemon):
        _reset_global_config_cache()
        out = _invoke(cli, "--format", "yaml").output

        assert "source: daemon" in out
        assert "dimension: 1024" in out

    def test_table_shows_source_row(self, cli, running_daemon):
        _reset_global_config_cache()
        out = _invoke(cli).output

        assert "Backend Source" in out
        assert "daemon" in out


class TestNoDaemon:
    """A3：无 daemon 时不伪造维度。"""

    def test_json_backend_block(self, cli, no_daemon):
        _reset_global_config_cache()
        data = json.loads(_invoke(cli, "--json").output)

        assert data["backend"]["source"] == "unloaded"
        assert data["backend"]["dimension"] is None
        assert data["backend"]["model"] == "auto (未加载)"

    def test_table_dimension_renders_unknown(self, cli, no_daemon):
        _reset_global_config_cache()
        out = _invoke(cli).output

        assert "Backend Source" in out
        assert "unloaded" in out
        assert "512" not in out
