# Index Command --kb Parameter Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--kb` parameter to the `jfox index` command so all sub-actions (status, rebuild, verify, rebuild-bm25, bm25-status) can target a specific knowledge base without prior `jfox kb switch`.

**Architecture:** Add `kb` parameter to the `index()` Typer command function and wrap its body with `use_kb(kb)` context manager — identical to how ~10 other commands (add, list, search, edit, delete, etc.) already handle it. No changes to indexer, vector store, or BM25 internals.

**Tech Stack:** Python, Typer CLI framework, pytest

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `jfox/cli.py` | Modify `index()` (lines 1588-1738) | Add `--kb` parameter + `use_kb()` wrapper |
| `tests/unit/test_index_kb_param.py` | Create | Unit tests for `--kb` on index command |

No other files need changes. `use_kb()` in `config.py` already handles singleton reset for `VectorStore` and `BM25Index`.

---

### Task 1: Write failing test — nonexistent KB reports error

**Files:**
- Create: `tests/unit/test_index_kb_param.py`

- [ ] **Step 1: Write the failing test**

```python
"""Tests for jfox index --kb parameter support (issue #104)"""

import pytest
from typer.testing import CliRunner

from jfox.cli import app

runner = CliRunner()


class TestIndexKbParam:
    """验证 index 命令的 --kb 参数功能"""

    def test_status_with_nonexistent_kb_returns_error(self):
        """--kb 指向不存在的知识库时应报错"""
        result = runner.invoke(app, ["index", "status", "--kb", "nonexistent_kb_104"])
        assert result.exit_code != 0
        assert "nonexistent_kb_104" in result.output.lower() or "not found" in result.output.lower()

    def test_verify_with_nonexistent_kb_returns_error(self):
        """index verify --kb <不存在的知识库> 应报错"""
        result = runner.invoke(app, ["index", "verify", "--kb", "nonexistent_kb_104"])
        assert result.exit_code != 0
        assert "nonexistent_kb_104" in result.output.lower() or "not found" in result.output.lower()

    def test_rebuild_with_nonexistent_kb_returns_error(self):
        """index rebuild --kb <不存在的知识库> 应报错"""
        result = runner.invoke(app, ["index", "rebuild", "--kb", "nonexistent_kb_104"])
        assert result.exit_code != 0
        assert "nonexistent_kb_104" in result.output.lower() or "not found" in result.output.lower()

    def test_rebuild_bm25_with_nonexistent_kb_returns_error(self):
        """index rebuild-bm25 --kb <不存在的知识库> 应报错"""
        result = runner.invoke(app, ["index", "rebuild-bm25", "--kb", "nonexistent_kb_104"])
        assert result.exit_code != 0
        assert "nonexistent_kb_104" in result.output.lower() or "not found" in result.output.lower()

    def test_bm25_status_with_nonexistent_kb_returns_error(self):
        """index bm25-status --kb <不存在的知识库> 应报错"""
        result = runner.invoke(app, ["index", "bm25-status", "--kb", "nonexistent_kb_104"])
        assert result.exit_code != 0
        assert "nonexistent_kb_104" in result.output.lower() or "not found" in result.output.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_index_kb_param.py -v`
Expected: All 5 tests FAIL — `--kb` is rejected as an unknown option by Typer (`No such option: --kb`).

---

### Task 2: Add `--kb` parameter to `index()` command

**Files:**
- Modify: `jfox/cli.py:1588-1738`

- [ ] **Step 1: Modify the `index()` function signature**

In `jfox/cli.py`, replace lines 1588-1597 (the function signature):

```python
@app.command()
def index(
    action: str = typer.Argument(
        "status", help="操作: status, rebuild, verify, rebuild-bm25, bm25-status"
    ),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"
    ),
):
```

with:

```python
@app.command()
def index(
    action: str = typer.Argument(
        "status", help="操作: status, rebuild, verify, rebuild-bm25, bm25-status"
    ),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"
    ),
):
```

- [ ] **Step 2: Wrap function body with `use_kb()`**

In the same function, replace lines 1598-1738 (from `"""索引管理..."""` to the end of the function). The entire body after the docstring gets wrapped in `with use_kb(kb):`. Here is the complete replacement:

```python
    """索引管理：查看状态、重建索引、验证完整性"""
    try:
        # 处理 --json 快捷方式
        if json_output:
            output_format = "json"

        from .config import use_kb

        with use_kb(kb):
            if action == "rebuild-bm25":
                # 重建 BM25 索引
                from . import note as note_module
                from .bm25_index import get_bm25_index

                console.print("[yellow]Rebuilding BM25 index...[/yellow]")
                bm25_index = get_bm25_index()
                notes = note_module.list_notes(limit=10000)
                success = bm25_index.rebuild_from_notes(notes)

                result = {
                    "success": success,
                    "indexed": len(notes),
                }

                if output_format == "json":
                    print(output_json(result))
                else:
                    if success:
                        console.print(f"[green]✓[/green] BM25 index rebuilt: {len(notes)} notes")
                    else:
                        console.print("[red]✗[/red] Failed to rebuild BM25 index")

            elif action == "bm25-status":
                # 查看 BM25 索引状态
                from .bm25_index import get_bm25_index

                bm25_index = get_bm25_index()
                stats = bm25_index.get_stats()

                result = {
                    "bm25_index": stats,
                }

                if output_format == "json":
                    print(output_json(result))
                else:
                    table = Table(title="BM25 Index Status")
                    table.add_column("Property", style="cyan")
                    table.add_column("Value", style="green")
                    table.add_row("Indexed Documents", str(stats["indexed"]))
                    table.add_row("Index Version", str(stats["version"]))
                    table.add_row("Index File", str(stats["index_path"]))
                    table.add_row("Index Exists", "Yes" if stats["index_exists"] else "No")
                    console.print(table)

            else:
                vector_store = get_vector_store()
                indexer = Indexer(config, vector_store)

                if action == "status":
                    stats = indexer.get_stats()
                    vs_stats = vector_store.get_stats()

                    result = {
                        "total_indexed": stats.total_indexed,
                        "last_indexed": stats.last_indexed.isoformat() if stats.last_indexed else None,
                        "pending_changes": stats.pending_changes,
                        "vector_store": vs_stats,
                    }

                    if output_format == "json":
                        print(output_json(result))
                    else:
                        table = Table(title="Index Status")
                        table.add_column("Property", style="cyan")
                        table.add_column("Value", style="green")
                        table.add_row("Total Indexed", str(stats.total_indexed))
                        table.add_row("Last Indexed", str(stats.last_indexed or "Never"))
                        table.add_row("Pending Changes", str(stats.pending_changes))
                        table.add_row("Vector Store Notes", str(vs_stats.get("total_notes", 0)))
                        console.print(table)

                        if stats.errors:
                            console.print("\n[yellow]Recent Errors:[/yellow]")
                            for err in stats.errors[-5:]:
                                console.print(f"  - {err}")

                elif action == "rebuild":
                    console.print("[yellow]Rebuilding index...[/yellow]")
                    count = indexer.index_all()

                    result = {
                        "success": True,
                        "indexed": count,
                    }

                    if output_format == "json":
                        print(output_json(result))
                    else:
                        console.print(f"[green]✓[/green] Indexed {count} notes")

                elif action == "verify":
                    verification = indexer.verify_index()

                    result = verification

                    if output_format == "json":
                        print(output_json(result))
                    else:
                        if verification["healthy"]:
                            console.print("[green]✓[/green] Index is healthy")
                        else:
                            console.print("[yellow]⚠[/yellow] Index has issues")

                        console.print(f"  Files: {verification['total_files']}")
                        console.print(f"  Indexed: {verification['total_indexed']}")

                        if verification["missing_from_index"]:
                            console.print(
                                f"\n[yellow]Missing from index ({len(verification['missing_from_index'])}):[/yellow]"
                            )
                        for nid in verification["missing_from_index"][:5]:
                            console.print(f"  - {nid}")

                        if verification["orphaned_in_index"]:
                            console.print(
                                f"\n[yellow]Orphaned in index ({len(verification['orphaned_in_index'])}):[/yellow]"
                            )
                        for nid in verification["orphaned_in_index"][:5]:
                            console.print(f"  - {nid}")

                else:
                    console.print(
                        f"[red]Unknown action: {action}. Use: status, rebuild, verify, rebuild-bm25, bm25-status[/red]"
                    )
                    raise typer.Exit(1)

    except Exception as e:
        result = {"success": False, "error": str(e)}
        if json_output:
            print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)
```

**Key changes:**
1. Added `kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称")` to signature
2. Added `from .config import use_kb` and `with use_kb(kb):` wrapping all action branches
3. All existing logic unchanged, just indented one level deeper inside the `with` block
4. `use_kb(None)` is a no-op (yields without switching), so default behavior is preserved

- [ ] **Step 3: Run Task 1 tests to verify they now pass (different failure)**

Run: `uv run pytest tests/unit/test_index_kb_param.py -v`
Expected: Tests now fail with "not found" error messages (not "No such option") because `--kb` is accepted, but the KB doesn't exist.

---

### Task 3: Add tests for successful `--kb` usage with a real KB

**Files:**
- Modify: `tests/unit/test_index_kb_param.py`

- [ ] **Step 1: Add tests that use a real temp KB**

Append to `tests/unit/test_index_kb_param.py`:

```python
    def test_status_with_valid_kb(self, temp_kb, cli):
        """index status --kb <存在的知识库> 应正常执行"""
        result = runner.invoke(app, ["index", "status", "--kb", cli.kb_name, "--json"])
        # 命令应该成功（exit_code 0），或者至少不因 --kb 报错
        # 空知识库的 index status 返回 {"total_indexed": 0, ...}
        assert "--kb" not in result.output  # 不应有 "No such option: --kb"
        if result.exit_code == 0 and result.output.strip():
            data = json.loads(result.output.strip())
            assert "total_indexed" in data

    def test_verify_with_valid_kb(self, temp_kb, cli):
        """index verify --kb <存在的知识库> 应正常执行"""
        result = runner.invoke(app, ["index", "verify", "--kb", cli.kb_name, "--json"])
        assert "--kb" not in result.output
        if result.exit_code == 0 and result.output.strip():
            data = json.loads(result.output.strip())
            assert "healthy" in data

    def test_default_kb_not_affected(self, temp_kb, cli):
        """不传 --kb 时行为与修改前一致"""
        result = runner.invoke(app, ["index", "status", "--json"])
        assert result.exit_code == 0
```

Also add the necessary imports and fixtures at the top of the file. Update the full file to:

```python
"""Tests for jfox index --kb parameter support (issue #104)"""

import json
import pytest
from typer.testing import CliRunner

from jfox.cli import app

runner = CliRunner()


class TestIndexKbParamErrors:
    """验证 --kb 参数错误处理"""

    def test_status_with_nonexistent_kb_returns_error(self):
        """--kb 指向不存在的知识库时应报错"""
        result = runner.invoke(app, ["index", "status", "--kb", "nonexistent_kb_104"])
        assert result.exit_code != 0
        output_lower = result.output.lower()
        assert "nonexistent_kb_104" in output_lower or "not found" in output_lower

    def test_verify_with_nonexistent_kb_returns_error(self):
        """index verify --kb <不存在的知识库> 应报错"""
        result = runner.invoke(app, ["index", "verify", "--kb", "nonexistent_kb_104"])
        assert result.exit_code != 0
        output_lower = result.output.lower()
        assert "nonexistent_kb_104" in output_lower or "not found" in output_lower

    def test_rebuild_with_nonexistent_kb_returns_error(self):
        """index rebuild --kb <不存在的知识库> 应报错"""
        result = runner.invoke(app, ["index", "rebuild", "--kb", "nonexistent_kb_104"])
        assert result.exit_code != 0
        output_lower = result.output.lower()
        assert "nonexistent_kb_104" in output_lower or "not found" in output_lower

    def test_rebuild_bm25_with_nonexistent_kb_returns_error(self):
        """index rebuild-bm25 --kb <不存在的知识库> 应报错"""
        result = runner.invoke(app, ["index", "rebuild-bm25", "--kb", "nonexistent_kb_104"])
        assert result.exit_code != 0
        output_lower = result.output.lower()
        assert "nonexistent_kb_104" in output_lower or "not found" in output_lower

    def test_bm25_status_with_nonexistent_kb_returns_error(self):
        """index bm25-status --kb <不存在的知识库> 应报错"""
        result = runner.invoke(app, ["index", "bm25-status", "--kb", "nonexistent_kb_104"])
        assert result.exit_code != 0
        output_lower = result.output.lower()
        assert "nonexistent_kb_104" in output_lower or "not found" in output_lower


class TestIndexKbParamSuccess:
    """验证 --kb 参数正常功能"""

    def test_status_with_valid_kb(self, cli):
        """index status --kb <存在的知识库> 应正常执行"""
        result = runner.invoke(app, ["index", "status", "--kb", cli.kb_name, "--json"])
        assert "--kb" not in result.output or "No such option" not in result.output
        if result.exit_code == 0 and result.output.strip():
            data = json.loads(result.output.strip())
            assert "total_indexed" in data

    def test_verify_with_valid_kb(self, cli):
        """index verify --kb <存在的知识库> 应正常执行"""
        result = runner.invoke(app, ["index", "verify", "--kb", cli.kb_name, "--json"])
        assert "--kb" not in result.output or "No such option" not in result.output
        if result.exit_code == 0 and result.output.strip():
            data = json.loads(result.output.strip())
            assert "healthy" in data

    def test_default_kb_not_affected(self, cli):
        """不传 --kb 时行为与修改前一致"""
        result = runner.invoke(app, ["index", "status", "--json"])
        assert result.exit_code == 0
```

Note: The `cli` fixture from `conftest.py` provides an initialized `ZKCLI` with a temp KB already registered.

- [ ] **Step 2: Run all tests to verify**

Run: `uv run pytest tests/unit/test_index_kb_param.py -v`
Expected: All tests in `TestIndexKbParamErrors` pass (error on nonexistent KB). Tests in `TestIndexKbParamSuccess` pass (valid KB operations succeed).

**Important:** The `TestIndexKbParamSuccess` tests may need the `cli` fixture with `_initialized=True` so the temp KB is registered in the global config. Check if the `cli` fixture from `conftest.py` already does this — it does: it creates a temp KB path, inits it, and registers it via `ZKCLI.init()`.

- [ ] **Step 3: Commit**

```bash
git add jfox/cli.py tests/unit/test_index_kb_param.py
git commit -m "fix: add --kb parameter to jfox index command (#104)"
```

---

### Task 4: Update ZKCLI index methods to be explicit about `--kb`

**Files:**
- Modify: `tests/utils/jfox_cli.py:297-309`

- [ ] **Step 1: Verify ZKCLI already handles --kb for index**

The `ZKCLI._run()` method at line 94 already adds `--kb` for all commands except `init` and `kb`:
```python
if cmd not in ("init", "kb") and self._initialized:
    if "--kb" not in args and "-k" not in args:
        command.extend(["--kb", self.kb_name])
```

Since `index` is not in `("init", "kb")`, it already receives `--kb` automatically. **No code change needed.** Verify by running an existing test that uses CLI:

Run: `uv run pytest tests/unit/test_index_kb_param.py::TestIndexKbParamSuccess -v`
Expected: PASS — `ZKCLI.index_status()` etc. now work because `index` accepts `--kb`.

- [ ] **Step 2: Commit (if any changes were needed)**

Only commit if changes were actually made to `jfox_cli.py`.

---

### Task 5: Final verification

- [ ] **Step 1: Run the new test file**

Run: `uv run pytest tests/unit/test_index_kb_param.py -v`
Expected: All tests PASS.

- [ ] **Step 2: Run fast unit tests to verify no regressions**

Run: `uv run pytest tests/unit/ -v`
Expected: All existing tests still PASS.

- [ ] **Step 3: Run format and lint**

Run: `uv run ruff check jfox/cli.py tests/unit/test_index_kb_param.py && uv run black --check jfox/cli.py tests/unit/test_index_kb_param.py`
Expected: No errors.

---

## Self-Review

**1. Spec coverage:**
- `jfox index verify --kb <name>` works → Task 2 (implementation) + Task 3 (test)
- `jfox index rebuild --kb <name>` works → Task 2 (implementation) + Task 3 (test)
- `jfox index status --kb <name>` works → Task 2 (implementation) + Task 3 (test)
- `jfox index rebuild-bm25 --kb <name>` works → Task 2 (implementation) + Task 1 (error test)
- `jfox index bm25-status --kb <name>` works → Task 2 (implementation) + Task 1 (error test)
- Error on nonexistent KB → Task 1 (tests)
- Backward compatibility (no `--kb` = same as before) → Task 3 test `test_default_kb_not_affected`

**2. Placeholder scan:** No TBD/TODO found. All steps have complete code.

**3. Type consistency:** `kb: Optional[str]` matches the pattern used in all other commands. `use_kb(kb)` accepts `Optional[str]` and handles `None` as no-op.
