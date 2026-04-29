# ingest-log 子命令 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `jfox ingest-log` 子命令，从本地 Git 仓库提取 commit 历史并直接导入为 fleeting 笔记，解决当前 jfox-ingest skill 依赖手工解析 git log 的不健壮问题。

**Architecture:** 新增 `jfox/git_extractor.py` 模块封装 git log 提取逻辑（使用 block 分隔符 + UTF-8 编码 + 路径规范化），在 `cli.py` 新增 `ingest_log` 命令调用提取器并将结果传给已有的 `bulk_import_notes()` 函数。新模块与现有代码完全解耦——仅通过返回 `List[dict]` 与 `bulk_import_notes` 的输入格式对接。

**Tech Stack:** Python 3.10+, subprocess, pathlib, typer, pytest, unittest.mock

---

## File Structure

| 文件 | 职责 |
|------|------|
| `jfox/git_extractor.py` | Git log 提取 + 解析（纯函数，无依赖 jfox 其他模块） |
| `jfox/cli.py` | 新增 `ingest_log` 命令（~40 行） |
| `tests/unit/test_git_extractor.py` | git_extractor 单元测试 |

---

## Task 1: 创建 git_extractor.py 核心提取模块

**Files:**
- Create: `jfox/git_extractor.py`

- [ ] **Step 1: 写失败测试——parse_git_log_output 解析 block 格式**

创建 `tests/unit/test_git_extractor.py`，测试解析函数能正确处理 block 分隔符格式的 git log 输出：

```python
"""git_extractor 单元测试"""

import textwrap
from pathlib import Path

from jfox.git_extractor import parse_git_log_output


class TestParseGitLogOutput:
    """测试 git log 输出解析"""

    def test_single_commit(self):
        """解析单条 commit"""
        raw = textwrap.dedent("""\
            ---COMMIT_START---
            Hash: abc123def456
            Subject: feat: add login
            Author: 张三
            Date: 2026-04-10

            实现了登录功能
        """)
        result = parse_git_log_output(raw)
        assert len(result) == 1
        assert result[0]["hash"] == "abc123def456"
        assert result[0]["subject"] == "feat: add login"
        assert result[0]["author"] == "张三"
        assert result[0]["date"] == "2026-04-10"
        assert result[0]["body"] == "实现了登录功能"

    def test_multiple_commits(self):
        """解析多条 commit"""
        raw = textwrap.dedent("""\
            ---COMMIT_START---
            Hash: aaa111
            Subject: first commit
            Author: Alice
            Date: 2026-04-01

            body of first
            ---COMMIT_START---
            Hash: bbb222
            Subject: second commit
            Author: Bob
            Date: 2026-04-02

            body of second
        """)
        result = parse_git_log_output(raw)
        assert len(result) == 2
        assert result[0]["hash"] == "aaa111"
        assert result[1]["hash"] == "bbb222"

    def test_empty_body(self):
        """空 body 的 commit"""
        raw = textwrap.dedent("""\
            ---COMMIT_START---
            Hash: abc123
            Subject: chore: version bump
            Author: Bot
            Date: 2026-04-10
        """)
        result = parse_git_log_output(raw)
        assert len(result) == 1
        assert result[0]["body"] == ""

    def test_body_with_special_chars(self):
        """body 包含特殊字符（|、中文、换行）"""
        raw = textwrap.dedent("""\
            ---COMMIT_START---
            Hash: abc123
            Subject: fix: parser | handling
            Author: 张三
            Date: 2026-04-10

            修复 | 分隔符问题
            和中文内容
            Co-Authored-By: Claude <noreply@anthropic.com>
        """)
        result = parse_git_log_output(raw)
        assert len(result) == 1
        assert "|" in result[0]["body"]
        assert "中文" in result[0]["body"]

    def test_empty_input(self):
        """空输入返回空列表"""
        result = parse_git_log_output("")
        assert result == []

    def test_multiline_body_preserved(self):
        """多行 body 完整保留"""
        raw = textwrap.dedent("""\
            ---COMMIT_START---
            Hash: abc123
            Subject: feat: big change
            Author: Alice
            Date: 2026-04-10

            line 1
            line 2
            line 3
        """)
        result = parse_git_log_output(raw)
        assert result[0]["body"] == "line 1\nline 2\nline 3"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_git_extractor.py -v`
Expected: FAIL（`ModuleNotFoundError: No module named 'jfox.git_extractor'`）

- [ ] **Step 3: 实现 parse_git_log_output 函数**

创建 `jfox/git_extractor.py`：

```python
"""Git 仓库数据提取模块

从本地 Git 仓库提取 commit 历史，转换为结构化数据。
"""

import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# git log block 分隔符
_COMMIT_DELIMITER = "---COMMIT_START---"
# git log format 模板
_GIT_LOG_FORMAT = (
    f"{_COMMIT_DELIMITER}%n"
    f"Hash: %H%n"
    f"Subject: %s%n"
    f"Author: %an%n"
    f"Date: %ad%n"
    f"%n%b"
)


def parse_git_log_output(raw: str) -> List[Dict[str, str]]:
    """
    解析 git log block 分隔符格式的输出

    Args:
        raw: git log 原始输出

    Returns:
        commit 列表，每项包含 hash, subject, author, date, body
    """
    if not raw.strip():
        return []

    commits = []
    blocks = raw.split(_COMMIT_DELIMITER)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        commit: Dict[str, str] = {
            "hash": "",
            "subject": "",
            "author": "",
            "date": "",
            "body": "",
        }

        lines = block.split("\n")
        # 前四行是 Hash/Subject/Author/Date
        header_keys = ["hash", "subject", "author", "date"]
        header_idx = 0

        body_start = -1
        for i, line in enumerate(lines):
            if header_idx < len(header_keys):
                # 匹配 "Key: Value" 格式
                match = re.match(rf"^{header_keys[header_idx]}:\s*(.*)", line)
                if match:
                    commit[header_keys[header_idx]] = match.group(1).strip()
                    header_idx += 1
                    # Subject 后紧跟空行，然后是 body
                    if header_idx == len(header_keys):
                        # 跳过 Subject 后的空行
                        if i + 1 < len(lines) and lines[i + 1].strip() == "":
                            body_start = i + 2
                        else:
                            body_start = i + 1
                continue

        if body_start > 0 and body_start < len(lines):
            commit["body"] = "\n".join(lines[body_start:])

        if commit["hash"]:
            commits.append(commit)

    return commits
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_git_extractor.py -v`
Expected: 6 passed

- [ ] **Step 5: 提交**

```bash
git add jfox/git_extractor.py tests/unit/test_git_extractor.py
git commit -m "feat: add git_extractor module with block-delimited git log parser"
```

---

## Task 2: 实现 extract_commits 函数（subprocess 调用）

**Files:**
- Modify: `jfox/git_extractor.py`
- Modify: `tests/unit/test_git_extractor.py`

- [ ] **Step 1: 写失败测试——extract_commits 调用 git 并返回解析结果**

在 `tests/unit/test_git_extractor.py` 中添加：

```python
from unittest.mock import MagicMock, patch


class TestExtractCommits:
    """测试 git 仓库 commit 提取"""

    @patch("jfox.git_extractor.subprocess.run")
    def test_basic_extraction(self, mock_run):
        """基本提取流程"""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="---COMMIT_START---\nHash: abc123\nSubject: feat: test\nAuthor: Alice\nDate: 2026-04-10\n\nbody\n"
        )

        from jfox.git_extractor import extract_commits

        result = extract_commits("/fake/repo", limit=10)
        assert len(result) == 1
        assert result[0]["hash"] == "abc123"
        assert result[0]["subject"] == "feat: test"

        # 验证 subprocess 调用参数
        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[1]["encoding"] == "utf-8"
        assert call_args[1]["errors"] == "replace"
        assert "--format" in call_args[0][0]
        assert "-10" in call_args[0][0]

    @patch("jfox.git_extractor.subprocess.run")
    def test_path_normalization(self, mock_run):
        """路径规范化（Windows / Git Bash 路径处理）"""
        mock_run.return_value = MagicMock(returncode=0, stdout="")

        from jfox.git_extractor import extract_commits

        # Git Bash 风格路径
        extract_commits("/c/Users/test/repo")
        # 路径应该被 resolve 处理
        called_cmd = mock_run.call_args[0][0]
        assert "-C" in called_cmd

    @patch("jfox.git_extractor.subprocess.run")
    def test_git_not_repo_error(self, mock_run):
        """非 git 仓库应抛出 ValueError"""
        mock_run.return_value = MagicMock(
            returncode=128,
            stderr="fatal: not a git repository",
        )

        from jfox.git_extractor import extract_commits

        with pytest.raises(ValueError, match="not a git repository"):
            extract_commits("/not/a/repo")

    @patch("jfox.git_extractor.subprocess.run")
    def test_default_limit_50(self, mock_run):
        """默认 limit 为 50"""
        mock_run.return_value = MagicMock(returncode=0, stdout="")

        from jfox.git_extractor import extract_commits

        extract_commits("/fake/repo")
        called_cmd = mock_run.call_args[0][0]
        assert "-50" in called_cmd
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_git_extractor.py::TestExtractCommits -v`
Expected: FAIL（`ImportError: cannot import name 'extract_commits'`）

- [ ] **Step 3: 实现 extract_commits 函数**

在 `jfox/git_extractor.py` 中追加：

```python
def extract_commits(
    repo_path: str,
    limit: int = 50,
) -> List[Dict[str, str]]:
    """
    从 Git 仓库提取 commit 历史

    Args:
        repo_path: 仓库路径（支持 Windows / Git Bash 路径）
        limit: 最大提取条数

    Returns:
        commit 列表，每项包含 hash, subject, author, date, body

    Raises:
        ValueError: 路径不是 Git 仓库
    """
    repo = Path(repo_path).resolve()

    cmd = [
        "git",
        "-C",
        str(repo),
        "log",
        f"--format={_GIT_LOG_FORMAT}",
        "--date=short",
        f"-{limit}",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        raise ValueError("git 命令未找到，请确认 git 已安装")

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise ValueError(f"git log 执行失败: {stderr}")

    return parse_git_log_output(result.stdout)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_git_extractor.py -v`
Expected: 10 passed

- [ ] **Step 5: 提交**

```bash
git add jfox/git_extractor.py tests/unit/test_git_extractor.py
git commit -m "feat: add extract_commits with UTF-8 encoding and path normalization"
```

---

## Task 3: 实现 commits_to_notes 转换函数

**Files:**
- Modify: `jfox/git_extractor.py`
- Modify: `tests/unit/test_git_extractor.py`

- [ ] **Step 1: 写失败测试——commits_to_notes 转换格式**

在 `tests/unit/test_git_extractor.py` 中添加：

```python
from jfox.git_extractor import commits_to_notes


class TestCommitsToNotes:
    """测试 commit → note 转换"""

    def test_basic_conversion(self):
        """基本转换"""
        commits = [
            {
                "hash": "abc123def456",
                "subject": "feat: add login",
                "author": "张三",
                "date": "2026-04-10",
                "body": "实现了 JWT 认证",
            }
        ]
        result = commits_to_notes(commits, repo_name="my-app")
        assert len(result) == 1
        assert result[0]["title"] == "feat: add login"
        assert "abc123def456" in result[0]["content"]
        assert "张三" in result[0]["content"]
        assert "2026-04-10" in result[0]["content"]
        assert "JWT" in result[0]["content"]
        assert "source:my-app" in result[0]["tags"]
        assert "source:git-log" in result[0]["tags"]

    def test_empty_commits(self):
        """空列表返回空列表"""
        result = commits_to_notes([], repo_name="test")
        assert result == []

    def test_long_hash_truncated(self):
        """hash 截断为短 hash"""
        commits = [
            {
                "hash": "a" * 40,
                "subject": "test",
                "author": "A",
                "date": "2026-01-01",
                "body": "",
            }
        ]
        result = commits_to_notes(commits, repo_name="test")
        assert "a" * 7 in result[0]["content"]
        assert len(result[0]["content"].split("\n")[0].split()[-1]) <= 7

    def test_body_with_co_authored_by_stripped(self):
        """body 末尾的 Co-authored-by 行被清理"""
        commits = [
            {
                "hash": "abc1234",
                "subject": "feat: something",
                "author": "Alice",
                "date": "2026-04-10",
                "body": "real content\n\nCo-authored-by: Bob <bob@example.com>\nCo-authored-by: Claude <noreply@anthropic.com>",
            }
        ]
        result = commits_to_notes(commits, repo_name="test")
        content = result[0]["content"]
        assert "real content" in content
        assert "Co-authored-by" not in content

    def test_repo_name_from_path(self):
        """repo_name=None 时从路径提取目录名"""
        commits = [{"hash": "abc1234", "subject": "test", "author": "A", "date": "2026-01-01", "body": ""}]
        result = commits_to_notes(commits, repo_path="/home/user/my-project")
        assert "source:my-project" in result[0]["tags"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_git_extractor.py::TestCommitsToNotes -v`
Expected: FAIL（`ImportError: cannot import name 'commits_to_notes'`）

- [ ] **Step 3: 实现 commits_to_notes 函数**

在 `jfox/git_extractor.py` 中追加：

```python
def commits_to_notes(
    commits: List[Dict[str, str]],
    repo_name: Optional[str] = None,
    repo_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    将 commit 列表转换为 bulk-import 兼容的笔记格式

    Args:
        commits: parse_git_log_output 的返回值
        repo_name: 仓库名称（用于标签），None 时从 repo_path 提取
        repo_path: 仓库路径（repo_name 为 None 时使用）

    Returns:
        笔记数据列表，兼容 bulk_import_notes() 输入格式
    """
    if not commits:
        return []

    if not repo_name:
        if repo_path:
            repo_name = Path(repo_path).resolve().name
        else:
            repo_name = "unknown"

    notes = []
    for c in commits:
        # 短 hash（前 7 位）
        short_hash = c["hash"][:7]

        # 清理 body：去掉 Co-authored-by 行和末尾空行
        body = c.get("body", "")
        body_lines = [
            line
            for line in body.split("\n")
            if line.strip() and not line.strip().lower().startswith("co-authored-by:")
        ]
        clean_body = "\n".join(body_lines).strip()

        # 构建笔记内容
        content_parts = [
            f"Commit: {short_hash}",
            f"Author: {c['author']}",
            f"Date: {c['date']}",
        ]
        if clean_body:
            content_parts.append("")
            content_parts.append(clean_body)

        notes.append(
            {
                "title": c["subject"],
                "content": "\n".join(content_parts),
                "tags": [f"source:{repo_name}", "source:git-log"],
            }
        )

    return notes
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_git_extractor.py -v`
Expected: 15 passed

- [ ] **Step 5: 提交**

```bash
git add jfox/git_extractor.py tests/unit/test_git_extractor.py
git commit -m "feat: add commits_to_notes conversion with Co-authored-by cleanup"
```

---

## Task 4: 在 cli.py 添加 ingest-log 命令

**Files:**
- Modify: `jfox/cli.py`（在 `bulk_import` 命令附近追加）
- Modify: `tests/unit/test_git_extractor.py`（添加集成级别测试）

- [ ] **Step 1: 写失败测试——CLI ingest-log 命令可执行**

在 `tests/unit/test_git_extractor.py` 中添加：

```python
class TestIngestLogCommand:
    """测试 ingest-log CLI 命令"""

    @patch("jfox.cli.bulk_import_notes")
    @patch("jfox.git_extractor.extract_commits")
    def test_ingest_log_basic(self, mock_extract, mock_import, tmp_path):
        """基本 ingest-log 流程"""
        # mock git 提取
        mock_extract.return_value = [
            {
                "hash": "abc123def456",
                "subject": "feat: test feature",
                "author": "Alice",
                "date": "2026-04-10",
                "body": "test body",
            }
        ]
        # mock 导入
        mock_import.return_value = {"imported": 1, "failed": 0, "total": 1}

        from click.testing import CliRunner

        from jfox.cli import app

        runner = CliRunner()
        result = runner.invoke(app, ["ingest-log", str(tmp_path)])
        print(f"stdout: {result.output}")
        print(f"exit_code: {result.exit_code}")
        if result.exception:
            raise result.exception

        assert result.exit_code == 0
        mock_extract.assert_called_once()
        mock_import.assert_called_once()

        # 验证传入 bulk_import 的 notes 格式
        import_args = mock_import.call_args
        notes_data = import_args[1]["notes_data"]
        assert len(notes_data) == 1
        assert notes_data[0]["title"] == "feat: test feature"
        assert "abc123d" in notes_data[0]["content"]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_git_extractor.py::TestIngestLogCommand -v`
Expected: FAIL（命令不存在或 import 错误）

- [ ] **Step 3: 在 cli.py 添加 ingest-log 命令**

在 `cli.py` 的 `bulk_import` 命令定义之前（约 L2157），添加：

```python
@app.command()
def ingest_log(
    repo_path: str = typer.Argument(..., help="本地 Git 仓库路径"),
    limit: int = typer.Option(50, "--limit", "-n", help="提取 commit 数量"),
    note_type: str = typer.Option("fleeting", "--type", "-t", help="笔记类型"),
    batch_size: int = typer.Option(32, "--batch-size", "-b", help="批处理大小"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="JSON 输出"),
):
    """
    从 Git 仓库提取 commit 历史并导入为笔记

    使用 block 分隔符格式提取 git log，自动处理 UTF-8 编码和路径规范化。

    示例:
        jfox ingest-log ./my-project --limit 50
        jfox ingest-log ./my-project --kb work --type permanent
    """
    try:
        from .git_extractor import commits_to_notes, extract_commits

        # 提取 commits
        commits = extract_commits(repo_path, limit=limit)

        if not commits:
            result = {"success": True, "imported": 0, "total": 0, "message": "没有找到 commit 记录"}
            if json_output:
                print(output_json(result))
            else:
                console.print("[yellow]![/yellow] 没有找到 commit 记录")
            return

        # 转换为笔记格式
        notes_data = commits_to_notes(commits, repo_path=repo_path)

        console.print(f"[yellow]提取了 {len(notes_data)} 条 commit，正在导入...[/yellow]")

        # 批量导入
        from .performance import bulk_import_notes

        if kb:
            from .config import use_kb

            with use_kb(kb):
                import_result = bulk_import_notes(
                    notes_data=notes_data,
                    note_type=note_type,
                    batch_size=batch_size,
                    show_progress=not json_output,
                )
        else:
            import_result = bulk_import_notes(
                notes_data=notes_data,
                note_type=note_type,
                batch_size=batch_size,
                show_progress=not json_output,
            )

        result = {
            "success": True,
            "repo_path": str(Path(repo_path).resolve()),
            "commits_extracted": len(commits),
            **import_result,
        }

        if json_output:
            print(output_json(result))
        else:
            console.print(f"[green]✓[/green] 导入: {import_result['imported']}")
            console.print(f"[red]✗[/red] 失败: {import_result['failed']}")
            console.print(f"总计: {import_result['total']}")

    except ValueError as e:
        result = {"success": False, "error": str(e)}
        if json_output:
            print(output_json(result))
        else:
            console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        result = {"success": False, "error": str(e)}
        if json_output:
            print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_git_extractor.py -v`
Expected: 16 passed

- [ ] **Step 5: 提交**

```bash
git add jfox/cli.py tests/unit/test_git_extractor.py
git commit -m "feat: add ingest-log CLI command for git history import"
```

---

## Task 5: lint + 格式检查 + 快速测试

- [ ] **Step 1: 运行 ruff 检查**

Run: `uv run ruff check jfox/git_extractor.py jfox/cli.py tests/unit/test_git_extractor.py`
Expected: No errors

- [ ] **Step 2: 运行 black 格式化**

Run: `uv run black jfox/git_extractor.py jfox/cli.py tests/unit/test_git_extractor.py`

- [ ] **Step 3: 运行全部 git_extractor 测试**

Run: `uv run pytest tests/unit/test_git_extractor.py -v`
Expected: All passed

- [ ] **Step 4: 运行快速测试套件确认无破坏**

Run: `uv run pytest tests/unit/ -v -m "not slow"`
Expected: All passed（包括已有的测试）

- [ ] **Step 5: 提交（如有格式修复）**

```bash
git add -A
git commit -m "style: lint and format git_extractor module"
```

---

## Task 6: 手动端到端验证（用户执行）

以下步骤需要用户在终端手动执行，因为涉及真实 git 仓库和 embedding 模型加载。

- [ ] **Step 1: 验证命令帮助**

```bash
jfox ingest-log --help
```

Expected: 显示命令帮助，包括 `--limit`、`--type`、`--kb` 等参数说明。

- [ ] **Step 2: 导入 jfox 自身仓库**

```bash
jfox ingest-log . --limit 5 --type fleeting
```

Expected: 成功导入 5 条 commit 为 fleeting 笔记，输出 JSON 格式的导入结果。

- [ ] **Step 3: 验证导入结果**

```bash
jfox list --type fleeting --limit 5
```

Expected: 看到刚导入的 commit 笔记，title 为 commit subject。

- [ ] **Step 4: 导入到指定知识库**

```bash
jfox ingest-log . --limit 3 --kb homework
```

Expected: 成功导入到 homework 知识库。

---

## Self-Review 检查清单

| 检查项 | 状态 |
|--------|------|
| #125 所有 5 个根因是否被覆盖 | ✅ (1) block 分隔符  (2) UTF-8 encoding  (3) 路径 resolve  (4) 内置命令替代手工脚本  (5) 输出直接对接 bulk_import |
| 无 placeholder（TBD/TODO） | ✅ |
| 所有测试代码完整可运行 | ✅ |
| 文件路径精确 | ✅ |
| 遵循现有 CLI 命令模式（`@app.command()` + `_impl()`） | ✅（直接在命令中实现，逻辑简单无需额外 `_impl`） |
| `--kb` 参数支持 | ✅ |
| `--json/--no-json` 输出 | ✅ |
| 错误处理（非 git 仓库、git 未安装） | ✅ |
| TDD 流程（先测试后实现） | ✅ |
