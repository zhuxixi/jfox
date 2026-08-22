# 原子写入修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将笔记文件写入改为原子操作（write-to-temp + rename），防止进程崩溃时产生 0 字节空文件。

**Architecture:** 新增 `_atomic_write()` 私有函数，替换 `save_note()`、`update_note()` 和 `performance.py` 批量导入中的 `open("w")` 直接写入。

**Tech Stack:** Python stdlib (`tempfile`, `os`), pytest

---

### Task 1: 新增 `_atomic_write()` 工具函数

**Files:**

- Modify: `jfox/note.py` (imports at line 1-12, new function before `save_note` at line 62)

- [ ] **Step 1: Add imports and `_atomic_write()` function**

In `jfox/note.py`, add `os` and `tempfile` to the imports at the top (after line 5):

```python
import logging
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
```

Then insert the new function before `save_note()` (before line 62):

```python
def _atomic_write(filepath: Path, content: str) -> None:
    """原子写入：先写临时文件再 rename，防止崩溃产生空文件"""
    filepath.parent.mkdir(parents=True, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(dir=filepath.parent, suffix=".tmp")
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp_path, filepath)
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def save_note(note: Note, add_to_index: bool = True) -> bool:
    ...
```

- [ ] **Step 2: Write failing test for `_atomic_write`**

Create `tests/unit/test_atomic_write.py`:

```python
"""
测试类型: 单元测试
目标模块: jfox.note (_atomic_write 函数)
预估耗时: < 1秒
依赖要求: 无外部依赖
"""

import os
from pathlib import Path
from unittest.mock import patch

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.note import _atomic_write


class TestAtomicWrite:
    """测试 _atomic_write 原子写入"""

    def test_normal_write(self, tmp_path):
        """正常写入：文件内容正确"""
        filepath = tmp_path / "test.md"
        _atomic_write(filepath, "hello world")
        assert filepath.read_text(encoding="utf-8") == "hello world"

    def test_creates_parent_dir(self, tmp_path):
        """目标目录不存在时自动创建"""
        filepath = tmp_path / "sub" / "dir" / "test.md"
        _atomic_write(filepath, "content")
        assert filepath.read_text(encoding="utf-8") == "content"

    def test_overwrites_existing(self, tmp_path):
        """覆盖已有文件时内容正确"""
        filepath = tmp_path / "test.md"
        filepath.write_text("old content", encoding="utf-8")
        _atomic_write(filepath, "new content")
        assert filepath.read_text(encoding="utf-8") == "new content"

    def test_no_tmp_file_on_write_failure(self, tmp_path):
        """写入失败时不留临时文件，原文件不受影响"""
        filepath = tmp_path / "test.md"
        filepath.write_text("original", encoding="utf-8")

        # 模拟写入过程中异常
        with patch("os.replace", side_effect=OSError("disk full")):
            with pytest.raises(OSError, match="disk full"):
                _atomic_write(filepath, "new content")

        # 原文件不受影响
        assert filepath.read_text(encoding="utf-8") == "original"
        # 无 .tmp 残留
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_no_empty_file_on_crash(self, tmp_path):
        """崩溃后不会产生 0 字节目标文件"""
        filepath = tmp_path / "test.md"
        filepath.write_text("original", encoding="utf-8")

        original_mkstemp = tempfile.mkstemp

        def failing_mkstemp(**kwargs):
            fd, path = original_mkstemp(**kwargs)
            # 写入一些内容到临时文件，但 replace 时失败
            os.write(fd, b"partial")
            os.close(fd)
            raise KeyboardInterrupt

        # mkstemp 返回前抛异常，临时文件可能残留但目标文件不受影响
        with pytest.raises(KeyboardInterrupt):
            _atomic_write(filepath, "new content")

        # 目标文件不受影响
        assert filepath.read_text(encoding="utf-8") == "original"


import tempfile
```

- [ ] **Step 3: Run test to verify**

Run: `uv run pytest tests/unit/test_atomic_write.py -v`
Expected: All 5 tests PASS

- [ ] **Step 4: Commit**

```bash
git add jfox/note.py tests/unit/test_atomic_write.py
git commit -m "feat(note): add _atomic_write() for crash-safe file writes"
```

---

### Task 2: 改造 `save_note()` 使用原子写入

**Files:**

- Modify: `jfox/note.py:62-95` (`save_note` function)

- [ ] **Step 1: Write failing test**

Add to `tests/unit/test_atomic_write.py`:

```python
from unittest.mock import patch, MagicMock

from jfox.config import ZKConfig
from jfox.models import NoteType
from jfox.note import create_note, save_note


class TestSaveNoteAtomic:
    """测试 save_note 使用原子写入"""

    def _make_config(self, tmp_path):
        cfg = ZKConfig(base_dir=tmp_path)
        cfg.ensure_dirs()
        return cfg

    @patch("jfox.note.config")
    def test_save_note_uses_atomic_write(self, mock_config, tmp_path):
        """save_note 应通过 _atomic_write 写入，不直接 open('w')"""
        cfg = self._make_config(tmp_path)
        mock_config.notes_dir = cfg.notes_dir

        n = create_note("test content", title="Test", note_type=NoteType.FLEETING)

        with patch("jfox.note._atomic_write", wraps=_atomic_write) as mock_aw:
            # 需要禁用索引
            save_note(n, add_to_index=False)
            mock_aw.assert_called_once()

        # 验证文件内容正确
        loaded = _load_raw(n.filepath)
        assert "test content" in loaded

    @patch("jfox.note.config")
    def test_save_note_no_zero_byte_on_failure(self, mock_config, tmp_path):
        """save_note 写入失败时不留 0 字节文件"""
        cfg = self._make_config(tmp_path)
        mock_config.notes_dir = cfg.notes_dir

        n = create_note("content", title="Test", note_type=NoteType.FLEETING)
        n.set_filepath(cfg.notes_dir / "fleeting" / "test.md")

        # 先创建一个有内容的文件
        n.filepath.parent.mkdir(parents=True, exist_ok=True)
        n.filepath.write_text("original content", encoding="utf-8")

        # 模拟 to_markdown 失败
        with patch.object(type(n), "to_markdown", side_effect=RuntimeError("boom")):
            result = save_note(n, add_to_index=False)

        assert result is False
        # 原文件不受影响（不会被截断为 0 字节）
        assert n.filepath.read_text(encoding="utf-8") == "original content"


def _load_raw(path):
    return path.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_atomic_write.py::TestSaveNoteAtomic -v`
Expected: `test_save_note_uses_atomic_write` FAILS (save_note still uses `open("w")`)

- [ ] **Step 3: Modify `save_note()` to use `_atomic_write()`**

Replace the body of `save_note()` in `jfox/note.py`. Change lines 64-70:

Before:

```python
    try:
        # 确保目录存在
        note.filepath.parent.mkdir(parents=True, exist_ok=True)

        # 写入文件
        with open(note.filepath, "w", encoding="utf-8") as f:
            f.write(note.to_markdown())
```

After:

```python
    try:
        _atomic_write(note.filepath, note.to_markdown())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_atomic_write.py::TestSaveNoteAtomic -v`
Expected: All PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/note.py tests/unit/test_atomic_write.py
git commit -m "refactor(note): save_note uses atomic write"
```

---

### Task 3: 改造 `update_note()` 使用原子写入

**Files:**

- Modify: `jfox/note.py:263-270` (`update_note` function)

- [ ] **Step 1: Write failing test**

Add to `tests/unit/test_atomic_write.py`:

```python
from jfox.note import update_note, find_note_file


class TestUpdateNoteAtomic:
    """测试 update_note 使用原子写入"""

    def _make_config(self, tmp_path):
        cfg = ZKConfig(base_dir=tmp_path)
        cfg.ensure_dirs()
        return cfg

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_update_note_no_zero_byte_on_failure(
        self, mock_global_config, mock_note_config, tmp_path
    ):
        """update_note 写入失败时不留 0 字节文件"""
        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        n = create_note("original", title="Test", note_type=NoteType.PERMANENT)
        save_note(n, add_to_index=False)

        # 修改内容
        n.content = "modified"

        # 模拟 to_markdown 失败
        with patch.object(type(n), "to_markdown", side_effect=RuntimeError("boom")):
            result = update_note(n, add_to_index=False)

        assert result is False
        # 磁盘上原文件不变
        old_file = find_note_file(cfg, n.id)
        assert old_file is not None
        assert "original" in old_file.read_text(encoding="utf-8")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_atomic_write.py::TestUpdateNoteAtomic -v`
Expected: `test_update_note_no_zero_byte_on_failure` FAILS

- [ ] **Step 3: Modify `update_note()` to use `_atomic_write()`**

In `jfox/note.py`, replace lines 267-270:

Before:

```python
        # 写入新文件（filepath 属性根据当前字段生成）
        note_obj.filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(note_obj.filepath, "w", encoding="utf-8") as f:
            f.write(note_obj.to_markdown())
```

After:

```python
        # 写入新文件（filepath 属性根据当前字段生成）
        _atomic_write(note_obj.filepath, note_obj.to_markdown())
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_atomic_write.py::TestUpdateNoteAtomic -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/note.py tests/unit/test_atomic_write.py
git commit -m "refactor(note): update_note uses atomic write"
```

---

### Task 4: 改造 `performance.py` 批量导入使用原子写入

**Files:**

- Modify: `jfox/performance.py:237-246` (batch save loop)

- [ ] **Step 1: Modify the batch save to use `_atomic_write`**

In `jfox/performance.py`, add the import at the top (after existing imports):

```python
from .note import _atomic_write
```

Then replace lines 237-246:

Before:

```python
            # 批量保存（不索引）
            for note in notes:
                try:
                    note.filepath.parent.mkdir(parents=True, exist_ok=True)
                    with open(note.filepath, "w", encoding="utf-8") as f:
                        f.write(note.to_markdown())
                    imported += 1
                except Exception as e:
                    logger.warning(f"Failed to save note: {e}")
                    failed += 1
```

After:

```python
            # 批量保存（不索引）
            for note in notes:
                try:
                    _atomic_write(note.filepath, note.to_markdown())
                    imported += 1
                except Exception as e:
                    logger.warning(f"Failed to save note: {e}")
                    failed += 1
```

- [ ] **Step 2: Verify no regression**

Run: `uv run pytest tests/unit/test_atomic_write.py -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add jfox/performance.py
git commit -m "refactor(performance): batch import uses atomic write"
```

---

### Task 5: 最终验证

- [ ] **Step 1: Run all fast unit tests**

Run: `uv run pytest tests/unit/ -v`
Expected: All PASS, no regressions

- [ ] **Step 2: Run linting**

Run: `uv run ruff check jfox/note.py jfox/performance.py tests/unit/test_atomic_write.py && uv run black --check jfox/note.py jfox/performance.py tests/unit/test_atomic_write.py`
Expected: No errors

- [ ] **Step 3: Final commit with cleanup if needed**

If any formatting fixes were needed:

```bash
git add -A
git commit -m "style: lint fixes for atomic write"
```
