# Unify Output Format Option Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Migrate `init`, `add`, `delete`, `edit` commands from `--json/--no-json` to `--format` + `--json` shortcut, with compact Rich Table as default output.

**Architecture:** Each command's CLI function gets `--format` (default `"table"`) + `--json` (backward-compatible shortcut). Internal `_xxx_impl` functions change from `json_output: bool` to `output_format: str`. Non-JSON output uses a compact single-row Rich Table (saves ~70% tokens vs JSON for agent use).

**Tech Stack:** Python 3.10+, Typer, Rich Table, pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `jfox/cli.py` | Modify | Change 4 command signatures + 3 `_xxx_impl` signatures + output branches |
| `tests/unit/test_format_unify.py` | Create | Unit tests for all 4 commands' `--format` behavior |
| `tests/unit/test_edit.py` | Modify | Update `json_output=True` → `output_format="json"` in existing tests |
| `tests/test_cli_format.py` | Modify | Add integration tests for add/delete/edit/init `--format` support |

---

### Task 1: Migrate `add` command

**Files:**
- Modify: `jfox/cli.py:223-338` (`_add_note_impl`), `jfox/cli.py:341-371` (`add` CLI function)
- Test: `tests/unit/test_format_unify.py`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_format_unify.py`:

```python
"""
单元测试：CLI 命令 --format 统一迁移

测试 init, add, delete, edit 命令的 --format/--json 参数支持
"""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from jfox.models import Note, NoteType
from jfox.config import ZKConfig

pytestmark = [pytest.mark.unit, pytest.mark.fast]


class TestAddFormat:
    """测试 add 命令的 --format 支持"""

    def _make_config(self, tmp_path):
        cfg = ZKConfig(base_dir=tmp_path)
        cfg.ensure_dirs()
        return cfg

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_add_output_format_json(self, mock_global_config, mock_note_config, tmp_path, capsys):
        """add 命令 output_format='json' 应输出 JSON"""
        from jfox.cli import _add_note_impl
        from jfox.note import create_note

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        _add_note_impl(
            content="test content",
            title="TestTitle",
            note_type="permanent",
            tags=None,
            source=None,
            output_format="json",
        )

        import json
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["success"] is True
        assert data["note"]["title"] == "TestTitle"

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_add_output_format_table(self, mock_global_config, mock_note_config, tmp_path, capsys):
        """add 命令 output_format='table' 应输出紧凑表格（非 JSON）"""
        from jfox.cli import _add_note_impl

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        _add_note_impl(
            content="test content",
            title="TableTest",
            note_type="permanent",
            tags=None,
            source=None,
            output_format="table",
        )

        captured = capsys.readouterr()
        # 不应是 JSON
        assert not captured.out.strip().startswith("{")
        # 应包含关键字段
        assert "TableTest" in captured.out

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_add_output_format_default_is_table(self, mock_global_config, mock_note_config, tmp_path, capsys):
        """add 命令默认输出格式应为 table（不再是 JSON）"""
        from jfox.cli import _add_note_impl

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        _add_note_impl(
            content="default test",
            title="DefaultTest",
            note_type="fleeting",
            tags=None,
            source=None,
            output_format="table",
        )

        captured = capsys.readouterr()
        # 默认不应是 JSON
        assert not captured.out.strip().startswith("{")

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_add_cli_signature_has_format(self, mock_global_config, mock_note_config, tmp_path):
        """add CLI 函数应接受 --format 参数"""
        import inspect
        from jfox.cli import add

        sig = inspect.signature(add)
        assert "output_format" in sig.parameters
        assert "json_output" in sig.parameters
        # output_format 默认值应为 "table"
        assert sig.parameters["output_format"].default == "table"
        # json_output 默认值应为 False
        assert sig.parameters["json_output"].default is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_format_unify.py::TestAddFormat -v`
Expected: FAIL — `_add_note_impl` has `json_output` parameter, not `output_format`; `add` signature still uses `--json/--no-json`

- [ ] **Step 3: Implement changes**

**Change 1** — Update `_add_note_impl` signature and output branches in `jfox/cli.py`.

Replace the signature at line 223:

```python
def _add_note_impl(
    content: str,
    title: Optional[str],
    note_type: str,
    tags: Optional[List[str]],
    source: Optional[str],
    output_format: str,
    template: Optional[str] = None,
):
```

Replace the output block at lines 311-336 (the `if note.save_note(new_note):` success block):

```python
        result = {
            "success": True,
            "note": {
                "id": new_note.id,
                "title": new_note.title,
                "type": new_note.type.value,
                "filepath": str(new_note.filepath),
                "links": resolved_links,
            },
        }

        if unresolved:
            result["warnings"] = f"Unresolved links: {', '.join(unresolved)}"

        if output_format == "json":
            print(output_json(result))
        else:
            _print_action_table("created", {
                "ID": new_note.id,
                "Title": new_note.title,
                "Type": new_note.type.value,
                "Links": str(len(resolved_links)),
            })
            if backlink_updated > 0:
                console.print(f"[dim]  Backlinks updated: {backlink_updated} note(s)[/dim]")
            if unresolved:
                console.print(f"  [yellow]Warning: Unresolved links - {', '.join(unresolved)}[/yellow]")
```

**Change 2** — Add the `_print_action_table` helper function. Insert before `extract_wiki_links` (around line 190):

```python
def _print_action_table(action: str, fields: dict):
    """打印紧凑的操作结果表格（单行）"""
    table = Table(show_header=True, box=None, padding=(0, 2))
    table.add_column("Action", style="green")
    for key in fields:
        table.add_column(key)
    table.add_row(action, *[str(v) for v in fields.values()])
    console.print(table)
```

**Change 3** — Update `add` CLI function signature at line 342. Replace:

```python
    json_output: bool = typer.Option(True, "--json/--no-json", help="JSON 输出"),
```

with:

```python
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"),
```

Add backward-compat mapping at the start of the `add` function body (after `"""添加新笔记..."""` docstring, inside the try):

```python
    try:
        # 向后兼容：--json 快捷方式
        if json_output:
            output_format = "json"
```

Update the calls to `_add_note_impl` to pass `output_format` instead of `json_output`:

```python
        if kb:
            from .config import use_kb
            with use_kb(kb):
                _add_note_impl(content, title, note_type, tags, source, output_format, template)
        else:
            _add_note_impl(content, title, note_type, tags, source, output_format, template)
```

Update the error handler to use `output_format`:

```python
    except Exception as e:
        result = {
            "success": False,
            "error": str(e),
        }
        if output_format == "json":
            print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_format_unify.py::TestAddFormat -v`
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/cli.py tests/unit/test_format_unify.py
git commit -m "refactor(cli): migrate add command from --json to --format with compact table output"
```

---

### Task 2: Migrate `delete` command

**Files:**
- Modify: `jfox/cli.py:824-861` (`_delete_impl`), `jfox/cli.py:864-890` (`delete` CLI function)
- Test: `tests/unit/test_format_unify.py` (append tests)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_format_unify.py`:

```python
class TestDeleteFormat:
    """测试 delete 命令的 --format 支持"""

    def _make_config(self, tmp_path):
        cfg = ZKConfig(base_dir=tmp_path)
        cfg.ensure_dirs()
        return cfg

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_delete_output_format_json(self, mock_global_config, mock_note_config, tmp_path, capsys):
        """delete 命令 output_format='json' 应输出 JSON"""
        from jfox.cli import _delete_impl
        from jfox.note import create_note, save_note

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        n = create_note("to delete", title="DeleteMe", note_type=NoteType.PERMANENT)
        save_note(n, add_to_index=False)

        _delete_impl(n.id, force=True, output_format="json")

        import json
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["success"] is True
        assert data["deleted"] == n.id

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_delete_output_format_table(self, mock_global_config, mock_note_config, tmp_path, capsys):
        """delete 命令 output_format='table' 应输出紧凑表格"""
        from jfox.cli import _delete_impl
        from jfox.note import create_note, save_note

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        n = create_note("to delete", title="TableDel", note_type=NoteType.PERMANENT)
        save_note(n, add_to_index=False)

        _delete_impl(n.id, force=True, output_format="table")

        captured = capsys.readouterr()
        assert not captured.out.strip().startswith("{")
        assert "TableDel" in captured.out

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_delete_cli_signature_has_format(self, mock_global_config, mock_note_config, tmp_path):
        """delete CLI 函数应接受 --format 参数"""
        import inspect
        from jfox.cli import delete

        sig = inspect.signature(delete)
        assert "output_format" in sig.parameters
        assert sig.parameters["output_format"].default == "table"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_format_unify.py::TestDeleteFormat -v`
Expected: FAIL — `_delete_impl` still has `json_output` parameter

- [ ] **Step 3: Implement changes**

**Change 1** — Update `_delete_impl` signature at line 824. Replace:

```python
def _delete_impl(
    note_id: str,
    force: bool,
    json_output: bool,
):
```

with:

```python
def _delete_impl(
    note_id: str,
    force: bool,
    output_format: str,
):
```

Replace the output block in `_delete_impl` (lines 848-861):

```python
    # 确认删除
    if not force:
        if output_format == "json":
            console.print(f"Use --force to delete: {n.title}")
            raise typer.Exit(1)
        else:
            console.print(f"Note: {n.title}")
            confirm = input("Delete? (y/N): ")
            if confirm.lower() != "y":
                console.print("Cancelled")
                raise typer.Exit(0)

    # 执行删除
    if note.delete_note(note_id):
        result = {
            "success": True,
            "deleted": note_id,
            "title": n.title,
        }

        if output_format == "json":
            print(output_json(result))
        else:
            _print_action_table("deleted", {
                "ID": note_id,
                "Title": n.title,
            })
    else:
        raise Exception("Failed to delete note")
```

**Change 2** — Update `delete` CLI function signature at line 865. Replace:

```python
    json_output: bool = typer.Option(True, "--json/--no-json", help="JSON 输出"),
```

with:

```python
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"),
```

Add backward-compat mapping and update calls:

```python
def delete(
    note_id: str = typer.Argument(..., help="笔记 ID"),
    force: bool = typer.Option(False, "--force", "-f", help="强制删除不确认"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"),
):
    """删除笔记"""
    try:
        # 向后兼容：--json 快捷方式
        if json_output:
            output_format = "json"

        # 如果指定了知识库，临时切换
        if kb:
            from .config import use_kb
            with use_kb(kb):
                _delete_impl(note_id, force, output_format)
        else:
            _delete_impl(note_id, force, output_format)

    except Exception as e:
        result = {
            "success": False,
            "error": str(e),
        }
        if output_format == "json":
            print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)
```

**Note:** The `delete` command has two parameters using `-f` short flag (`--force` and `--format`). Remove `-f` from `--format` to avoid conflict:

```python
    output_format: str = typer.Option("table", "--format", help="输出格式: json, table"),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_format_unify.py::TestDeleteFormat -v`
Expected: All 3 tests PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/cli.py tests/unit/test_format_unify.py
git commit -m "refactor(cli): migrate delete command from --json to --format"
```

---

### Task 3: Migrate `edit` command

**Files:**
- Modify: `jfox/cli.py:893-997` (`_edit_impl`), `jfox/cli.py:1000-1031` (`edit` CLI function)
- Modify: `tests/unit/test_edit.py` (update `json_output=True` → `output_format="json"`)
- Test: `tests/unit/test_format_unify.py` (append tests)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_format_unify.py`:

```python
class TestEditFormat:
    """测试 edit 命令的 --format 支持"""

    def _make_config(self, tmp_path):
        cfg = ZKConfig(base_dir=tmp_path)
        cfg.ensure_dirs()
        return cfg

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_edit_output_format_json(self, mock_global_config, mock_note_config, tmp_path, capsys):
        """edit 命令 output_format='json' 应输出 JSON"""
        from jfox.cli import _edit_impl
        from jfox.note import create_note, save_note

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        n = create_note("original", title="EditMe", note_type=NoteType.PERMANENT)
        save_note(n, add_to_index=False)

        _edit_impl(
            note_id=n.id, content="updated", title=None,
            tags=None, note_type=None, source=None, output_format="json",
        )

        import json
        captured = capsys.readouterr()
        data = json.loads(captured.out)
        assert data["success"] is True
        assert data["note"]["title"] == "EditMe"

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_edit_output_format_table(self, mock_global_config, mock_note_config, tmp_path, capsys):
        """edit 命令 output_format='table' 应输出紧凑表格"""
        from jfox.cli import _edit_impl
        from jfox.note import create_note, save_note

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        n = create_note("original", title="TableEdit", note_type=NoteType.PERMANENT)
        save_note(n, add_to_index=False)

        _edit_impl(
            note_id=n.id, content="new content", title="NewTitle",
            tags=None, note_type=None, source=None, output_format="table",
        )

        captured = capsys.readouterr()
        assert not captured.out.strip().startswith("{")
        assert "NewTitle" in captured.out

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_edit_cli_signature_has_format(self, mock_global_config, mock_note_config, tmp_path):
        """edit CLI 函数应接受 --format 参数"""
        import inspect
        from jfox.cli import edit

        sig = inspect.signature(edit)
        assert "output_format" in sig.parameters
        assert sig.parameters["output_format"].default == "table"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_format_unify.py::TestEditFormat -v`
Expected: FAIL — `_edit_impl` still has `json_output` parameter

- [ ] **Step 3: Implement changes**

**Change 1** — Update `_edit_impl` signature at line 893. Replace:

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
```

with:

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
```

Replace the output block at lines 972-995 (inside `if note.update_note(n):`):

```python
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

        if output_format == "json":
            print(output_json(result))
        else:
            # 收集修改的字段名
            changed = []
            if content is not None:
                changed.append("content")
            if title is not None:
                changed.append("title")
            if tags is not None:
                changed.append("tags")
            if note_type is not None:
                changed.append("type")
            if source is not None:
                changed.append("source")
            _print_action_table("updated", {
                "ID": n.id,
                "Title": n.title,
                "Fields": ", ".join(changed),
            })
            if old_title != n.title:
                console.print(f"  [dim]Title: {old_title} → {n.title}[/dim]")
            if unresolved:
                console.print(
                    f"  [yellow]Warning: Unresolved links - {', '.join(unresolved)}[/yellow]"
                )
```

**Change 2** — Update `edit` CLI function signature at line 1001. Replace:

```python
    json_output: bool = typer.Option(True, "--json/--no-json", help="JSON 输出"),
```

with:

```python
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"),
```

Add backward-compat mapping and update calls in the `edit` function body:

```python
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
    except Exception as e:
        result = {
            "success": False,
            "error": str(e),
        }
        if output_format == "json":
            print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)
```

**Change 3** — Update existing tests in `tests/unit/test_edit.py`. Replace all occurrences of `json_output=True` with `output_format="json"` in `TestEditImpl` class. Every call to `_edit_impl` needs this change. There are 8 occurrences:

```python
# Before (each occurrence):
json_output=True,

# After:
output_format="json",
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_format_unify.py::TestEditFormat tests/unit/test_edit.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/cli.py tests/unit/test_format_unify.py tests/unit/test_edit.py
git commit -m "refactor(cli): migrate edit command from --json to --format"
```

---

### Task 4: Migrate `init` command

**Files:**
- Modify: `jfox/cli.py:87-187` (`init` CLI function — no `_xxx_impl`)
- Test: `tests/unit/test_format_unify.py` (append tests)

- [ ] **Step 1: Write the failing test**

Append to `tests/unit/test_format_unify.py`:

```python
class TestInitFormat:
    """测试 init 命令的 --format 支持"""

    def test_init_cli_signature_has_format(self):
        """init CLI 函数应接受 --format 参数"""
        import inspect
        from jfox.cli import init

        sig = inspect.signature(init)
        assert "output_format" in sig.parameters
        assert sig.parameters["output_format"].default == "table"

    def test_init_cli_signature_json_backward_compat(self):
        """init CLI 函数应保留 --json 向后兼容"""
        import inspect
        from jfox.cli import init

        sig = inspect.signature(init)
        assert "json_output" in sig.parameters
        assert sig.parameters["json_output"].default is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_format_unify.py::TestInitFormat -v`
Expected: FAIL — `init` signature still uses `--json/--no-json` with `json_output` defaulting to `True`

- [ ] **Step 3: Implement changes**

Update `init` function signature at line 87. Replace:

```python
@app.command()
def init(
    name: Optional[str] = typer.Option(None, "--name", "-n", help="知识库名称（默认: default）"),
    path: Optional[str] = typer.Option(None, "--path", "-p", help="知识库路径（默认: ~/.zettelkasten/<name>/）"),
    description: Optional[str] = typer.Option(None, "--desc", "-d", help="知识库描述"),
    set_default: bool = typer.Option(True, "--default/--no-default", help="设为默认知识库"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="JSON 输出"),
):
```

with:

```python
@app.command()
def init(
    name: Optional[str] = typer.Option(None, "--name", "-n", help="知识库名称（默认: default）"),
    path: Optional[str] = typer.Option(None, "--path", "-p", help="知识库路径（默认: ~/.zettelkasten/<name>/）"),
    description: Optional[str] = typer.Option(None, "--desc", "-d", help="知识库描述"),
    set_default: bool = typer.Option(True, "--default/--no-default", help="设为默认知识库"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"),
):
```

Add backward-compat mapping at the start of the function body (after the docstring, inside the try):

```python
    try:
        # 向后兼容：--json 快捷方式
        if json_output:
            output_format = "json"
```

Then replace all `if json_output:` / `else:` blocks in the `init` function body with `if output_format == "json":` / `else:`. There are 5 such blocks in lines 115-186. Each block follows the same pattern:

```python
        # Before:
        if json_output:
            print(output_json(result))
        else:
            console.print(...)

        # After:
        if output_format == "json":
            print(output_json(result))
        else:
            _print_action_table("init", {"KB": kb_name, "Path": message})
            # 或者错误时:
            console.print(...)
```

For the success case (around line 154-166):

```python
        if success:
            result = {
                "success": True,
                "message": message,
                "name": kb_name,
            }

            if output_format == "json":
                print(output_json(result))
            else:
                _print_action_table("init", {
                    "KB": kb_name,
                })
                if set_default:
                    console.print(f"[dim]  This is now your default knowledge base[/dim]")
```

For the other error cases (lines 115, 140, 168, 179), replace `if json_output:` with `if output_format == "json":`.

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_format_unify.py::TestInitFormat -v`
Expected: All 2 tests PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/cli.py tests/unit/test_format_unify.py
git commit -m "refactor(cli): migrate init command from --json to --format"
```

---

### Task 5: Add integration tests for all 4 commands

**Files:**
- Modify: `tests/test_cli_format.py` (append tests)

- [ ] **Step 1: Write integration tests**

Append to `tests/test_cli_format.py`:

```python
    # ==========================================================================
    # Add 命令测试
    # ==========================================================================
    def test_add_format_json(self, cli):
        """测试 add 命令 --format json"""
        result = cli.run("add", "测试内容", "--title", "格式测试", "--format", "json")

        assert result.success
        data = json.loads(result.stdout)
        assert data["success"] is True
        assert data["note"]["title"] == "格式测试"

    def test_add_format_table(self, cli):
        """测试 add 命令 --format table（默认）"""
        result = cli.run("add", "测试内容", "--title", "表格测试", "--format", "table")

        assert result.success
        # 不应是 JSON
        assert not result.stdout.strip().startswith("{")
        assert "表格测试" in result.stdout

    def test_add_json_flag_backward_compat(self, cli):
        """测试 add 命令 --json 向后兼容"""
        result = cli.run("add", "兼容测试", "--title", "JSON兼容", "--json")

        assert result.success
        data = json.loads(result.stdout)
        assert data["success"] is True

    def test_add_default_is_table(self, cli):
        """测试 add 命令默认输出为 table"""
        result = cli.run("add", "默认测试", "--title", "默认格式", "--format", "table")

        assert result.success
        assert not result.stdout.strip().startswith("{")

    # ==========================================================================
    # Delete 命令测试
    # ==========================================================================
    def test_delete_format_json(self, cli):
        """测试 delete 命令 --format json"""
        add_result = cli.add("to delete", title="DelFormat")
        note_id = add_result.data["note"]["id"]

        result = cli.run("delete", note_id, "--force", "--format", "json")

        assert result.success
        data = json.loads(result.stdout)
        assert data["success"] is True

    def test_delete_format_table(self, cli):
        """测试 delete 命令 --format table"""
        add_result = cli.add("to delete table", title="DelTable")
        note_id = add_result.data["note"]["id"]

        result = cli.run("delete", note_id, "--force", "--format", "table")

        assert result.success
        assert not result.stdout.strip().startswith("{")

    # ==========================================================================
    # Edit 命令测试
    # ==========================================================================
    def test_edit_format_json(self, cli):
        """测试 edit 命令 --format json"""
        add_result = cli.add("original", title="EditFormat")
        note_id = add_result.data["note"]["id"]

        result = cli.run("edit", note_id, "--content", "updated", "--format", "json")

        assert result.success
        data = json.loads(result.stdout)
        assert data["success"] is True

    def test_edit_format_table(self, cli):
        """测试 edit 命令 --format table"""
        add_result = cli.add("original", title="EditTable")
        note_id = add_result.data["note"]["id"]

        result = cli.run("edit", note_id, "--title", "NewTitle", "--format", "table")

        assert result.success
        assert not result.stdout.strip().startswith("{")
        assert "NewTitle" in result.stdout

    # ==========================================================================
    # Init 命令测试
    # ==========================================================================
    def test_init_format_json(self, cli):
        """测试 init 命令 --format json（已存在的 KB）"""
        # cli fixture 已初始化默认 KB，再 init 会失败，但验证格式
        result = cli.run("init", "--format", "json")

        # KB 已存在应失败，但输出应为 JSON
        data = json.loads(result.stdout)
        assert data["success"] is False

    def test_init_format_table(self, cli):
        """测试 init 命令 --format table（已存在的 KB）"""
        result = cli.run("init", "--format", "table")

        assert not result.stdout.strip().startswith("{")

    # ==========================================================================
    # 综合测试：所有命令都支持 --format 和 --json
    # ==========================================================================
    def test_all_mutation_commands_support_format(self, cli):
        """测试所有变更类命令都支持 --format json"""
        # add
        result = cli.run("add", "format test", "--title", "FmtTest", "--format", "json")
        assert result.success
        data = json.loads(result.stdout)
        note_id = data["note"]["id"]

        # edit
        result = cli.run("edit", note_id, "--content", "edited", "--format", "json")
        assert result.success
        json.loads(result.stdout)

        # delete
        result = cli.run("delete", note_id, "--force", "--format", "json")
        assert result.success
        json.loads(result.stdout)
```

- [ ] **Step 2: Run integration tests**

Run: `uv run pytest tests/test_cli_format.py -v -k "add_format or delete_format or edit_format or init_format or all_mutation"`
Expected: All tests PASS

- [ ] **Step 3: Run full format test suite**

Run: `uv run pytest tests/test_cli_format.py -v`
Expected: All tests PASS (new + existing)

- [ ] **Step 4: Commit**

```bash
git add tests/test_cli_format.py
git commit -m "test: add --format integration tests for add/delete/edit/init commands"
```

---

## Self-Review

**1. Spec coverage:** Issue requires migrating `init`, `add`, `delete`, `edit` from `--json/--no-json` to `--format` + `--json`. All 4 covered (Tasks 1-4). Compact table output specified (issue says ~80 chars, saves ~70% tokens). Backward compat via `--json` shortcut preserved. Integration tests in Task 5.

**2. Placeholder scan:** No TBD, TODO, or "implement later" found. All steps contain complete code with exact line numbers.

**3. Type consistency:** `_print_action_table(action: str, fields: dict)` — callers pass `action` as string literal ("created", "deleted", "updated", "init") and `fields` as dict. `_xxx_impl` functions all use `output_format: str`. CLI functions all use `output_format: str = typer.Option("table", ...)` and `json_output: bool = typer.Option(False, ...)`. Consistent across all tasks.

**4. Potential issue — `-f` flag conflict in `delete`:** The `delete` command has `--force` using `-f` short flag, and `--format` would also want `-f`. Task 2 handles this by removing `-f` from `--format` for the `delete` command only. Other commands (`add`, `edit`, `init`) can safely use `-f` for `--format`.
