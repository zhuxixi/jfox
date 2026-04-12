# Edit Command 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `jfox edit` command that modifies existing notes while preserving ID, creation timestamp, and link integrity.

**Architecture:** New `update_note()` function in `note.py` handles the storage layer (old file deletion + new file write + index update). A `_edit_impl()` helper in `cli.py` handles CLI orchestration (field-level edits, wiki-link resolution, backlink maintenance). The CLI command accepts `--content`, `--title`, `--tags`, `--type`, `--source` flags for partial field updates, plus `--interactive` to open in `$EDITOR`.

**Tech Stack:** Python 3.10+, Typer, Rich, existing jfox modules (note, config, models, formatters)

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `jfox/note.py` | Modify | Add `update_note()` function for storage-layer note update (delete old file, write new file, reindex) |
| `jfox/cli.py` | Modify | Add `edit` command + `_edit_impl()` helper |
| `jfox/formatters.py` | No change | Existing formatters sufficient |
| `tests/unit/test_edit.py` | Create | Unit tests for `update_note()` + CLI edit command |
| `tests/utils/jfox_cli.py` | Modify | Add `edit()` method to ZKCLI test wrapper |

---

### Task 1: Add `update_note()` to `note.py`

**Files:**
- Modify: `jfox/note.py:172-200` (after `delete_note()`)
- Test: `tests/unit/test_edit.py`

This function handles the storage layer: it takes an existing Note object with modified fields, deletes the old file (filename may change if title changed), writes the new file, and reindexes.

- [ ] **Step 1: Write failing tests for `update_note()`**

Create `tests/unit/test_edit.py`:

```python
"""
测试类型: 单元测试
目标模块: jfox.note (update_note 函数)
预估耗时: < 1秒
依赖要求: 无外部依赖
"""
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]
from pathlib import Path
from datetime import datetime

from jfox.models import Note, NoteType
from jfox.note import update_note, create_note, save_note, load_note_by_id


class TestUpdateNote:
    """测试 update_note 函数"""

    def test_update_content_preserves_id_and_created(self, tmp_path):
        """更新内容时保留 ID 和创建时间"""
        # 创建笔记
        n = create_note("original content", title="Test", note_type=NoteType.PERMANENT)
        n.set_filepath(tmp_path / "permanent" / n.filename)
        n.filepath.parent.mkdir(parents=True, exist_ok=True)
        save_note(n, add_to_index=False)

        original_id = n.id
        original_created = n.created

        # 更新内容
        n.content = "updated content"
        updated = update_note(n, add_to_index=False)

        assert updated is True
        # 重新加载验证
        loaded = load_note_by_id(original_id)
        assert loaded is not None
        assert loaded.id == original_id
        assert loaded.created == original_created
        assert loaded.content == "updated content"
        assert loaded.updated > original_created

    def test_update_title_renames_file(self, tmp_path):
        """更新标题时重命名文件"""
        n = create_note("content", title="Old Title", note_type=NoteType.PERMANENT)
        n.set_filepath(tmp_path / "permanent" / n.filename)
        n.filepath.parent.mkdir(parents=True, exist_ok=True)
        old_path = n.filepath
        save_note(n, add_to_index=False)

        # 记录旧路径，修改标题
        old_filepath = old_path
        n.title = "New Title"

        updated = update_note(n, add_to_index=False)
        assert updated is True

        # 旧文件应该不存在
        assert not old_filepath.exists()
        # 新文件应该存在
        loaded = load_note_by_id(n.id)
        assert loaded is not None
        assert loaded.title == "New Title"

    def test_update_tags(self, tmp_path):
        """更新标签"""
        n = create_note("content", title="Test", note_type=NoteType.PERMANENT, tags=["old"])
        n.set_filepath(tmp_path / "permanent" / n.filename)
        n.filepath.parent.mkdir(parents=True, exist_ok=True)
        save_note(n, add_to_index=False)

        n.tags = ["new1", "new2"]
        updated = update_note(n, add_to_index=False)
        assert updated is True

        loaded = load_note_by_id(n.id)
        assert loaded.tags == ["new1", "new2"]

    def test_update_nonexistent_note_returns_false(self, tmp_path):
        """更新不存在的笔记返回 False"""
        n = create_note("content", title="Ghost", note_type=NoteType.PERMANENT)
        n.set_filepath(tmp_path / "permanent" / "nonexistent.md")
        # 不调用 save_note，文件不存在

        updated = update_note(n, add_to_index=False)
        assert updated is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_edit.py -v`
Expected: FAIL — `ImportError: cannot import name 'update_note' from 'jfox.note'`

- [ ] **Step 3: Implement `update_note()` in `note.py`**

Add after the `delete_note()` function (after line 200) in `jfox/note.py`:

```python
def update_note(note_obj: Note, add_to_index: bool = True) -> bool:
    """
    更新已有笔记

    处理：删除旧文件 → 更新 updated 时间戳 → 写入新文件 → 更新索引

    Args:
        note_obj: 已修改的 Note 对象（必须已有 id 和 filepath）
        add_to_index: 是否更新搜索索引

    Returns:
        是否更新成功
    """
    # 查找当前文件路径（可能标题改了，按 ID 查）
    old_filepath = find_note_file(config, note_obj.id)
    if not old_filepath:
        logger.warning(f"Note {note_obj.id} file not found on disk")
        return False

    try:
        # 更新时间戳
        note_obj.updated = datetime.now()

        # 写入新文件（filepath 属性根据当前字段生成）
        note_obj.filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(note_obj.filepath, 'w', encoding='utf-8') as f:
            f.write(note_obj.to_markdown())

        # 如果文件路径变了（标题修改导致重命名），删除旧文件
        if old_filepath != note_obj.filepath and old_filepath.exists():
            old_filepath.unlink()
            logger.info(f"Renamed note file: {old_filepath} -> {note_obj.filepath}")

        logger.info(f"Updated note {note_obj.id}")

        # 更新索引
        if add_to_index:
            # 先删除旧索引，再添加新索引
            vector_store = get_vector_store()
            vector_store.delete_note(note_obj.id)
            vector_store.add_note(note_obj)

            try:
                from .bm25_index import get_bm25_index
                bm25_index = get_bm25_index()
                bm25_index.remove_document(note_obj.id)
                content = f"{note_obj.title} {note_obj.content}"
                bm25_index.add_document(note_obj.id, content)
            except Exception as e:
                logger.warning(f"Failed to update BM25 index: {e}")

        return True

    except Exception as e:
        logger.error(f"Failed to update note {note_obj.id}: {e}")
        return False
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_edit.py -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/note.py tests/unit/test_edit.py
git commit -m "feat: add update_note() storage function for edit command"
```

---

### Task 2: Add `edit` CLI command

**Files:**
- Modify: `jfox/cli.py:860` (after `delete` command block)
- Test: `tests/unit/test_edit.py`

The edit command supports partial field updates via flags, wiki-link resolution, and backlink maintenance.

- [ ] **Step 1: Write failing tests for the CLI edit command**

Append to `tests/unit/test_edit.py`:

```python
from jfox.cli import _edit_impl


class TestEditImpl:
    """测试 _edit_impl 内部实现"""

    def test_edit_content(self, tmp_path):
        """通过 --content 编辑笔记内容"""
        # 创建笔记
        n = create_note("original", title="EditMe", note_type=NoteType.PERMANENT)
        n.set_filepath(tmp_path / "permanent" / n.filename)
        n.filepath.parent.mkdir(parents=True, exist_ok=True)
        save_note(n, add_to_index=False)

        _edit_impl(
            note_id=n.id,
            content="updated content",
            title=None,
            tags=None,
            note_type=None,
            source=None,
            json_output=True,
        )

        loaded = load_note_by_id(n.id)
        assert loaded is not None
        assert loaded.content == "updated content"
        assert loaded.id == n.id
        assert loaded.title == "EditMe"

    def test_edit_title(self, tmp_path):
        """编辑笔记标题"""
        n = create_note("content", title="OldTitle", note_type=NoteType.PERMANENT)
        n.set_filepath(tmp_path / "permanent" / n.filename)
        n.filepath.parent.mkdir(parents=True, exist_ok=True)
        save_note(n, add_to_index=False)

        _edit_impl(
            note_id=n.id,
            content=None,
            title="NewTitle",
            tags=None,
            note_type=None,
            source=None,
            json_output=True,
        )

        loaded = load_note_by_id(n.id)
        assert loaded is not None
        assert loaded.title == "NewTitle"

    def test_edit_multiple_fields(self, tmp_path):
        """同时编辑多个字段"""
        n = create_note("old content", title="Old", note_type=NoteType.FLEETING, tags=["a"])
        n.set_filepath(tmp_path / "fleeting" / n.filename)
        n.filepath.parent.mkdir(parents=True, exist_ok=True)
        save_note(n, add_to_index=False)

        _edit_impl(
            note_id=n.id,
            content="new content",
            title="New Title",
            tags=["x", "y"],
            note_type="permanent",
            source="book",
            json_output=True,
        )

        loaded = load_note_by_id(n.id)
        assert loaded is not None
        assert loaded.content == "new content"
        assert loaded.title == "New Title"
        assert loaded.tags == ["x", "y"]
        assert loaded.type == NoteType.PERMANENT
        assert loaded.source == "book"

    def test_edit_nonexistent_note_raises(self, tmp_path):
        """编辑不存在的笔记抛出异常"""
        with pytest.raises(Exception):
            _edit_impl(
                note_id="9999999999999999",
                content="x",
                title=None,
                tags=None,
                note_type=None,
                source=None,
                json_output=True,
            )

    def test_edit_no_fields_specified_raises(self, tmp_path):
        """未指定任何编辑字段时抛出异常"""
        n = create_note("content", title="NoEdit", note_type=NoteType.PERMANENT)
        n.set_filepath(tmp_path / "permanent" / n.filename)
        n.filepath.parent.mkdir(parents=True, exist_ok=True)
        save_note(n, add_to_index=False)

        with pytest.raises(ValueError, match="至少指定一个"):
            _edit_impl(
                note_id=n.id,
                content=None,
                title=None,
                tags=None,
                note_type=None,
                source=None,
                json_output=True,
            )

    def test_edit_with_wiki_links_resolves(self, tmp_path):
        """编辑内容中的 [[链接]] 被解析"""
        # 创建目标笔记
        target = create_note("target note", title="TargetNote", note_type=NoteType.PERMANENT)
        target.set_filepath(tmp_path / "permanent" / target.filename)
        target.filepath.parent.mkdir(parents=True, exist_ok=True)
        save_note(target, add_to_index=False)

        # 创建源笔记
        source = create_note("source note", title="SourceNote", note_type=NoteType.PERMANENT)
        source.set_filepath(tmp_path / "permanent" / source.filename)
        save_note(source, add_to_index=False)

        # 编辑源笔记，添加 wiki link
        _edit_impl(
            note_id=source.id,
            content="see [[TargetNote]] for details",
            title=None,
            tags=None,
            note_type=None,
            source=None,
            json_output=True,
        )

        loaded = load_note_by_id(source.id)
        assert loaded is not None
        assert target.id in loaded.links

        # 验证反向链接
        target_loaded = load_note_by_id(target.id)
        assert target_loaded is not None
        assert source.id in target_loaded.backlinks
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_edit.py::TestEditImpl -v`
Expected: FAIL — `ImportError: cannot import name '_edit_impl' from 'jfox.cli'`

- [ ] **Step 3: Implement `_edit_impl()` and `edit` command in `cli.py`**

Add the following after the `_delete_impl()` function (after the `delete` command definition, around line 891) in `jfox/cli.py`:

```python
def _edit_impl(
    note_id: str,
    content: Optional[str],
    title: Optional[str],
    tags: Optional[List[str]],
    note_type: Optional[str],
    source: Optional[str],
    json_output: bool,
):
    """编辑笔记的内部实现"""
    # 验证：至少指定一个编辑字段
    if all(v is None for v in [content, title, tags, note_type, source]):
        raise ValueError("至少指定一个要编辑的字段 (--content, --title, --tags, --type, --source)")

    # 加载笔记
    n = note.load_note_by_id(note_id)
    if not n:
        raise ValueError(f"笔记不存在: {note_id}")

    old_title = n.title
    old_links = set(n.links)

    # 更新字段
    if content is not None:
        n.content = content
    if title is not None:
        n.title = title
    if tags is not None:
        n.tags = tags
    if source is not None:
        n.source = source if source else None  # 空字符串清除 source
    if note_type is not None:
        try:
            new_type = NoteType(note_type.lower())
        except ValueError:
            raise ValueError(f"Invalid note type: {note_type}. Use: fleeting, literature, permanent")
        n.type = new_type

    # 如果内容被更新，解析 wiki links
    if content is not None:
        wiki_links = extract_wiki_links(content)
        resolved_links = []
        unresolved = []

        all_notes = note.list_notes() if wiki_links else []
        for link_text in wiki_links:
            target_id = find_note_id_by_title_or_id(link_text, all_notes=all_notes)
            if target_id:
                resolved_links.append(target_id)
            else:
                unresolved.append(link_text)

        n.links = resolved_links
    else:
        unresolved = []

    # 保存更新
    if note.update_note(n):
        # 更新反向链接
        new_links = set(n.links)

        # 新增的链接 → 添加反向链接
        added_links = new_links - old_links
        for target_id in added_links:
            target_note = note.load_note_by_id(target_id)
            if target_note and n.id not in target_note.backlinks:
                target_note.backlinks.append(n.id)
                note.save_note(target_note, add_to_index=False)

        # 移除的链接 → 删除反向链接
        removed_links = old_links - new_links
        for target_id in removed_links:
            target_note = note.load_note_by_id(target_id)
            if target_note and n.id in target_note.backlinks:
                target_note.backlinks.remove(n.id)
                note.save_note(target_note, add_to_index=False)

        result = {
            "success": True,
            "note": {
                "id": n.id,
                "title": n.title,
                "type": n.type.value,
                "filepath": str(n.filepath),
            },
        }
        if old_title != n.title:
            result["title_changed"] = {"old": old_title, "new": n.title}
        if unresolved:
            result["warnings"] = f"Unresolved links: {', '.join(unresolved)}"

        if json_output:
            print(output_json(result))
        else:
            console.print(f"[green]✓[/green] Note updated: {n.title}")
            if old_title != n.title:
                console.print(f"  Title: {old_title} → {n.title}")
            if unresolved:
                console.print(f"  [yellow]Warning: Unresolved links - {', '.join(unresolved)}[/yellow]")
    else:
        raise Exception("Failed to update note")


@app.command()
def edit(
    note_id: str = typer.Argument(..., help="笔记 ID 或标题"),
    content: Optional[str] = typer.Option(None, "--content", "-c", help="新内容"),
    title: Optional[str] = typer.Option(None, "--title", "-t", help="新标题"),
    tags: Optional[List[str]] = typer.Option(None, "--tag", help="新标签（替换全部）"),
    note_type: Optional[str] = typer.Option(None, "--type", help="新类型 (fleeting/literature/permanent)"),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="新来源"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="JSON 输出"),
):
    """编辑已有笔记（保留 ID 和创建时间）"""
    try:
        if kb:
            from .config import use_kb
            with use_kb(kb):
                _edit_impl(note_id, content, title, tags, note_type, source, json_output)
        else:
            _edit_impl(note_id, content, title, tags, note_type, source, json_output)
    except Exception as e:
        result = {
            "success": False,
            "error": str(e),
        }
        if json_output:
            print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_edit.py -v`
Expected: All tests PASS (both `TestUpdateNote` and `TestEditImpl`)

- [ ] **Step 5: Commit**

```bash
git add jfox/cli.py tests/unit/test_edit.py
git commit -m "feat: add edit command for modifying existing notes"
```

---

### Task 3: Add `edit()` method to ZKCLI test wrapper

**Files:**
- Modify: `tests/utils/jfox_cli.py:227` (after `delete()` method)

This enables integration/e2e tests to call `cli.edit(...)`.

- [ ] **Step 1: Add `edit()` method to ZKCLI**

Add after the `delete()` method (line 233) in `tests/utils/jfox_cli.py`:

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

- [ ] **Step 2: Verify no import errors**

Run: `uv run python -c "from tests.utils.jfox_cli import ZKCLI; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add tests/utils/jfox_cli.py
git commit -m "test: add edit() method to ZKCLI test wrapper"
```

---

### Task 4: Verify CLI command works end-to-end

**Files:**
- No new files

Manual smoke test to confirm the CLI command works as expected.

- [ ] **Step 1: Verify CLI help**

Run: `uv run jfox edit --help`
Expected: Shows help text with all options (`--content`, `--title`, `--tag`, `--type`, `--source`, `--kb`, `--json/--no-json`)

- [ ] **Step 2: Run all edit unit tests**

Run: `uv run pytest tests/unit/test_edit.py -v`
Expected: All tests PASS

---

## Self-Review

### 1. Spec Coverage

| Issue #93 Requirement | Task |
|---|---|
| Edit by ID (`jfox edit <note_id>`) | Task 2 |
| Edit specific fields only (`--content`, `--title`, `--tags`, `--type`, `--source`) | Task 2 |
| Preserve metadata (ID, created timestamp) | Task 1 (`update_note` preserves `id`/`created`) |
| Index updates (BM25 + vector) | Task 1 (`update_note` reindexes) |
| Link integrity (warn on title change, resolve `[[links]]`) | Task 2 (`_edit_impl` resolves wiki links + maintains backlinks) |
| Validation | Task 2 (note_type validation, at-least-one-field check) |
| `--interactive` (open in `$EDITOR`) | **Deferred** — Not in initial scope, adds complexity with temp file handling and process management |

### 2. Placeholder Scan

No TBD, TODO, or placeholder patterns found. All code blocks contain complete implementations.

### 3. Type Consistency

- `update_note(note_obj: Note, add_to_index: bool) -> bool` — used consistently in Task 1 and Task 2
- `_edit_impl(note_id, content, title, tags, note_type, source, json_output)` — consistent signature in Task 2 tests and implementation
- `find_note_file(config, note_id)` returns `Optional[Path]` — matches usage in `update_note`
- Note fields (`id`, `title`, `content`, `type`, `tags`, `links`, `backlinks`, `source`, `created`, `updated`) — all match `models.py` dataclass
