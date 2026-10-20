"""jfox add --agent / --session-path / --agent-model 行为。"""

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _add(cli, *extra):
    return cli.run(
        "add",
        "正文",
        "--title",
        "会话",
        "--type",
        "session",
        "--topic",
        "t",
        *extra,
    )


def test_fields_written_to_frontmatter(cli):
    res = _add(
        cli,
        "--agent",
        "pi-coding-agent",
        "--session-path",
        "/tmp/x.jsonl",
        "--agent-model",
        "p/m",
    )
    assert res.returncode == 0, res.stderr
    text = Path(res.json()["note"]["filepath"]).read_text(encoding="utf-8")
    assert "agent: pi-coding-agent" in text
    assert "session_file: /tmp/x.jsonl" in text
    assert "agent_model: p/m" in text


def test_fields_in_add_json(cli):
    res = _add(cli, "--agent", "kimi-code", "--session-path", "/tmp/k.jsonl")
    note = res.json()["note"]
    assert note["agent"] == "kimi-code"
    assert note["session_file"] == "/tmp/k.jsonl"


def test_empty_agent_rejected(cli):
    res = _add(cli, "--agent", "  ")
    assert res.returncode == 1


def test_relative_session_path_rejected(cli):
    res = _add(cli, "--agent", "pi-coding-agent", "--session-path", "rel/path.jsonl")
    assert res.returncode == 1


def test_tilde_expanded(cli):
    res = _add(cli, "--agent", "pi-coding-agent", "--session-path", "~/x.jsonl")
    assert res.json()["note"]["session_file"].startswith("/")


def test_nonexistent_absolute_path_accepted(cli):
    res = _add(cli, "--agent", "pi-coding-agent", "--session-path", "/nope/gone.jsonl")
    assert res.returncode == 0
    assert res.json()["note"]["session_file"] == "/nope/gone.jsonl"


def test_show_json_exposes_fields(cli):
    res = _add(cli, "--agent", "pi-coding-agent", "--session-path", "/tmp/s.jsonl")
    note_id = res.json()["id"]
    shown = cli.run("show", note_id)
    assert shown.json()["agent"] == "pi-coding-agent"
