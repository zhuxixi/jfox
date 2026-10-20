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


def test_fields_written_to_frontmatter(cli, tmp_path):
    session_file = tmp_path / "x.jsonl"
    res = _add(
        cli,
        "--agent",
        "pi-coding-agent",
        "--session-path",
        str(session_file),
        "--agent-model",
        "p/m",
    )
    assert res.returncode == 0, res.stderr
    text = Path(res.json()["note"]["filepath"]).read_text(encoding="utf-8")
    assert "agent: pi-coding-agent" in text
    assert f"session_file: {session_file}" in text
    assert "agent_model: p/m" in text


def test_fields_in_add_json(cli, tmp_path):
    session_file = tmp_path / "k.jsonl"
    res = _add(cli, "--agent", "kimi-code", "--session-path", str(session_file))
    note = res.json()["note"]
    assert note["agent"] == "kimi-code"
    assert note["session_file"] == str(session_file)


def test_empty_agent_rejected(cli):
    res = _add(cli, "--agent", "  ")
    assert res.returncode == 1


def test_relative_session_path_rejected(cli):
    res = _add(cli, "--agent", "pi-coding-agent", "--session-path", "rel/path.jsonl")
    assert res.returncode == 1


def test_tilde_expanded(cli):
    res = _add(cli, "--agent", "pi-coding-agent", "--session-path", "~/x.jsonl")
    stored = Path(res.json()["note"]["session_file"])
    assert stored.is_absolute()
    assert "~" not in str(stored)


def test_nonexistent_absolute_path_accepted(cli, tmp_path):
    gone = tmp_path / "nope" / "gone.jsonl"  # 父目录不存在，故意不创建
    res = _add(cli, "--agent", "pi-coding-agent", "--session-path", str(gone))
    assert res.returncode == 0
    assert res.json()["note"]["session_file"] == str(gone)


def test_show_json_exposes_fields(cli, tmp_path):
    res = _add(cli, "--agent", "pi-coding-agent", "--session-path", str(tmp_path / "s.jsonl"))
    note_id = res.json()["id"]
    shown = cli.run("show", note_id)
    assert shown.json()["agent"] == "pi-coding-agent"
