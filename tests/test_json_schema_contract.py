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


def _run_json(
    cli, *args: str, with_kb: bool = True, append_json: bool = True
) -> subprocess.CompletedProcess:
    """Run `jfox <args> --json --kb <kb>` as a real subprocess, merge stderr.

    with_kb=False for commands without a --kb option (kb itself); those still
    run in the isolated registry via ZK_CONFIG_PATH inherited from conftest.
    append_json=False for commands without a --json option (fragments list
    takes --format json; fragments show is json-only with no flags).
    """
    cmd = [sys.executable, "-m", "jfox", *args]
    if append_json:
        cmd += ["--json"]
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
    assert isinstance(
        data["success"], bool
    ), f"success must be bool, got {type(data['success'])}: {data['success']!r}"
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

    def test_add_top_level_shortcuts(self, cli):
        """#502 C3: add --json 顶层冗余 id/title 快捷字段，与 note 内同值。"""
        r = _run_json(cli, "add", "快捷字段正文", "--title", "Contract-Shortcut-1")
        data = assert_json_shape(r.stdout, True)
        assert data["id"] == data["note"]["id"]
        assert data["title"] == data["note"]["title"]


class TestContractList:
    """Every entry: (id, cmd-args-after-'jfox', needs_existing_note).

    Commands are added here by the task that fixes them; the list is the
    contract. Run with no setup beyond an initialized temp KB unless
    needs_existing_note (then a note is created first via cli fixture).
    """

    # command ids that accept no --kb option (main CLI kb/fragments families;
    # auto-summary/backup sub-apps also have no --kb option)
    NO_KB = {
        "kb-list",
        "kb-current",
        "fragments-list",
        "auto-summary-status",
        "auto-summary-scan",
        "backup-status",
        "backup-list",
    }
    # command ids that accept no --json option (their args carry the format flag)
    NO_EXTRA_FLAGS = {
        "fragments-list",
        "auto-summary-status",
        "auto-summary-scan",
        "backup-status",
        "backup-list",
    }

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
        # --- Task 5: template/fragments ---
        ("template-list", ["template", "list", "--format", "json"], False),
        ("template-show", ["template", "show", "quick"], False),
        ("fragments-list", ["fragments", "list", "--format", "json"], False),
        # --- Task 6: prompts ---
        ("prompts-list", ["prompts", "list"], False),
        ("prompts-status", ["prompts", "status"], False),
        # --- Task 7: bookshelf/auto-summary/backup ---
        ("bookshelf-list", ["bookshelf", "list"], False),
        ("auto-summary-status", ["auto-summary", "status", "--format", "json"], False),
        ("auto-summary-scan", ["auto-summary", "scan", "--format", "json"], False),
        ("backup-status", ["backup", "status", "--format", "json"], False),
        ("backup-list", ["backup", "list", "--format", "json"], False),
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
        # kb/fragments families lack --kb; fragments also lacks --json
        r = _run_json(
            cli,
            *final_args,
            with_kb=cmd_id not in self.NO_KB,
            append_json=cmd_id not in self.NO_EXTRA_FLAGS,
        )
        assert r.returncode == 0, f"stdout: {r.stdout[:300]}"
        assert_json_shape(r.stdout, True)

    def test_prompts_list_is_object_with_items(self, cli):
        # prompts list 曾输出裸 JSON 数组；C5a 包装为 {success, items}
        r = _run_json(cli, "prompts", "list")
        data = assert_json_shape(r.stdout, True)
        assert isinstance(data["items"], list)

    def test_backup_list_is_object_with_items(self, cli):
        # backup list 曾输出裸 JSON 数组；C5b 包装为 {success, items}
        r = _run_json(cli, "backup", "list", "--format", "json", with_kb=False, append_json=False)
        data = assert_json_shape(r.stdout, True)
        assert isinstance(data["items"], list)

    def test_auto_summary_scan_shape(self, cli):
        # auto-summary scan --json 顶层 success + pending 列表
        r = _run_json(
            cli, "auto-summary", "scan", "--format", "json", with_kb=False, append_json=False
        )
        data = assert_json_shape(r.stdout, True)
        assert isinstance(data.get("pending"), list)


class TestErrorContract:
    """Error branches must emit {success:false, error} JSON + exit 1 (#502 C2a)."""

    def test_kb_switch_nonexistent_outputs_json_error(self, cli):
        r = _run_json(cli, "kb", "switch", "definitely-no-such-kb-502", with_kb=False)
        assert r.returncode == 1, f"stdout: {r.stdout[:300]}"
        assert_json_shape(r.stdout, False)

    def test_kb_remove_missing_name_outputs_json_error(self, cli):
        # kb remove with no name arg: Task 3 (#502 C2a) 起该分支输出 JSON 错误
        # {"success": false, "error": ...} 并以退出码 1 结束
        r = _run_json(cli, "kb", "remove", with_kb=False)
        assert r.returncode == 1, f"stdout: {r.stdout[:300]}"
        assert_json_shape(r.stdout, False)

    def test_template_show_not_found_json_error(self, cli):
        r = _run_json(cli, "template", "show", "no-such-template-502")
        assert r.returncode == 1, f"stdout: {r.stdout[:300]}"
        assert_json_shape(r.stdout, False)

    def test_template_remove_not_found_json_error(self, cli):
        # remove 的 json 选项默认 True（--json/--no-json），_run_json 追加的 --json 合法
        r = _run_json(cli, "template", "remove", "nonexistent-tpl-502")
        assert r.returncode == 1, f"stdout: {r.stdout[:300]}"
        assert_json_shape(r.stdout, False)

    def test_fragments_show_missing_json_error(self, cli):
        # fragments show 是纯 JSON 命令：无 --json/--kb 选项，错误分支也必须输出 JSON
        r = _run_json(cli, "fragments", "show", "999999999", with_kb=False, append_json=False)
        assert r.returncode == 1, f"stdout: {r.stdout[:300]}"
        assert_json_shape(r.stdout, False)

    def test_prompts_config_bad_set_json_error(self, cli):
        # config --set 未知 key：该命令有 JSON 输出模式，错误分支也必须 JSON（C2 精神）
        r = _run_json(cli, "prompts", "config", "--set", "unknown-key-502=x", with_kb=False)
        assert r.returncode == 1, f"stdout: {r.stdout[:300]}"
        assert_json_shape(r.stdout, False)

    def test_backup_verify_missing_snapshot_json_error(self, cli):
        # backup verify 失败（快照不存在）→ success:false + 非空 error + 退出码 1。
        # JFOX_BACKUP_ROOT 已被 conftest 隔离到临时目录，verify 对缺失归档返回 False，
        # 不触碰真实 ~/.jfox-backup（#502 Task 7 fix round 1）
        r = _run_json(
            cli,
            "backup",
            "verify",
            "does-not-exist-502",
            "--format",
            "json",
            with_kb=False,
            append_json=False,
        )
        assert r.returncode == 1, f"stdout: {r.stdout[:300]}"
        data = assert_json_shape(r.stdout, False)
        assert data["ok"] is False  # 兼容键保留
        assert "snapshot" in data


class TestAutoSummaryRunShape:
    def test_run_json_has_bool_success_and_int_succeeded(self, cli, monkeypatch):
        """run 的 json 分支形状：success=bool，succeeded=int（C4 重命名）。

        run 会触发 claude -p，不能用子进程测；monkeypatch run_once 返回
        计数型 FakeReport，直接调命令函数断言输出形状。
        """
        from jfox.auto_summary import cli as as_cli

        class FakeReport:
            scanned = processed = skipped = failed = 0
            success = 3  # int 计数——被重命名的字段
            items = []

        monkeypatch.setattr(as_cli, "run_once", lambda dry_run: FakeReport())
        import contextlib
        import io

        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            as_cli.run(dry_run=True, output_format="json")
        data = json.loads(buf.getvalue())
        assert data["success"] is True  # 布尔
        assert data["succeeded"] == 3  # 重命名后的计数
        assert "error" not in data
