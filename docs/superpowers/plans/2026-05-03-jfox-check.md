# jfox check 命令 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `jfox check` 命令，扫描知识库检测空文件和损坏文件，支持 `--clean` 删除空文件。

**Architecture:** 纯 CLI 层实现。`cli.py` 中新增 `check` 命令 + `_check_impl()` helper。复用 `load_note()` 判断文件是否损坏。单文件改动 + 新测试文件。

**Tech Stack:** Python, Typer, Rich, pytest

---

### Task 1: 写测试 + 实现 check 命令

**Files:**
- Modify: `jfox/cli.py:2702-2717` (在 `main()` 入口前插入新命令)
- Test: `tests/unit/test_check.py` (新建)

- [ ] **Step 1: 写测试**

创建 `tests/unit/test_check.py`：

```python
"""
测试类型: 单元测试
目标模块: jfox.cli (check 命令)
预估耗时: < 1秒
依赖要求: 无外部依赖
"""

import pytest
from typer.testing import CliRunner

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.cli import app

runner = CliRunner()


class TestCheckCommand:
    """jfox check 命令测试"""

    def test_check_clean_kb(self, temp_kb):
        """干净知识库返回无问题"""
        from jfox.config import ZKConfig

        cfg = ZKConfig(base_dir=temp_kb)
        cfg.ensure_dirs()

        # 设置环境变量指向临时知识库
        import os

        os.environ["JFOX_KB"] = str(temp_kb)
        try:
            result = runner.invoke(app, ["check"])
            assert result.exit_code == 0
            assert "No issues found" in result.output or "clean" in result.output.lower()
        finally:
            del os.environ["JFOX_KB"]

    def test_check_detects_empty_file(self, temp_kb):
        """检测空文件"""
        from jfox.config import ZKConfig

        cfg = ZKConfig(base_dir=temp_kb)
        cfg.ensure_dirs()

        # 创建一个空文件
        empty_file = cfg.notes_dir / "permanent" / "empty.md"
        empty_file.write_text("", encoding="utf-8")

        import os

        os.environ["JFOX_KB"] = str(temp_kb)
        try:
            result = runner.invoke(app, ["check"])
            assert result.exit_code == 1
            assert "empty" in result.output.lower()
            assert "empty.md" in result.output
        finally:
            del os.environ["JFOX_KB"]

    def test_check_detects_corrupt_file(self, temp_kb):
        """检测损坏文件（无 frontmatter）"""
        from jfox.config import ZKConfig

        cfg = ZKConfig(base_dir=temp_kb)
        cfg.ensure_dirs()

        # 创建一个损坏文件（无 frontmatter）
        corrupt_file = cfg.notes_dir / "fleeting" / "corrupt.md"
        corrupt_file.write_text("This is not valid markdown for jfox", encoding="utf-8")

        import os

        os.environ["JFOX_KB"] = str(temp_kb)
        try:
            result = runner.invoke(app, ["check"])
            assert result.exit_code == 1
            assert "corrupt" in result.output.lower()
            assert "corrupt.md" in result.output
        finally:
            del os.environ["JFOX_KB"]

    def test_check_json_output(self, temp_kb):
        """JSON 格式输出"""
        from jfox.config import ZKConfig

        cfg = ZKConfig(base_dir=temp_kb)
        cfg.ensure_dirs()

        empty_file = cfg.notes_dir / "permanent" / "empty.md"
        empty_file.write_text("", encoding="utf-8")

        import json
        import os

        os.environ["JFOX_KB"] = str(temp_kb)
        try:
            result = runner.invoke(app, ["check", "--format", "json"])
            assert result.exit_code == 1
            data = json.loads(result.output)
            assert data["total"] == 1
            assert data["issues"][0]["issue"] == "empty"
            assert data["issues"][0]["size"] == 0
        finally:
            del os.environ["JFOX_KB"]

    def test_check_clean_deletes_empty(self, temp_kb):
        """--clean 删除空文件"""
        from jfox.config import ZKConfig

        cfg = ZKConfig(base_dir=temp_kb)
        cfg.ensure_dirs()

        empty_file = cfg.notes_dir / "permanent" / "empty.md"
        empty_file.write_text("", encoding="utf-8")

        import os

        os.environ["JFOX_KB"] = str(temp_kb)
        try:
            result = runner.invoke(app, ["check", "--clean"], input="y\n")
            assert "Deleted" in result.output or "deleted" in result.output.lower()
            assert not empty_file.exists()
        finally:
            del os.environ["JFOX_KB"]

    def test_check_clean_keeps_corrupt(self, temp_kb):
        """--clean 不删除损坏但非空的文件"""
        from jfox.config import ZKConfig

        cfg = ZKConfig(base_dir=temp_kb)
        cfg.ensure_dirs()

        corrupt_file = cfg.notes_dir / "fleeting" / "corrupt.md"
        corrupt_file.write_text("Some content without frontmatter", encoding="utf-8")

        import os

        os.environ["JFOX_KB"] = str(temp_kb)
        try:
            result = runner.invoke(app, ["check", "--clean"])
            # corrupt 文件不应被删除（即使加了 --clean）
            assert corrupt_file.exists()
            assert "corrupt" in result.output.lower()
        finally:
            del os.environ["JFOX_KB"]
```

- [ ] **Step 2: 运行测试验证失败**

Run: `uv run pytest tests/unit/test_check.py -v`
Expected: FAIL — `check` 命令尚未存在，Typer 报错

- [ ] **Step 3: 实现 check 命令**

在 `jfox/cli.py` 的 `# 入口点` 注释（第 2703 行）之前插入以下代码：

```python
# =============================================================================
# 知识库健康检查
# =============================================================================


def _check_impl(clean: bool = False, output_format: str = "table"):
    """check 命令的内部实现"""
    from .config import config
    from .models import NoteType
    from .note import load_note

    issues = []

    for note_type in NoteType:
        dir_path = config.notes_dir / note_type.value
        if not dir_path.exists():
            continue

        for filepath in sorted(dir_path.glob("*.md")):
            file_size = filepath.stat().st_size
            if file_size == 0:
                issues.append({
                    "file": filepath.relative_to(config.base_dir),
                    "issue": "empty",
                    "size": 0,
                })
            elif load_note(filepath) is None:
                issues.append({
                    "file": filepath.relative_to(config.base_dir),
                    "issue": "corrupt",
                    "size": file_size,
                })

    # --clean: 删除空文件
    if clean:
        empty_files = [i for i in issues if i["issue"] == "empty"]
        if empty_files:
            count = len(empty_files)
            confirm = typer.confirm(f"Delete {count} empty file(s)?")
            if confirm:
                for issue in empty_files:
                    full_path = config.base_dir / issue["file"]
                    full_path.unlink()
                console.print(f"Deleted {count} empty file(s).")
                # 从 issues 中移除已删除的空文件
                issues = [i for i in issues if i["issue"] != "empty"]

    # 输出结果
    if output_format == "json":
        print(output_json({"total": len(issues), "issues": issues}))
    else:
        if not issues:
            console.print("No issues found. Knowledge base is clean.")
        else:
            console.print(f"\n Found {len(issues)} issue(s) in knowledge base\n")
            table = Table()
            table.add_column("File", style="cyan")
            table.add_column("Issue", style="yellow")
            table.add_column("Size", style="dim")

            for issue in issues:
                size_str = "0 B" if issue["size"] == 0 else f"{issue['size']} B"
                table.add_row(str(issue["file"]), issue["issue"], size_str)

            console.print(table)

    if issues:
        raise typer.Exit(1)


@app.command()
def check(
    clean: bool = typer.Option(False, "--clean", help="删除空文件（需确认）"),
    output_format: str = typer.Option(
        "table", "--format", "-f", help="输出格式: json, table"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"
    ),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
):
    """检查知识库中的空文件和损坏文件"""
    try:
        if json_output:
            output_format = "json"

        from .config import use_kb

        with use_kb(kb):
            _check_impl(clean=clean, output_format=output_format)

    except typer.Exit:
        raise
    except Exception as e:
        if json_output:
            print(output_json({"success": False, "error": str(e)}))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)
```

注意：`output_json` 是 `cli.py` 中已有的 JSON 序列化函数（第 46 行附近定义）。`config`、`NoteType`、`load_note` 在函数内部 import，遵循 cli.py 的延迟 import 惯例。

- [ ] **Step 4: 运行测试验证通过**

Run: `uv run pytest tests/unit/test_check.py -v`
Expected: 6 tests PASS

- [ ] **Step 5: 运行 lint**

Run: `uv run ruff check jfox/cli.py && uv run black --check jfox/cli.py`
Expected: 无错误。如有格式问题，运行 `uv run black jfox/cli.py` 修复后重新验证。

- [ ] **Step 6: 提交**

```bash
git add jfox/cli.py tests/unit/test_check.py
git commit -m "feat(cli): add jfox check command for detecting corrupt files (#189)"
```
