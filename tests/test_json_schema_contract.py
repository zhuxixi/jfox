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


def _run_json(cli, *args: str, with_kb: bool = True) -> subprocess.CompletedProcess:
    """Run `jfox <args> --json --kb <kb>` as a real subprocess, merge stderr.

    with_kb=False for commands without a --kb option (kb itself); those still
    run in the isolated registry via ZK_CONFIG_PATH inherited from conftest.
    """
    cmd = [sys.executable, "-m", "jfox", *args, "--json"]
    if with_kb:
        cmd += ["--kb", cli.kb_name]
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


class TestContractList:
    """Every entry: (id, cmd-args-after-'jfox', needs_existing_note).

    Commands are added here by the task that fixes them; the list is the
    contract. Run with no setup beyond an initialized temp KB unless
    needs_existing_note (then a note is created first via cli fixture).
    """

    EXPECTED_SUCCESS_COMMANDS = [
        # --- Task 2: main CLI query class ---
        ("search", ["search", "任意词"], False),
        ("status", ["status"], False),
        ("list", ["list"], False),
        ("show", ["show", "{note_id}"], True),
        ("refs-default", ["refs"], False),
        ("query", ["query", "任意词"], False),
        ("graph-stats", ["graph", "--stats"], False),
        ("graph-orphans", ["graph", "--orphans"], False),
        ("graph-note", ["graph", "--note", "{note_id}"], True),
        ("daily", ["daily"], False),
        ("inbox", ["inbox"], False),
        ("suggest-links", ["suggest-links", "一段内容"], False),
        (
            "bulk-import",
            ["bulk-import", str(Path(__file__).parent / "fixtures" / "bulk_import_notes.json")],
            False,
        ),
        ("check", ["check"], False),
        # --- Task 3: index/kb ---
        ("index-status", ["index", "status"], False),
        ("index-bm25-status", ["index", "bm25-status"], False),
        ("index-verify", ["index", "verify"], False),
        ("kb-list", ["kb", "list"], False),
        ("kb-current", ["kb", "current"], False),
    ]

    @pytest.mark.parametrize(
        "cmd_id,args,needs_note",
        EXPECTED_SUCCESS_COMMANDS,
        ids=[c[0] for c in EXPECTED_SUCCESS_COMMANDS],
    )
    def test_success_has_top_level_success(self, cli, cmd_id, args, needs_note):
        note_id = None
        if needs_note:
            created = _run_json(cli, "add", "契约前置正文", "--title", f"Contract-Setup-{cmd_id}")
            note_id = assert_json_shape(created.stdout, True)["note"]["id"]
        final_args = [a.format(note_id=note_id) for a in args]
        # kb family has no --kb option; everything else targets the temp KB
        r = _run_json(cli, *final_args, with_kb=cmd_id != "kb-list" and cmd_id != "kb-current")
        assert r.returncode == 0, f"stdout: {r.stdout[:300]}"
        assert_json_shape(r.stdout, True)


class TestErrorContract:
    """Error branches must emit {success:false, error} JSON + exit 1 (#502 C2a)."""

    def test_kb_switch_nonexistent_outputs_json_error(self, cli):
        r = _run_json(cli, "kb", "switch", "definitely-no-such-kb-502", with_kb=False)
        assert r.returncode == 1, f"stdout: {r.stdout[:300]}"
        assert_json_shape(r.stdout, False)

    def test_kb_remove_missing_name_outputs_json_error(self, cli):
        # kb remove with no name arg: currently console-only
        r = _run_json(cli, "kb", "remove", with_kb=False)
        assert r.returncode == 1, f"stdout: {r.stdout[:300]}"
        assert_json_shape(r.stdout, False)
