"""#502 JSON schema contract tests.

Rule under test (docs/json-schemas.md): every --json output has top-level
boolean `success`; error outputs additionally have non-empty `error` and
exit code 1. Uses real subprocesses with stderr merged (TestJsonPurity
pattern from tests/test_add_dedup_cli.py).
"""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_json(cli, *args: str) -> subprocess.CompletedProcess:
    """Run `jfox <args> --json --kb <kb>` as a real subprocess, merge stderr."""
    cmd = [sys.executable, "-m", "jfox", *args, "--json", "--kb", cli.kb_name]
    env = {**os.environ, "PYTHONUTF8": "1"}
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        encoding="utf-8",
        cwd=str(REPO_ROOT),
        env=env,
    )


def assert_json_shape(stdout: str, success_expected: bool) -> dict:
    """Parse stdout as strict JSON and assert the contract shape."""
    data = json.loads(stdout)  # strict: any pollution raises here
    assert isinstance(data, dict), f"top level must be object, got {type(data)}"
    assert "success" in data, f"missing top-level success in: {stdout[:200]}"
    assert isinstance(data["success"], bool), (
        f"success must be bool, got {type(data['success'])}: {data['success']!r}"
    )
    assert data["success"] is success_expected
    if not success_expected:
        assert data.get("error"), "error output must carry non-empty error"
    return data


def test_helper_rejects_non_json():
    """Guard the guard: helper must raise on polluted output."""
    with pytest.raises(json.JSONDecodeError):
        assert_json_shape("INFO something\n{}", True)


def test_helper_rejects_missing_success():
    with pytest.raises(AssertionError):
        assert_json_shape('{"total": 0}', True)


class TestAlreadyCompliantSmoke:
    """Commands that already emit success — proves the harness works."""

    def test_add_success_shape(self, cli):
        r = _run_json(cli, "add", "契约冒烟正文", "--title", "Contract-Smoke-1")
        assert r.returncode == 0
        data = assert_json_shape(r.stdout, True)
        assert data["note"]["id"]  # #483 shape intact
