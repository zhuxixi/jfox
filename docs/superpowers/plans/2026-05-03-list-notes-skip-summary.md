# list_notes 跳过文件汇总提示 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `list_notes()` 扫描结束时，如果跳过了无效文件，输出一条 warning 汇总。

**Architecture:** 在 `list_notes()` 遍历循环中计数 `load_note()` 返回 `None` 的次数，函数末尾条件输出 `logger.warning`。单文件改动。

**Tech Stack:** Python, pytest

---

### Task 1: 添加跳过计数和 warning 输出

**Files:**
- Modify: `jfox/note.py:167-197` (list_notes 函数)
- Test: `tests/unit/test_list_notes_skip.py` (新建)

- [ ] **Step 1: 写测试**

创建 `tests/unit/test_list_notes_skip.py`：

```python
"""
测试类型: 单元测试
目标模块: jfox.note (list_notes 跳过文件汇总)
预估耗时: < 1秒
依赖要求: 无外部依赖
"""

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.note import list_notes


class TestListNotesSkipSummary:
    """list_notes 跳过无效文件时的 warning 汇总"""

    @pytest.fixture
    def kb_with_corrupt_file(self, temp_kb):
        """创建包含一个损坏文件的知识库"""
        from jfox.config import ZKConfig
        from jfox.models import Note, NoteType
        from datetime import datetime

        cfg = ZKConfig(base_dir=temp_kb)
        cfg.ensure_dirs()

        # 一个正常笔记
        note = Note(
            id="20260503001",
            title="正常笔记",
            content="内容",
            type=NoteType.PERMANENT,
            tags=[],
            created=datetime(2026, 5, 3, 0, 1),
            updated=datetime(2026, 5, 3, 0, 1),
        )
        note_dir = cfg.notes_dir / note.type.value
        note_dir.mkdir(parents=True, exist_ok=True)
        (note_dir / f"{note.id}.md").write_text(note.to_markdown(), encoding="utf-8")

        # 一个空文件（损坏）
        (note_dir / "empty.md").write_text("", encoding="utf-8")

        return cfg

    def test_no_warning_when_all_valid(self, temp_kb, caplog):
        """所有文件有效时不输出 warning"""
        import logging

        from jfox.config import ZKConfig
        from jfox.models import Note, NoteType
        from datetime import datetime

        cfg = ZKConfig(base_dir=temp_kb)
        cfg.ensure_dirs()

        note = Note(
            id="20260503001",
            title="正常笔记",
            content="内容",
            type=NoteType.PERMANENT,
            tags=[],
            created=datetime(2026, 5, 3, 0, 1),
            updated=datetime(2026, 5, 3, 0, 1),
        )
        note_dir = cfg.notes_dir / note.type.value
        note_dir.mkdir(parents=True, exist_ok=True)
        (note_dir / f"{note.id}.md").write_text(note.to_markdown(), encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger="jfox.note"):
            results = list_notes(cfg=cfg)

        assert len(results) == 1
        skip_warnings = [r for r in caplog.records if "无法加载" in r.message]
        assert len(skip_warnings) == 0

    def test_warning_when_corrupt_file_skipped(self, kb_with_corrupt_file, caplog):
        """有损坏文件时输出汇总 warning"""
        import logging

        with caplog.at_level(logging.WARNING, logger="jfox.note"):
            results = list_notes(cfg=kb_with_corrupt_file)

        assert len(results) == 1
        skip_warnings = [r for r in caplog.records if "无法加载" in r.message]
        assert len(skip_warnings) == 1
        assert "1 个文件无法加载" in skip_warnings[0].message
        assert "jfox check" in skip_warnings[0].message

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/unit/test_list_notes_skip.py -v`
Expected: FAIL — `list_notes` 尚未输出 warning，`assert len(skip_warnings) == 1` 失败

- [ ] **Step 3: 实现改动**

修改 `jfox/note.py:167-197`，在 `list_notes()` 函数中：

1. 在 `notes = []` 后添加 `skipped = 0`
2. 在循环内 `if note:` 的 else 分支（即 `load_note` 返回 None 时）递增 `skipped`
3. 在 `return notes` 前添加条件 warning

修改后的完整函数体（从第 167 行 `use_config = cfg or config` 到第 197 行 `return notes`）：

```python
    use_config = cfg or config
    notes = []
    skipped = 0

    types_to_list = [note_type] if note_type else list(NoteType)

    for nt in types_to_list:
        dir_path = use_config.notes_dir / nt.value
        if not dir_path.exists():
            continue

        for filepath in sorted(dir_path.glob("*.md"), reverse=True):
            note = load_note(filepath)
            if note:
                notes.append(note)
            else:
                skipped += 1

            # 无标签过滤时可提前截断，避免全量遍历
            if limit and not tags and len(notes) >= limit:
                break

        if limit and not tags and len(notes) >= limit:
            break

    # 标签过滤（AND 逻辑）—— 先过滤再截断，避免 limit + tags 组合时数量不足
    if tags:
        notes = [n for n in notes if all(t in n.tags for t in tags)]

    # 截断到 limit
    if limit:
        notes = notes[:limit]

    if skipped > 0:
        logger.warning(
            f"{skipped} 个文件无法加载，已跳过。运行 jfox check 清理。"
        )

    return notes
```

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/unit/test_list_notes_skip.py -v`
Expected: 2 tests PASS

- [ ] **Step 5: 运行现有 tag filter 测试确认无回归**

Run: `uv run pytest tests/unit/test_tag_filter.py -v`
Expected: 全部 PASS（`list_notes` 返回值类型不变）

- [ ] **Step 6: 提交**

```bash
git add jfox/note.py tests/unit/test_list_notes_skip.py
git commit -m "feat(note): add skip summary warning in list_notes (#188)"
```
