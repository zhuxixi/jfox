# Fix Daemon Deprecation Warnings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Eliminate two deprecation warnings from daemon startup log (`~/.jfox_daemon.log`)

**Architecture:** Three files, four surgical replacements — FastAPI lifespan migration + sentence-transformers API rename + dimension property unification

**Tech Stack:** Python, FastAPI, sentence-transformers

**Spec:** `docs/superpowers/specs/2026-04-26-fix-daemon-deprecation-warnings-design.md`

---

## File Structure

| File | Change |
|------|--------|
| `jfox/daemon/server.py` | Replace `@app.on_event("startup")` with `lifespan` context manager |
| `jfox/embedding_backend.py` | Rename `get_sentence_embedding_dimension()` → `get_embedding_dimension()` (2 places) |
| `jfox/performance.py` | Replace `backend.model.get_sentence_embedding_dimension()` → `backend.dimension` |

No new files created. No test changes needed — these are pure renames/migrations with identical behavior.

---

### Task 1: Migrate FastAPI `on_event` to `lifespan`

**Files:**
- Modify: `jfox/daemon/server.py`

- [ ] **Step 1: Add import and replace `on_event` with `lifespan`**

Replace the top of `server.py` (lines 8-18) to add `asynccontextmanager` import:

```python
import argparse
import logging
import os
from contextlib import asynccontextmanager
from typing import List

from fastapi import FastAPI
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# 全局 embedding 后端（模型加载后常驻内存）
_backend = None


def _load_model():
    """启动时加载模型（标记为 daemon 进程，防止自引用）"""
    global _backend
    os.environ["JFOX_DAEMON_PROCESS"] = "1"
    from ..config import config
    from ..embedding_backend import EmbeddingBackend

    model_name = config.embedding_model if config.embedding_model != "auto" else None
    _backend = EmbeddingBackend(device=config.device, model_name=model_name)
    try:
        _backend.load()
        logger.info(
            f"Daemon: 模型已加载 {_backend.model_name} "
            f"(device={_backend._resolved_device}, dimension={_backend._resolved_dim})"
        )
    except Exception as e:
        logger.error(f"Daemon: 模型加载失败，进程退出: {e}")
        os._exit(1)


@asynccontextmanager
async def lifespan(app):
    _load_model()
    yield


app = FastAPI(title="JFox Embedding Daemon", lifespan=lifespan)
```

This replaces lines 8-18 (imports + global + old `@app.on_event` decorated `_load_model` + old `app = FastAPI(...)`).

- [ ] **Step 2: Verify daemon starts without DeprecationWarning**

Run: `uv run python -c "from jfox.daemon.server import app; print('OK')"`

Expected: `OK` with no `DeprecationWarning` about `on_event`.

- [ ] **Step 3: Commit**

```bash
git add jfox/daemon/server.py
git commit -m "fix(daemon): migrate FastAPI on_event to lifespan pattern

Removes DeprecationWarning from daemon log. Refs #164."
```

---

### Task 2: Rename `get_sentence_embedding_dimension` in `embedding_backend.py`

**Files:**
- Modify: `jfox/embedding_backend.py:98`
- Modify: `jfox/embedding_backend.py:138`

- [ ] **Step 1: Replace two occurrences**

Line 98, in `load()` method:
```python
# Before:
self._resolved_dim = self.model.get_sentence_embedding_dimension()
# After:
self._resolved_dim = self.model.get_embedding_dimension()
```

Line 138, in `dimension` property:
```python
# Before:
return self.model.get_sentence_embedding_dimension()
# After:
return self.model.get_embedding_dimension()
```

- [ ] **Step 2: Verify import works without FutureWarning**

Run: `uv run python -c "from jfox.embedding_backend import EmbeddingBackend; print('OK')"`

Expected: `OK` with no `FutureWarning`.

- [ ] **Step 3: Commit**

```bash
git add jfox/embedding_backend.py
git commit -m "fix(embedding): rename get_sentence_embedding_dimension to get_embedding_dimension

Removes FutureWarning from sentence-transformers. Refs #164."
```

---

### Task 3: Use `backend.dimension` in `performance.py` fallback

**Files:**
- Modify: `jfox/performance.py:144`

- [ ] **Step 1: Replace direct model access with dimension property**

Line 144:
```python
# Before:
dim = backend.model.get_sentence_embedding_dimension()
# After:
dim = backend.dimension
```

- [ ] **Step 2: Verify module imports cleanly**

Run: `uv run python -c "from jfox.performance import BatchEmbeddingProcessor; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add jfox/performance.py
git commit -m "fix(perf): use backend.dimension instead of direct model access

Unifies dimension access and fixes FutureWarning. Refs #164."
```

---

### Task 4: Final verification

- [ ] **Step 1: Run fast tests**

Run: `uv run pytest tests/unit/test_daemon_process.py -v`

Expected: All pass.

- [ ] **Step 2: Grep for any remaining deprecated calls**

Run: `grep -rn "get_sentence_embedding_dimension\|on_event.*startup" jfox/ --include="*.py"`

Expected: No matches.
