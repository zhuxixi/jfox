"""release_helper.py verify 子命令测试（#333 CHANGELOG 漂移校验）"""

import importlib.util
import json
import os
import subprocess
from pathlib import Path

HELPER = str(
    Path(__file__).resolve().parents[2] / ".claude" / "skills" / "release" / "release_helper.py"
)
PROJECT_ROOT = Path(__file__).resolve().parents[2]

_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t",
    "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t",
    "GIT_COMMITTER_EMAIL": "t@t",
}


def _load_helper_module():
    spec = importlib.util.spec_from_file_location("release_helper", HELPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _init_repo(tmp_path: Path):
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True, env=_GIT_ENV)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(tmp_path), check=True)


def _commit(tmp_path: Path, msg: str, filename: str = "f.txt"):
    (tmp_path / filename).write_text(msg, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=str(tmp_path), check=True, env=_GIT_ENV)


def _write_changelog(tmp_path: Path, prs: list[int], version: str = "0.2.0"):
    cl = tmp_path / "CHANGELOG.md"
    body = "\n".join(f"- something (#{p})" for p in prs)
    cl.write_text(
        f"# Changelog\n\n## [{version}] - 2026-07-27\n\n{body}\n\n"
        f"## [0.1.0] - 2026-07-01\n\n- old (#1)\n",
        encoding="utf-8",
    )


class TestVerify:
    def test_ok_when_changelog_covers_all_functional_prs(self, tmp_path):
        mod = _load_helper_module()
        _init_repo(tmp_path)
        _commit(tmp_path, "feat: a (#101)")
        subprocess.run(["git", "tag", "v0.1.0"], cwd=str(tmp_path), check=True)
        _commit(tmp_path, "feat: c (#103)", "g0.txt")
        _commit(tmp_path, "fix: d (#104)", "g1.txt")
        _write_changelog(tmp_path, [103, 104])
        res = mod.verify(tmp_path)
        assert res["ok"] is True
        assert res["missing"] == []

    def test_missing_when_changelog_lags(self, tmp_path):
        mod = _load_helper_module()
        _init_repo(tmp_path)
        _commit(tmp_path, "feat: a (#101)")
        subprocess.run(["git", "tag", "v0.1.0"], cwd=str(tmp_path), check=True)
        _commit(tmp_path, "feat: b (#202)", "g.txt")
        _write_changelog(tmp_path, [101])  # 漏了 202
        res = mod.verify(tmp_path)
        assert res["ok"] is False
        assert 202 in res["missing"]

    def test_chore_and_bump_commits_excluded(self, tmp_path):
        mod = _load_helper_module()
        _init_repo(tmp_path)
        _commit(tmp_path, "feat: a (#101)")
        subprocess.run(["git", "tag", "v0.1.0"], cwd=str(tmp_path), check=True)
        _commit(tmp_path, "chore: x (#303)", "h0.txt")
        _commit(tmp_path, "chore: bump version to 0.2.0 (#304)", "h1.txt")
        _write_changelog(tmp_path, [])  # 非功能 commit 不应判 missing
        res = mod.verify(tmp_path)
        assert res["ok"] is True
        assert res["missing"] == []


class TestVerifyCLI:
    def test_cli_returns_json_with_ok_key(self):
        e = {**os.environ, "PYTHONUTF8": "1"}
        result = subprocess.run(
            ["python", HELPER, "verify"],
            capture_output=True,
            text=True,
            cwd=str(PROJECT_ROOT),
            env=e,
            encoding="utf-8",
            errors="replace",
        )
        data = json.loads(result.stdout.strip())
        assert "ok" in data and "missing" in data
        assert result.returncode in (0, 1)
