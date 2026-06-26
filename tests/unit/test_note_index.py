"""
测试类型: 单元测试
目标模块: jfox.note_index
预估耗时: < 1秒
依赖要求: 无外部依赖

测试 NoteIndex 的构建和查询功能
"""

from datetime import datetime

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.config import ZKConfig
from jfox.models import Note, NoteType
from jfox.note_index import NoteIndex, NoteMeta


class TestNoteIndexRebuild:
    """NoteIndex 构建测试"""

    @pytest.fixture
    def kb_with_notes(self, temp_kb):
        """创建包含多条笔记的知识库"""
        cfg = ZKConfig(base_dir=temp_kb)
        cfg.ensure_dirs()

        notes = [
            Note(
                id="20260428001",
                title="Python 基础",
                content="Python 编程基础内容，比较长的一段文字。",
                type=NoteType.PERMANENT,
                tags=["python", "编程"],
                created=datetime(2026, 4, 28, 0, 1),
                updated=datetime(2026, 4, 28, 0, 1),
            ),
            Note(
                id="20260428002",
                title="Java 入门",
                content="Java 编程入门内容。",
                type=NoteType.PERMANENT,
                tags=["java", "编程"],
                created=datetime(2026, 4, 28, 0, 2),
                updated=datetime(2026, 4, 28, 0, 2),
            ),
            Note(
                id="20260428003",
                title="机器学习笔记",
                content="机器学习相关内容。",
                type=NoteType.LITERATURE,
                tags=["python", "机器学习"],
                created=datetime(2026, 4, 28, 0, 3),
                updated=datetime(2026, 4, 28, 0, 3),
            ),
        ]

        for n in notes:
            note_dir = cfg.notes_dir / n.type.value
            note_dir.mkdir(parents=True, exist_ok=True)
            note_file = note_dir / f"{n.id}.md"
            note_file.write_text(n.to_markdown(), encoding="utf-8")

        return cfg

    def test_rebuild_counts_notes(self, kb_with_notes):
        """rebuild 后统计数正确"""
        idx = NoteIndex(kb_with_notes)
        idx.rebuild()
        assert len(idx.get_all_meta()) == 3

    def test_find_by_id(self, kb_with_notes):
        """按 ID 查找"""
        idx = NoteIndex(kb_with_notes)
        idx.rebuild()
        meta = idx.find_by_id("20260428001")
        assert meta is not None
        assert meta.title == "Python 基础"
        assert meta.type == NoteType.PERMANENT
        assert meta.tags == ["python", "编程"]

    def test_find_by_id_not_found(self, kb_with_notes):
        """ID 不存在返回 None"""
        idx = NoteIndex(kb_with_notes)
        idx.rebuild()
        assert idx.find_by_id("99999") is None

    def test_find_by_title_case_insensitive(self, kb_with_notes):
        """按标题查找，大小写不敏感"""
        idx = NoteIndex(kb_with_notes)
        idx.rebuild()
        meta = idx.find_by_title("python 基础")
        assert meta is not None
        assert meta.id == "20260428001"

    def test_find_by_title_not_found(self, kb_with_notes):
        """标题不存在返回 None"""
        idx = NoteIndex(kb_with_notes)
        idx.rebuild()
        assert idx.find_by_title("不存在的标题") is None

    def test_list_meta_by_type(self, kb_with_notes):
        """按类型筛选"""
        idx = NoteIndex(kb_with_notes)
        idx.rebuild()
        result = idx.list_meta(note_type=NoteType.PERMANENT)
        assert len(result) == 2
        assert all(m.type == NoteType.PERMANENT for m in result)

    def test_list_meta_by_tags(self, kb_with_notes):
        """按标签筛选（AND 逻辑）"""
        idx = NoteIndex(kb_with_notes)
        idx.rebuild()
        result = idx.list_meta(tags=["python", "编程"])
        assert len(result) == 1
        assert result[0].title == "Python 基础"

    def test_list_meta_with_limit(self, kb_with_notes):
        """limit 提前截断"""
        idx = NoteIndex(kb_with_notes)
        idx.rebuild()
        result = idx.list_meta(limit=2)
        assert len(result) == 2

    def test_list_meta_tags_with_limit(self, kb_with_notes):
        """tags + limit 组合，limit 生效"""
        idx = NoteIndex(kb_with_notes)
        idx.rebuild()
        # "编程" 标签有 2 条
        result = idx.list_meta(tags=["编程"], limit=1)
        assert len(result) == 1

    def test_find_by_title_prefix(self, kb_with_notes):
        """按标题前缀模糊匹配"""
        idx = NoteIndex(kb_with_notes)
        idx.rebuild()
        results = idx.find_by_title_prefix("Python")
        assert len(results) == 1
        assert results[0].title == "Python 基础"

    def test_get_all_meta_returns_list(self, kb_with_notes):
        """get_all_meta 返回全部"""
        idx = NoteIndex(kb_with_notes)
        idx.rebuild()
        all_meta = idx.get_all_meta()
        assert isinstance(all_meta, list)
        assert len(all_meta) == 3

    def test_note_meta_fields(self, kb_with_notes):
        """NoteMeta 包含所有必要字段"""
        idx = NoteIndex(kb_with_notes)
        idx.rebuild()
        meta = idx.find_by_id("20260428001")
        assert isinstance(meta, NoteMeta)
        assert meta.id == "20260428001"
        assert meta.title == "Python 基础"
        assert meta.type == NoteType.PERMANENT
        assert meta.tags == ["python", "编程"]
        assert meta.created == datetime(2026, 4, 28, 0, 1).isoformat()
        assert meta.updated == datetime(2026, 4, 28, 0, 1).isoformat()
        assert isinstance(meta.filepath, str)
        assert isinstance(meta.links, list)
        assert isinstance(meta.backlinks, list)


class TestNoteIndexInvalidFiles:
    """无效文件处理测试"""

    @pytest.fixture
    def kb_with_invalid(self, temp_kb):
        """创建包含无效文件的知识库"""
        cfg = ZKConfig(base_dir=temp_kb)
        cfg.ensure_dirs()

        # 正常笔记
        note = Note(
            id="20260428001",
            title="正常笔记",
            content="正常内容",
            type=NoteType.PERMANENT,
            tags=[],
            created=datetime(2026, 4, 28, 0, 1),
            updated=datetime(2026, 4, 28, 0, 1),
        )
        note_dir = cfg.notes_dir / NoteType.PERMANENT.value
        note_file = note_dir / f"{note.id}.md"
        note_file.write_text(note.to_markdown(), encoding="utf-8")

        # 空文件
        empty_file = note_dir / "20260428002.md"
        empty_file.write_text("", encoding="utf-8")

        # 损坏 frontmatter
        corrupt_file = note_dir / "20260428003.md"
        corrupt_file.write_text("no frontmatter here\njust content\n", encoding="utf-8")

        return cfg

    def test_invalid_files_skipped(self, kb_with_invalid):
        """无效文件不进入索引"""
        idx = NoteIndex(kb_with_invalid)
        idx.rebuild()
        assert len(idx.get_all_meta()) == 1
        assert idx.find_by_id("20260428001") is not None

    def test_get_invalid_files(self, kb_with_invalid):
        """记录无效文件路径"""
        idx = NoteIndex(kb_with_invalid)
        idx.rebuild()
        invalid = idx.get_invalid_files()
        assert len(invalid) == 2

    def test_empty_kb(self, temp_kb):
        """空知识库不报错"""
        cfg = ZKConfig(base_dir=temp_kb)
        cfg.ensure_dirs()
        idx = NoteIndex(cfg)
        idx.rebuild()
        assert len(idx.get_all_meta()) == 0
        assert idx.get_invalid_files() == []


class TestListNotesViaIndex:
    """验证 list_notes() 通过索引减少 load_note 调用"""

    @pytest.fixture
    def kb_with_many_notes(self, temp_kb):
        """创建包含多条笔记的知识库"""
        cfg = ZKConfig(base_dir=temp_kb)
        cfg.ensure_dirs()

        for i in range(10):
            n = Note(
                id=f"20260428{i:04d}",
                title=f"笔记 {i}",
                content=f"这是第 {i} 条笔记的内容，比较长。" * 10,
                type=NoteType.PERMANENT,
                tags=["tag1"] if i % 2 == 0 else ["tag2"],
                created=datetime(2026, 4, 28, 0, i),
                updated=datetime(2026, 4, 28, 0, i),
            )
            note_dir = cfg.notes_dir / n.type.value
            note_dir.mkdir(parents=True, exist_ok=True)
            note_file = note_dir / f"{n.id}.md"
            note_file.write_text(n.to_markdown(), encoding="utf-8")

        return cfg

    def test_list_notes_returns_full_note_objects(self, kb_with_many_notes):
        """list_notes 仍然返回完整 Note 对象（含 content）"""
        from jfox.note import list_notes

        notes = list_notes(cfg=kb_with_many_notes)
        assert len(notes) == 10
        assert all(hasattr(n, "content") for n in notes)
        assert all(len(n.content) > 0 for n in notes)

    def test_list_notes_with_tags_and_limit(self, kb_with_many_notes):
        """tags + limit 组合正常工作（修复原有 bug）"""
        from jfox.note import list_notes

        # tag1 has 5 notes
        result = list_notes(tags=["tag1"], limit=3, cfg=kb_with_many_notes)
        assert len(result) == 3
        assert all("tag1" in n.tags for n in result)

    def test_list_notes_with_type_filter(self, kb_with_many_notes):
        """类型过滤正常"""
        from jfox.note import list_notes

        result = list_notes(note_type=NoteType.PERMANENT, cfg=kb_with_many_notes)
        assert len(result) == 10

    def test_list_notes_limit_without_tags(self, kb_with_many_notes):
        """无 tags 时 limit 提前截断"""
        from jfox.note import list_notes

        result = list_notes(limit=3, cfg=kb_with_many_notes)
        assert len(result) == 3


class TestNoteIndexFindNotesReferencingTitle:
    """测试 find_notes_referencing_title"""

    @pytest.fixture
    def kb_with_wiki_links(self, temp_kb):
        """创建包含维基链接引用的知识库"""
        cfg = ZKConfig(base_dir=temp_kb)
        cfg.ensure_dirs()

        notes = [
            Note(
                id="20260428001",
                title="笔记A",
                content="笔记A 正文，引用了 [[笔记B]]。",
                type=NoteType.PERMANENT,
                created=datetime(2026, 4, 28, 0, 1),
                updated=datetime(2026, 4, 28, 0, 1),
            ),
            Note(
                id="20260428002",
                title="笔记B",
                content="笔记B 正文。",
                type=NoteType.PERMANENT,
                created=datetime(2026, 4, 28, 0, 2),
                updated=datetime(2026, 4, 28, 0, 2),
            ),
            Note(
                id="20260428003",
                title="笔记C",
                content="笔记C 引用了 [[笔记A]] 和 [[笔记B]]。",
                type=NoteType.PERMANENT,
                created=datetime(2026, 4, 28, 0, 3),
                updated=datetime(2026, 4, 28, 0, 3),
            ),
        ]

        for n in notes:
            note_dir = cfg.notes_dir / n.type.value
            note_dir.mkdir(parents=True, exist_ok=True)
            note_file = note_dir / f"{n.id}.md"
            note_file.write_text(n.to_markdown(), encoding="utf-8")

        return cfg

    def test_find_notes_referencing_title(self, kb_with_wiki_links):
        """能找出正文中引用了指定标题的笔记"""
        idx = NoteIndex(kb_with_wiki_links)
        idx.rebuild()

        refs = idx.find_notes_referencing_title("笔记B")
        ids = {m.id for m in refs}

        assert "20260428001" in ids
        assert "20260428003" in ids
        assert "20260428002" not in ids

    def test_find_notes_referencing_title_case_insensitive(self, kb_with_wiki_links):
        """标题匹配大小写不敏感"""
        idx = NoteIndex(kb_with_wiki_links)
        idx.rebuild()

        refs = idx.find_notes_referencing_title("笔记a")
        ids = {m.id for m in refs}

        assert "20260428003" in ids

    def test_find_notes_referencing_title_not_found(self, kb_with_wiki_links):
        """不存在引用时返回空列表"""
        idx = NoteIndex(kb_with_wiki_links)
        idx.rebuild()

        refs = idx.find_notes_referencing_title("不存在的笔记")
        assert refs == []

    def test_find_notes_referencing_title_skips_frontmatter(self, kb_with_wiki_links):
        """frontmatter 中的 [[...]] 不应被误判为正文引用"""
        cfg = kb_with_wiki_links
        note_dir = cfg.notes_dir / NoteType.PERMANENT.value
        note_dir.mkdir(parents=True, exist_ok=True)

        # 手动构造一篇笔记：title 里带 [[笔记B]]，但正文没有引用
        note_file = note_dir / "20260428004.md"
        note_file.write_text(
            "---\n"
            "id: '20260428004'\n"
            "title: '[[笔记B]] 的标题只在 frontmatter'\n"
            "type: permanent\n"
            "created: '2026-04-28T00:04:00'\n"
            "updated: '2026-04-28T00:04:00'\n"
            "tags: []\n"
            "links: []\n"
            "backlinks: []\n"
            "---\n\n"
            "# 标题\n\n"
            "正文没有任何维基链接。\n",
            encoding="utf-8",
        )

        idx = NoteIndex(cfg)
        idx.rebuild()

        refs = idx.find_notes_referencing_title("笔记B")
        ids = {m.id for m in refs}

        # 原来的 20260428001 和 20260428003 仍然命中
        assert "20260428001" in ids
        assert "20260428003" in ids
        # 新加的这篇因为只在 frontmatter 里出现，不应命中
        assert "20260428004" not in ids

    def test_find_notes_referencing_title_alias_and_anchor(self, kb_with_wiki_links):
        """支持 [[标题|别名]] 和 [[标题#锚点]] 变体"""
        cfg = kb_with_wiki_links
        note_dir = cfg.notes_dir / NoteType.PERMANENT.value
        note_dir.mkdir(parents=True, exist_ok=True)

        note_file = note_dir / "20260428005.md"
        note_file.write_text(
            "---\n"
            "id: '20260428005'\n"
            "title: '变体引用'\n"
            "type: permanent\n"
            "created: '2026-04-28T00:05:00'\n"
            "updated: '2026-04-28T00:05:00'\n"
            "tags: []\n"
            "links: []\n"
            "backlinks: []\n"
            "---\n\n"
            "正文引用了 [[笔记B|别名]] 和 [[笔记B#章节]]。\n",
            encoding="utf-8",
        )

        idx = NoteIndex(cfg)
        idx.rebuild()

        refs = idx.find_notes_referencing_title("笔记B")
        ids = {m.id for m in refs}

        assert "20260428005" in ids

    def test_find_notes_referencing_title_skips_code_block_and_comment(self, kb_with_wiki_links):
        """fenced code block 和 HTML 注释中的 [[...]] 不应被误判"""
        cfg = kb_with_wiki_links
        note_dir = cfg.notes_dir / NoteType.PERMANENT.value
        note_dir.mkdir(parents=True, exist_ok=True)

        note_file = note_dir / "20260428006.md"
        note_file.write_text(
            "---\n"
            "id: '20260428006'\n"
            "title: '代码块和注释'\n"
            "type: permanent\n"
            "created: '2026-04-28T00:06:00'\n"
            "updated: '2026-04-28T00:06:00'\n"
            "tags: []\n"
            "links: []\n"
            "backlinks: []\n"
            "---\n\n"
            "```\n"
            "这里出现 [[笔记B]] 但属于代码块\n"
            "```\n\n"
            "<!-- [[笔记B]] 这是 HTML 注释 -->\n\n"
            "正文没有实际引用。\n",
            encoding="utf-8",
        )

        idx = NoteIndex(cfg)
        idx.rebuild()

        refs = idx.find_notes_referencing_title("笔记B")
        ids = {m.id for m in refs}

        assert "20260428006" not in ids

    def test_find_notes_referencing_title_unicode_decode_error(self, kb_with_wiki_links):
        """遇到非 UTF-8 文件时不抛异常，而是跳过该文件"""
        cfg = kb_with_wiki_links
        note_dir = cfg.notes_dir / NoteType.PERMANENT.value
        note_dir.mkdir(parents=True, exist_ok=True)

        # 写入非法 UTF-8 字节
        corrupt_file = note_dir / "20260428007.md"
        corrupt_file.write_bytes(
            b"---\n"
            b"id: '20260428007'\n"
            b"title: '\xff\xfe'\n"
            b"type: permanent\n"
            b"---\n\n"
            b"\xff\xfe [[\xb1\xca\xc7\xf0]]"
        )

        idx = NoteIndex(cfg)
        idx.rebuild()

        # 不应抛出 UnicodeDecodeError
        refs = idx.find_notes_referencing_title("笔记B")
        ids = {m.id for m in refs}

        # 非法文件本身不会被识别为笔记（frontmatter 解析也会失败），
        # 但重点是查询过程不崩溃
        assert "20260428007" not in ids
