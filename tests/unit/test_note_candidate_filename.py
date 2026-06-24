"""candidate 笔记文件名 = id + title slug（同 permanent 风格）。"""

from datetime import datetime

from jfox.models import Note, NoteType


def test_candidate_filename_uses_title_slug():
    note = Note(
        id="20260621143000",
        title="Gem Synthesis Design",
        content="x",
        type=NoteType.CANDIDATE,
        created=datetime(2026, 6, 21, 14, 30),
        updated=datetime(2026, 6, 21, 14, 30),
    )
    assert note.filename == "20260621143000-gem-synthesis-design.md"
