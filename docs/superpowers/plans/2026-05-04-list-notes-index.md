# list_notes() 元数据索引 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a lightweight in-memory metadata index so list_notes() and callers don't load full note content on every call.

**Architecture:** New `NoteIndex` class parses only YAML frontmatter (not content), stores `NoteMeta` dataclasses in dicts keyed by id/title/type. Exposed via `get_note_index(cfg)`. `list_notes()` signature unchanged but internally uses the index to reduce `load_note()` calls. Metadata-only callers (`find_note_id_by_title_or_id`, `refs`, `daily`, `inbox`) switch to `NoteIndex` directly.

**Tech Stack:** Python 3.10+, PyYAML (already in deps), no new dependencies.

---

## Task 1: Create NoteMeta dataclass and NoteIndex skeleton

**Files:**
- Create: `jfox/note_index.py`
- Test: `tests/unit/test_note_index.py`

- [ ] **Step 1: Write failing test for NoteIndex rebuild and basic query**

```python
"""
测试类型: 单元测试
目标模块: jfox.note_index
预估耗时: < 1秒
依赖要求: 无外部依赖

测试 NoteIndex 的构建和查询功能
"""

from datetime import datetime
from pathlib import Path

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_note_index.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jfox.note_index'`

- [ ] **Step 3: Implement NoteMeta and NoteIndex**

Create `jfox/note_index.py`:

```python
"""轻量级元数据索引，只解析 frontmatter 不读正文"""

import logging
import re
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .config import ZKConfig
from .models import NoteType

logger = logging.getLogger(__name__)


@dataclass
class NoteMeta:
    """笔记元数据（不含正文）"""

    id: str
    title: str
    type: NoteType
    tags: List[str] = field(default_factory=list)
    created: str = ""
    updated: str = ""
    filepath: str = ""
    links: List[str] = field(default_factory=list)
    backlinks: List[str] = field(default_factory=list)


def _parse_frontmatter_only(filepath: Path) -> Optional[dict]:
    """只读取 frontmatter 部分，不解析正文内容。

    Returns:
        解析后的 frontmatter dict，解析失败返回 None
    """
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            first_line = f.readline()
            if first_line.strip() != "---":
                return None

            lines = []
            for line in f:
                stripped = line.strip()
                if stripped == "---":
                    break
                lines.append(line)

            if not lines:
                return None

            fm_text = "".join(lines)
            return yaml.safe_load(fm_text)

    except (yaml.YAMLError, UnicodeDecodeError, OSError):
        return None


class NoteIndex:
    """轻量级元数据索引，CLI 模式每次启动时重建"""

    def __init__(self, cfg: ZKConfig):
        self._cfg = cfg
        self._by_id: Dict[str, NoteMeta] = {}
        self._by_title: Dict[str, NoteMeta] = {}  # title.lower() -> meta
        self._by_type: Dict[NoteType, List[NoteMeta]] = {t: [] for t in NoteType}
        self._invalid_files: List[str] = []

    def rebuild(self) -> None:
        """重建索引：遍历所有笔记目录，只解析 frontmatter"""
        self._by_id.clear()
        self._by_title.clear()
        for t in NoteType:
            self._by_type[t] = []
        self._invalid_files.clear()

        start = time.monotonic()

        for note_type in NoteType:
            dir_path = self._cfg.notes_dir / note_type.value
            if not dir_path.exists():
                continue

            for filepath in sorted(dir_path.glob("*.md"), reverse=True):
                fm = _parse_frontmatter_only(filepath)
                if fm is None:
                    self._invalid_files.append(str(filepath))
                    continue

                try:
                    note_id = fm.get("id", "")
                    if not note_id:
                        self._invalid_files.append(str(filepath))
                        continue

                    meta = NoteMeta(
                        id=note_id,
                        title=fm.get("title", "Untitled"),
                        type=NoteType(fm.get("type", "fleeting")),
                        tags=fm.get("tags", []),
                        created=str(fm.get("created", "")),
                        updated=str(fm.get("updated", "")),
                        filepath=str(filepath),
                        links=fm.get("links", []),
                        backlinks=fm.get("backlinks", []),
                    )

                    self._by_id[meta.id] = meta
                    self._by_title[meta.title.lower()] = meta
                    self._by_type[meta.type].append(meta)

                except (ValueError, KeyError):
                    self._invalid_files.append(str(filepath))
                    continue

        elapsed = time.monotonic() - start
        logger.debug(
            f"NoteIndex rebuilt: {len(self._by_id)} notes, "
            f"{len(self._invalid_files)} invalid, "
            f"{elapsed:.3f}s"
        )

    def find_by_id(self, note_id: str) -> Optional[NoteMeta]:
        """按 ID 精确查找"""
        return self._by_id.get(note_id)

    def find_by_title(self, title: str) -> Optional[NoteMeta]:
        """按标题查找（大小写不敏感）"""
        return self._by_title.get(title.lower())

    def find_by_title_prefix(self, prefix: str) -> List[NoteMeta]:
        """按标题前缀模糊匹配"""
        prefix_lower = prefix.lower()
        return [m for m in self._by_id.values() if m.title.lower().startswith(prefix_lower)]

    def list_meta(
        self,
        note_type: Optional[NoteType] = None,
        tags: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> List[NoteMeta]:
        """列出元数据，支持类型/标签过滤和 limit 截断"""
        if note_type:
            result = list(self._by_type.get(note_type, []))
        else:
            result = list(self._by_id.values())

        if tags:
            result = [m for m in result if all(t in m.tags for t in tags)]

        if limit:
            result = result[:limit]

        return result

    def get_all_meta(self) -> List[NoteMeta]:
        """返回全部元数据"""
        return list(self._by_id.values())

    def get_invalid_files(self) -> List[str]:
        """返回无效文件路径列表"""
        return list(self._invalid_files)


# 模块级缓存：同一命令进程内只构建一次
_index_cache: Optional[NoteIndex] = None
_index_cfg_path: Optional[str] = None


def get_note_index(cfg: Optional[ZKConfig] = None) -> NoteIndex:
    """获取 NoteIndex 单例（按 cfg.base_dir 缓存）"""
    from .config import config

    use_cfg = cfg or config
    global _index_cache, _index_cfg_path

    cfg_path = str(use_cfg.base_dir)
    if _index_cache is not None and _index_cfg_path == cfg_path:
        return _index_cache

    idx = NoteIndex(use_cfg)
    idx.rebuild()
    _index_cache = idx
    _index_cfg_path = cfg_path
    return idx


def reset_note_index():
    """重置索引缓存（供 use_kb 切换知识库时调用）"""
    global _index_cache, _index_cfg_path
    _index_cache = None
    _index_cfg_path = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_note_index.py -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/note_index.py tests/unit/test_note_index.py
git commit -m "feat: add NoteIndex with frontmatter-only metadata parsing (#190)"
```

---

## Task 2: Wire reset_note_index into use_kb and _reset_singletons

**Files:**
- Modify: `jfox/config.py:129-141` — `_reset_singletons()`

- [ ] **Step 1: Add reset_note_index to _reset_singletons**

In `jfox/config.py`, add the note_index reset to the `_reset_singletons` loop. Find the `_reset_singletons` function (line ~129) and add `(".note_index", "reset_note_index")` to the list:

```python
def _reset_singletons():
    """重置所有缓存的单例（搜索引擎、向量存储、BM25 索引、embedding 后端、元数据索引）"""
    import importlib

    for module_name, fn_name in [
        (".bm25_index", "reset_bm25_index"),
        (".search_engine", "reset_search_engine"),
        (".vector_store", "reset_vector_store"),
        (".embedding_backend", "reset_backend"),
        (".note_index", "reset_note_index"),
    ]:
        try:
            module = importlib.import_module(module_name, package="jfox")
            getattr(module, fn_name)()
        except Exception:
            pass
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `uv run pytest tests/unit/test_use_kb_env_var.py -v`
Expected: PASS (use_kb resets index on KB switch)

- [ ] **Step 3: Commit**

```bash
git add jfox/config.py
git commit -m "feat: wire reset_note_index into use_kb singleton reset (#190)"
```

---

## Task 3: Refactor list_notes() to use NoteIndex internally

**Files:**
- Modify: `jfox/note.py:149-203` — `list_notes()`

- [ ] **Step 1: Write failing test for list_notes efficiency (verify limit+tags bug fix)**

Add to `tests/unit/test_note_index.py`:

```python
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

        # tag1 有 5 条
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
```

- [ ] **Step 2: Run test to verify it fails on the tags+limit case**

Run: `uv run pytest tests/unit/test_note_index.py::TestListNotesViaIndex -v`
Expected: `test_list_notes_with_tags_and_limit` may pass (existing behavior), but we're about to change the implementation

- [ ] **Step 3: Rewrite list_notes() to use NoteIndex**

In `jfox/note.py`, replace the `list_notes` function (lines 149-203) with:

```python
def list_notes(
    note_type: Optional[NoteType] = None,
    limit: Optional[int] = None,
    cfg: Optional[ZKConfig] = None,
    tags: Optional[List[str]] = None,
) -> List[Note]:
    """
    列出笔记

    内部通过 NoteIndex 减少不必要的 load_note 调用。

    Args:
        note_type: 笔记类型筛选
        limit: 数量限制
        cfg: 可选的配置对象，默认使用全局 config
        tags: 标签筛选列表（AND 逻辑）

    Returns:
        笔记列表
    """
    from .note_index import get_note_index

    use_config = cfg or config

    # 通过索引获取匹配的元数据列表（tags/limit 在索引层生效）
    idx = get_note_index(use_config)
    metas = idx.list_meta(note_type=note_type, tags=tags, limit=limit)

    # 只加载匹配到的笔记文件
    notes = []
    skipped = 0
    for meta in metas:
        filepath = Path(meta.filepath)
        note = load_note(filepath)
        if note:
            notes.append(note)
        else:
            skipped += 1

    if skipped > 0:
        logger.warning(f"{skipped} 个文件无法加载，已跳过。运行 jfox check 清理。")

    return notes
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_note_index.py::TestListNotesViaIndex tests/unit/test_tag_filter.py -v`
Expected: All PASS (tag filter tests still pass, verifying backward compatibility)

- [ ] **Step 5: Commit**

```bash
git add jfox/note.py tests/unit/test_note_index.py
git commit -m "refactor: list_notes() uses NoteIndex to reduce load_note calls (#190)"
```

---

## Task 4: Migrate find_note_id_by_title_or_id to NoteIndex

**Files:**
- Modify: `jfox/cli.py:239-261` — `find_note_id_by_title_or_id()`

- [ ] **Step 1: Rewrite find_note_id_by_title_or_id to use NoteIndex**

Replace `find_note_id_by_title_or_id` in `jfox/cli.py` (lines 239-261):

```python
def find_note_id_by_title_or_id(
    title_or_id: str, all_notes: Optional[list] = None
) -> Optional[str]:
    """通过标题或ID查找笔记

    匹配优先级：精确ID → 精确标题 → 标题包含

    当 all_notes 未提供时，使用 NoteIndex 直接查找，避免全量加载。
    all_notes 参数保留用于向后兼容。
    """
    if all_notes is not None:
        # 向后兼容：调用者已提供全量列表
        title_lower = title_or_id.lower()
        contains_match = None
        for n in all_notes:
            if n.id == title_or_id:
                return n.id
            if n.title.lower() == title_lower:
                return n.id
            if contains_match is None and title_lower in n.title.lower():
                contains_match = n.id
        return contains_match

    # 通过 NoteIndex 直接查找
    from .note_index import get_note_index

    idx = get_note_index()

    # 精确 ID
    meta = idx.find_by_id(title_or_id)
    if meta:
        return meta.id

    # 精确标题
    meta = idx.find_by_title(title_or_id)
    if meta:
        return meta.id

    # 标题包含
    title_lower = title_or_id.lower()
    for meta in idx.get_all_meta():
        if title_lower in meta.title.lower():
            return meta.id

    return None
```

- [ ] **Step 2: Update add command to stop passing all_notes**

In `jfox/cli.py`, find the `_add_note_impl` function (~line 319). Replace:

```python
    all_notes = note.list_notes() if wiki_links else []
```

with:

```python
    # wiki link 解析不再需要预加载全量列表，
    # find_note_id_by_title_or_id 会通过 NoteIndex 查找
```

And replace the loop that uses `all_notes`:

```python
    for link_text in wiki_links:
        target_id = find_note_id_by_title_or_id(link_text, all_notes=all_notes)
```

with:

```python
    for link_text in wiki_links:
        target_id = find_note_id_by_title_or_id(link_text)
```

- [ ] **Step 3: Update edit command to stop passing all_notes**

In `jfox/cli.py`, find the `_edit_impl` function (~line 1202). Replace:

```python
        all_notes = note.list_notes() if wiki_links else []
        for link_text in wiki_links:
            target_id = find_note_id_by_title_or_id(link_text, all_notes=all_notes)
```

with:

```python
        for link_text in wiki_links:
            target_id = find_note_id_by_title_or_id(link_text)
```

- [ ] **Step 4: Run existing tests to verify backward compatibility**

Run: `uv run pytest tests/unit/test_show.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/cli.py
git commit -m "refactor: find_note_id_by_title_or_id uses NoteIndex (#190)"
```

---

## Task 5: Migrate refs, daily, inbox to NoteIndex

**Files:**
- Modify: `jfox/cli.py:894-1000` — `_refs_impl`
- Modify: `jfox/cli.py:1560-1600` — `_daily_impl`
- Modify: `jfox/cli.py:1631-1660` — `_inbox_impl`

- [ ] **Step 1: Migrate _refs_impl search branch (~line 903)**

Replace:

```python
        all_notes = note.list_notes()
        matches = [n for n in all_notes if search.lower() in n.title.lower()]
```

with:

```python
        from .note_index import get_note_index

        idx = get_note_index()
        all_meta = idx.get_all_meta()
        matches = [m for m in all_meta if search.lower() in m.title.lower()]
```

Then update the `matches` output to use `NoteMeta` fields instead of `Note` fields (both have `id`, `title`, `type`, `backlinks` — same attribute names). The `len(n.backlinks)` at ~line 919 works the same since `NoteMeta.backlinks` is a list.

- [ ] **Step 2: Migrate _refs_impl all-notes branch (~line 981)**

Replace:

```python
        all_notes = note.list_notes()
        notes_with_links = []
        for n in all_notes:
            notes_with_links.append(
                {
                    "id": n.id,
                    "title": n.title,
                    "type": n.type.value,
                    "outgoing": len(n.links),
                    "incoming": len(n.backlinks),
                }
            )
```

with:

```python
        from .note_index import get_note_index

        idx = get_note_index()
        all_meta = idx.get_all_meta()
        notes_with_links = []
        for m in all_meta:
            notes_with_links.append(
                {
                    "id": m.id,
                    "title": m.title,
                    "type": m.type.value,
                    "outgoing": len(m.links),
                    "incoming": len(m.backlinks),
                }
            )
```

- [ ] **Step 3: Migrate _daily_impl (~line 1574)**

Replace:

```python
    all_notes = note.list_notes()
    daily_notes = [n for n in all_notes if n.id.startswith(date_str)]
```

with:

```python
    from .note_index import get_note_index

    idx = get_note_index()
    all_meta = idx.get_all_meta()
    daily_notes = [m for m in all_meta if m.id.startswith(date_str)]
```

Update the output dict to use `NoteMeta` fields (`m.id`, `m.title`, `m.type.value`, `m.created`). Note that `m.created` is a string (ISO format), not a datetime — use it directly instead of `.isoformat()`:

```python
        "notes": [
            {
                "id": m.id,
                "title": m.title,
                "type": m.type.value,
                "created": m.created,
            }
            for m in daily_notes
        ],
```

For the table output branch, `m.created` is an ISO string — format it with:

```python
            created_str = m.created[:10] if m.created else ""
            console.print(f"- [{m.type.value}] {m.title}")
```

- [ ] **Step 4: Migrate _inbox_impl (~line 1637)**

Replace:

```python
    fleeting_notes = note.list_notes(note_type=NoteType.FLEETING, limit=limit)
```

with:

```python
    from .note_index import get_note_index

    idx = get_note_index()
    fleeting_notes = idx.list_meta(note_type=NoteType.FLEETING, limit=limit)
```

Update the output dict — `NoteMeta.filepath` is a string:

```python
        "notes": [
            {
                "id": m.id,
                "title": m.title,
                "created": m.created,
                "filepath": m.filepath,
            }
            for m in fleeting_notes
        ],
```

For the table output, `m.created` is an ISO string:

```python
        for m in fleeting_notes:
            time_str = m.created[11:16] if m.created and len(m.created) >= 16 else ""
            console.print(f"- [{time_str}] {m.title}")
```

- [ ] **Step 5: Commit**

```bash
git add jfox/cli.py
git commit -m "refactor: migrate refs/daily/inbox to use NoteIndex (#190)"
```

---

## Task 6: Final verification

- [ ] **Step 1: Run all fast unit tests**

Run: `uv run pytest tests/unit/ -v`
Expected: All PASS

- [ ] **Step 2: Run list_notes related tests**

Run: `uv run pytest tests/unit/test_note_index.py tests/unit/test_tag_filter.py tests/unit/test_list_notes_skip.py -v`
Expected: All PASS

- [ ] **Step 3: Provide full test command for user to run**

```
uv run pytest tests/ -v
```

User should run this to verify full integration.
