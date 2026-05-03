"""
测试类型: 单元测试
目标模块: jfox.note (list_notes 跳过文件汇总)
预估耗时: < 1秒
依赖要求: 无外部依赖
"""

import logging
from datetime import datetime

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.note import list_notes


class TestListNotesSkipSummary:
    """list_notes 跳过无效文件时的 warning 汇总"""

    @pytest.fixture
    def kb_with_corrupt_file(self, temp_kb):
        """创建包含一个损坏文件的知识库"""
        from jfox.config import ZKConfig
        from jfox.models import Note, NoteType

        cfg = ZKConfig(base_dir=temp_kb)
        cfg.ensure_dirs()

        # 一个正常笔记
        note = Note(
            id="20260503001",
            title="正常笔记",
            content="内容",
            type=NoteType.PERMANENT,
            tags=[],
            created=datetime(2026, 5, 3, 0, 1),
            updated=datetime(2026, 5, 3, 0, 1),
        )
        note_dir = cfg.notes_dir / note.type.value
        note_dir.mkdir(parents=True, exist_ok=True)
        (note_dir / f"{note.id}.md").write_text(note.to_markdown(), encoding="utf-8")

        # 一个空文件（损坏）
        (note_dir / "empty.md").write_text("", encoding="utf-8")

        return cfg

    def test_no_warning_when_all_valid(self, temp_kb, caplog):
        """所有文件有效时不输出 warning"""
        from jfox.config import ZKConfig
        from jfox.models import Note, NoteType

        cfg = ZKConfig(base_dir=temp_kb)
        cfg.ensure_dirs()

        note = Note(
            id="20260503001",
            title="正常笔记",
            content="内容",
            type=NoteType.PERMANENT,
            tags=[],
            created=datetime(2026, 5, 3, 0, 1),
            updated=datetime(2026, 5, 3, 0, 1),
        )
        note_dir = cfg.notes_dir / note.type.value
        note_dir.mkdir(parents=True, exist_ok=True)
        (note_dir / f"{note.id}.md").write_text(note.to_markdown(), encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger="jfox.note"):
            results = list_notes(cfg=cfg)

        assert len(results) == 1
        skip_warnings = [r for r in caplog.records if "无法加载" in r.message]
        assert len(skip_warnings) == 0

    def test_warning_when_corrupt_file_skipped(self, kb_with_corrupt_file, caplog):
        """有损坏文件时输出汇总 warning"""
        with caplog.at_level(logging.WARNING, logger="jfox.note"):
            results = list_notes(cfg=kb_with_corrupt_file)

        assert len(results) == 1
        skip_warnings = [r for r in caplog.records if "无法加载" in r.message]
        assert len(skip_warnings) == 1
        assert "1 个文件无法加载" in skip_warnings[0].message
        assert "jfox check" in skip_warnings[0].message
