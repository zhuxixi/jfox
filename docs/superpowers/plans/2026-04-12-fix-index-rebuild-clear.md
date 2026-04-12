# Fix index rebuild 不清除 ChromaDB 旧数据 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `jfox index rebuild` to clear ChromaDB before re-indexing, eliminating stale entries for deleted notes.

**Architecture:** Add a `clear()` method to `VectorStore` (mirroring the existing `BM25Index.clear()` pattern), then call it at the start of `Indexer.index_all()` so every rebuild starts from a clean state.

**Tech Stack:** Python, ChromaDB, pytest

---

### Task 1: Add `VectorStore.clear()` method

**Files:**
- Modify: `jfox/vector_store.py:170` (after `get_stats`, before the global instance block)
- Test: `tests/unit/test_vector_store_clear.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_vector_store_clear.py`:

```python
"""
测试 VectorStore.clear() 方法

验证 rebuild 前清除旧数据的逻辑
"""

import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestVectorStoreClear:
    """VectorStore.clear() 单元测试"""

    def test_clear_removes_all_documents(self):
        """clear() 应删除 collection 中所有文档"""
        from jfox.vector_store import VectorStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = VectorStore(persist_directory=Path(tmpdir))
            store.init()

            # 插入 mock 数据（跳过 embedding，直接操作 collection）
            store.collection.add(
                ids=["note_001", "note_002", "note_003"],
                documents=["doc1", "doc2", "doc3"],
                embeddings=[[0.1] * 384, [0.2] * 384, [0.3] * 384],
                metadatas=[
                    {"title": "t1", "type": "permanent", "filepath": "/a", "tags": ""},
                    {"title": "t2", "type": "permanent", "filepath": "/b", "tags": ""},
                    {"title": "t3", "type": "permanent", "filepath": "/c", "tags": ""},
                ],
            )

            assert store.collection.count() == 3

            # 清除
            result = store.clear()

            assert result is True
            assert store.collection.count() == 0

    def test_clear_on_empty_collection(self):
        """clear() 在空 collection 上应正常返回 True"""
        from jfox.vector_store import VectorStore

        with tempfile.TemporaryDirectory() as tmpdir:
            store = VectorStore(persist_directory=Path(tmpdir))
            store.init()

            assert store.collection.count() == 0

            result = store.clear()

            assert result is True
            assert store.collection.count() == 0

    def test_clear_returns_false_on_failure(self):
        """clear() 在异常时应返回 False 而非抛出"""
        from jfox.vector_store import VectorStore

        store = VectorStore()
        # 不调用 init()，collection 为 None
        # clear 应该自动 init 或者返回 False
        # 这里 mock 一个会抛异常的 collection
        store.collection = MagicMock()
        store.collection.get.side_effect = Exception("DB error")

        result = store.clear()

        assert result is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_vector_store_clear.py -v`
Expected: FAIL — `VectorStore` has no `clear` method.

- [ ] **Step 3: Implement `VectorStore.clear()`**

Add the following method to `VectorStore` class in `jfox/vector_store.py`, after the `get_stats` method (line 184) and before the global instance block (line 187):

```python
    def clear(self) -> bool:
        """
        清空向量存储中的所有数据

        用于 index rebuild 时先清除旧数据，确保干净重建。

        Returns:
            是否成功清空
        """
        if self.collection is None:
            self.init()

        try:
            result = self.collection.get(include=[])
            ids = result.get("ids", [])
            if ids:
                self.collection.delete(ids=ids)
            logger.info(f"Cleared vector store ({len(ids)} notes removed)")
            return True
        except Exception as e:
            logger.error(f"Failed to clear vector store: {e}")
            return False
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_vector_store_clear.py -v`
Expected: All 3 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add jfox/vector_store.py tests/unit/test_vector_store_clear.py
git commit -m "feat: add VectorStore.clear() method for index rebuild"
```

---

### Task 2: Call `clear()` in `Indexer.index_all()` before re-indexing

**Files:**
- Modify: `jfox/indexer.py:220-224` (start of `index_all` method body)
- Test: `tests/unit/test_indexer_clear_before_rebuild.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_indexer_clear_before_rebuild.py`:

```python
"""
测试 Indexer.index_all() 在重建前清除旧数据

验证 rebuild 流程：先 clear 再 index
"""

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest


class TestIndexerClearBeforeRebuild:
    """Indexer.index_all() 应先清除旧索引再重建"""

    def test_index_all_calls_vector_store_clear(self):
        """index_all() 应在索引笔记前调用 vector_store.clear()"""
        from jfox.indexer import Indexer

        mock_config = MagicMock()
        mock_vector_store = MagicMock()

        # 配置：返回空目录（0 个笔记，只测 clear 调用顺序）
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            notes_dir = Path(tmpdir) / "notes"
            notes_dir.mkdir()
            mock_config.notes_dir = str(notes_dir)

            indexer = Indexer(config=mock_config, vector_store=mock_vector_store)
            count = indexer.index_all()

            # 0 个笔记，index_all 返回 0
            assert count == 0
            # 但 clear 应该被调用
            mock_vector_store.clear.assert_called_once()

    def test_index_all_clear_called_before_add(self):
        """clear() 必须在 add_or_update_note() 之前调用"""
        from jfox.indexer import Indexer

        mock_config = MagicMock()
        mock_vector_store = MagicMock()

        # 创建一个临时笔记文件
        import tempfile

        with tempfile.TemporaryDirectory() as tmpdir:
            notes_dir = Path(tmpdir) / "notes"
            notes_dir.mkdir()
            mock_config.notes_dir = str(notes_dir)

            # 创建一个假笔记文件
            note_file = notes_dir / "20260412120000-test.md"
            note_file.write_text(
                "---\nid: '20260412120000'\ntitle: Test\ntype: permanent\ntags: []\n---\nContent"
            )

            with patch("jfox.indexer.NoteManager") as mock_note_mgr:
                mock_note = MagicMock()
                mock_note.id = "20260412120000"
                mock_note_mgr.load_note.return_value = mock_note

                # 需要在 import 时就 patch
                with patch.dict("sys.modules", {}):
                    indexer = Indexer(config=mock_config, vector_store=mock_vector_store)
                    indexer.index_all()

            # 验证调用顺序：clear 在 add_or_update_note 之前
            calls = mock_vector_store.method_calls
            clear_indices = [i for i, c in enumerate(calls) if c[0] == "clear"]
            add_indices = [i for i, c in enumerate(calls) if c[0] == "add_or_update_note"]

            if clear_indices and add_indices:
                assert clear_indices[0] < add_indices[0], (
                    f"clear() (call #{clear_indices[0]}) must be called before "
                    f"add_or_update_note() (call #{add_indices[0]})"
                )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_indexer_clear_before_rebuild.py -v`
Expected: FAIL — `index_all()` does not call `clear()` yet.

- [ ] **Step 3: Add `clear()` call to `index_all()`**

In `jfox/indexer.py`, modify the `index_all` method. Change lines 220-224 from:

```python
        from .note import NoteManager

        notes_dir = Path(self.config.notes_dir)
        if not notes_dir.exists():
            return 0
```

to:

```python
        from .note import NoteManager

        notes_dir = Path(self.config.notes_dir)
        if not notes_dir.exists():
            return 0

        # 清除旧索引数据，确保干净重建
        self.vector_store.clear()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_indexer_clear_before_rebuild.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add jfox/indexer.py tests/unit/test_indexer_clear_before_rebuild.py
git commit -m "fix: clear vector store before re-indexing in index_all()"
```

---

### Task 3: Integration verification

**Files:**
- No new files. Verify existing tests still pass.

- [ ] **Step 1: Run fast unit tests**

Run: `uv run pytest tests/unit/ -v`
Expected: All tests PASS (including the 5 new ones from Tasks 1-2).

- [ ] **Step 2: Close issue #102**

```bash
gh issue close 102 --comment "Fixed in #XXX. \`VectorStore.clear()\` now called before \`Indexer.index_all()\` rebuild."
```

Replace `#XXX` with the actual PR number after creating the PR.
