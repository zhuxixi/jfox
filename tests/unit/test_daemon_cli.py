"""daemon start/restart --enable-auto-summary / --no-auto-summary 交互逻辑测试"""

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from jfox.cli import app


@pytest.fixture
def runner():
    return CliRunner()


@pytest.fixture
def mock_global_config():
    """Mock GlobalConfigManager，默认 auto_summary.enabled=False"""
    with patch("jfox.cli.get_global_config_manager") as mock_get:
        mgr = MagicMock()
        cfg = MagicMock()
        cfg.enabled = False
        mgr.get_auto_summary_config.return_value = cfg
        mgr.update_auto_summary_config.return_value = True
        mock_get.return_value = mgr
        yield mgr


@pytest.fixture
def mock_start_daemon():
    with patch("jfox.daemon.process.start_daemon", return_value=True):
        yield


@pytest.fixture
def mock_restart_daemon():
    with patch("jfox.daemon.process.restart_daemon", return_value=True):
        yield


@pytest.fixture
def mock_daemon_status():
    with patch(
        "jfox.daemon.process.get_daemon_status",
        return_value={
            "pid": 1234,
            "port": 18700,
            "model": "test",
            "dimension": 384,
            "device": "cpu",
        },
    ):
        yield


class TestDaemonStartAutoSummaryFlags:
    """测试 --enable-auto-summary 和 --no-auto-summary 参数"""

    def test_both_flags_mutually_exclusive(self, runner):
        """同时传 --enable-auto-summary 和 --no-auto-summary 应报错"""
        result = runner.invoke(
            app, ["daemon", "start", "--enable-auto-summary", "--no-auto-summary"]
        )
        assert result.exit_code != 0
