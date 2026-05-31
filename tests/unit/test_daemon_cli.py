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
    with patch("jfox.global_config.get_global_config_manager") as mock_get:
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

    def test_enable_flag_skips_prompt_and_enables(
        self, runner, mock_global_config, mock_start_daemon, mock_daemon_status
    ):
        """--enable-auto-summary 跳过询问，直接写入 enabled=True"""
        result = runner.invoke(app, ["daemon", "start", "--enable-auto-summary"])
        assert result.exit_code == 0
        mock_global_config.update_auto_summary_config.assert_called_once_with(enabled=True)

    def test_no_flag_skips_prompt_and_does_not_enable(
        self, runner, mock_global_config, mock_start_daemon, mock_daemon_status
    ):
        """--no-auto-summary 跳过询问，不写入配置"""
        result = runner.invoke(app, ["daemon", "start", "--no-auto-summary"])
        assert result.exit_code == 0
        mock_global_config.update_auto_summary_config.assert_not_called()

    def test_no_flags_enabled_true_skips_prompt(
        self, runner, mock_global_config, mock_start_daemon, mock_daemon_status
    ):
        """无 flag 且 enabled=True 时不询问也不写入"""
        cfg = mock_global_config.get_auto_summary_config.return_value
        cfg.enabled = True
        result = runner.invoke(app, ["daemon", "start"])
        assert result.exit_code == 0
        mock_global_config.update_auto_summary_config.assert_not_called()

    def test_no_flags_enabled_false_user_says_yes(
        self, runner, mock_global_config, mock_start_daemon, mock_daemon_status
    ):
        """无 flag 且 enabled=false，用户选 yes → 写入 enabled=True"""
        with patch("jfox.cli.os.isatty", return_value=True):
            result = runner.invoke(app, ["daemon", "start"], input="y\n")
        assert result.exit_code == 0
        mock_global_config.update_auto_summary_config.assert_called_once_with(enabled=True)

    def test_no_flags_enabled_false_user_says_no(
        self, runner, mock_global_config, mock_start_daemon, mock_daemon_status
    ):
        """无 flag 且 enabled=false，用户选 no → 不写入"""
        with patch("jfox.cli.os.isatty", return_value=True):
            result = runner.invoke(app, ["daemon", "start"], input="n\n")
        assert result.exit_code == 0
        mock_global_config.update_auto_summary_config.assert_not_called()

    def test_no_flags_non_tty_skips_prompt(
        self, runner, mock_global_config, mock_start_daemon, mock_daemon_status
    ):
        """非 TTY 环境下不询问，不写入配置"""
        with patch("jfox.cli.os.isatty", return_value=False):
            result = runner.invoke(app, ["daemon", "start"])
        assert result.exit_code == 0
        mock_global_config.update_auto_summary_config.assert_not_called()


class TestDaemonRestartAutoSummaryFlags:
    """测试 daemon restart 的 auto-summary flag 处理"""

    def test_restart_no_flags_keeps_config(
        self, runner, mock_global_config, mock_restart_daemon, mock_daemon_status
    ):
        """restart 无 flag 时保持当前配置"""
        result = runner.invoke(app, ["daemon", "restart"])
        assert result.exit_code == 0
        mock_global_config.update_auto_summary_config.assert_not_called()

    def test_restart_enable_flag_sets_enabled(
        self, runner, mock_global_config, mock_restart_daemon, mock_daemon_status
    ):
        """restart --enable-auto-summary 写入 enabled=True"""
        result = runner.invoke(app, ["daemon", "restart", "--enable-auto-summary"])
        assert result.exit_code == 0
        mock_global_config.update_auto_summary_config.assert_called_once_with(enabled=True)

    def test_restart_no_flag_sets_disabled(
        self, runner, mock_global_config, mock_restart_daemon, mock_daemon_status
    ):
        """restart --no-auto-summary 写入 enabled=False"""
        result = runner.invoke(app, ["daemon", "restart", "--no-auto-summary"])
        assert result.exit_code == 0
        mock_global_config.update_auto_summary_config.assert_called_once_with(enabled=False)

    def test_restart_no_prompt(
        self, runner, mock_global_config, mock_restart_daemon, mock_daemon_status
    ):
        """restart 不会触发交互式询问"""
        cfg = mock_global_config.get_auto_summary_config.return_value
        cfg.enabled = False
        # 不提供 input — 如果有 prompt 会导致超时或 hang
        result = runner.invoke(app, ["daemon", "restart"])
        assert result.exit_code == 0
        mock_global_config.update_auto_summary_config.assert_not_called()
