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
        assert result.endswith("pythonw.exe") or result.endswith("python.exe")

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
