"""Note 的 agent / session_file / agent_model 三字段序列化。"""

from datetime import datetime

import pytest

from jfox.models import Note, NoteType

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def _note(**kwargs) -> Note:
    now = datetime(2026, 10, 19, 9, 0, 0)
    return Note(
        id="202610190900000001",
        title="会话",
        content="正文",
        type=NoteType.SESSION,
        created=now,
        updated=now,
        topic="demo",
        **kwargs,
    )


def test_roundtrip_keeps_agent_fields():
    note = _note(agent="pi-coding-agent", session_file="/tmp/s.jsonl", agent_model="p/m")
    parsed = Note.from_markdown(note.to_markdown())
    assert parsed.agent == "pi-coding-agent"
    assert parsed.session_file == "/tmp/s.jsonl"
    assert parsed.agent_model == "p/m"


def test_empty_fields_not_serialized():
    md = _note().to_markdown()
    assert "agent:" not in md
    assert "session_file:" not in md
    assert "agent_model:" not in md


def test_legacy_note_parses_as_none():
    parsed = Note.from_markdown(_note().to_markdown())
    assert parsed.agent is None
    assert parsed.session_file is None
    assert parsed.agent_model is None


def test_json_outputs_include_optional_fields():
    note = _note(agent="claude-code", session_file="/tmp/c.jsonl", agent_model="x/y")
    assert note.to_dict()["agent"] == "claude-code"
    assert note.to_show_dict()["session_file"] == "/tmp/c.jsonl"


def test_json_outputs_omit_empty_fields():
    d = _note().to_dict()
    assert "agent" not in d
    assert "session_file" not in d
    assert "agent_model" not in d
