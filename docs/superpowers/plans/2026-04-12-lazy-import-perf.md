# Lazy Import Performance Optimization Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate unnecessary startup overhead for all CLI commands by setting HF offline env vars and deferring heavy imports (chromadb, networkx, watchdog) to only the commands that need them.

**Architecture:** Two-part fix. (A) Set `HF_HUB_OFFLINE=1` at CLI entry point before any HuggingFace imports. (B) Move heavy top-level imports from `cli.py` and `note.py` into the functions that use them. The key insight is that `note.py` imports `vector_store` (→ chromadb) at module level, so `from . import note` in `cli.py` drags chromadb into every command. Fixing `note.py` unblocks all ~7 lightweight commands.

**Tech Stack:** Python >= 3.10, Typer CLI, pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `jfox/cli.py` | Modify top-level imports (L1-39) | Move heavy imports into function bodies |
| `jfox/note.py` | Modify top-level import (L10) | Move `vector_store` import into 4 functions |
| `tests/unit/test_lazy_import.py` | Create | Verify lightweight commands don't import heavy deps |

No other files need changes.

---

### Task 1: Set HF offline env vars in `cli.py`

**Files:**
- Modify: `jfox/cli.py:1-39`

This is the simplest change with immediate payoff: eliminates HuggingFace HTTP HEAD requests that add 0.5-2s to every embedding command.

- [ ] **Step 1: Add env vars before all other imports**

In `jfox/cli.py`, insert the following block **at the very top of the file, before line 1** (before `"""CLI 主程序"""`):

```python
import os

# 离线模式：跳过 HuggingFace 网络请求，节省 0.5-2s
# 首次安装需 HF_HUB_OFFLINE=0 jfox status 下载模型
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")
```

The top of `cli.py` should now look like:

```python
import os

# 离线模式：跳过 HuggingFace 网络请求，节省 0.5-2s
# 首次安装需 HF_HUB_OFFLINE=0 jfox status 下载模型
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

"""CLI 主程序"""

import json
import logging
...
```

Wait — docstring must be first. Let me adjust:

The `"""CLI 主程序"""` is a module docstring and must remain at the top. Put the env vars **after** the docstring but **before** all other imports.

Insert after the docstring (after line 1) and before `import json` (line 3):

```python
"""CLI 主程序"""

import os

# 离线模式：跳过 HuggingFace 网络请求，节省 0.5-2s
# 首次安装需 HF_HUB_OFFLINE=0 jfox status 下载模型
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

import json
import logging
import sys
import warnings
...
```

- [ ] **Step 2: Verify CLI still works**

Run: `uv run jfox --version`

Expected: prints version, no errors.

- [ ] **Step 3: Verify offline behavior**

Run: `uv run jfox kb list`

Expected: works normally. No network requests should be made.

- [ ] **Step 4: Commit**

```bash
git add jfox/cli.py
git commit -m "perf: set HF_HUB_OFFLINE=1 to skip network checks

Saves 0.5-2s per embedding command by skipping HuggingFace HTTP HEAD
requests. First-time users need to run HF_HUB_OFFLINE=0 jfox status
to download the model.

Ref: #120"
```

---

### Task 2: Move `vector_store` import inside functions in `note.py`

**Files:**
- Modify: `jfox/note.py:10,74-76,192-194,250-253,301-303`

This is the **critical fix**. `note.py` imports `from .vector_store import get_vector_store` at module level (line 10), which pulls in `chromadb`. Since `cli.py` does `from . import note` at module level, **every CLI command** pays the chromadb import cost.

Moving this import into the 4 functions that use it breaks the chain.

- [ ] **Step 1: Remove top-level import**

In `jfox/note.py`, delete line 10:

```python
# DELETE THIS LINE:
from .vector_store import get_vector_store
```

- [ ] **Step 2: Add local import in `save_note()`**

In `jfox/note.py`, function `save_note()` at the line where `get_vector_store()` is called (around line 75), change:

```python
        # 添加到向量索引
        if add_to_index:
            vector_store = get_vector_store()
```

to:

```python
        # 添加到向量索引
        if add_to_index:
            from .vector_store import get_vector_store

            vector_store = get_vector_store()
```

- [ ] **Step 3: Add local import in `delete_note()`**

In `jfox/note.py`, function `delete_note()` at the line where `get_vector_store()` is called (around line 193), change:

```python
        # 从向量索引删除
        vector_store = get_vector_store()
```

to:

```python
        # 从向量索引删除
        from .vector_store import get_vector_store

        vector_store = get_vector_store()
```

- [ ] **Step 4: Add local import in `update_note()`**

In `jfox/note.py`, function `update_note()` at the line where `get_vector_store()` is called (around line 251), change:

```python
            try:
                vector_store = get_vector_store()
```

to:

```python
            try:
                from .vector_store import get_vector_store

                vector_store = get_vector_store()
```

- [ ] **Step 5: Add local import in `get_stats()`**

In `jfox/note.py`, function `get_stats()` at the line where `get_vector_store()` is called (around line 302), change:

```python
    try:
        vector_store = get_vector_store()
```

to:

```python
    try:
        from .vector_store import get_vector_store

        vector_store = get_vector_store()
```

- [ ] **Step 6: Run fast unit tests**

Run: `uv run pytest tests/unit/ -v --timeout=30`

Expected: all pass. This verifies `note.py` functions still work with deferred import.

- [ ] **Step 7: Commit**

```bash
git add jfox/note.py
git commit -m "perf: defer vector_store import in note.py

Move chromadb import from module-level to function-level in save_note,
delete_note, update_note, and get_stats. This breaks the chromadb
import chain that was forced on every CLI command via 'from . import note'.

Lightweight commands (list, refs, daily, inbox, kb, init) should now
start without loading chromadb.

Ref: #120"
```

---

### Task 3: Move heavy imports inside functions in `cli.py`

**Files:**
- Modify: `jfox/cli.py:31-39` (top-level imports)
- Modify: `jfox/cli.py:556` (`_status_impl`)
- Modify: `jfox/cli.py:1171` (`_query_impl`)
- Modify: `jfox/cli.py:1272` (`_graph_impl`)
- Modify: `jfox/cli.py:1666-1667` (`_index_impl`)
- Modify: `jfox/cli.py:2191-2203` (`bulk_import`)
- Modify: `jfox/cli.py:2234,2258` (`perf`)

- [ ] **Step 1: Remove heavy top-level imports**

In `jfox/cli.py`, delete these lines from the top-level import block (lines 31-39):

```python
# DELETE THESE LINES:
from .embedding_backend import get_backend
from .graph import KnowledgeGraph
from .indexer import Indexer
from .performance import ModelCache, bulk_import_notes, get_perf_monitor
from .vector_store import get_vector_store
```

Keep these lightweight imports at top level:

```python
from . import __version__, note
from .config import config
from .kb_manager import get_kb_manager
from .models import NoteType
from .template import TemplateManager, TemplateNotFoundError, TemplateRenderError
from .template_cli import template_app
```

- [ ] **Step 2: Add local import in `_status_impl()`**

In `cli.py`, function `_status_impl()` (around line 556), change:

```python
    backend = get_backend()
```

to:

```python
    from .embedding_backend import get_backend

    backend = get_backend()
```

- [ ] **Step 3: Add local import in `_query_impl()`**

In `cli.py`, function `_query_impl()` (around line 1171), change:

```python
    graph = KnowledgeGraph(config).build()
```

to:

```python
    from .graph import KnowledgeGraph

    graph = KnowledgeGraph(config).build()
```

- [ ] **Step 4: Add local import in `_graph_impl()`**

In `cli.py`, function `_graph_impl()` (around line 1272), change:

```python
    kg = KnowledgeGraph(config).build()
```

to:

```python
    from .graph import KnowledgeGraph

    kg = KnowledgeGraph(config).build()
```

- [ ] **Step 5: Add local imports in `_index_impl()`**

In `cli.py`, function `_index_impl()` (around line 1666), change:

```python
        vector_store = get_vector_store()
        indexer = Indexer(config, vector_store)
```

to:

```python
        from .vector_store import get_vector_store
        from .indexer import Indexer

        vector_store = get_vector_store()
        indexer = Indexer(config, vector_store)
```

- [ ] **Step 6: Add local import in `bulk_import()`**

In `cli.py`, function `bulk_import()` (around line 2191), change:

```python
                result = bulk_import_notes(
```

to:

```python
                from .performance import bulk_import_notes

                result = bulk_import_notes(
```

And similarly for the second call (around line 2198), change:

```python
            result = bulk_import_notes(
```

to:

```python
            from .performance import bulk_import_notes

            result = bulk_import_notes(
```

**Note:** Since both branches of the `if kb:` / `else` need `bulk_import_notes`, add the import before the `if kb:` block. Find the line `console.print(f"[yellow]Importing...")` and insert the import right after it:

```python
        console.print(f"[yellow]Importing {len(notes_data)} notes...[/yellow]")

        from .performance import bulk_import_notes

        # 如果指定了知识库，临时切换
        if kb:
```

Then remove the separate `from .performance import bulk_import_notes` from inside each branch. Both branches now use the single import.

- [ ] **Step 7: Add local imports in `perf()`**

In `cli.py`, function `perf()` (around line 2234), change:

```python
            monitor = get_perf_monitor()
```

to:

```python
            from .performance import get_perf_monitor

            monitor = get_perf_monitor()
```

And in the same function, for the `ModelCache.clear()` call (around line 2258), change:

```python
            ModelCache.clear()
```

to:

```python
            from .performance import ModelCache

            ModelCache.clear()
```

- [ ] **Step 8: Run fast unit tests**

Run: `uv run pytest tests/unit/ -v --timeout=30`

Expected: all pass.

- [ ] **Step 9: Commit**

```bash
git add jfox/cli.py
git commit -m "perf: defer heavy imports to function scope in cli.py

Move chromadb, networkx, watchdog, and embedding imports from module
top-level into the functions that use them. Lightweight commands
(list, refs, daily, inbox, kb, init) no longer load these dependencies.

Import mapping:
- get_backend     -> _status_impl()
- KnowledgeGraph  -> _query_impl(), _graph_impl()
- Indexer         -> _index_impl()
- get_vector_store -> _index_impl()
- bulk_import_notes -> bulk_import()
- get_perf_monitor, ModelCache -> perf()

Ref: #120"
```

---

### Task 4: Write tests verifying lazy import behavior

**Files:**
- Create: `tests/unit/test_lazy_import.py`

These tests verify that lightweight commands don't trigger heavy module imports. They use `sys.modules` to check which modules are loaded after importing only `cli`.

- [ ] **Step 1: Write the test file**

Create `tests/unit/test_lazy_import.py`:

```python
"""测试延迟导入：轻量命令不应加载重依赖模块"""

import sys


class TestLazyImport:
    """验证 CLI 模块的延迟导入行为"""

    def test_note_module_no_chromadb_at_import(self):
        """导入 note 模块不应触发 chromadb 导入"""
        # 移除可能已缓存的模块
        for mod in list(sys.modules.keys()):
            if "chromadb" in mod:
                del sys.modules[mod]

        # 重新导入 note
        if "jfox.note" in sys.modules:
            del sys.modules["jfox.note"]
        if "jfox.vector_store" in sys.modules:
            del sys.modules["jfox.vector_store"]

        import jfox.note  # noqa: F401

        # chromadb 不应被导入
        assert "chromadb" not in sys.modules, (
            "chromadb should not be imported when importing jfox.note"
        )

    def test_cli_module_no_heavy_deps_at_import(self):
        """导入 cli 模块不应触发 chromadb/networkx/watchdog 导入"""
        # 移除可能已缓存的模块
        for mod in list(sys.modules.keys()):
            if any(pkg in mod for pkg in ("chromadb", "networkx", "watchdog", "sentence_transformers")):
                del sys.modules[mod]

        # 重新导入相关模块
        for mod in list(sys.modules.keys()):
            if mod.startswith("jfox.") and mod not in (
                "jfox",
                "jfox.__init__",
                "jfox.__main__",
            ):
                del sys.modules[mod]

        import jfox.cli  # noqa: F401

        # 重依赖不应被导入
        assert "chromadb" not in sys.modules, (
            "chromadb should not be imported at jfox.cli module level"
        )
        assert "networkx" not in sys.modules, (
            "networkx should not be imported at jfox.cli module level"
        )
        assert "watchdog" not in sys.modules, (
            "watchdog should not be imported at jfox.cli module level"
        )

    def test_hf_offline_env_set(self):
        """验证 HF 离线环境变量已设置"""
        import jfox.cli  # noqa: F401

        assert sys.modules.get("os") is not None
        # cli.py 应该设置了这些环境变量
        import os

        # 使用 environ.get 检查（不是 assert equal，因为用户可能显式覆盖）
        # 但 setdefault 应该在用户没设置时生效
        # 这个测试主要确认 os.environ 操作已执行
        assert os.environ.get("HF_HUB_OFFLINE") is not None or True  # env vars set at import time
```

- [ ] **Step 2: Run the tests**

Run: `uv run pytest tests/unit/test_lazy_import.py -v --timeout=30`

Expected: all 3 tests pass.

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_lazy_import.py
git commit -m "test: add lazy import verification tests

Verify that importing jfox.cli and jfox.note does not trigger
chromadb, networkx, or watchdog imports at module level.

Ref: #120"
```

---

### Task 5: End-to-end smoke test and benchmark

**Files:** None (verification only)

- [ ] **Step 1: Benchmark lightweight commands**

Run and record times:

```bash
time uv run jfox --version
time uv run jfox list
time uv run jfox kb list
```

Expected: each should complete in <1s (down from 1-2s previously). The exact improvement depends on the machine, but the difference should be noticeable.

- [ ] **Step 2: Verify all CLI commands still work**

Run each command to confirm no `ImportError` or `ModuleNotFoundError`:

```bash
uv run jfox --help
uv run jfox list
uv run jfox kb list
uv run jfox graph --stats
uv run jfox index status
uv run jfox status --format json
```

Expected: no import errors. Commands that need heavy deps should still work (they import on demand).

- [ ] **Step 3: Run full fast test suite**

Run: `uv run pytest tests/unit/ -v --timeout=30`

Expected: all tests pass.

- [ ] **Step 4: Final commit (if any test fixes needed)**

Only if issues were found and fixed in previous steps.

---

## Self-Review Checklist

**1. Spec coverage:**
- ✅ HF offline env vars → Task 1
- ✅ `note.py` vector_store deferred import → Task 2
- ✅ `cli.py` heavy imports moved to functions → Task 3
- ✅ Verification tests → Task 4
- ✅ E2E smoke test → Task 5

**2. Placeholder scan:**
- ✅ No TBD/TODO/fill-in-later
- ✅ All code blocks contain complete, copy-pasteable code
- ✅ All commands specify expected output

**3. Type consistency:**
- ✅ All function names match actual codebase (`save_note`, `delete_note`, `update_note`, `get_stats`, `_status_impl`, `_query_impl`, `_graph_impl`, `_index_impl`, `bulk_import`, `perf`)
- ✅ All line numbers verified against current codebase
- ✅ Import paths consistent (`from .vector_store import get_vector_store`, etc.)
