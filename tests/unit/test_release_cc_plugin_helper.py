"""release_cc_plugin_helper.py 单元测试"""
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 被测模块路径
HELPER = str(
    Path(__file__).resolve().parents[2]
    / ".claude"
    / "skills"
    / "release-cc-plugin"
    / "release_cc_plugin_helper.py"
)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run_helper(*args, env=None):
    """运行 helper 并返回 (stdout, stderr, returncode)"""
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


def _load_helper_module():
    """importlib 加载 helper 模块，用于直接测函数（写盘/原子性需隔离）"""
    spec = importlib.util.spec_from_file_location("release_cc_plugin_helper", HELPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── dry-run：版本计算 ──


class TestDryRun:
    def test_current_version_is_semver(self):
        stdout, _, rc = _run_helper("patch", "--dry-run")
        assert rc == 0, f"stderr: {_}"
        cur = _parse_json(stdout)["current_version"].split(".")
        assert len(cur) == 3 and all(p.isdigit() for p in cur)

    def test_patch_bump(self):
        data = _parse_json(_run_helper("patch", "--dry-run")[0])
        cur = [int(x) for x in data["current_version"].split(".")]
        new = [int(x) for x in data["new_version"].split(".")]
        assert new == [cur[0], cur[1], cur[2] + 1]

    def test_minor_bump(self):
        data = _parse_json(_run_helper("minor", "--dry-run")[0])
        cur = [int(x) for x in data["current_version"].split(".")]
        new = [int(x) for x in data["new_version"].split(".")]
        assert new == [cur[0], cur[1] + 1, 0]

    def test_major_bump(self):
        data = _parse_json(_run_helper("major", "--dry-run")[0])
        cur = [int(x) for x in data["current_version"].split(".")]
        new = [int(x) for x in data["new_version"].split(".")]
        assert new == [cur[0] + 1, 0, 0]

    def test_explicit_version(self):
        data = _parse_json(_run_helper("0.7.3", "--dry-run")[0])
        assert data["new_version"] == "0.7.3"

    def test_files_to_change_lists_two(self):
        data = _parse_json(_run_helper("patch", "--dry-run")[0])
        assert data["files_to_change"] == [
            "packages/cc-plugin/.claude-plugin/plugin.json",
            ".claude-plugin/marketplace.json",
        ]

    def test_changelog_is_list(self):
        data = _parse_json(_run_helper("patch", "--dry-run")[0])
        assert isinstance(data["changelog_summary"], list)


# ── 校验：非法输入 ──


class TestValidation:
    def test_invalid_bump_type(self):
        stdout, _, rc = _run_helper("foobar", "--dry-run")
        assert rc != 0
        assert "error" in _parse_json(stdout)

    def test_invalid_semver(self):
        stdout, _, rc = _run_helper("1.2", "--dry-run")
        assert rc != 0
        assert "error" in _parse_json(stdout)


# ── changelog：解析 git log（mock subprocess）──


class TestChangelog:
    def test_get_changelog_parses_git_log(self, tmp_path):
        mod = _load_helper_module()
        fake = MagicMock(stdout="abc1234 feat: x\ndef5678 fix: y\n", returncode=0)
        with patch.object(mod.subprocess, "run", return_value=fake):
            result = mod.get_changelog(tmp_path, "0.5.1")
        assert result == ["abc1234 feat: x", "def5678 fix: y"]
