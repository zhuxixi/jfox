"""release_all_helper.py detect 测试"""

import importlib.util
import json
import os
import subprocess
from pathlib import Path

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
