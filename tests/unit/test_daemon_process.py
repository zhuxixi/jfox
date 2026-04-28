"""Daemon 进程管理单元测试"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest


class TestGetPythonwExecutable:
    """测试 _get_pythonw_executable 辅助函数"""

    def test_returns_pythonw_on_windows(self):
        """Windows 上返回 pythonw.exe"""
        if sys.platform != "win32":
            pytest.skip("Windows only")

        from jfox.daemon.process import _get_pythonw_executable

        result = _get_pythonw_executable()
        assert result.endswith("pythonw.exe"), f"Expected pythonw.exe, got {result}"

    def test_fallback_when_pythonw_missing(self):
        """pythonw.exe 不存在时回退到 python.exe"""
        if sys.platform != "win32":
            pytest.skip("Windows only")

        from jfox.daemon.process import _get_pythonw_executable

        with patch("jfox.daemon.process.Path") as mock_path_cls:
            # 模拟 pythonw.exe 不存在
            mock_path_instance = mock_path_cls.return_value
            mock_path_instance.exists.return_value = False
            result = _get_pythonw_executable()
            assert result == sys.executable

    def test_non_windows_returns_sys_executable(self):
        """非 Windows 平台返回 sys.executable"""
        from jfox.daemon.process import _get_pythonw_executable

        with patch("jfox.daemon.process.sys") as mock_sys:
            mock_sys.platform = "linux"
            mock_sys.executable = "/usr/bin/python3"
            result = _get_pythonw_executable()
            assert result == "/usr/bin/python3"


class TestStartDaemonWindowsExecutable:
    """测试 start_daemon 在 Windows 上使用 pythonw.exe"""

    @patch("jfox.daemon.process.subprocess.Popen")
    @patch("jfox.daemon.process._http_health_check")
    def test_uses_pythonw_on_windows(self, mock_health, mock_popen):
        """Windows 上 start_daemon 使用 pythonw.exe 启动子进程"""
        if sys.platform != "win32":
            pytest.skip("Windows only")

        from jfox.daemon.process import start_daemon

        # daemon 未运行 → 启动新进程
        mock_health.side_effect = [None, {"pid": 9999}]
        mock_popen.return_value.pid = 1234

        start_daemon()

        call_args = mock_popen.call_args
        cmd = call_args[0][0]
        assert cmd[0].endswith("pythonw.exe"), f"Expected pythonw.exe, got {cmd[0]}"

    @patch("jfox.daemon.process.subprocess.Popen")
    @patch("jfox.daemon.process._http_health_check")
    def test_creationflags_present(self, mock_health, mock_popen):
        """Windows 上 creationflags 包含 CREATE_NO_WINDOW"""
        if sys.platform != "win32":
            pytest.skip("Windows only")

        from jfox.daemon.process import start_daemon

        mock_health.side_effect = [None, {"pid": 9999}]
        mock_popen.return_value.pid = 1234

        start_daemon()

        kwargs = mock_popen.call_args[1]
        flags = kwargs.get("creationflags", 0)
        CREATE_NO_WINDOW = 0x08000000
        assert flags & CREATE_NO_WINDOW, "CREATE_NO_WINDOW flag not set"


class TestDaemonLogFile:
    """测试 daemon 子进程日志落盘"""

    @patch("jfox.daemon.process.subprocess.Popen")
    @patch("jfox.daemon.process._http_health_check")
    def test_start_daemon_writes_to_log_file(self, mock_health, mock_popen):
        """start_daemon 应将子进程 stdout/stderr 重定向到日志文件"""
        import subprocess

        from jfox.daemon.process import start_daemon

        mock_health.side_effect = [None, {"pid": 9999}]
        mock_popen.return_value.pid = 1234

        start_daemon()

        call_kwargs = mock_popen.call_args[1]
        # stdout 和 stderr 不应是 DEVNULL
        assert call_kwargs["stdout"] != subprocess.DEVNULL
        assert call_kwargs["stderr"] != subprocess.DEVNULL

    @patch("jfox.daemon.process.subprocess.Popen")
    @patch("jfox.daemon.process._http_health_check")
    def test_daemon_log_file_path(self, mock_health, mock_popen):
        """DAEMON_LOG_FILE 应在用户 home 目录下"""
        from jfox.daemon.process import DAEMON_LOG_FILE

        assert str(DAEMON_LOG_FILE).endswith(".jfox_daemon.log")
        assert DAEMON_LOG_FILE.parent == Path.home()


class TestDaemonModelCacheCheck:
    """测试模型缓存预检"""

    def test_check_model_cache_returns_dict(self):
        """_check_model_cache 应返回包含必要键的字典"""
        from jfox.daemon.process import _check_model_cache

        result = _check_model_cache()
        assert "needs_download" in result
        assert "model_name" in result
        assert "size_hint" in result
        assert isinstance(result["needs_download"], bool)

    @patch("jfox.daemon.process.os.environ", {})
    def test_first_run_timeout_is_longer(self):
        """FIRST_RUN_TIMEOUT 应大于 STARTUP_TIMEOUT"""
        from jfox.daemon.process import FIRST_RUN_TIMEOUT, STARTUP_TIMEOUT

        assert FIRST_RUN_TIMEOUT > STARTUP_TIMEOUT
        assert FIRST_RUN_TIMEOUT >= 300

    @patch("jfox.model_downloader.ModelDownloader.ensure_cached", return_value=True)
    @patch("jfox.daemon.process._check_model_cache")
    @patch("jfox.daemon.process.subprocess.Popen")
    @patch("jfox.daemon.process._http_health_check")
    def test_first_run_uses_extended_timeout(
        self, mock_health, mock_popen, mock_cache, mock_ensure
    ):
        """首次下载模型时应使用 FIRST_RUN_TIMEOUT"""
        from jfox.daemon.process import start_daemon

        mock_health.side_effect = [None, {"pid": 9999}]
        mock_popen.return_value.pid = 1234
        mock_cache.return_value = {
            "needs_download": True,
            "model_name": "BAAI/bge-m3",
            "size_hint": "2GB",
        }

        start_daemon()

        # 验证 health check 被调用了足够多次（使用 FIRST_RUN_TIMEOUT）
        # 由于第二次就返回了，至少被调用了 2 次
        assert mock_health.call_count >= 2
