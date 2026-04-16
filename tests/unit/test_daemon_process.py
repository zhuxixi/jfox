"""Daemon 进程管理单元测试"""
import sys
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
