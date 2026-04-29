# Bulk-Import VectorStore 初始化修复 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 `bulk_import_notes()` 中 VectorStore.collection 未初始化导致批量索引静默失败的问题，同时让 `index rebuild` 命令同时重建 BM25 索引。

**Architecture:** 两处独立修复：(1) `performance.py` 在批量索引前确保 VectorStore 已初始化；(2) `cli.py` 的 `index rebuild` 命令增加 BM25 重建步骤。两处修复互不依赖。

**Tech Stack:** Python 3.10+, pytest, unittest.mock

---

## Task 1: 修复 bulk_import_notes 中 VectorStore 未初始化的 bug

**Files:**
- Modify: `jfox/performance.py:266`
- Test: `tests/unit/test_bm25_batch.py`

- [ ] **Step 1: 写一个能复现 bug 的失败测试**

在 `tests/unit/test_bm25_batch.py` 的 `TestBulkImportBM25Integration` 类中，添加一个测试：模拟 `VectorStore` 的 `collection` 为 `None`（即真实场景），验证 `bulk_import_notes` 不会抛异常。

```python
@patch("jfox.bm25_index.get_bm25_index")
@patch("jfox.embedding_backend.get_backend")
@patch("jfox.note.create_note")
def test_bulk_import_with_uninitialized_vectorstore(
    self, mock_create_note, mock_get_backend, mock_get_bm25, tmp_path
):
    """bulk_import_notes 应在 collection.add() 前自动初始化 VectorStore"""
    import numpy as np

    from jfox.models import Note, NoteType
    from jfox.performance import bulk_import_notes

    # 准备 mock note
    mock_note = MagicMock(spec=Note)
    mock_note.id = "20260413120000"
    mock_note.title = "测试初始化"
    mock_note.content = "内容"
    mock_note.type = NoteType.PERMANENT
    mock_note.tags = []
    mock_note.filepath = tmp_path / "notes" / "permanent" / "test.md"
    mock_note.to_markdown.return_value = "# 测试初始化\n内容"
    mock_create_note.return_value = mock_note

    # mock embedding backend
    mock_backend = MagicMock()
    mock_backend.model = MagicMock()
    mock_backend.encode.return_value = np.array([[0.1] * 384])
    mock_get_backend.return_value = mock_backend

    # mock BM25
    mock_bm25 = MagicMock()
    mock_bm25.add_documents_batch.return_value = True
    mock_get_bm25.return_value = mock_bm25

    # 不 mock get_vector_store，让真实的 VectorStore 被创建
    # 但 patch 掉 VectorStore.init 来验证它被调用了
    with patch("jfox.performance.get_vector_store") as mock_get_vs:
        mock_vs = MagicMock()
        # 关键：collection 初始为 None，模拟真实场景
        mock_vs.collection = None

        # init() 会设置 collection
        def fake_init():
            mock_vs.collection = MagicMock()

        mock_vs.init.side_effect = fake_init
        mock_get_vs.return_value = mock_vs

        notes_data = [{"title": "测试初始化", "content": "内容"}]
        result = bulk_import_notes(notes_data, show_progress=False)

        # 验证 init 被调用了
        mock_vs.init.assert_called()
        # 导入成功
        assert result["imported"] == 1
```

- [ ] **Step 2: 运行测试确认它失败**

Run: `uv run pytest tests/unit/test_bm25_batch.py::TestBulkImportBM25Integration::test_bulk_import_with_uninitialized_vectorstore -v`
Expected: FAIL — 当前代码直接访问 `vector_store.collection.add()`，不会调用 `init()`，mock 的 `collection` 仍为 None，会抛 `AttributeError`。

- [ ] **Step 3: 修复 performance.py — 在 collection.add() 前添加初始化**

在 `jfox/performance.py` 第 266 行之前，添加初始化检查。修改 `# 批量添加到 ChromaDB` 注释后的代码块：

```python
                # 确保 VectorStore 已初始化
                if vector_store.collection is None:
                    vector_store.init()

                # 批量添加到 ChromaDB
                vector_store.collection.add(
                    ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas
                )
```

完整上下文（`performance.py` 约第 254-268 行）修改后为：

```python
                # 批量添加到 ChromaDB
                ids = [n.id for n in notes]
                metadatas = [
                    {
                        "title": n.title,
                        "type": n.type.value,
                        "filepath": str(n.filepath),
                        "tags": ",".join(n.tags),
                    }
                    for n in notes
                ]

                # 确保 VectorStore 已初始化
                if vector_store.collection is None:
                    vector_store.init()

                vector_store.collection.add(
                    ids=ids, documents=documents, embeddings=embeddings, metadatas=metadatas
                )
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_bm25_batch.py -v`
Expected: ALL PASS（包括新测试和原有测试）

- [ ] **Step 5: Commit**

```bash
git add jfox/performance.py tests/unit/test_bm25_batch.py
git commit -m "fix: bulk_import_notes 中 VectorStore.collection 未初始化导致索引失败

performance.py 的 bulk_import_notes() 直接访问 vector_store.collection.add()，
绕过了 add_note() 中的 init() 保护。在新会话中直接执行 bulk-import 时，
collection 为 None 导致 'NoneType' object has no attribute 'add' 错误。

在 collection.add() 前添加 if vector_store.collection is None: vector_store.init()。

Closes #126 (修复 1/2)"
```

---

## Task 2: 让 index rebuild 同时重建 BM25 索引

**Files:**
- Modify: `jfox/cli.py:1701-1713`
- Test: `tests/unit/test_index_kb_param.py`（在已有文件中添加测试）

- [ ] **Step 1: 写失败测试 — 验证 rebuild 时也调用了 BM25 重建**

在 `tests/unit/test_index_kb_param.py` 中添加测试：

```python
class TestIndexRebuildIncludesBM25:
    """验证 index rebuild 同时重建 BM25 索引"""

@patch("jfox.cli.note")
@patch("jfox.cli.get_bm25_index")
@patch("jfox.cli.Indexer")
@patch("jfox.cli.get_vector_store")
def test_rebuild_calls_bm25_rebuild(
    self, mock_get_vs, mock_indexer_cls, mock_get_bm25, mock_note, tmp_path
):
    """index rebuild 应在 ChromaDB 重建后调用 BM25 rebuild_from_notes"""
    from jfox.cli import _index_impl

    # mock vector store
    mock_vs = MagicMock()
    mock_get_vs.return_value = mock_vs

    # mock indexer
    mock_indexer = MagicMock()
    mock_indexer.index_all.return_value = 10
    mock_indexer_cls.return_value = mock_indexer

    # mock note.list_notes
    mock_notes = [MagicMock() for _ in range(3)]
    mock_note.list_notes.return_value = mock_notes

    # mock BM25
    mock_bm25 = MagicMock()
    mock_bm25.rebuild_from_notes.return_value = True
    mock_get_bm25.return_value = mock_bm25

    _index_impl("rebuild", "text")

    # 验证 ChromaDB 重建被调用
    mock_indexer.index_all.assert_called_once()
    # 验证 BM25 重建也被调用
    mock_get_bm25.assert_called_once()
    mock_bm25.rebuild_from_notes.assert_called_once_with(mock_notes)
```

- [ ] **Step 2: 运行测试确认它失败**

Run: `uv run pytest tests/unit/test_index_kb_param.py::TestIndexRebuildIncludesBM25 -v`
Expected: FAIL — 当前 `rebuild` 分支不调用 BM25 重建。

- [ ] **Step 3: 修改 cli.py 的 rebuild 分支，增加 BM25 重建**

修改 `jfox/cli.py` 第 1701-1713 行的 `rebuild` 分支。修改后：

```python
        elif action == "rebuild":
            console.print("[yellow]Rebuilding index...[/yellow]")
            count = indexer.index_all()

            # 同时重建 BM25 索引
            from . import note as note_module
            from .bm25_index import get_bm25_index

            bm25_index = get_bm25_index()
            notes = note_module.list_notes(limit=10000)
            bm25_success = bm25_index.rebuild_from_notes(notes)

            result = {
                "success": True,
                "indexed": count,
                "bm25_rebuilt": bm25_success,
                "bm25_indexed": len(notes),
            }

            if output_format == "json":
                print(output_json(result))
            else:
                console.print(f"[green]✓[/green] Indexed {count} notes")
                if bm25_success:
                    console.print(f"[green]✓[/green] BM25 index rebuilt: {len(notes)} notes")
                else:
                    console.print("[yellow]⚠[/yellow] ChromaDB rebuilt, but BM25 rebuild failed")
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_index_kb_param.py -v`
Expected: ALL PASS

- [ ] **Step 5: 验证现有 rebuild-bm25 单独命令仍正常**

Run: `uv run pytest tests/unit/test_index_kb_param.py -v -k "not RebuildIncludesBM25"`
Expected: ALL PASS（原有测试不受影响）

- [ ] **Step 6: Commit**

```bash
git add jfox/cli.py tests/unit/test_index_kb_param.py
git commit -m "fix: index rebuild 同时重建 BM25 索引

之前 index rebuild 只重建 ChromaDB，用户需额外手动执行 rebuild-bm25。
现在 rebuild 操作自动同时重建两个索引，输出中显示各自的重建状态。

Refs #126 (修复 2/2)"
```

---

## 自查清单

| 检查项 | 状态 |
|--------|------|
| 修复 1: performance.py VectorStore 初始化 | Task 1 覆盖 |
| 修复 2: cli.py rebuild 含 BM25 | Task 2 覆盖 |
| 现有测试不受影响 | Task 1/2 的 Step 4 验证 |
| 无 placeholder / TBD | 已检查，每步都有完整代码 |
| 类型/方法签名一致 | `rebuild_from_notes(notes)` 在 bm25_index.py:369 和 cli.py 一致 |
| `rebuild-bm25` 独立命令仍可用 | Task 2 Step 5 验证，独立命令逻辑未被修改 |
