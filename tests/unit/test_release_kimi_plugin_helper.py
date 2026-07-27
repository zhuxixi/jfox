"""release_kimi_plugin_helper.py 单元测试"""

import importlib.util
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

HELPER = str(
    Path(__file__).resolve().parents[2]
    / ".claude"
    / "skills"
    / "release-kimi-plugin"
    / "release_kimi_plugin_helper.py"
)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run_helper(*args, env=None):
    e = env or {**os.environ, "PYTHONUTF8": "1"}
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
    spec = importlib.util.spec_from_file_location("release_kimi_plugin_helper", HELPER)
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

    def test_files_to_change_single(self):
        data = _parse_json(_run_helper("patch", "--dry-run")[0])
        assert data["files_to_change"] == ["packages/kimi-plugin/kimi.plugin.json"]

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

    def test_downgrade_rejected(self):
        cur = _parse_json(_run_helper("patch", "--dry-run")[0])["current_version"]
        parts = [int(x) for x in cur.split(".")]
        lower = f"{parts[0]}.{parts[1]}.{max(0, parts[2] - 1)}"
        stdout, _, rc = _run_helper(lower, "--dry-run")
        assert rc != 0
        assert "error" in _parse_json(stdout)

    def test_same_version_rejected(self):
        cur = _parse_json(_run_helper("patch", "--dry-run")[0])["current_version"]
        stdout, _, rc = _run_helper(cur, "--dry-run")
        assert rc != 0
        assert "error" in _parse_json(stdout)


# ── changelog：解析 git log（mock subprocess）──


class TestChangelog:
    def test_get_changelog_parses_git_log(self, tmp_path):
        mod = _load_helper_module()
        fake = MagicMock(stdout="abc1234 feat: x\ndef5678 fix: y\n", returncode=0)
        with patch.object(mod.subprocess, "run", return_value=fake):
            result = mod.get_changelog(tmp_path, "0.14.0")
        assert result == ["abc1234 feat: x", "def5678 fix: y"]


# ── bump 单字段 + 原子性（直接调函数，tmp 隔离）──


def _setup_repo(tmp_path: Path, ver="0.14.0"):
    p = tmp_path / "packages" / "kimi-plugin" / "kimi.plugin.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"name": "jfox", "version": ver}, indent=2), encoding="utf-8")
    return p


class TestBumpFiles:
    def test_bump_single_field(self, tmp_path):
        mod = _load_helper_module()
        p = _setup_repo(tmp_path)
        changed = mod.bump_version_files(tmp_path, "0.14.0", "0.15.0")
        assert json.loads(p.read_text(encoding="utf-8"))["version"] == "0.15.0"
        assert "kimi.plugin.json" in changed[0]

    def test_count_mismatch_no_write(self, tmp_path):
        """version 命中数 ≠ 1 → 报错且不写（原子性）"""
        mod = _load_helper_module()
        p = _setup_repo(tmp_path)
        txt = p.read_text(encoding="utf-8").replace(
            '"version": "0.14.0"', '"versionX": "0.14.0"', 1
        )
        p.write_text(txt, encoding="utf-8")
        with pytest.raises(ValueError):
            mod.bump_version_files(tmp_path, "0.14.0", "0.15.0")

    def test_rollback_on_write_failure(self, tmp_path):
        """写失败时回滚到原值（事务性）"""
        mod = _load_helper_module()
        p = _setup_repo(tmp_path)
        real_write = Path.write_text
        state = {"raised": False}

        def fake_write(self, data, **kw):
            # 只在写 kimi.plugin.json（新值）时抛一次
            if not state["raised"] and "0.15.0" in data:
                state["raised"] = True
                raise OSError("disk full (mock)")
            return real_write(self, data, **kw)

        with patch.object(Path, "write_text", fake_write):
            with pytest.raises(OSError):
                mod.bump_version_files(tmp_path, "0.14.0", "0.15.0")
        # 回滚后应保持 0.14.0
        assert json.loads(p.read_text(encoding="utf-8"))["version"] == "0.14.0"
