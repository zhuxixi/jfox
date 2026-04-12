# Fix: index verify ID Mismatch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix `jfox index verify` so it correctly matches filesystem filenames to indexed note IDs instead of reporting all notes as missing/orphaned.

**Architecture:** Add a pure function `_extract_note_id_from_filename()` to `indexer.py` that converts filename stems (e.g. `20260412-0150293323`, `202604120150293323-slug`) to raw 18-digit note IDs. Replace the `f.stem` set comprehension in `verify_index()` with a call to this function.

**Tech Stack:** Python 3.10+, pytest

---

### Task 1: Failing unit tests for `_extract_note_id_from_filename`

**Files:**
- Create: `tests/unit/test_indexer_verify.py`

- [ ] **Step 1: Write failing tests**

```python
"""
测试 indexer.verify_index 的 ID 提取逻辑

Issue #103: index verify 误报 missing/orphaned（文件名 slug 与索引 ID 不匹配）
"""

import pytest

from jfox.indexer import _extract_note_id_from_filename


class TestExtractNoteIdFromFilename:
    """从文件名 stem 提取笔记纯 ID 的单元测试"""

    def test_fleeting_filename(self):
        """Fleeting: YYYYMMDD-HHMMSSNNNN → YYYYMMDDHHMMSSNNNN"""
        assert _extract_note_id_from_filename("20260412-0150293323") == "202604120150293323"

    def test_literature_filename_with_chinese_slug(self):
        """Literature/Permanent: ID-中英文slug → ID"""
        assert (
            _extract_note_id_from_filename("202604120150293323-jfox-迭代历史")
            == "202604120150293323"
        )

    def test_permanent_filename_with_english_slug(self):
        """Permanent: ID-english-slug → ID"""
        assert (
            _extract_note_id_from_filename("202604120150293323-some-english-slug")
            == "202604120150293323"
        )

    def test_pure_id_no_slug(self):
        """向后兼容：纯 ID（无 slug）也正确提取"""
        assert _extract_note_id_from_filename("202604120150293323") == "202604120150293323"

    def test_empty_slug(self):
        """ID 后紧跟连字符但无 slug 内容"""
        assert _extract_note_id_from_filename("202604120150293323-") == "202604120150293323"

    def test_invalid_filename_returns_none(self):
        """非笔记文件名返回 None"""
        assert _extract_note_id_from_filename("readme") is None

    def test_random_filename_returns_none(self):
        """不含数字的文件名返回 None"""
        assert _extract_note_id_from_filename("notes") is None

    def test_partial_digits_returns_none(self):
        """不足 18 位的数字不匹配"""
        assert _extract_note_id_from_filename("20260412") is None

    def test_fleeting_wrong_dash_position_returns_none(self):
        """Fleeting 格式连字符不在第 8 位时不应匹配"""
        assert _extract_note_id_from_filename("202604-12015029323") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_indexer_verify.py -v`
Expected: FAIL — `ImportError: cannot import name '_extract_note_id_from_filename' from 'jfox.indexer'`

---

### Task 2: Implement `_extract_note_id_from_filename`

**Files:**
- Modify: `jfox/indexer.py` (add import + new function)

- [ ] **Step 1: Add `re` import to `indexer.py`**

At the top of `jfox/indexer.py`, add `re` to the imports. After line 11 (`import threading`), add:

```python
import re
```

- [ ] **Step 2: Add `_extract_note_id_from_filename` function**

Add this function right before the `IndexStats` dataclass (i.e., after the `console = Console()` line, around line 27). Insert between line 26 and 27:

```python
def _extract_note_id_from_filename(filename_stem: str) -> Optional[str]:
    """
    从文件名 stem 提取笔记 ID（18位纯数字时间戳）。

    支持的文件名格式：
    - Fleeting:     YYYYMMDD-HHMMSSNNNN  → 去掉连字符
    - 其他类型:     YYYYMMDDHHMMSSNNNN-slug → 取前18位
    - 纯 ID（无 slug）: YYYYMMDDHHMMSSNNNN → 直接返回

    Args:
        filename_stem: 文件名去掉 .md 扩展名的部分

    Returns:
        18 位纯数字 ID，或 None（不匹配任何已知格式时）
    """
    # Fleeting: YYYYMMDD-HHMMSSNNNN（8位日期-10位时间+随机数）
    if re.match(r"^\d{8}-\d{10}$", filename_stem):
        return filename_stem.replace("-", "")
    # Literature/Permanent: 18位ID 后跟可选的 -slug
    match = re.match(r"^(\d{18})(?:-.*)?$", filename_stem)
    if match:
        return match.group(1)
    return None
```

- [ ] **Step 3: Run unit tests to verify they pass**

Run: `uv run pytest tests/unit/test_indexer_verify.py -v`
Expected: All 9 tests PASS

- [ ] **Step 4: Commit**

```bash
git add jfox/indexer.py tests/unit/test_indexer_verify.py
git commit -m "feat(indexer): add _extract_note_id_from_filename for ID extraction from filenames

Introduces a pure function that converts filename stems (with slug or
fleeting dash format) to raw 18-digit note IDs. Unit tests cover all
note types and edge cases. Refs #103."
```

---

### Task 3: Fix `verify_index()` to use `_extract_note_id_from_filename`

**Files:**
- Modify: `jfox/indexer.py:298-306` (the `verify_index` method)

- [ ] **Step 1: Write a failing integration test**

Add a new test at the end of `tests/test_advanced_features.py`:

```python
def test_verify_index_matches_filenames_to_ids(isolated_config):
    """验证 verify_index 正确匹配文件名和索引 ID（不误报 missing/orphaned）

    Issue #103: 文件名含 slug 或 fleeting 连字符，索引 ID 为纯数字，格式不匹配导致全部误报
    """
    vector_store = VectorStore(isolated_config.chroma_dir)
    vector_store.init()
    indexer = Indexer(isolated_config, vector_store)

    # 创建一个 fleeting 笔记（文件名含连字符）
    note1 = note_module.create_note(
        content="Fleeting test", title="Fleeting Test", note_type=NoteType.FLEETING
    )
    note1.set_filepath(
        isolated_config.notes_dir / "fleeting" / f"{note1.id[:8]}-{note1.id[8:]}.md"
    )
    note_module.save_note(note1, add_to_index=False)

    # 创建一个 permanent 笔记（文件名含 slug）
    note2 = note_module.create_note(
        content="Permanent test", title="Test Slug", note_type=NoteType.PERMANENT
    )
    note2.set_filepath(
        isolated_config.notes_dir / "permanent" / f"{note2.id}-test-slug.md"
    )
    note_module.save_note(note2, add_to_index=False)

    # 索引所有笔记
    indexer.index_all()

    # verify 应报告 healthy
    result = indexer.verify_index()
    assert result["healthy"] is True, (
        f"Expected healthy=True, got missing={result['missing_from_index']}, "
        f"orphaned={result['orphaned_in_index']}"
    )
    assert result["missing_from_index"] == []
    assert result["orphaned_in_index"] == []
    assert result["total_files"] == 2
    assert result["total_indexed"] == 2
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_advanced_features.py::test_verify_index_matches_filenames_to_ids -v`
Expected: FAIL — `assert result["healthy"] is True` because `verify_index` still uses `f.stem`

- [ ] **Step 3: Fix `verify_index()` in `indexer.py`**

Replace lines 299-300 in `jfox/indexer.py`:

Old code (lines 299-300):
```python
        note_files = list(notes_dir.rglob("*.md"))
        file_ids = {f.stem for f in note_files}
```

New code:
```python
        note_files = list(notes_dir.rglob("*.md"))
        file_ids = set()
        for f in note_files:
            note_id = _extract_note_id_from_filename(f.stem)
            if note_id:
                file_ids.add(note_id)
```

This is a drop-in replacement. The rest of the method (lines 302-314) stays unchanged — it already correctly compares `file_ids` against `indexed_ids` using set operations.

- [ ] **Step 4: Run the integration test to verify it passes**

Run: `uv run pytest tests/test_advanced_features.py::test_verify_index_matches_filenames_to_ids -v`
Expected: PASS

- [ ] **Step 5: Run the existing `test_indexer` to verify no regression**

Run: `uv run pytest tests/test_advanced_features.py::test_indexer -v`
Expected: PASS (the existing test creates a fleeting note with `{note1.id}.md` filename, which `_extract_note_id_from_filename` handles via the `^\d{18}$` case)

- [ ] **Step 6: Commit**

```bash
git add jfox/indexer.py tests/test_advanced_features.py
git commit -m "fix(indexer): use _extract_note_id_from_filename in verify_index

verify_index now extracts pure 18-digit IDs from filenames instead of
comparing raw stems, fixing false positive missing/orphaned reports for
fleeting notes (dash format) and permanent/literature notes (slug
format). Closes #103."
```

---

### Task 4: Final verification

- [ ] **Step 1: Run all fast unit tests (no embedding)**

Run: `uv run pytest tests/unit/ -v`
Expected: All PASS

- [ ] **Step 2: Provide full integration test command for user**

The full test suite requires embedding models and takes time. Provide to user:

```bash
uv run pytest tests/test_advanced_features.py -v
```

User should verify that both `test_indexer` and `test_verify_index_matches_filenames_to_ids` pass.

---

## Self-Review

**Spec coverage:** All requirements from issue #103 covered:
- Root cause fix (ID extraction from filenames) → Task 2 + Task 3
- Fleeting dash format handling → Task 2 regex `\d{8}-\d{10}`
- Permanent/Literature slug format → Task 2 regex `^\d{18}(?:-.*)?$`
- Invalid filename handling → Task 2 returns `None`
- Unit tests → Task 1 (9 cases)
- Integration test → Task 3 (fleeting + permanent, verify healthy)
- No regression → Task 4 (existing `test_indexer` still passes)

**Placeholder scan:** No TBD/TODO found. All steps contain complete code and exact commands.

**Type consistency:** `_extract_note_id_from_filename` returns `Optional[str]` in all tasks. `verify_index()` uses `set()` of strings matching `indexed_ids` from `vector_store.get_all_ids()` which returns `List[str]`. Types are consistent throughout.
