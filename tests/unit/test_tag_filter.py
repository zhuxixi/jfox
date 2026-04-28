"""
测试类型: 单元测试
目标模块: jfox.note (list_notes tags 过滤)
预估耗时: < 1秒
依赖要求: 无外部依赖

测试 list_notes 的 tags 过滤功能（AND 逻辑）
"""

from datetime import datetime

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.models import Note, NoteType
from jfox.note import list_notes


class TestListNotesTagFilter:
    """list_notes tags 过滤测试"""

    @pytest.fixture
    def kb_with_tagged_notes(self, temp_kb):
        """创建带标签笔记的知识库"""
        from jfox.config import ZKConfig

        cfg = ZKConfig(base_dir=temp_kb)
        cfg.ensure_dirs()

        notes = [
            Note(
                id="20260428001",
                title="Python 基础",
                content="Python 编程基础",
                type=NoteType.PERMANENT,
                tags=["python", "编程"],
                created=datetime(2026, 4, 28, 0, 1),
                updated=datetime(2026, 4, 28, 0, 1),
            ),
            Note(
                id="20260428002",
                title="Java 入门",
                content="Java 编程入门",
                type=NoteType.PERMANENT,
                tags=["java", "编程"],
                created=datetime(2026, 4, 28, 0, 2),
                updated=datetime(2026, 4, 28, 0, 2),
            ),
            Note(
                id="20260428003",
                title="机器学习笔记",
                content="机器学习相关内容",
                type=NoteType.LITERATURE,
                tags=["python", "机器学习"],
                created=datetime(2026, 4, 28, 0, 3),
                updated=datetime(2026, 4, 28, 0, 3),
            ),
            Note(
                id="20260428004",
                title="今日想法",
                content="随手记录",
                type=NoteType.FLEETING,
                tags=[],
                created=datetime(2026, 4, 28, 0, 4),
                updated=datetime(2026, 4, 28, 0, 4),
            ),
        ]

        for n in notes:
            # 直接写入文件（save_note 不接受 cfg 参数）
            note_dir = cfg.notes_dir / n.type.value
            note_dir.mkdir(parents=True, exist_ok=True)
            note_file = note_dir / f"{n.id}.md"
            note_file.write_text(n.to_markdown(), encoding="utf-8")

        return cfg

    def test_filter_single_tag(self, kb_with_tagged_notes):
        """单标签过滤"""
        results = list_notes(tags=["python"], cfg=kb_with_tagged_notes)
        assert len(results) == 2
        titles = {n.title for n in results}
        assert titles == {"Python 基础", "机器学习笔记"}

    def test_filter_multiple_tags_and_logic(self, kb_with_tagged_notes):
        """多标签 AND 逻辑"""
        results = list_notes(tags=["python", "编程"], cfg=kb_with_tagged_notes)
        assert len(results) == 1
        assert results[0].title == "Python 基础"

    def test_filter_nonexistent_tag(self, kb_with_tagged_notes):
        """不存在的标签返回空"""
        results = list_notes(tags=["nonexistent"], cfg=kb_with_tagged_notes)
        assert len(results) == 0

    def test_filter_no_tag_param(self, kb_with_tagged_notes):
        """不传 tags 参数返回全部"""
        results = list_notes(cfg=kb_with_tagged_notes)
        assert len(results) == 4

    def test_filter_empty_notes(self, kb_with_tagged_notes):
        """无标签笔记不会被选中"""
        results = list_notes(tags=["python"], cfg=kb_with_tagged_notes)
        for n in results:
            assert "今日想法" not in n.title

    def test_filter_with_note_type(self, kb_with_tagged_notes):
        """标签 + 类型联合过滤"""
        results = list_notes(
            tags=["python"], note_type=NoteType.PERMANENT, cfg=kb_with_tagged_notes
        )
        assert len(results) == 1
        assert results[0].title == "Python 基础"
