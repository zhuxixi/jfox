"""
测试类型: 单元测试
目标模块: jfox.models (session note type)
预估耗时: < 1秒
依赖要求: 无外部依赖
"""

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from datetime import datetime
from pathlib import Path

from jfox.models import Note, NoteType


class TestSessionNoteType:
    """Test session note type support"""

    def test_session_enum_value(self):
        assert NoteType.SESSION.value == "session"

    def test_session_note_creation(self):
        n = Note(
            id="202605091430221234",
            title="Session: fix atomic write",
            content="Fixed atomic write bug",
            type=NoteType.SESSION,
            created=datetime(2026, 5, 9, 14, 30, 22),
            updated=datetime(2026, 5, 9, 14, 30, 22),
            tags=["session"],
            topic="atomic-write",
        )
        assert n.topic == "atomic-write"
        assert n.type == NoteType.SESSION

    def test_session_filename_uses_topic(self):
        n = Note(
            id="202605091430221234",
            title="Session: fix atomic write bug",
            content="content",
            type=NoteType.SESSION,
            created=datetime(2026, 5, 9, 14, 30, 22),
            updated=datetime(2026, 5, 9, 14, 30, 22),
            topic="atomic-write",
        )
        assert n.filename == "202605091430221234-atomic-write.md"

    def test_session_filename_falls_back_to_title(self):
        n = Note(
            id="202605091430221234",
            title="Session: fix atomic write bug",
            content="content",
            type=NoteType.SESSION,
            created=datetime(2026, 5, 9, 14, 30, 22),
            updated=datetime(2026, 5, 9, 14, 30, 22),
        )
        # Without topic, slug comes from title
        assert n.filename == "202605091430221234-session-fix-atomic-write-bug.md"

    def test_session_topic_persisted_to_frontmatter(self):
        n = Note(
            id="202605091430221234",
            title="Session: test",
            content="content",
            type=NoteType.SESSION,
            created=datetime(2026, 5, 9, 14, 30, 22),
            updated=datetime(2026, 5, 9, 14, 30, 22),
            topic="my-topic",
        )
        md = n.to_markdown()
        assert "topic: my-topic" in md

    def test_session_topic_absent_when_none(self):
        n = Note(
            id="202605091430221234",
            title="Session: test",
            content="content",
            type=NoteType.SESSION,
            created=datetime(2026, 5, 9, 14, 30, 22),
            updated=datetime(2026, 5, 9, 14, 30, 22),
        )
        md = n.to_markdown()
        assert "topic:" not in md

    def test_session_topic_parsed_from_markdown(self):
        md_content = """---
id: "202605091430221234"
title: "Session: test"
type: session
created: "2026-05-09T14:30:22"
updated: "2026-05-09T14:30:22"
tags:
  - session
links: []
backlinks: []
topic: my-topic
---

# Session: test

content here
"""
        n = Note.from_markdown(md_content, Path("test.md"))
        assert n.type == NoteType.SESSION
        assert n.topic == "my-topic"

    def test_session_to_dict_includes_topic(self):
        n = Note(
            id="202605091430221234",
            title="Session: test",
            content="content",
            type=NoteType.SESSION,
            created=datetime(2026, 5, 9, 14, 30, 22),
            updated=datetime(2026, 5, 9, 14, 30, 22),
            topic="my-topic",
        )
        d = n.to_dict()
        assert d["topic"] == "my-topic"

    def test_non_session_note_topic_is_none(self):
        n = Note(
            id="202605091430221234",
            title="Some title",
            content="content",
            type=NoteType.FLEETING,
            created=datetime(2026, 5, 9, 14, 30, 22),
            updated=datetime(2026, 5, 9, 14, 30, 22),
        )
        assert n.topic is None

    def test_config_ensure_dirs_creates_session_dir(self):
        from jfox.config import ZKConfig
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = ZKConfig(base_dir=Path(tmpdir))
            cfg.ensure_dirs()
            assert (cfg.notes_dir / "session").exists()
            assert (cfg.notes_dir / "session").is_dir()
