"""candidate promote/reject 单元测试。目标模块: jfox.note"""

import pytest

from jfox.models import Note, NoteType
from jfox.note import create_note

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_reject_reason_roundtrip():
    """reject_reason 字段可序列化与反序列化"""
    n = create_note("内容", title="测试", note_type=NoteType.CANDIDATE)
    n.reject_reason = "知识不准确"
    md = n.to_markdown()
    assert "reject_reason: 知识不准确" in md
    restored = Note.from_markdown(md, n.filepath)
    assert restored.reject_reason == "知识不准确"


def test_reject_reason_not_written_when_none():
    """无 reject_reason 时不写入 frontmatter"""
    n = create_note("内容", title="测试", note_type=NoteType.CANDIDATE)
    assert "reject_reason" not in n.to_markdown()
