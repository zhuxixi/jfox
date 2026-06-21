"""验证 candidate 笔记的专属字段序列化往返。"""

from datetime import datetime

from jfox.models import GemLevel, Note, NoteType


def _candidate_note():
    return Note(
        id="20260621143000",
        title="测试候选宝石",
        content="# 测试\n正文",
        type=NoteType.CANDIDATE,
        created=datetime(2026, 6, 21, 14, 30),
        updated=datetime(2026, 6, 21, 14, 30),
        tags=[],
        gem_level=GemLevel.FLAWED.value,
        confidence=0.82,
        source_fragments=[12, 15],
        grounded_by=["已有永久笔记A"],
        knowledge_type="procedural",
        status="pending",
    )


def test_candidate_to_markdown_has_fields():
    md = _candidate_note().to_markdown()
    assert "gem_level: flawed" in md
    assert "confidence: 0.82" in md
    assert "source_fragments:" in md
    assert "grounded_by:" in md
    assert "knowledge_type: procedural" in md
    assert "status: pending" in md


def test_candidate_roundtrip_preserves_fields():
    note = _candidate_note()
    restored = Note.from_markdown(note.to_markdown())
    assert restored.type == NoteType.CANDIDATE
    assert restored.gem_level == "flawed"
    assert restored.confidence == 0.82
    assert restored.source_fragments == [12, 15]
    assert restored.grounded_by == ["已有永久笔记A"]
    assert restored.knowledge_type == "procedural"
    assert restored.status == "pending"


def test_non_candidate_note_has_no_candidate_fields():
    note = Note(
        id="20260621143001",
        title="普通永久",
        content="x",
        type=NoteType.PERMANENT,
        created=datetime(2026, 6, 21, 14, 30),
        updated=datetime(2026, 6, 21, 14, 30),
    )
    md = note.to_markdown()
    assert "gem_level" not in md
    assert "confidence" not in md
