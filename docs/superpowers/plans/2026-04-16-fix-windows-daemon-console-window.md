# Fix Windows Daemon Console Window Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `jfox daemon start` on Windows so it spawns no visible console window when using Microsoft Store Python.

**Architecture:** Replace `python.exe` with `pythonw.exe` in the subprocess command on Windows. Add a helper function with fallback to `python.exe` if `pythonw.exe` doesn't exist. Keep existing `CREATE_NO_WINDOW` flags as defense-in-depth.

**Tech Stack:** Python 3.10+, subprocess, pathlib

---

### Task 1: Add `_get_pythonw_executable` helper and test

**Files:**
- Modify: `jfox/daemon/process.py:1-22` (add helper after imports)
- Create: `tests/unit/test_daemon_process.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_daemon_process.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_daemon_process.py -v -k "test_returns_pythonw_on_windows or test_fallback_when_pythonw_missing or test_non_windows_returns" --no-header`
Expected: FAIL with `ImportError: cannot import name '_get_pythonw_executable'`

- [ ] **Step 3: Write minimal implementation**

Add to `jfox/daemon/process.py` after the imports (after line 17), before `logger = logging.getLogger(__name__)`:

```python
def _get_pythonw_executable() -> str:
    """获取 pythonw.exe 路径（Windows 无控制台入口）

    Windows 上优先使用 pythonw.exe 避免 daemon 子进程弹出控制台窗口。
    如果 pythonw.exe 不存在则回退到 sys.executable。
    非 Windows 平台直接返回 sys.executable。
    """
    if sys.platform != "win32":
        return sys.executable

    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    if pythonw != sys.executable and Path(pythonw).exists():
        return pythonw
    return sys.executable
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_daemon_process.py -v --no-header`
Expected: all 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/daemon/process.py tests/unit/test_daemon_process.py
git commit -m "feat(daemon): add _get_pythonw_executable helper for Windows"
```

---

### Task 2: Use `_get_pythonw_executable` in `start_daemon`

**Files:**
- Modify: `jfox/daemon/process.py:111` (change cmd construction)
- Modify: `tests/unit/test_daemon_process.py` (add test)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_daemon_process.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_daemon_process.py -v -k "test_uses_pythonw_on_windows" --no-header`
Expected: FAIL — `cmd[0]` is `python.exe`, not `pythonw.exe`

- [ ] **Step 3: Update `start_daemon` to use the helper**

In `jfox/daemon/process.py`, replace line 111:

```python
    # 构建启动命令
    cmd = [sys.executable, "-m", "jfox.daemon.server", "--host", host, "--port", str(port)]
```

with:

```python
    # 构建启动命令（Windows 使用 pythonw.exe 避免控制台窗口）
    cmd = [_get_pythonw_executable(), "-m", "jfox.daemon.server", "--host", host, "--port", str(port)]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_daemon_process.py -v --no-header`
Expected: all 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/daemon/process.py tests/unit/test_daemon_process.py
git commit -m "fix(daemon): use pythonw.exe to prevent console window on Windows

Closes #159"
```

---

## Self-Review

**1. Spec coverage:** Issue #159 要求用 `pythonw.exe` 替代 `python.exe`，Task 2 实现了这一点。fallback 逻辑在 Task 1 的 helper 中。`creationflags` 保留在 Task 2 中验证。

**2. Placeholder scan:** 无 TBD/TODO。所有步骤都有完整代码和命令。

**3. Type consistency:** `_get_pythonw_executable()` 返回 `str`，与 `sys.executable` 类型一致，直接用于 `cmd` 列表第一个元素。
