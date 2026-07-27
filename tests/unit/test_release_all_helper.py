"""release_all_helper.py detect 测试"""

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
    / "release-all"
    / "release_all_helper.py"
)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _load_helper_module():
    spec = importlib.util.spec_from_file_location("release_all_helper", HELPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git_repo(tmp_path: Path):
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True, env=_GIT_ENV)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(tmp_path), check=True)


def _commit(tmp_path: Path, msg: str, files: dict):
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=str(tmp_path), check=True, env=_GIT_ENV)


def _pyproject(ver):
    return f'version = "{ver}"\n'


def _plugin_json(ver):
    return json.dumps({"name": "jfox", "version": ver}, indent=2)


def _marketplace(ver):
    return json.dumps(
        {"metadata": {"version": ver}, "plugins": [{"name": "jfox", "version": ver}]},
        indent=2,
    )


def _kimi_json(ver):
    return json.dumps({"name": "jfox", "version": ver}, indent=2)


def _bootstrap_all(tmp_path, jfox="1.5.0", cc="0.6.0", kimi="0.14.0"):
    """搭一个含三组件版本文件 + jfox tag + cc/kimi bump commit 的最小仓。"""
    _git_repo(tmp_path)
    _commit(
        tmp_path,
        "chore: bump version to " + jfox,
        {"pyproject.toml": _pyproject(jfox), "jfox/__init__.py": f'__version__ = "{jfox}"\n'},
    )
    subprocess.run(["git", "tag", "v" + jfox], cwd=str(tmp_path), check=True)
    _commit(
        tmp_path,
        f"chore(cc-plugin): bump version 0.5.1 → {cc}",
        {
            "packages/cc-plugin/.claude-plugin/plugin.json": _plugin_json(cc),
            ".claude-plugin/marketplace.json": _marketplace(cc),
        },
    )
    _commit(
        tmp_path,
        f"chore(kimi-plugin): bump version 0.13.0 → {kimi}",
        {"packages/kimi-plugin/kimi.plugin.json": _kimi_json(kimi)},
    )


class TestDetectJfox:
    def test_unchanged_when_no_commit_since_tag(self, tmp_path):
        mod = _load_helper_module()
        _bootstrap_all(tmp_path)
        res = mod.detect_jfox(tmp_path)
        assert res["changed"] is False
        assert "无改动" in res["skip_reason"]

    def test_changed_with_feat_suggests_minor(self, tmp_path):
        mod = _load_helper_module()
        _bootstrap_all(tmp_path)
        _commit(tmp_path, "feat(x): new (#101)", {"jfox/x.py": "1"})
        res = mod.detect_jfox(tmp_path)
        assert res["changed"] is True
        assert res["suggested_bump"] == "minor"
        assert res["suggested_version"] == "1.6.0"

    def test_changed_with_fix_suggests_patch(self, tmp_path):
        mod = _load_helper_module()
        _bootstrap_all(tmp_path)
        _commit(tmp_path, "fix(x): bug (#102)", {"jfox/y.py": "1"})
        res = mod.detect_jfox(tmp_path)
        assert res["changed"] is True
        assert res["suggested_bump"] == "patch"
        assert res["suggested_version"] == "1.5.1"

    def test_plugin_bump_commits_not_counted_as_jfox(self, tmp_path):
        """cc/kimi bump commit 在 jfox tag..HEAD 内，但含 'bump version' 应被滤掉"""
        mod = _load_helper_module()
        _bootstrap_all(tmp_path)
        res = mod.detect_jfox(tmp_path)
        assert res["changed"] is False


class TestDetectCcKimi:
    def test_cc_unchanged_then_changed(self, tmp_path):
        mod = _load_helper_module()
        _bootstrap_all(tmp_path)
        assert mod.detect_cc(tmp_path)["changed"] is False
        _commit(
            tmp_path,
            "docs(promote): rewrite (#342)",
            {"packages/cc-plugin/skills/promote/SKILL.md": "x"},
        )
        assert mod.detect_cc(tmp_path)["changed"] is True

    def test_kimi_unchanged_then_changed(self, tmp_path):
        mod = _load_helper_module()
        _bootstrap_all(tmp_path)
        assert mod.detect_kimi(tmp_path)["changed"] is False
        _commit(
            tmp_path,
            "feat: k skill (#300)",
            {"packages/kimi-plugin/skills/search/SKILL.md": "x"},
        )
        assert mod.detect_kimi(tmp_path)["changed"] is True


class TestDetectAggregate:
    def test_any_changed_and_components_count(self, tmp_path):
        mod = _load_helper_module()
        _bootstrap_all(tmp_path)
        res = mod.detect(tmp_path)
        assert len(res["components"]) == 3
        assert res["any_changed"] is False
        _commit(tmp_path, "feat: a (#1)", {"jfox/a.py": "1"})
        res2 = mod.detect(tmp_path)
        assert res2["any_changed"] is True


class TestDetectFailClosed:
    """git 异常时 detect 报独立的 skip_reason（与「无改动」区分），不静默跳过。"""

    def test_detect_jfox_git_log_failure(self, tmp_path):
        mod = _load_helper_module()
        _bootstrap_all(tmp_path)
        fake_describe = MagicMock(stdout="v1.5.0\n", returncode=0)
        fake_log_fail = MagicMock(stdout="", stderr="fatal: bad object", returncode=1)
        with patch.object(mod, "_git", side_effect=[fake_describe, fake_log_fail]):
            res = mod.detect_jfox(tmp_path)
        assert res["changed"] is False
        assert "git log 失败" in res["skip_reason"]

    def test_detect_cc_git_log_failure(self, tmp_path):
        mod = _load_helper_module()
        _bootstrap_all(tmp_path)
        fake_fail = MagicMock(stdout="", stderr="fatal: bad object", returncode=1)
        with patch.object(mod, "_find_last_bump_commit", return_value="deadbeef"):
            with patch.object(mod, "_git", return_value=fake_fail):
                res = mod.detect_cc(tmp_path)
        assert res["changed"] is False
        assert "git log 失败" in res["skip_reason"]

    def test_detect_cc_find_bump_git_error(self, tmp_path):
        """_find_last_bump_commit 的 git log -S 失败 → detect 报 skip_reason，不静默。"""
        mod = _load_helper_module()
        _bootstrap_all(tmp_path)
        with patch.object(
            mod,
            "_find_last_bump_commit",
            side_effect=RuntimeError("git log 失败（定位 bump commit）: x"),
        ):
            res = mod.detect_cc(tmp_path)
        assert res["changed"] is False
        assert "git log 失败" in res["skip_reason"]

    def test_detect_cc_bad_version_format(self, tmp_path):
        """版本号非 X.Y.Z → 降级为 changed=False + skip_reason，不冒泡 traceback。"""
        mod = _load_helper_module()
        _git_repo(tmp_path)
        ccj = tmp_path / "packages/cc-plugin/.claude-plugin/plugin.json"
        ccj.parent.mkdir(parents=True)
        ccj.write_text(json.dumps({"name": "jfox", "version": "0.6"}), encoding="utf-8")
        mkt = tmp_path / ".claude-plugin/marketplace.json"
        mkt.parent.mkdir(parents=True)
        mkt.write_text(
            json.dumps(
                {"metadata": {"version": "0.6"}, "plugins": [{"name": "jfox", "version": "0.6"}]}
            ),
            encoding="utf-8",
        )
        res = mod.detect_cc(tmp_path)
        assert res["changed"] is False
        assert "读取版本失败" in res["skip_reason"]


class TestFindLastBumpCommit:
    def test_fallback_after_s_fail(self, tmp_path):
        """-S 失败时尝试 fallback；fallback 成功则用之（不直接 raise）。"""
        mod = _load_helper_module()
        _bootstrap_all(tmp_path)
        s_fail = MagicMock(stdout="", stderr="fatal: pickaxe error", returncode=1)
        s_ok = MagicMock(stdout="deadbeef\n", returncode=0)
        with patch.object(mod, "_git", side_effect=[s_fail, s_ok]):
            res = mod._find_last_bump_commit(tmp_path, "0.6.0", ".claude-plugin/marketplace.json")
        assert res == "deadbeef"

    def test_both_fail_raises(self, tmp_path):
        """两次 git log 都失败 → raise（fail-closed）。"""
        mod = _load_helper_module()
        _bootstrap_all(tmp_path)
        fail = MagicMock(stdout="", stderr="fatal: corrupt repo", returncode=1)
        with patch.object(mod, "_git", return_value=fail):
            with pytest.raises(RuntimeError, match="git log 失败"):
                mod._find_last_bump_commit(tmp_path, "0.6.0", ".claude-plugin/marketplace.json")

    def test_single_fail_fallback_empty_no_raise(self, tmp_path):
        """-S 失败 + fallback 成功但无命中 → 返回 ''（单次失败不 raise，与 docstring 一致）。"""
        mod = _load_helper_module()
        _bootstrap_all(tmp_path)
        s_fail = MagicMock(stdout="", stderr="fatal: pickaxe error", returncode=1)
        s_ok_empty = MagicMock(stdout="", returncode=0)
        with patch.object(mod, "_git", side_effect=[s_fail, s_ok_empty]):
            assert (
                mod._find_last_bump_commit(tmp_path, "0.6.0", ".claude-plugin/marketplace.json")
                == ""
            )

    def test_both_fail_empty_stderr_raises(self, tmp_path):
        """两次都失败即使 stderr 为空也 raise（fail-closed，不依赖 stderr 文本）。"""
        mod = _load_helper_module()
        _bootstrap_all(tmp_path)
        fail_empty = MagicMock(stdout="", stderr="", returncode=1)
        with patch.object(mod, "_git", return_value=fail_empty):
            with pytest.raises(RuntimeError, match="git log 失败"):
                mod._find_last_bump_commit(tmp_path, "0.6.0", ".claude-plugin/marketplace.json")


class TestMain:
    def test_main_outputs_error_json_on_failure(self, monkeypatch, capsys):
        """detect 抛异常时 main 兜底输出 error JSON + exit 1（不 traceback）。"""
        mod = _load_helper_module()
        monkeypatch.setattr(mod, "PROJECT_ROOT", Path("/tmp/nonexistent-release-all-test"))
        monkeypatch.setattr(
            mod, "detect", lambda root: (_ for _ in ()).throw(OSError("git missing"))
        )
        with pytest.raises(SystemExit) as exc:
            mod.main()
        assert exc.value.code == 1
        data = json.loads(capsys.readouterr().out.strip())
        assert "error" in data and "git missing" in data["error"]


class TestDetectCLI:
    def test_cli_returns_three_components(self):
        e = {**os.environ, "PYTHONUTF8": "1"}
        result = subprocess.run(
            ["python", HELPER, "detect"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            env=e,
            encoding="utf-8",
            errors="replace",
        )
        data = json.loads(result.stdout.strip())
        assert len(data["components"]) == 3
        names = [c["name"] for c in data["components"]]
        assert names == ["jfox", "cc-plugin", "kimi-plugin"]
        assert "any_changed" in data
