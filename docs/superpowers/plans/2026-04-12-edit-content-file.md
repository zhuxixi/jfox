# Edit --content-file Parameter Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--content-file` parameter to `jfox edit` so users can pass long text or text with special shell characters via a file instead of `--content`.

**Architecture:** Add `content_file` parameter to `_edit_impl()` and the `edit()` Typer command. Read file content at the top of `_edit_impl()`, then the existing `n.content = content` assignment handles it identically to `--content`. Mutual exclusion between `--content` and `--content-file` is enforced. No changes to `note.py`, `models.py`, or any other module.

**Tech Stack:** Python, Typer CLI framework, pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `jfox/cli.py` | Modify `_edit_impl()` (L962-1085) + `edit()` (L1088-1128) | Add `content_file` param + file reading + validation |
| `tests/unit/test_edit.py` | Modify `TestEditImpl` class (L120-387) | Add tests for `--content-file` behavior |
| `tests/utils/jfox_cli.py` | Modify `ZKCLI.edit()` (L236-269) | Add `content_file` parameter to test wrapper |

No other files need changes.

---

### Task 1: Write failing tests for `--content-file` in `_edit_impl`

**Files:**
- Modify: `tests/unit/test_edit.py` (append to `TestEditImpl` class after line 387)

- [ ] **Step 1: Add failing tests**

Append the following tests to the `TestEditImpl` class in `tests/unit/test_edit.py` (after line 387, still inside the class):

```python
    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_edit_content_file_reads_content(self, mock_global_config, mock_note_config, tmp_path):
        """通过 --content-file 编辑笔记内容"""
        from jfox.cli import _edit_impl

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        # 创建笔记
        n = create_note("original", title="FileEdit", note_type=NoteType.PERMANENT)
        save_note(n, add_to_index=False)

        # 写入临时文件
        content_file = tmp_path / "content.txt"
        content_file.write_text("content from file", encoding="utf-8")

        _edit_impl(
            note_id=n.id,
            content=None,
            content_file=str(content_file),
            title=None,
            tags=None,
            note_type=None,
            source=None,
            output_format="json",
        )

        loaded = load_note_by_id(n.id, cfg=cfg)
        assert loaded is not None
        assert loaded.content == "content from file"

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_edit_content_file_not_exists_raises(self, mock_global_config, mock_note_config, tmp_path):
        """--content-file 指向不存在的文件时报错"""
        from jfox.cli import _edit_impl

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        n = create_note("content", title="NoFile", note_type=NoteType.PERMANENT)
        save_note(n, add_to_index=False)

        with pytest.raises(ValueError, match="文件不存在"):
            _edit_impl(
                note_id=n.id,
                content=None,
                content_file=str(tmp_path / "nonexistent.txt"),
                title=None,
                tags=None,
                note_type=None,
                source=None,
                output_format="json",
            )

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_edit_content_and_content_file_exclusive(self, mock_global_config, mock_note_config, tmp_path):
        """--content 和 --content-file 不能同时指定"""
        from jfox.cli import _edit_impl

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        n = create_note("content", title="Exclusive", note_type=NoteType.PERMANENT)
        save_note(n, add_to_index=False)

        content_file = tmp_path / "content.txt"
        content_file.write_text("from file", encoding="utf-8")

        with pytest.raises(ValueError, match="不能同时指定"):
            _edit_impl(
                note_id=n.id,
                content="from arg",
                content_file=str(content_file),
                title=None,
                tags=None,
                note_type=None,
                source=None,
                output_format="json",
            )

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_edit_content_file_with_special_chars(self, mock_global_config, mock_note_config, tmp_path):
        """--content-file 正确处理反引号、换行、特殊字符"""
        from jfox.cli import _edit_impl

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        n = create_note("original", title="SpecialChars", note_type=NoteType.PERMANENT)
        save_note(n, add_to_index=False)

        special_content = "包含 `jfox rebuild` 命令\n还有 $variable 和 \"引号\"\n以及 [[WikiLink]]"
        content_file = tmp_path / "special.txt"
        content_file.write_text(special_content, encoding="utf-8")

        _edit_impl(
            note_id=n.id,
            content=None,
            content_file=str(content_file),
            title=None,
            tags=None,
            note_type=None,
            source=None,
            output_format="json",
        )

        loaded = load_note_by_id(n.id, cfg=cfg)
        assert loaded is not None
        assert loaded.content == special_content

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_edit_content_file_empty(self, mock_global_config, mock_note_config, tmp_path):
        """--content-file 空文件将内容清空"""
        from jfox.cli import _edit_impl

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        n = create_note("has content", title="EmptyFile", note_type=NoteType.PERMANENT)
        save_note(n, add_to_index=False)

        content_file = tmp_path / "empty.txt"
        content_file.write_text("", encoding="utf-8")

        _edit_impl(
            note_id=n.id,
            content=None,
            content_file=str(content_file),
            title=None,
            tags=None,
            note_type=None,
            source=None,
            output_format="json",
        )

        loaded = load_note_by_id(n.id, cfg=cfg)
        assert loaded is not None
        assert loaded.content == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_edit.py::TestEditImpl::test_edit_content_file_reads_content -v`
Expected: FAIL — `TypeError: _edit_impl() got an unexpected keyword argument 'content_file'`

---

### Task 2: Add `content_file` parameter to `_edit_impl()`

**Files:**
- Modify: `jfox/cli.py` lines 962-974 (function signature + validation block)

- [ ] **Step 1: Update `_edit_impl` signature and validation**

In `jfox/cli.py`, replace lines 962-974:

```python
def _edit_impl(
    note_id: str,
    content: Optional[str],
    title: Optional[str],
    tags: Optional[List[str]],
    note_type: Optional[str],
    source: Optional[str],
    output_format: str,
):
    """编辑笔记的内部实现"""
    # 验证：至少指定一个编辑字段
    if all(v is None for v in [content, title, tags, note_type, source]):
        raise ValueError("至少指定一个要编辑的字段 (--content, --title, --tags, --type, --source)")
```

with:

```python
def _edit_impl(
    note_id: str,
    content: Optional[str],
    content_file: Optional[str],
    title: Optional[str],
    tags: Optional[List[str]],
    note_type: Optional[str],
    source: Optional[str],
    output_format: str,
):
    """编辑笔记的内部实现"""
    # 验证：--content 和 --content-file 互斥
    if content is not None and content_file is not None:
        raise ValueError("--content 和 --content-file 不能同时指定")

    # 从文件读取内容
    if content_file is not None:
        from pathlib import Path

        p = Path(content_file)
        if not p.exists():
            raise ValueError(f"文件不存在: {content_file}")
        content = p.read_text(encoding="utf-8")

    # 验证：至少指定一个编辑字段
    if all(v is None for v in [content, title, tags, note_type, source]):
        raise ValueError("至少指定一个要编辑的字段 (--content, --content-file, --title, --tags, --type, --source)")
```

**Key changes:**
1. Added `content_file: Optional[str]` parameter (after `content`, before `title`)
2. Added mutual exclusion check for `--content` / `--content-file`
3. Added file reading: `content = p.read_text(encoding="utf-8")` — overwrites `content` so downstream code (`n.content = content`, wiki links parsing, etc.) works unchanged
4. Updated "at least one field" validation to include `content_file` in error message

- [ ] **Step 2: Run Task 1 tests to verify they now pass**

Run: `uv run pytest tests/unit/test_edit.py::TestEditImpl -k "content_file" -v`
Expected: All 5 new tests PASS.

---

### Task 3: Add `--content-file` parameter to `edit()` Typer command

**Files:**
- Modify: `jfox/cli.py` lines 1088-1116

- [ ] **Step 1: Update `edit()` function signature**

In `jfox/cli.py`, replace lines 1088-1116:

```python
@app.command()
def edit(
    note_id: str = typer.Argument(..., help="笔记 ID"),
    content: Optional[str] = typer.Option(None, "--content", "-c", help="新内容"),
    title: Optional[str] = typer.Option(None, "--title", "-t", help="新标题"),
    tags: Optional[List[str]] = typer.Option(None, "--tag", help="新标签（替换全部）"),
    note_type: Optional[str] = typer.Option(
        None, "--type", help="新类型 (fleeting/literature/permanent)"
    ),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="新来源"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"
    ),
):
    """编辑已有笔记（保留 ID 和创建时间）"""
    try:
        # 向后兼容：--json 快捷方式
        if json_output:
            output_format = "json"

        if kb:
            from .config import use_kb

            with use_kb(kb):
                _edit_impl(note_id, content, title, tags, note_type, source, output_format)
        else:
            _edit_impl(note_id, content, title, tags, note_type, source, output_format)
```

with:

```python
@app.command()
def edit(
    note_id: str = typer.Argument(..., help="笔记 ID"),
    content: Optional[str] = typer.Option(None, "--content", "-c", help="新内容"),
    content_file: Optional[str] = typer.Option(
        None, "--content-file", help="从文件读取内容（支持长文本和特殊字符）"
    ),
    title: Optional[str] = typer.Option(None, "--title", "-t", help="新标题"),
    tags: Optional[List[str]] = typer.Option(None, "--tag", help="新标签（替换全部）"),
    note_type: Optional[str] = typer.Option(
        None, "--type", help="新类型 (fleeting/literature/permanent)"
    ),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="新来源"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"
    ),
):
    """编辑已有笔记（保留 ID 和创建时间）"""
    try:
        # 向后兼容：--json 快捷方式
        if json_output:
            output_format = "json"

        if kb:
            from .config import use_kb

            with use_kb(kb):
                _edit_impl(
                    note_id, content, content_file, title, tags, note_type, source, output_format
                )
        else:
            _edit_impl(
                note_id, content, content_file, title, tags, note_type, source, output_format
            )
```

**Key changes:**
1. Added `content_file` parameter between `content` and `title` (mirrors `_edit_impl` signature order)
2. Pass `content_file` to both `_edit_impl` call sites (with-kb branch and without-kb branch)

- [ ] **Step 2: Run all edit tests to verify no regressions**

Run: `uv run pytest tests/unit/test_edit.py -v`
Expected: All tests PASS (both old and new).

- [ ] **Step 3: Commit**

```bash
git add jfox/cli.py tests/unit/test_edit.py
git commit -m "feat(edit): add --content-file parameter for long text input (#106)"
```

---

### Task 4: Update `ZKCLI.edit()` test wrapper

**Files:**
- Modify: `tests/utils/jfox_cli.py` lines 236-269

- [ ] **Step 1: Add `content_file` parameter to `ZKCLI.edit()`**

In `tests/utils/jfox_cli.py`, replace lines 236-269:

```python
    def edit(
        self,
        note_id: str,
        content: Optional[str] = None,
        title: Optional[str] = None,
        tags: Optional[List[str]] = None,
        note_type: Optional[str] = None,
        source: Optional[str] = None,
    ) -> CLIResult:
        """
        编辑笔记

        Args:
            note_id: 笔记 ID
            content: 新内容
            title: 新标题
            tags: 新标签列表（替换全部）
            note_type: 新类型 (fleeting/literature/permanent)
            source: 新来源
        """
        args = [note_id]
        if content:
            args.extend(["--content", content])
        if title:
            args.extend(["--title", title])
        if tags:
            for tag in tags:
                args.extend(["--tag", tag])
        if note_type:
            args.extend(["--type", note_type])
        if source:
            args.extend(["--source", source])

        return self._run("edit", *args)
```

with:

```python
    def edit(
        self,
        note_id: str,
        content: Optional[str] = None,
        content_file: Optional[str] = None,
        title: Optional[str] = None,
        tags: Optional[List[str]] = None,
        note_type: Optional[str] = None,
        source: Optional[str] = None,
    ) -> CLIResult:
        """
        编辑笔记

        Args:
            note_id: 笔记 ID
            content: 新内容
            content_file: 从文件读取内容
            title: 新标题
            tags: 新标签列表（替换全部）
            note_type: 新类型 (fleeting/literature/permanent)
            source: 新来源
        """
        args = [note_id]
        if content:
            args.extend(["--content", content])
        if content_file:
            args.extend(["--content-file", content_file])
        if title:
            args.extend(["--title", title])
        if tags:
            for tag in tags:
                args.extend(["--tag", tag])
        if note_type:
            args.extend(["--type", note_type])
        if source:
            args.extend(["--source", source])

        return self._run("edit", *args)
```

- [ ] **Step 2: Verify existing tests still pass**

Run: `uv run pytest tests/unit/test_edit.py -v`
Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add tests/utils/jfox_cli.py
git commit -m "test: add content_file parameter to ZKCLI.edit() wrapper (#106)"
```

---

### Task 5: Final verification

- [ ] **Step 1: Run the full edit test suite**

Run: `uv run pytest tests/unit/test_edit.py -v`
Expected: All tests PASS.

- [ ] **Step 2: Run format and lint**

Run: `uv run ruff check jfox/cli.py tests/unit/test_edit.py tests/utils/jfox_cli.py && uv run black --check jfox/cli.py tests/unit/test_edit.py tests/utils/jfox_cli.py`
Expected: No errors.

---

## Self-Review

**1. Spec coverage:**
- `--content-file` reads content from file → Task 2 (implementation) + Task 1 (test: `test_edit_content_file_reads_content`)
- Error on nonexistent file → Task 2 (implementation) + Task 1 (test: `test_edit_content_file_not_exists_raises`)
- Mutual exclusion with `--content` → Task 2 (implementation) + Task 1 (test: `test_edit_content_and_content_file_exclusive`)
- Special characters (backticks, newlines, shell chars, wiki links) → Task 1 (test: `test_edit_content_file_with_special_chars`)
- Empty file clears content → Task 1 (test: `test_edit_content_file_empty`)
- CLI `edit()` passes param through → Task 3
- `ZKCLI` test wrapper updated → Task 4
- Backward compatibility (no `--content-file` = same as before) → existing tests still pass (Task 3 Step 2)

**2. Placeholder scan:** No TBD/TODO found. All steps have complete code.

**3. Type consistency:**
- `content_file: Optional[str]` in all three locations: `_edit_impl()`, `edit()`, `ZKCLI.edit()`
- `content_file` parameter position consistent: after `content`, before `title`
- `_edit_impl` call sites pass `content_file` in the correct position (after `content`, before `title`)
