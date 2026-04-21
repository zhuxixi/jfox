"""release_helper.py 单元测试"""
import json
import os
import subprocess
from pathlib import Path

import pytest

# 被测模块路径
HELPER = str(
    Path(__file__).resolve().parents[2] / ".claude" / "skills" / "release" / "release_helper.py"
)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run_helper(*args, env=None):
    """运行 release_helper.py 并返回 (stdout, stderr, returncode)"""
    e = env or os.environ.copy()
    e["PYTHONUTF8"] = "1"
    result = subprocess.run(
        ["python", HELPER, *args],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        env=e,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout, result.stderr, result.returncode


def _parse_json(stdout: str) -> dict:
    return json.loads(stdout.strip())


# ── 版本号计算 ──


class TestVersionParsing:
    """测试从 pyproject.toml 读取当前版本"""

    def test_read_current_version(self):
        """能正确读取当前项目版本"""
        stdout, _, rc = _run_helper("patch", "--dry-run")
        assert rc == 0, f"stderr: {_.strip()}"
        data = _parse_json(stdout)
        assert "current_version" in data
        # 验证是 semver 格式
        parts = data["current_version"].split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)


class TestVersionBump:
    """测试 bump 类型版本号计算"""

    def test_patch_bump(self):
        stdout, _, rc = _run_helper("patch", "--dry-run")
        assert rc == 0
        data = _parse_json(stdout)
        cur = [int(x) for x in data["current_version"].split(".")]
        new = [int(x) for x in data["new_version"].split(".")]
        assert new[0] == cur[0]
        assert new[1] == cur[1]
        assert new[2] == cur[2] + 1  # patch +1

    def test_minor_bump(self):
        stdout, _, rc = _run_helper("minor", "--dry-run")
        assert rc == 0
        data = _parse_json(stdout)
        cur = [int(x) for x in data["current_version"].split(".")]
        new = [int(x) for x in data["new_version"].split(".")]
        assert new[0] == cur[0]
        assert new[1] == cur[1] + 1
        assert new[2] == 0

    def test_major_bump(self):
        stdout, _, rc = _run_helper("major", "--dry-run")
        assert rc == 0
        data = _parse_json(stdout)
        cur = [int(x) for x in data["current_version"].split(".")]
        new = [int(x) for x in data["new_version"].split(".")]
        assert new[0] == cur[0] + 1
        assert new[1] == 0
        assert new[2] == 0

    def test_explicit_version(self):
        stdout, _, rc = _run_helper("99.99.99", "--dry-run")
        assert rc == 0
        data = _parse_json(stdout)
        assert data["new_version"] == "99.99.99"


class TestVersionValidation:
    """测试版本号校验"""

    def test_invalid_bump_type(self):
        stdout, _, rc = _run_helper("foobar")
        assert rc != 0
        data = _parse_json(stdout)
        assert "error" in data

    def test_same_version_rejected(self):
        """指定当前版本应被拒绝"""
        stdout, _, rc = _run_helper("patch", "--dry-run")
        data = _parse_json(stdout)
        current = data["current_version"]
        stdout2, _, rc2 = _run_helper(current)
        assert rc2 != 0
        data2 = _parse_json(stdout2)
        assert "error" in data2

    def test_lower_version_rejected(self):
        """指定比当前更低的版本应被拒绝"""
        stdout, _, _ = _run_helper("patch", "--dry-run")
        data = _parse_json(stdout)
        cur_parts = [int(x) for x in data["current_version"].split(".")]
        lower = f"{cur_parts[0]}.{cur_parts[1]}.{max(0, cur_parts[2] - 1)}"
        stdout2, _, rc = _run_helper(lower)
        assert rc != 0
        data2 = _parse_json(stdout2)
        assert "error" in data2

    def test_invalid_semver_rejected(self):
        """非 semver 格式应被拒绝"""
        stdout, _, rc = _run_helper("1.2")
        assert rc != 0
        data = _parse_json(stdout)
        assert "error" in data
