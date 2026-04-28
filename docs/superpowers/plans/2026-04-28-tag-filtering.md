# Tag Filtering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--tag` (repeatable, AND logic) to `jfox list` and `jfox search` commands, threading a `tags` parameter through all layers.

**Architecture:** ChromaDB `$contains` metadata filter for semantic/hybrid search, post-filter for BM25, in-memory filter for list_notes. Tags are a hard pre-filter.

**Tech Stack:** Python, Typer CLI, ChromaDB, pytest

**Spec:** `docs/superpowers/specs/2026-04-28-tag-filtering-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `jfox/vector_store.py` | Modify | Add `tags` param to `search()`, build `$contains` where clause |
| `jfox/search_engine.py` | Modify | Add `tags` param to `search()`, pass through + BM25 post-filter |
| `jfox/note.py` | Modify | Add `tags` param to `list_notes()` and `search_notes()` |
| `jfox/cli.py` | Modify | Add `--tag` option to `search` and `list` commands |
| `tests/utils/jfox_cli.py` | Modify | Add `tags` param to `list()` and `search()` wrapper methods |
| `tests/unit/test_tag_filter.py` | Create | Unit tests for `list_notes(tags=...)` |
| `tests/integration/test_tag_filter_cli.py` | Create | CLI integration tests for `jfox list --tag` and `jfox search --tag` |

---

### Task 1: Add `tags` parameter to `vector_store.py`

**Files:**
- Modify: `jfox/vector_store.py:108-152` (the `search()` method)

- [ ] **Step 1: Add `tags` parameter and build where clause**

In `jfox/vector_store.py`, modify the `search()` method signature (line 108-109) and the where-clause construction (lines 122-125). Replace:

```python
    def search(
        self, query: str, top_k: int = 5, note_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
```

with:

```python
    def search(
        self,
        query: str,
        top_k: int = 5,
        note_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
```

Then replace the where-clause block (lines 122-125):

```python
            # 构建过滤条件
            where = {}
            if note_type:
                where["type"] = note_type
```

with:

```python
            # 构建过滤条件
            where = {}
            if note_type:
                where["type"] = note_type
            if tags:
                tag_clauses = [{"tags": {"$contains": t}} for t in tags]
                if where:
                    # 已有 note_type 条件，合并到 $and
                    combined = [where] + tag_clauses
                    where = {"$and": combined}
                elif len(tag_clauses) > 1:
                    where = {"$and": tag_clauses}
                else:
                    where = tag_clauses[0]
```

- [ ] **Step 2: Verify the change compiles**

Run: `uv run python -c "from jfox.vector_store import VectorStore; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add jfox/vector_store.py
git commit -m "feat(vector_store): add tags parameter to search() for ChromaDB filtering"
```

---

### Task 2: Add `tags` parameter to `search_engine.py`

**Files:**
- Modify: `jfox/search_engine.py:51-75` (the `search()` method)
- Modify: `jfox/search_engine.py:77-92` (`_semantic_search`)
- Modify: `jfox/search_engine.py:94-127` (`_keyword_search`)
- Modify: `jfox/search_engine.py:129-211` (`_hybrid_search`)

- [ ] **Step 1: Add `tags` parameter to `search()` and thread through**

In `jfox/search_engine.py`, modify the `search()` method (lines 51-75). Replace:

```python
    def search(
        self,
        query: str,
        top_k: int = 5,
        mode: SearchMode = SearchMode.HYBRID,
        note_type: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        执行搜索

        Args:
            query: 搜索查询
            top_k: 返回结果数量
            mode: 搜索模式
            note_type: 笔记类型筛选

        Returns:
            搜索结果列表
        """
        if mode == SearchMode.SEMANTIC:
            return self._semantic_search(query, top_k, note_type)
        elif mode == SearchMode.KEYWORD:
            return self._keyword_search(query, top_k)
        else:  # HYBRID
            return self._hybrid_search(query, top_k, note_type)
```

with:

```python
    def search(
        self,
        query: str,
        top_k: int = 5,
        mode: SearchMode = SearchMode.HYBRID,
        note_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        执行搜索

        Args:
            query: 搜索查询
            top_k: 返回结果数量
            mode: 搜索模式
            note_type: 笔记类型筛选
            tags: 标签筛选（AND 逻辑，所有标签必须匹配）

        Returns:
            搜索结果列表
        """
        if mode == SearchMode.SEMANTIC:
            return self._semantic_search(query, top_k, note_type, tags)
        elif mode == SearchMode.KEYWORD:
            return self._keyword_search(query, top_k, tags)
        else:  # HYBRID
            return self._hybrid_search(query, top_k, note_type, tags)
```

- [ ] **Step 2: Add `tags` to `_semantic_search`**

Replace `_semantic_search` (lines 77-92):

```python
    def _semantic_search(
        self,
        query: str,
        top_k: int,
        note_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """纯语义搜索"""
        try:
            results = self.vector_store.search(
                query, top_k=top_k, note_type=note_type, tags=tags
            )
            # 添加搜索模式标记
            for r in results:
                r["search_mode"] = "semantic"
            return results
        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            return []
```

- [ ] **Step 3: Add `tags` to `_keyword_search` with post-filter**

Replace `_keyword_search` (lines 94-127):

```python
    def _keyword_search(
        self,
        query: str,
        top_k: int,
        tags: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """纯关键词搜索 (BM25)"""
        try:
            bm25_results = self.bm25_index.search(query, top_k=top_k)

            # 转换为与语义搜索一致的格式
            results = []
            for r in bm25_results:
                # 获取笔记详情
                from . import note as note_module

                note = note_module.load_note_by_id(r["note_id"])
                if note:
                    # 标签过滤：AND 逻辑
                    if tags and not all(t in note.tags for t in tags):
                        continue
                    results.append(
                        {
                            "id": r["note_id"],
                            "document": (
                                note.content[:300] + "..."
                                if len(note.content) > 300
                                else note.content
                            ),
                            "metadata": {
                                "title": note.title,
                                "type": note.type.value,
                                "tags": ",".join(note.tags),
                            },
                            "score": r["score"],
                            "search_mode": "keyword",
                        }
                    )

            return results
        except Exception as e:
            logger.error(f"Keyword search failed: {e}")
            return []
```

Note: Also added `"tags": ",".join(note.tags)` to keyword search metadata so it's consistent with semantic results.

- [ ] **Step 4: Add `tags` to `_hybrid_search` with post-filter for BM25**

Replace `_hybrid_search` (lines 129-211):

```python
    def _hybrid_search(
        self,
        query: str,
        top_k: int,
        note_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        混合搜索：RRF 融合

        公式: score = Σ 1 / (k + rank)
        """
        # 1. 执行两种搜索（获取更多结果用于融合）
        search_k = max(top_k * 2, 10)  # 获取足够多的结果

        semantic_results = []
        bm25_results = []

        try:
            semantic_results = self.vector_store.search(
                query, top_k=search_k, note_type=note_type, tags=tags
            )
        except Exception as e:
            logger.warning(f"Semantic search failed in hybrid mode: {e}")

        try:
            bm25_results = self.bm25_index.search(query, top_k=search_k)
        except Exception as e:
            logger.warning(f"BM25 search failed in hybrid mode: {e}")

        # BM25 结果按标签过滤
        if tags and bm25_results:
            filtered_bm25 = []
            for r in bm25_results:
                from . import note as note_module

                note_obj = note_module.load_note_by_id(r["note_id"])
                if note_obj and all(t in note_obj.tags for t in tags):
                    filtered_bm25.append(r)
            bm25_results = filtered_bm25

        # 如果一种搜索失败，回退到另一种
        if not semantic_results and not bm25_results:
            return []
        elif not semantic_results:
            return self._keyword_search(query, top_k, tags)
        elif not bm25_results:
            for r in semantic_results[:top_k]:
                r["search_mode"] = "semantic"
            return semantic_results[:top_k]

        # 2. RRF 融合
        fused_scores: Dict[str, float] = {}
        result_data: Dict[str, Dict] = {}

        # 处理语义搜索结果
        for rank, result in enumerate(semantic_results, start=1):
            note_id = result.get("id")
            if note_id:
                fused_scores[note_id] = fused_scores.get(note_id, 0) + 1 / (self.rrf_k + rank)
                result_data[note_id] = result

        # 处理 BM25 搜索结果
        for rank, result in enumerate(bm25_results, start=1):
            note_id = result.get("note_id")
            if note_id:
                fused_scores[note_id] = fused_scores.get(note_id, 0) + 1 / (self.rrf_k + rank)
                # 如果没有语义搜索结果，使用 BM25 的数据
                if note_id not in result_data:
                    from . import note as note_module

                    note_obj = note_module.load_note_by_id(note_id)
                    if note_obj:
                        result_data[note_id] = {
                            "id": note_id,
                            "document": (
                                note_obj.content[:300] + "..."
                                if len(note_obj.content) > 300
                                else note_obj.content
                            ),
                            "metadata": {
                                "title": note_obj.title,
                                "type": note_obj.type.value,
                                "tags": ",".join(note_obj.tags),
                            },
                        }

        # 3. 排序并返回 top_k
        sorted_ids = sorted(fused_scores.keys(), key=lambda x: fused_scores[x], reverse=True)

        results = []
        for note_id in sorted_ids[:top_k]:
            data = result_data.get(note_id, {})
            data["score"] = fused_scores[note_id]
            data["search_mode"] = "hybrid"
            results.append(data)

        return results
```

- [ ] **Step 5: Verify the change compiles**

Run: `uv run python -c "from jfox.search_engine import HybridSearchEngine; print('OK')"`

Expected: `OK`

- [ ] **Step 6: Commit**

```bash
git add jfox/search_engine.py
git commit -m "feat(search_engine): add tags parameter to search() with BM25 post-filter"
```

---

### Task 3: Add `tags` parameter to `note.py`

**Files:**
- Modify: `jfox/note.py:141-178` (`list_notes()`)
- Modify: `jfox/note.py:318-348` (`search_notes()`)

- [ ] **Step 1: Add `tags` to `list_notes()`**

In `jfox/note.py`, modify `list_notes()` signature (line 141). Replace:

```python
def list_notes(
    note_type: Optional[NoteType] = None,
    limit: Optional[int] = None,
    cfg: Optional[ZKConfig] = None,
) -> List[Note]:
    """
    列出笔记

    Args:
        note_type: 笔记类型筛选
        limit: 数量限制
        cfg: 可选的配置对象，默认使用全局 config

    Returns:
        笔记列表
    """
```

with:

```python
def list_notes(
    note_type: Optional[NoteType] = None,
    limit: Optional[int] = None,
    cfg: Optional[ZKConfig] = None,
    tags: Optional[List[str]] = None,
) -> List[Note]:
    """
    列出笔记

    Args:
        note_type: 笔记类型筛选
        limit: 数量限制
        cfg: 可选的配置对象，默认使用全局 config
        tags: 标签筛选（AND 逻辑，所有标签必须匹配）

    Returns:
        笔记列表
    """
```

Then add tag filtering after the for-loop block (after line 176, before the return). Find this:

```python
        if limit and len(notes) >= limit:
            break

    return notes
```

Replace with:

```python
        if limit and len(notes) >= limit:
            break

    # 标签过滤（AND 逻辑）
    if tags:
        notes = [n for n in notes if all(t in n.tags for t in tags)]

    return notes
```

- [ ] **Step 2: Add `tags` to `search_notes()`**

Replace `search_notes()` (lines 318-348):

```python
def search_notes(
    query: str,
    top_k: int = 5,
    note_type: Optional[str] = None,
    mode: str = "hybrid",
    tags: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    搜索笔记

    Args:
        query: 搜索查询
        top_k: 返回结果数量
        note_type: 笔记类型筛选
        mode: 搜索模式 - "hybrid"(混合), "semantic"(语义), "keyword"(关键词)
        tags: 标签筛选（AND 逻辑，所有标签必须匹配）

    Returns:
        搜索结果列表
    """
    from .search_engine import SearchMode, get_search_engine

    search_engine = get_search_engine()

    # 转换模式
    mode_map = {
        "hybrid": SearchMode.HYBRID,
        "semantic": SearchMode.SEMANTIC,
        "keyword": SearchMode.KEYWORD,
    }
    search_mode = mode_map.get(mode.lower(), SearchMode.HYBRID)

    return search_engine.search(
        query, top_k=top_k, mode=search_mode, note_type=note_type, tags=tags
    )
```

- [ ] **Step 3: Verify the change compiles**

Run: `uv run python -c "from jfox.note import list_notes, search_notes; print('OK')"`

Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add jfox/note.py
git commit -m "feat(note): add tags parameter to list_notes() and search_notes()"
```

---

### Task 4: Add `--tag` to CLI commands

**Files:**
- Modify: `jfox/cli.py:530-578` (`search` command and `_search_impl`)
- Modify: `jfox/cli.py:759-855` (`_list_impl` and `list` command)

- [ ] **Step 1: Add `--tag` to `search()` command**

In `jfox/cli.py`, modify the `search()` function (starting at line 530). Add the `tags` parameter after `search_mode` and before `output_format`. Replace:

```python
def search(
    query: str = typer.Argument(..., help="搜索查询"),
    top: int = typer.Option(5, "--top", "-n", help="返回结果数量"),
    note_type: Optional[str] = typer.Option(None, "--type", "-t", help="筛选笔记类型"),
    search_mode: str = typer.Option(
        "hybrid", "--mode", "-m", help="搜索模式: hybrid, semantic, keyword"
    ),
    output_format: str = typer.Option(
        "table", "--format", "-f", help="输出格式: json, table, csv, yaml, paths"
    ),
```

with:

```python
def search(
    query: str = typer.Argument(..., help="搜索查询"),
    top: int = typer.Option(5, "--top", "-n", help="返回结果数量"),
    note_type: Optional[str] = typer.Option(None, "--type", "-t", help="筛选笔记类型"),
    tags: Optional[List[str]] = typer.Option(None, "--tag", help="按标签筛选（可多次使用，AND 逻辑）"),
    search_mode: str = typer.Option(
        "hybrid", "--mode", "-m", help="搜索模式: hybrid, semantic, keyword"
    ),
    output_format: str = typer.Option(
        "table", "--format", "-f", help="输出格式: json, table, csv, yaml, paths"
    ),
```

Note: The `from typing import List` import should already exist at the top of `cli.py` (used by the `add` command's `--tag`). If not, add it.

Then update the two call sites to `_search_impl` inside `search()`. Find (around lines 565-567):

```python
                _search_impl(query, top, note_type, search_mode, output_format)
        else:
            _search_impl(query, top, note_type, search_mode, output_format)
```

Replace with:

```python
                _search_impl(query, top, note_type, tags, search_mode, output_format)
        else:
            _search_impl(query, top, note_type, tags, search_mode, output_format)
```

- [ ] **Step 2: Add `tags` to `_search_impl()`**

Modify `_search_impl()` (starting at line 450). Replace:

```python
def _search_impl(
    query: str,
    top: int,
    note_type: Optional[str],
    search_mode: str,
    output_format: str,
):
    """搜索笔记的内部实现"""
    from .formatters import OutputFormatter

    results = note.search_notes(query, top_k=top, note_type=note_type, mode=search_mode)
```

with:

```python
def _search_impl(
    query: str,
    top: int,
    note_type: Optional[str],
    tags: Optional[List[str]],
    search_mode: str,
    output_format: str,
):
    """搜索笔记的内部实现"""
    from .formatters import OutputFormatter

    results = note.search_notes(
        query, top_k=top, note_type=note_type, mode=search_mode, tags=tags
    )
```

- [ ] **Step 3: Add `--tag` to `list()` command**

Modify the `list()` function (starting at line 812). Replace:

```python
def list(
    note_type: Optional[str] = typer.Option(None, "--type", "-t", help="筛选笔记类型"),
    limit: int = typer.Option(10, "--limit", "-n", help="显示数量"),
    output_format: str = typer.Option(
        "table", "--format", "-f", help="输出格式: json, table, csv, yaml, paths, tree"
    ),
```

with:

```python
def list(
    note_type: Optional[str] = typer.Option(None, "--type", "-t", help="筛选笔记类型"),
    tags: Optional[List[str]] = typer.Option(None, "--tag", help="按标签筛选（可多次使用，AND 逻辑）"),
    limit: int = typer.Option(10, "--limit", "-n", help="显示数量"),
    output_format: str = typer.Option(
        "table", "--format", "-f", help="输出格式: json, table, csv, yaml, paths, tree"
    ),
```

Then update the call sites to `_list_impl`. Find (around lines 842-844):

```python
                _list_impl(note_type, limit, output_format)
        else:
            _list_impl(note_type, limit, output_format)
```

Replace with:

```python
                _list_impl(note_type, tags, limit, output_format)
        else:
            _list_impl(note_type, tags, limit, output_format)
```

- [ ] **Step 4: Add `tags` to `_list_impl()`**

Modify `_list_impl()` (starting at line 759). Replace:

```python
def _list_impl(
    note_type: Optional[str],
    limit: int,
    output_format: str,
):
    """列出笔记的内部实现"""
    from .formatters import OutputFormatter

    # 解析类型
    nt = None
    if note_type:
        try:
            nt = NoteType(note_type.lower())
        except ValueError:
            raise ValueError(f"Invalid note type: {note_type}")

    notes = note.list_notes(note_type=nt, limit=limit)
```

with:

```python
def _list_impl(
    note_type: Optional[str],
    tags: Optional[List[str]],
    limit: int,
    output_format: str,
):
    """列出笔记的内部实现"""
    from .formatters import OutputFormatter

    # 解析类型
    nt = None
    if note_type:
        try:
            nt = NoteType(note_type.lower())
        except ValueError:
            raise ValueError(f"Invalid note type: {note_type}")

    notes = note.list_notes(note_type=nt, limit=limit, tags=tags)
```

- [ ] **Step 5: Verify CLI compiles and `--tag` option appears**

Run: `uv run jfox list --help`

Expected: output includes `--tag` option

Run: `uv run jfox search --help`

Expected: output includes `--tag` option

- [ ] **Step 6: Commit**

```bash
git add jfox/cli.py
git commit -m "feat(cli): add --tag option to list and search commands"
```

---

### Task 5: Unit tests for `list_notes(tags=...)`

**Files:**
- Create: `tests/unit/test_tag_filter.py`

- [ ] **Step 1: Write the test file**

Create `tests/unit/test_tag_filter.py`:

```python
"""
测试类型: 单元测试
目标模块: jfox.note (list_notes tags 过滤)
预估耗时: < 1秒
依赖要求: 无外部依赖

测试 list_notes 的 tags 过滤功能（AND 逻辑）
"""

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

        from jfox.note import save_note

        notes = [
            Note(
                id="20260428001",
                title="Python 基础",
                content="Python 编程基础",
                type=NoteType.PERMANENT,
                tags=["python", "编程"],
            ),
            Note(
                id="20260428002",
                title="Java 入门",
                content="Java 编程入门",
                type=NoteType.PERMANENT,
                tags=["java", "编程"],
            ),
            Note(
                id="20260428003",
                title="机器学习笔记",
                content="机器学习相关内容",
                type=NoteType.LITERATURE,
                tags=["python", "机器学习"],
            ),
            Note(
                id="20260428004",
                title="今日想法",
                content="随手记录",
                type=NoteType.FLEETING,
                tags=[],
            ),
        ]

        for n in notes:
            save_note(n, cfg=cfg)

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
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/unit/test_tag_filter.py -v`

Expected: All 6 tests PASS

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_tag_filter.py
git commit -m "test: add unit tests for list_notes tags filtering"
```

---

### Task 6: Update `ZKCLI` test wrapper and write CLI integration tests

**Files:**
- Modify: `tests/utils/jfox_cli.py:210-226` (the `list()` and `search()` methods)
- Create: `tests/integration/test_tag_filter_cli.py`

- [ ] **Step 1: Add `tags` param to `ZKCLI.list()`**

In `tests/utils/jfox_cli.py`, replace the `list()` method (line 210):

```python
    def list(self, note_type: Optional[str] = None, limit: Optional[int] = None) -> CLIResult:
        """列出笔记"""
        args = []
        if note_type:
            args.extend(["--type", note_type])
        if limit:
            args.extend(["--limit", str(limit)])

        return self._run("list", *args)
```

with:

```python
    def list(
        self,
        note_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> CLIResult:
        """列出笔记"""
        args = []
        if note_type:
            args.extend(["--type", note_type])
        if tags:
            for tag in tags:
                args.extend(["--tag", tag])
        if limit:
            args.extend(["--limit", str(limit)])

        return self._run("list", *args)
```

- [ ] **Step 2: Add `tags` param to `ZKCLI.search()`**

Replace the `search()` method (line 220):

```python
    def search(self, query: str, top: int = 5, note_type: Optional[str] = None) -> CLIResult:
        """语义搜索"""
        args = [query, "--top", str(top)]
        if note_type:
            args.extend(["--type", note_type])

        return self._run("search", *args)
```

with:

```python
    def search(
        self,
        query: str,
        top: int = 5,
        note_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> CLIResult:
        """语义搜索"""
        args = [query, "--top", str(top)]
        if note_type:
            args.extend(["--type", note_type])
        if tags:
            for tag in tags:
                args.extend(["--tag", tag])

        return self._run("search", *args)
```

- [ ] **Step 3: Write CLI integration tests for `jfox list --tag`**

Create `tests/integration/test_tag_filter_cli.py`:

```python
"""
测试类型: 集成测试（CLI 层）
目标模块: jfox.cli (list --tag, search --tag)
预估耗时: < 5秒
依赖要求: 不需要 embedding

测试 CLI 层面的 --tag 标签过滤功能
"""

import json

import pytest

pytestmark = [pytest.mark.integration, pytest.mark.fast]


class TestListTagFilterCLI:
    """jfox list --tag CLI 集成测试"""

    def test_list_filter_single_tag(self, cli):
        """单标签过滤"""
        cli.add("Python 编程基础", title="Python 基础", tags=["python", "编程"])
        cli.add("Java 编程入门", title="Java 入门", tags=["java", "编程"])
        cli.add("今日想法", title="想法")

        result = cli.list(tags=["python"])
        assert result.success
        data = result.json()
        assert data["total"] == 1
        assert data["notes"][0]["title"] == "Python 基础"

    def test_list_filter_multiple_tags_and(self, cli):
        """多标签 AND 逻辑"""
        cli.add("Python 编程基础", title="Python 基础", tags=["python", "编程"])
        cli.add("Python 机器学习", title="ML 笔记", tags=["python", "机器学习"])
        cli.add("Java 编程入门", title="Java 入门", tags=["java", "编程"])

        result = cli.list(tags=["python", "编程"])
        assert result.success
        data = result.json()
        assert data["total"] == 1
        assert data["notes"][0]["title"] == "Python 基础"

    def test_list_filter_nonexistent_tag(self, cli):
        """不存在的标签返回空"""
        cli.add("一些内容", title="测试笔记")

        result = cli.list(tags=["nonexistent"])
        assert result.success
        data = result.json()
        assert data["total"] == 0

    def test_list_filter_no_tag(self, cli):
        """不传 --tag 返回全部"""
        cli.add("笔记1", title="笔记1", tags=["tag1"])
        cli.add("笔记2", title="笔记2")

        result = cli.list()
        assert result.success
        data = result.json()
        assert data["total"] == 2


class TestSearchTagFilterCLI:
    """jfox search --tag CLI 集成测试

    注意：search 需要 embedding，标记为 embedding。
    仅在 core/full CI job 中运行。
    """

    pytestmark = [pytest.mark.integration, pytest.mark.embedding]

    def test_search_filter_by_tag(self, cli):
        """search --tag 按标签预过滤"""
        cli.add("Python 编程基础教程", title="Python 基础", tags=["python"])
        cli.add("Java 编程入门教程", title="Java 入门", tags=["java"])

        result = cli.search("编程教程", tags=["python"])
        assert result.success
        data = result.json()
        assert data["total"] >= 1
        # 所有结果应该都有 python 标签
        for r in data["results"]:
            assert "python" in r.get("metadata", {}).get("tags", "")
```

- [ ] **Step 4: Run the list tests (fast, no embedding)**

Run: `uv run pytest tests/integration/test_tag_filter_cli.py::TestListTagFilterCLI -v`

Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add tests/utils/jfox_cli.py tests/integration/test_tag_filter_cli.py
git commit -m "test: add CLI integration tests for --tag filtering on list and search"
```

---

### Task 7: Update `_list_impl` table output to show tags

**Files:**
- Modify: `jfox/cli.py` (the table rendering in `_list_impl`, around lines 786-796)

- [ ] **Step 1: Add Tags column to the list table output**

In `_list_impl()`, find the table rendering block (around lines 786-796):

```python
        table = Table(title=f"Notes ({len(notes)} total)")
        table.add_column("ID", style="dim")
        table.add_column("Title", style="cyan")
        table.add_column("Type", style="green")
        table.add_column("Created", style="dim")

        for n in notes:
            created_str = n.created.strftime("%Y-%m-%d") if n.created else ""
            table.add_row(n.id, n.title[:40], n.type.value, created_str)
```

Replace with:

```python
        table = Table(title=f"Notes ({len(notes)} total)")
        table.add_column("ID", style="dim")
        table.add_column("Title", style="cyan")
        table.add_column("Type", style="green")
        table.add_column("Tags", style="yellow")
        table.add_column("Created", style="dim")

        for n in notes:
            created_str = n.created.strftime("%Y-%m-%d") if n.created else ""
            tags_str = ", ".join(n.tags) if n.tags else ""
            table.add_row(n.id, n.title[:40], n.type.value, tags_str, created_str)
```

- [ ] **Step 2: Verify visually**

Run: `uv run jfox list --help`

Expected: help text shows `--tag` option

- [ ] **Step 3: Commit**

```bash
git add jfox/cli.py
git commit -m "feat(cli): show tags column in list table output"
```

---

### Task 8: Final verification

- [ ] **Step 1: Run fast tests (no embedding)**

Run: `uv run pytest tests/unit/test_tag_filter.py tests/integration/test_tag_filter_cli.py::TestListTagFilterCLI -v`

Expected: All tests PASS

- [ ] **Step 2: Run lint checks**

Run: `uv run ruff check jfox/ tests/ && uv run black --check jfox/ tests/`

Expected: No errors

- [ ] **Step 3: Provide full test command for user**

The search tests require embedding (slow). Provide this command for the user to run manually:

```
uv run pytest tests/unit/test_tag_filter.py tests/integration/test_tag_filter_cli.py -v
```
