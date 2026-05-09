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
        import tempfile

        from jfox.config import ZKConfig

        with tempfile.TemporaryDirectory() as tmpdir:
            cfg = ZKConfig(base_dir=Path(tmpdir))
            cfg.ensure_dirs()
            assert (cfg.notes_dir / "session").exists()
            assert (cfg.notes_dir / "session").is_dir()


class TestSessionCLI:
    """Test session CLI integration"""

    def test_add_session_requires_topic(self):
        """--type session without --topic should raise error"""
        from jfox.cli import _add_note_impl

        with pytest.raises(ValueError, match="--topic"):
            _add_note_impl(
                content="test content",
                title="Session: test",
                note_type="session",
                tags=None,
                source=None,
                output_format="json",
                topic=None,
            )

    def test_add_session_with_topic(self):
        """--type session with --topic should succeed"""
        import tempfile

        from jfox.cli import _add_note_impl
        from jfox.config import config

        with tempfile.TemporaryDirectory() as tmpdir:
            old_base = config.base_dir
            old_notes_dir = config.notes_dir
            old_zk_dir = config.zk_dir
            config.base_dir = Path(tmpdir)
            config.notes_dir = Path(tmpdir) / "notes"
            config.zk_dir = Path(tmpdir) / ".zk"
            (config.notes_dir / "session").mkdir(parents=True, exist_ok=True)

            try:
                _add_note_impl(
                    content="test content",
                    title="Session: test",
                    note_type="session",
                    tags=["session"],
                    source=None,
                    output_format="json",
                    topic="my-topic",
                )
                session_files = list((config.notes_dir / "session").glob("*.md"))
                assert len(session_files) == 1
                assert "my-topic" in session_files[0].name
            finally:
                config.base_dir = old_base
                config.notes_dir = old_notes_dir
                config.zk_dir = old_zk_dir


class TestSessionTemplate:
    """Test session built-in template"""

    def test_session_builtin_template_exists(self):
        import tempfile

        from jfox.template import TemplateManager

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = TemplateManager(Path(tmpdir))
            tmpl = mgr.get_template("session")
            assert tmpl is not None
            assert tmpl.note_type == "session"

    def test_session_template_renders(self):
        import tempfile

        from jfox.template import TemplateManager

        with tempfile.TemporaryDirectory() as tmpdir:
            mgr = TemplateManager(Path(tmpdir))
            result = mgr.render(
                "session",
                {
                    "title": "Session: test",
                    "content": "did some work",
                    "source": "",
                    "topic": "my-topic",
                },
            )
            assert result["note_type"] == "session"
            assert "my-topic" in result["title"]
            assert "完成的工作" in result["content"]
            assert "session" in result["tags"]
