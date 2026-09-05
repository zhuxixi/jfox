"""candidate 起草与 source_prompts 溯源测试。"""

import pytest

from jfox.models import Note, NoteType

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_note_source_prompts_field_exists():
    n = Note(
        id="20260902000000-000001",
        title="测试",
        content="内容",
        type=NoteType.CANDIDATE,
        created=__import__("datetime").datetime.now(),
        updated=__import__("datetime").datetime.now(),
    )
    assert n.source_prompts == []  # 默认空列表


def test_note_source_prompts_serialized_to_markdown():
    from datetime import datetime

    now = datetime.now()
    n = Note(
        id="20260902000000-000001",
        title="带溯源",
        content="内容",
        type=NoteType.CANDIDATE,
        created=now,
        updated=now,
        source_prompts=[42, 43],
    )
    md = n.to_markdown()
    assert "source_prompts:" in md
    assert "42" in md and "43" in md


def test_note_source_prompts_parsed_from_markdown():
    from datetime import datetime

    now = datetime.now()
    n = Note(
        id="20260902000000-000001",
        title="roundtrip",
        content="内容",
        type=NoteType.CANDIDATE,
        created=now,
        updated=now,
        source_prompts=[7, 8, 9],
    )
    md = n.to_markdown()
    parsed = Note.from_markdown(md)
    assert parsed.source_prompts == [7, 8, 9]


def test_note_to_dict_includes_source_prompts():
    from datetime import datetime

    now = datetime.now()
    n = Note(
        id="20260902000000-000001",
        title="dict",
        content="内容",
        type=NoteType.CANDIDATE,
        created=now,
        updated=now,
        source_prompts=[5],
    )
    d = n.to_dict()
    assert "source_prompts" in d
    assert d["source_prompts"] == [5]


def test_note_promote_semantics_preserves_source_prompts():
    """promote 语义验证：type 改 PERMANENT 后 source_prompts 保留并序列化。"""
    from datetime import datetime

    now = datetime.now()
    n = Note(
        id="20260902000000-000001",
        title="要晋升的",
        content="内容",
        type=NoteType.CANDIDATE,
        created=now,
        updated=now,
        status="pending",
        source_prompts=[42],
    )

    # 模拟 promote_note 的字段操作（真实 promote_note 在 test_note_promote.py 有覆盖）
    n.type = NoteType.PERMANENT
    n.status = None
    n.gem_level = None
    n.confidence = None
    n.knowledge_type = None

    # source_prompts 跨类型保留
    assert n.source_prompts == [42]
    # 序列化到 markdown 仍保留
    md = n.to_markdown()
    assert "source_prompts:" in md
    parsed = Note.from_markdown(md)
    assert parsed.source_prompts == [42]
    assert parsed.type == NoteType.PERMANENT
