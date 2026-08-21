"""NoteType.STRUCTURE 与 CLI 类型文案动态化测试。"""

from __future__ import annotations

import re

from typer.testing import CliRunner

from jfox.cli import _NOTE_TYPE_SLASH, _NOTE_TYPE_VALUES, app
from jfox.models import Note, NoteType, datetime

runner = CliRunner()


def test_note_type_structure_member_exists():
    assert NoteType.STRUCTURE.value == "structure"
    assert len([t for t in NoteType]) == 6


def test_structure_note_filename_uses_slug_branch():
    note = Note(
        id="20260822010101",
        title="Zima Workflow MOC",
        content="",
        type=NoteType.STRUCTURE,
        created=datetime(2026, 8, 22, 1, 1, 1),
        updated=datetime(2026, 8, 22, 1, 1, 1),
    )
    assert note.filename == "20260822010101-zima-workflow-moc.md"


def test_structure_note_markdown_roundtrip_keeps_links():
    note = Note(
        id="20260822010101",
        title="Zima Workflow MOC",
        content="## zima\n\n- [[Zima One]] — 2 links",
        type=NoteType.STRUCTURE,
        created=datetime(2026, 8, 22, 1, 1, 1),
        updated=datetime(2026, 8, 22, 1, 1, 1),
        links=["20260820010101"],
    )
    restored = Note.from_markdown(note.to_markdown())
    assert restored.type == NoteType.STRUCTURE
    assert restored.links == ["20260820010101"]
    assert restored.content == note.content


def _strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def test_cli_type_lists_cover_all_six_types():
    assert _NOTE_TYPE_VALUES.split(", ") == [
        "fleeting",
        "literature",
        "permanent",
        "session",
        "candidate",
        "structure",
    ]
    assert _NOTE_TYPE_SLASH == "fleeting/literature/permanent/session/candidate/structure"


def test_add_invalid_type_error_lists_all_six():
    result = runner.invoke(app, ["add", "hello", "--type", "nope"])
    output = _strip_ansi(result.output)
    assert result.exit_code != 0
    for expected in ("fleeting", "literature", "permanent", "session", "candidate", "structure"):
        assert expected in output


def test_add_type_help_lists_all_six():
    result = runner.invoke(app, ["add", "--help"], env={"COLUMNS": "200"})
    output = _strip_ansi(result.output)
    assert "fleeting/literature/permanent/session/candidate/structure" in output
