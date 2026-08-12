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
    """dry-run：版本号计算与输出契约。"""

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
        # 动态取「大于当前」的版本，避免随 cc-plugin 发版后硬编码值过期
        # （#378 bump 到 0.7.3 后，旧硬编码 0.7.3 命中「不允许同号」护栏）
        cur = _parse_json(_run_helper("patch", "--dry-run")[0])["current_version"]
        parts = [int(x) for x in cur.split(".")]
        explicit = f"{parts[0]}.{parts[1]}.{parts[2] + 1}"
        data = _parse_json(_run_helper(explicit, "--dry-run")[0])
        assert data["new_version"] == explicit

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
    """非法输入与版本护栏校验。"""

    def test_invalid_bump_type(self):
        stdout, _, rc = _run_helper("foobar", "--dry-run")
        assert rc != 0
        assert "error" in _parse_json(stdout)

    def test_invalid_semver(self):
        stdout, _, rc = _run_helper("1.2", "--dry-run")
        assert rc != 0
        assert "error" in _parse_json(stdout)

    def test_explicit_downgrade_rejected(self):
        """explicit 版本低于当前应被拒（不允许降级）"""
        cur = _parse_json(_run_helper("patch", "--dry-run")[0])["current_version"]
        parts = [int(x) for x in cur.split(".")]
        lower = f"{parts[0]}.{parts[1]}.{max(0, parts[2] - 1)}"
        stdout, _, rc = _run_helper(lower, "--dry-run")
        assert rc != 0
        assert "error" in _parse_json(stdout)

    def test_same_version_rejected(self):
        """explicit 版本等于当前应被拒（不允许同号）"""
        cur = _parse_json(_run_helper("patch", "--dry-run")[0])["current_version"]
        stdout, _, rc = _run_helper(cur, "--dry-run")
        assert rc != 0
        assert "error" in _parse_json(stdout)


# ── changelog：解析 git log（mock subprocess）──


class TestChangelog:
    """changelog 解析（mock git log）。"""

    def test_get_changelog_parses_git_log(self, tmp_path):
        mod = _load_helper_module()
        fake = MagicMock(stdout="abc1234 feat: x\ndef5678 fix: y\n", returncode=0)
        with patch.object(mod.subprocess, "run", return_value=fake):
            result = mod.get_changelog(tmp_path, "0.5.1")
        assert result == ["abc1234 feat: x", "def5678 fix: y"]


# ── bump 三字段 + 原子性（直接调函数，tmp 隔离）──


def _setup_repo(tmp_path: Path, plugin_ver="0.5.1", market_versions=("0.5.1", "0.5.1")):
    """在 tmp_path 搭一个最小 plugin.json + marketplace.json"""
    plugin = tmp_path / "packages" / "cc-plugin" / ".claude-plugin" / "plugin.json"
    plugin.parent.mkdir(parents=True)
    plugin.write_text(
        json.dumps({"name": "jfox", "version": plugin_ver}, indent=2),
        encoding="utf-8",
    )
    market = tmp_path / ".claude-plugin" / "marketplace.json"
    market.parent.mkdir(parents=True)
    market.write_text(
        json.dumps(
            {
                "metadata": {"version": market_versions[0]},
                "plugins": [{"name": "jfox", "version": market_versions[1]}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return plugin, market


class TestBumpFiles:
    """bump 三字段 + 原子性/回滚（tmp 隔离）。"""

    def test_bump_all_three(self, tmp_path):
        mod = _load_helper_module()
        plugin, market = _setup_repo(tmp_path)
        changed = mod.bump_version_files(tmp_path, "0.5.1", "0.6.0")
        assert json.loads(plugin.read_text(encoding="utf-8"))["version"] == "0.6.0"
        m = json.loads(market.read_text(encoding="utf-8"))
        assert m["metadata"]["version"] == "0.6.0"
        assert m["plugins"][0]["version"] == "0.6.0"
        assert "plugin.json" in changed[0]
        assert "marketplace.json" in changed[1]

    def test_count_mismatch_no_write(self, tmp_path):
        """marketplace 命中数不符 → 报错且 plugin.json 不被改（原子性）"""
        mod = _load_helper_module()
        plugin, market = _setup_repo(tmp_path)
        # 把 marketplace 第一个 version 改掉，命中数从 2 变 1
        txt = market.read_text(encoding="utf-8").replace(
            '"version": "0.5.1"', '"versionX": "0.5.1"', 1
        )
        market.write_text(txt, encoding="utf-8")
        with pytest.raises(ValueError):
            mod.bump_version_files(tmp_path, "0.5.1", "0.6.0")
        # plugin.json 未被改动
        assert json.loads(plugin.read_text(encoding="utf-8"))["version"] == "0.5.1"

    def test_rollback_on_write_failure(self, tmp_path):
        """第二个文件写失败时，已写的第一个文件应回滚到原值（事务性）"""
        mod = _load_helper_module()
        plugin, market = _setup_repo(tmp_path)
        real_write = Path.write_text
        state = {"n": 0}

        def fake_write(self, data, **kw):
            state["n"] += 1
            if state["n"] == 2:  # 第二次写 = marketplace
                raise OSError("disk full (mock)")
            return real_write(self, data, **kw)

        with patch.object(Path, "write_text", fake_write):
            with pytest.raises(OSError):
                mod.bump_version_files(tmp_path, "0.5.1", "0.6.0")
        # plugin.json（先写的）应已回滚到 0.5.1
        assert json.loads(plugin.read_text(encoding="utf-8"))["version"] == "0.5.1"
