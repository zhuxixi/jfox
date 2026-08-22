# Todo 便签笔记类型 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `todo` 笔记类型，提供 `jfox todo` 命令族，支持 open/done 状态管理和批量 review。

**Architecture:** 最小侵入式扩展现有 NoteType 枚举和 Note 模型，新增 `status` 可选字段（遵循 `source`/`topic` 的 type-specific 字段模式）。CLI 使用 Typer sub-app 模式，Agent 优先（默认非交互， `--interactive` 可选）。todo 笔记自动融入 search、graph、backlinks 等现有功能。

**Tech Stack:** Python 3.10+, Typer, Rich, pytest, unittest.mock

---

## File Structure

| 文件 | 职责 | 操作 |
|------|------|------|
| `jfox/models.py` | NoteType 枚举、Note 数据模型、序列化/反序列化 | Modify |
| `jfox/config.py` | KB 目录初始化 | Modify |
| `jfox/note.py` | 笔记 CRUD、统计 | Modify |
| `jfox/cli.py` | CLI 入口、type 校验文案 | Modify |
| `jfox/todo_cli.py` | `jfox todo` 子命令族（新增文件） | Create |
| `tests/unit/test_todo_crud.py` | models + note CRUD 测试 | Create |
| `tests/unit/test_todo_cli.py` | todo CLI 命令测试 | Create |
| `tests/unit/test_todo_review.py` | review 命令测试 | Create |
| `tests/unit/test_todo_integration.py` | search/graph 集成测试 | Create |

---

### Task 1: 扩展 NoteType 枚举和 Note 模型

**Files:**

- Modify: `jfox/models.py`
- Test: `tests/unit/test_todo_crud.py`

- [ ] **Step 1: 写 failing test — todo enum 和 status 字段**

```python
"""
测试类型: 单元测试
目标模块: jfox.models (todo note type)
预估耗时: < 1秒
依赖要求: 无外部依赖
"""

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from datetime import datetime

from jfox.models import Note, NoteType


class TestTodoNoteType:
    """Test todo note type support"""

    def test_todo_enum_value(self):
        assert NoteType.TODO.value == "todo"

    def test_todo_note_creation_with_status(self):
        n = Note(
            id="202605221430001234",
            title="跟进客户反馈",
            content="客户提出了三个问题",
            type=NoteType.TODO,
            status="open",
            created=datetime(2026, 5, 22, 14, 30, 0),
            updated=datetime(2026, 5, 22, 14, 30, 0),
            tags=["工作"],
        )
        assert n.status == "open"
        assert n.type == NoteType.TODO

    def test_todo_note_defaults_to_none_status(self):
        n = Note(
            id="202605221430001234",
            title="Test",
            content="content",
            type=NoteType.PERMANENT,
            created=datetime(2026, 5, 22, 14, 30, 0),
            updated=datetime(2026, 5, 22, 14, 30, 0),
        )
        assert n.status is None

    def test_todo_filename_uses_slug(self):
        n = Note(
            id="202605221430001234",
            title="跟进客户反馈",
            content="content",
            type=NoteType.TODO,
            created=datetime(2026, 5, 22, 14, 30, 0),
            updated=datetime(2026, 5, 22, 14, 30, 0),
        )
        assert n.filename == "202605221430001234-跟进客户反馈.md"

    def test_todo_status_persisted_to_frontmatter(self):
        n = Note(
            id="202605221430001234",
            title="跟进客户反馈",
            content="content",
            type=NoteType.TODO,
            status="open",
            created=datetime(2026, 5, 22, 14, 30, 0),
            updated=datetime(2026, 5, 22, 14, 30, 0),
        )
        md = n.to_markdown()
        assert 'status: "open"' in md
        assert "type: todo" in md

    def test_todo_status_absent_when_none(self):
        n = Note(
            id="202605221430001234",
            title="跟进客户反馈",
            content="content",
            type=NoteType.TODO,
            status=None,
            created=datetime(2026, 5, 22, 14, 30, 0),
            updated=datetime(2026, 5, 22, 14, 30, 0),
        )
        md = n.to_markdown()
        assert "status:" not in md

    def test_todo_roundtrip_from_markdown(self):
        n = Note(
            id="202605221430001234",
            title="跟进客户反馈",
            content="客户提出了三个问题",
            type=NoteType.TODO,
            status="done",
            tags=["工作", "客户"],
            created=datetime(2026, 5, 22, 14, 30, 0),
            updated=datetime(2026, 5, 22, 14, 30, 0),
        )
        md = n.to_markdown()
        loaded = Note.from_markdown(md, n.filepath)
        assert loaded.status == "done"
        assert loaded.type == NoteType.TODO
        assert loaded.title == "跟进客户反馈"

    def test_todo_to_dict_includes_status(self):
        n = Note(
            id="202605221430001234",
            title="跟进客户反馈",
            content="content",
            type=NoteType.TODO,
            status="open",
            created=datetime(2026, 5, 22, 14, 30, 0),
            updated=datetime(2026, 5, 22, 14, 30, 0),
        )
        d = n.to_dict()
        assert d["status"] == "open"
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_todo_crud.py -v`
Expected: FAIL (NoteType.TODO 不存在，Note 无 status 字段)

- [ ] **Step 3: 实现 NoteType 和 Note 模型扩展**

修改 `jfox/models.py`：

1. 在 `NoteType` 枚举中新增 `TODO = "todo"`（line 19 后）

```python
class NoteType(Enum):
    """笔记类型"""

    FLEETING = "fleeting"
    LITERATURE = "literature"
    PERMANENT = "permanent"
    SESSION = "session"
    TODO = "todo"  # 新增: 便签待办
```

1. 在 `Note` dataclass 中新增 `status` 字段（line 36 后，backlinks 之前）

```python
    source: Optional[str] = None  # 来源（文献笔记）
    topic: Optional[str] = None  # 会话主题（session 类型）
    status: Optional[str] = None  # 状态（todo 类型: open | done）
```

1. 修改 `to_markdown()`（line 86-89 后），在 `topic` 处理之后添加：

```python
        if self.status:
            frontmatter["status"] = self.status
```

1. 修改 `from_markdown()`（line 137-138 后），在 `topic` 参数之后添加：

```python
            source=fm.get("source"),
            topic=fm.get("topic"),
            status=fm.get("status"),
        )
```

1. 修改 `to_dict()`（line 155 后），在 `topic` 之后添加：

```python
            "topic": self.topic,
            "status": self.status,
        }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_todo_crud.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/models.py tests/unit/test_todo_crud.py
git commit -m "feat(models): add TODO note type with status field

- Add NoteType.TODO enum value
- Add Note.status field for open/done state
- Serialize status to frontmatter for todo notes
- Deserialize status from frontmatter on load

Refs #230"
```

---

### Task 2: 更新配置层（config.py + note.py）

**Files:**

- Modify: `jfox/config.py`
- Modify: `jfox/note.py`
- Test: `tests/unit/test_todo_crud.py`（追加测试）

- [ ] **Step 1: 写 failing test — todo 目录创建和 CRUD**

在 `tests/unit/test_todo_crud.py` 中追加：

```python
from unittest.mock import patch

from jfox.config import ZKConfig
from jfox.note import create_note, load_note_by_id, save_note, get_stats


class TestTodoCrud:
    """Test todo note CRUD operations"""

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_create_todo_note_defaults(self, mock_global_config, mock_note_config, tmp_path):
        """创建 todo 笔记时 status 默认为 open"""
        cfg = ZKConfig(base_dir=tmp_path)
        cfg.ensure_dirs()
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        n = create_note("跟进客户反馈", note_type=NoteType.TODO, tags=["工作"])
        assert n.type == NoteType.TODO
        assert n.status == "open"  # 默认值
        assert n.title == "跟进客户反馈"

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_todo_directory_created(self, mock_global_config, mock_note_config, tmp_path):
        """KB 初始化时创建 todo 目录"""
        cfg = ZKConfig(base_dir=tmp_path)
        cfg.ensure_dirs()
        assert (tmp_path / "notes" / "todo").exists()

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_save_and_load_todo_note(self, mock_global_config, mock_note_config, tmp_path):
        """保存并加载 todo 笔记"""
        cfg = ZKConfig(base_dir=tmp_path)
        cfg.ensure_dirs()
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        n = create_note("跟进客户反馈", note_type=NoteType.TODO, tags=["工作"])
        save_note(n, add_to_index=False)

        loaded = load_note_by_id(n.id, cfg=cfg)
        assert loaded is not None
        assert loaded.type == NoteType.TODO
        assert loaded.status == "open"
        assert loaded.title == "跟进客户反馈"

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_get_stats_includes_todo(self, mock_global_config, mock_note_config, tmp_path):
        """统计包含 todo 类型"""
        cfg = ZKConfig(base_dir=tmp_path)
        cfg.ensure_dirs()
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        n = create_note("跟进客户反馈", note_type=NoteType.TODO)
        save_note(n, add_to_index=False)

        stats = get_stats(cfg=cfg)
        assert "todo" in stats["by_type"]
        assert stats["by_type"]["todo"] == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_todo_crud.py::TestTodoCrud -v`
Expected: FAIL (config.ensure_dirs 不创建 todo 目录，create_note 不设置 status)

- [ ] **Step 3: 实现配置层改动**

修改 `jfox/config.py` line 63，在 `session` 目录后添加 `todo`：

```python
        dirs = [
            self.notes_dir / "fleeting",
            self.notes_dir / "literature",
            self.notes_dir / "permanent",
            self.notes_dir / "session",
            self.notes_dir / "todo",  # 新增
            self.zk_dir,
            self.chroma_dir,
            self.zk_dir / "cache",
        ]
```

修改 `jfox/note.py` line 32-63，在 `create_note()` 中设置 todo 默认 status：

```python
def create_note(
    content: str,
    title: Optional[str] = None,
    note_type: NoteType = NoteType.FLEETING,
    tags: Optional[List[str]] = None,
    links: Optional[List[str]] = None,
    source: Optional[str] = None,
    topic: Optional[str] = None,
    status: Optional[str] = None,
) -> Note:
    """创建新笔记"""
    note_id = generate_id()
    now = datetime.now()

    # 如果没有标题，从内容提取
    if title is None:
        title = content[:50] + "..." if len(content) > 50 else content

    # todo 类型默认 status 为 open
    if note_type == NoteType.TODO and status is None:
        status = "open"

    note = Note(
        id=note_id,
        title=title,
        content=content,
        type=note_type,
        created=now,
        updated=now,
        tags=tags or [],
        links=links or [],
        backlinks=[],
        source=source,
        topic=topic,
        status=status,
    )

    return note
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_todo_crud.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/config.py jfox/note.py tests/unit/test_todo_crud.py
git commit -m "feat(config,note): support todo note type in storage layer

- ZKConfig.ensure_dirs() creates notes/todo/ directory
- create_note() defaults status='open' for todo type
- get_stats() auto-counts todo via NoteType iteration

Refs #230"
```

---

### Task 3: 更新 CLI type 校验文案

**Files:**

- Modify: `jfox/cli.py`

- [ ] **Step 1: 修改 _add_note_impl 的校验文案**

`jfox/cli.py` line 342：

```python
        raise ValueError(
            f"Invalid note type: {note_type}. Use: fleeting, literature, permanent, session, todo"
        )
```

- [ ] **Step 2: 修改 _list_impl 的校验文案**

`jfox/cli.py` line 802：

```python
            raise ValueError(
                f"Invalid note type: {note_type}. Use: fleeting, literature, permanent, session, todo"
            )
```

- [ ] **Step 3: Commit**

```bash
git add jfox/cli.py
git commit -m "chore(cli): update type validation messages to include todo

Refs #230"
```

---

### Task 4: 创建 todo_cli.py — add / list 命令

**Files:**

- Create: `jfox/todo_cli.py`
- Modify: `jfox/cli.py`（注册 sub-app）
- Test: `tests/unit/test_todo_cli.py`

- [ ] **Step 1: 写 failing test — todo add / list CLI**

```python
"""
测试类型: 单元测试
目标模块: jfox.todo_cli
预估耗时: < 1秒
依赖要求: 无外部依赖，使用 mock
"""

import json
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]
from datetime import datetime
from pathlib import Path
from unittest.mock import MagicMock, patch

from jfox.models import Note, NoteType

PATCH_USE_KB = "jfox.todo_cli.use_kb"
PATCH_NOTE_MODULE = "jfox.todo_cli.note"


class TestTodoAdd:
    """测试 todo add 命令"""

    @patch(PATCH_USE_KB)
    @patch(PATCH_NOTE_MODULE)
    def test_add_todo_basic(self, mock_note, mock_use_kb):
        """快速添加 todo"""
        from jfox.todo_cli import _todo_add_impl

        mock_note.create_note.return_value = Note(
            id="202605221430001234",
            title="跟进客户反馈",
            content="",
            type=NoteType.TODO,
            status="open",
            created=datetime.now(),
            updated=datetime.now(),
        )
        mock_note.save_note.return_value = True

        result = _todo_add_impl(title="跟进客户反馈", content="", tags=None, links=None)

        mock_note.create_note.assert_called_once()
        call_kwargs = mock_note.create_note.call_args.kwargs
        assert call_kwargs["note_type"] == NoteType.TODO
        assert call_kwargs["title"] == "跟进客户反馈"
        mock_note.save_note.assert_called_once()
        assert result["success"] is True

    @patch(PATCH_USE_KB)
    @patch(PATCH_NOTE_MODULE)
    def test_add_todo_with_content(self, mock_note, mock_use_kb):
        """添加带内容的 todo"""
        from jfox.todo_cli import _todo_add_impl

        mock_note.create_note.return_value = Note(
            id="202605221430001234",
            title="跟进客户反馈",
            content="客户提出了三个问题",
            type=NoteType.TODO,
            status="open",
            created=datetime.now(),
            updated=datetime.now(),
        )
        mock_note.save_note.return_value = True

        result = _todo_add_impl(
            title="跟进客户反馈", content="客户提出了三个问题", tags=["工作"], links=None
        )

        call_kwargs = mock_note.create_note.call_args.kwargs
        assert call_kwargs["content"] == "客户提出了三个问题"
        assert call_kwargs["tags"] == ["工作"]


class TestTodoList:
    """测试 todo list 命令"""

    @patch(PATCH_USE_KB)
    @patch(PATCH_NOTE_MODULE)
    def test_list_defaults_to_open_only(self, mock_note, mock_use_kb):
        """默认只列出 open 状态的 todo"""
        from jfox.todo_cli import _todo_list_impl

        open_todo = Note(
            id="202605221430001234",
            title="Open task",
            content="",
            type=NoteType.TODO,
            status="open",
            created=datetime.now(),
            updated=datetime.now(),
        )
        done_todo = Note(
            id="202605221430005678",
            title="Done task",
            content="",
            type=NoteType.TODO,
            status="done",
            created=datetime.now(),
            updated=datetime.now(),
        )
        mock_note.list_notes.return_value = [open_todo]

        result = _todo_list_impl(show_all=False, tags=None, output_format="json")

        # 验证 list_notes 被调用时传入了 status 过滤
        call_kwargs = mock_note.list_notes.call_args.kwargs
        assert call_kwargs["note_type"] == NoteType.TODO
        assert result["total"] == 1
        assert result["notes"][0]["title"] == "Open task"

    @patch(PATCH_USE_KB)
    @patch(PATCH_NOTE_MODULE)
    def test_list_all_shows_done(self, mock_note, mock_use_kb):
        """--all 列出所有 todo"""
        from jfox.todo_cli import _todo_list_impl

        open_todo = Note(
            id="202605221430001234",
            title="Open task",
            content="",
            type=NoteType.TODO,
            status="open",
            created=datetime.now(),
            updated=datetime.now(),
        )
        done_todo = Note(
            id="202605221430005678",
            title="Done task",
            content="",
            type=NoteType.TODO,
            status="done",
            created=datetime.now(),
            updated=datetime.now(),
        )
        mock_note.list_notes.return_value = [open_todo, done_todo]

        result = _todo_list_impl(show_all=True, tags=None, output_format="json")

        assert result["total"] == 2
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_todo_cli.py -v`
Expected: FAIL (todo_cli.py 不存在)

- [ ] **Step 3: 创建 todo_cli.py**

创建 `jfox/todo_cli.py`：

```python
"""Todo 便签笔记 CLI 子命令"""

import logging
from datetime import datetime
from typing import List, Optional

import typer
from rich.console import Console
from rich.table import Table

from . import note
from .config import config, use_kb
from .models import Note, NoteType
from .cli import find_note_id_by_title_or_id, output_json

logger = logging.getLogger(__name__)
console = Console(legacy_windows=False)

# 创建 todo 子应用
todo_app = typer.Typer(name="todo", help="待办便签管理")


def _todo_add_impl(
    title: str,
    content: str,
    tags: Optional[List[str]],
    links: Optional[List[str]],
) -> dict:
    """添加 todo 的内部实现"""
    # 解析链接
    resolved_links = []
    unresolved = []
    if links:
        for link_text in links:
            target_id = find_note_id_by_title_or_id(link_text)
            if target_id:
                resolved_links.append(target_id)
            else:
                unresolved.append(link_text)

    # 创建 todo 笔记
    new_note = note.create_note(
        content=content,
        title=title,
        note_type=NoteType.TODO,
        tags=tags or [],
        links=resolved_links,
    )

    # 保存
    if note.save_note(new_note):
        # 更新反向链接
        for target_id in resolved_links:
            target_note = note.load_note_by_id(target_id)
            if target_note and new_note.id not in target_note.backlinks:
                target_note.backlinks.append(new_note.id)
                note.save_note(target_note, add_to_index=False)

        result = {
            "success": True,
            "note": {
                "id": new_note.id,
                "title": new_note.title,
                "type": "todo",
                "status": new_note.status,
                "filepath": str(new_note.filepath),
            },
        }
        if unresolved:
            result["warnings"] = f"Unresolved links: {', '.join(unresolved)}"
        return result
    else:
        return {"success": False, "error": "Failed to save note"}


def _todo_list_impl(
    show_all: bool,
    tags: Optional[List[str]],
    output_format: str,
) -> dict:
    """列出 todo 的内部实现"""
    from .formatters import OutputFormatter

    # 获取所有 todo 笔记
    todos = note.list_notes(note_type=NoteType.TODO, tags=tags)

    # 默认只显示 open 状态
    if not show_all:
        todos = [t for t in todos if t.status == "open"]

    data = []
    for t in todos:
        d = t.to_dict()
        d["status"] = t.status  # 确保 status 在输出中
        data.append(d)

    result = {
        "total": len(todos),
        "notes": data,
    }

    if output_format == "json":
        print(OutputFormatter.to_json(result))
    elif output_format == "table":
        table = Table(title=f"Todos ({len(todos)} total)")
        table.add_column("ID", style="dim")
        table.add_column("Title", style="cyan")
        table.add_column("Status", style="green")
        table.add_column("Tags", style="yellow")
        table.add_column("Created", style="dim")

        for t in todos:
            status_style = "green" if t.status == "open" else "dim"
            created_str = t.created.strftime("%Y-%m-%d") if t.created else ""
            table.add_row(
                t.id,
                t.title[:40],
                f"[{status_style}]{t.status}[/{status_style}]",
                ", ".join(t.tags) if t.tags else "",
                created_str,
            )
        console.print(table)
    elif output_format == "csv":
        console.print(
            OutputFormatter.to_csv(
                data, headers=["id", "title", "status", "tags", "created"]
            )
        )
    elif output_format == "yaml":
        print(OutputFormatter.to_yaml(result))
    elif output_format == "paths":
        paths = [{"filepath": str(t.filepath)} for t in todos]
        console.print(OutputFormatter.to_paths(paths, key="filepath"))
    else:
        raise ValueError(f"Unsupported format: {output_format}")

    return result


@todo_app.command()
def add(
    title: str = typer.Argument(..., help="待办标题"),
    content: str = typer.Option("", "--content", "-c", help="待办内容/备注"),
    tags: Optional[List[str]] = typer.Option(None, "--tag", "-t", help="标签（可多次使用）"),
    links: Optional[List[str]] = typer.Option(None, "--link", "-l", help="链接到已有笔记（[[标题]] 或 ID）"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(False, "--json", help="JSON 输出"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
):
    """添加待办便签"""
    try:
        if json_output:
            output_format = "json"

        with use_kb(kb):
            result = _todo_add_impl(title, content, tags, links)

        if output_format == "json":
            print(output_json(result))
        else:
            if result.get("success"):
                console.print(f"[green]✓[/green] Todo created: {result['note']['title']}")
                console.print(f"[dim]  ID: {result['note']['id']}[/dim]")
                if result.get("warnings"):
                    console.print(f"[yellow]⚠ {result['warnings']}[/yellow]")
            else:
                console.print(f"[red]✗[/red] {result.get('error', 'Unknown error')}")
                raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@todo_app.command()
def list(
    show_all: bool = typer.Option(False, "--all", "-a", help="显示所有 todo（包括已完成）"),
    tags: Optional[List[str]] = typer.Option(None, "--tag", "-t", help="按标签筛选"),
    output_format: str = typer.Option(
        "table", "--format", "-f", help="输出格式: json, table, csv, yaml, paths"
    ),
    json_output: bool = typer.Option(False, "--json", help="JSON 输出"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
):
    """列出待办便签（默认只显示未完成的）"""
    try:
        if json_output:
            output_format = "json"

        with use_kb(kb):
            _todo_list_impl(show_all, tags, output_format)
    except Exception as e:
        if output_format == "json":
            print(output_json({"success": False, "error": str(e)}))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)
```

- [ ] **Step 4: 在 cli.py 注册 todo_app**

在 `jfox/cli.py` 中，找到 `app.add_typer(auto_summary_app, name="auto-summary")` 后添加：

```python
# Todo 子命令组
from .todo_cli import todo_app  # noqa: E402

app.add_typer(todo_app, name="todo")
```

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_todo_cli.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add jfox/todo_cli.py jfox/cli.py tests/unit/test_todo_cli.py
git commit -m "feat(todo): add todo add and list commands

- jfox/todo_cli.py: new sub-app with add/list commands
- Agent-friendly: list defaults to open-only, --all for all
- Supports --content, --tag, --link options on add
- Supports json/table/csv/yaml/paths output formats

Refs #230"
```

---

### Task 5: 创建 done / open / delete 命令

**Files:**

- Modify: `jfox/todo_cli.py`
- Test: `tests/unit/test_todo_cli.py`（追加测试）

- [ ] **Step 1: 写 failing test — done / open / delete**

在 `tests/unit/test_todo_cli.py` 中追加：

```python
class TestTodoStatus:
    """测试 done / open / delete 命令"""

    @patch(PATCH_USE_KB)
    @patch(PATCH_NOTE_MODULE)
    def test_done_todo(self, mock_note, mock_use_kb):
        """标记 todo 为完成"""
        from jfox.todo_cli import _todo_done_impl

        mock_todo = Note(
            id="202605221430001234",
            title="跟进客户反馈",
            content="",
            type=NoteType.TODO,
            status="open",
            created=datetime.now(),
            updated=datetime.now(),
        )
        mock_note.load_note_by_id.return_value = mock_todo
        mock_note.update_note.return_value = True

        result = _todo_done_impl("跟进客户反馈")

        assert result["success"] is True
        assert mock_todo.status == "done"
        mock_note.update_note.assert_called_once()

    @patch(PATCH_USE_KB)
    @patch(PATCH_NOTE_MODULE)
    def test_done_already_done_warns(self, mock_note, mock_use_kb):
        """done 一个已经是 done 的 todo 发出警告"""
        from jfox.todo_cli import _todo_done_impl

        mock_todo = Note(
            id="202605221430001234",
            title="跟进客户反馈",
            content="",
            type=NoteType.TODO,
            status="done",
            created=datetime.now(),
            updated=datetime.now(),
        )
        mock_note.load_note_by_id.return_value = mock_todo

        result = _todo_done_impl("跟进客户反馈")

        assert result["success"] is True
        assert "already" in result.get("message", "").lower()

    @patch(PATCH_USE_KB)
    @patch(PATCH_NOTE_MODULE)
    def test_open_todo(self, mock_note, mock_use_kb):
        """重新打开 todo"""
        from jfox.todo_cli import _todo_open_impl

        mock_todo = Note(
            id="202605221430001234",
            title="跟进客户反馈",
            content="",
            type=NoteType.TODO,
            status="done",
            created=datetime.now(),
            updated=datetime.now(),
        )
        mock_note.load_note_by_id.return_value = mock_todo
        mock_note.update_note.return_value = True

        result = _todo_open_impl("跟进客户反馈")

        assert result["success"] is True
        assert mock_todo.status == "open"

    @patch(PATCH_USE_KB)
    @patch(PATCH_NOTE_MODULE)
    def test_delete_todo(self, mock_note, mock_use_kb):
        """删除 todo"""
        from jfox.todo_cli import _todo_delete_impl

        mock_todo = Note(
            id="202605221430001234",
            title="跟进客户反馈",
            content="",
            type=NoteType.TODO,
            status="open",
            created=datetime.now(),
            updated=datetime.now(),
        )
        mock_note.load_note_by_id.return_value = mock_todo
        mock_note.delete_note.return_value = True

        result = _todo_delete_impl("跟进客户反馈")

        assert result["success"] is True
        mock_note.delete_note.assert_called_once_with("202605221430001234")

    @patch(PATCH_USE_KB)
    @patch(PATCH_NOTE_MODULE)
    def test_not_found_returns_error(self, mock_note, mock_use_kb):
        """找不到 todo 返回错误"""
        from jfox.todo_cli import _todo_done_impl

        mock_note.load_note_by_id.return_value = None

        result = _todo_done_impl("不存在的待办")

        assert result["success"] is False
        assert "not found" in result["error"].lower()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_todo_cli.py::TestTodoStatus -v`
Expected: FAIL (_todo_done_impl 等不存在)

- [ ] **Step 3: 实现 done / open / delete 命令**

在 `jfox/todo_cli.py` 中，在 `_todo_list_impl` 函数后追加：

```python
def _todo_done_impl(note_ref: str) -> dict:
    """标记 todo 为完成的内部实现"""
    note_id = find_note_id_by_title_or_id(note_ref)
    if not note_id:
        return {"success": False, "error": f"Todo not found: {note_ref}"}

    target = note.load_note_by_id(note_id)
    if not target:
        return {"success": False, "error": f"Todo not found: {note_ref}"}

    if target.status == "done":
        return {"success": True, "message": "Todo is already done", "note": target.to_dict()}

    target.status = "done"
    target.updated = datetime.now()
    if note.update_note(target, add_to_index=False):
        return {"success": True, "note": target.to_dict()}
    else:
        return {"success": False, "error": "Failed to update todo"}


def _todo_open_impl(note_ref: str) -> dict:
    """重新打开 todo 的内部实现"""
    note_id = find_note_id_by_title_or_id(note_ref)
    if not note_id:
        return {"success": False, "error": f"Todo not found: {note_ref}"}

    target = note.load_note_by_id(note_id)
    if not target:
        return {"success": False, "error": f"Todo not found: {note_ref}"}

    if target.status == "open":
        return {"success": True, "message": "Todo is already open", "note": target.to_dict()}

    target.status = "open"
    target.updated = datetime.now()
    if note.update_note(target, add_to_index=False):
        return {"success": True, "note": target.to_dict()}
    else:
        return {"success": False, "error": "Failed to update todo"}


def _todo_delete_impl(note_ref: str) -> dict:
    """删除 todo 的内部实现"""
    note_id = find_note_id_by_title_or_id(note_ref)
    if not note_id:
        return {"success": False, "error": f"Todo not found: {note_ref}"}

    target = note.load_note_by_id(note_id)
    if not target:
        return {"success": False, "error": f"Todo not found: {note_ref}"}

    if note.delete_note(note_id):
        return {"success": True, "note": {"id": note_id, "title": target.title}}
    else:
        return {"success": False, "error": "Failed to delete todo"}
```

然后在文件末尾追加 CLI 命令装饰器：

```python
@todo_app.command()
def done(
    note_ref: str = typer.Argument(..., help="待办 ID 或标题"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
):
    """标记待办为已完成"""
    try:
        with use_kb(kb):
            result = _todo_done_impl(note_ref)

        if result["success"]:
            msg = result.get("message", "Todo marked as done")
            console.print(f"[green]✓[/green] {msg}: {result['note']['title']}")
        else:
            console.print(f"[red]✗[/red] {result['error']}")
            raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@todo_app.command()
def open(
    note_ref: str = typer.Argument(..., help="待办 ID 或标题"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
):
    """重新打开已完成的待办"""
    try:
        with use_kb(kb):
            result = _todo_open_impl(note_ref)

        if result["success"]:
            msg = result.get("message", "Todo reopened")
            console.print(f"[green]✓[/green] {msg}: {result['note']['title']}")
        else:
            console.print(f"[red]✗[/red] {result['error']}")
            raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@todo_app.command()
def delete(
    note_ref: str = typer.Argument(..., help="待办 ID 或标题"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
):
    """删除待办便签"""
    try:
        with use_kb(kb):
            result = _todo_delete_impl(note_ref)

        if result["success"]:
            console.print(f"[green]✓[/green] Deleted: {result['note']['title']}")
        else:
            console.print(f"[red]✗[/red] {result['error']}")
            raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_todo_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/todo_cli.py tests/unit/test_todo_cli.py
git commit -m "feat(todo): add done, open, delete commands

- done: mark todo as done with idempotency warning
- open: reopen a done todo
- delete: remove todo and its index entries
- All commands support --kb for multi-kb usage

Refs #230"
```

---

### Task 6: 创建 review 命令

**Files:**

- Modify: `jfox/todo_cli.py`
- Test: `tests/unit/test_todo_review.py`

- [ ] **Step 1: 写 failing test — review 命令**

```python
"""
测试类型: 单元测试
目标模块: jfox.todo_cli (review 命令)
预估耗时: < 1秒
依赖要求: 无外部依赖，使用 mock
"""

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]
from datetime import datetime
from unittest.mock import patch

from jfox.models import Note, NoteType

PATCH_USE_KB = "jfox.todo_cli.use_kb"
PATCH_NOTE_MODULE = "jfox.todo_cli.note"


class TestTodoReview:
    """测试 todo review 命令"""

    @patch(PATCH_USE_KB)
    @patch(PATCH_NOTE_MODULE)
    def test_review_default_returns_list(self, mock_note, mock_use_kb):
        """默认 review 返回 open todo 列表（Agent 友好）"""
        from jfox.todo_cli import _todo_review_impl

        todos = [
            Note(
                id="202605221430001234",
                title="Task 1",
                content="",
                type=NoteType.TODO,
                status="open",
                created=datetime(2026, 5, 20, 10, 0, 0),
                updated=datetime.now(),
            ),
            Note(
                id="202605221430005678",
                title="Task 2",
                content="",
                type=NoteType.TODO,
                status="done",
                created=datetime(2026, 5, 21, 10, 0, 0),
                updated=datetime.now(),
            ),
        ]
        mock_note.list_notes.return_value = [todos[0]]  # 默认过滤后只剩 open

        result = _todo_review_impl(interactive=False, output_format="json")

        assert result["total"] == 1
        assert result["notes"][0]["title"] == "Task 1"
        assert result["stats"]["open"] == 1

    @patch(PATCH_USE_KB)
    @patch(PATCH_NOTE_MODULE)
    def test_review_stats_include_all_statuses(self, mock_note, mock_use_kb):
        """review 统计包含所有状态"""
        from jfox.todo_cli import _todo_review_impl

        todos = [
            Note(
                id="202605221430001234",
                title="Task 1",
                content="",
                type=NoteType.TODO,
                status="open",
                created=datetime.now(),
                updated=datetime.now(),
            ),
            Note(
                id="202605221430005678",
                title="Task 2",
                content="",
                type=NoteType.TODO,
                status="done",
                created=datetime.now(),
                updated=datetime.now(),
            ),
            Note(
                id="202605221430009012",
                title="Task 3",
                content="",
                type=NoteType.TODO,
                status="open",
                created=datetime.now(),
                updated=datetime.now(),
            ),
        ]
        mock_note.list_notes.return_value = todos

        result = _todo_review_impl(interactive=False, output_format="json")

        assert result["stats"]["open"] == 2
        assert result["stats"]["done"] == 1
        assert result["stats"]["total"] == 3

    @patch(PATCH_USE_KB)
    @patch("jfox.todo_cli.typer.confirm")
    @patch(PATCH_NOTE_MODULE)
    def test_review_interactive_marks_done(self, mock_note, mock_confirm, mock_use_kb):
        """交互模式下可以标记完成"""
        from jfox.todo_cli import _todo_review_impl

        todo = Note(
            id="202605221430001234",
            title="Task 1",
            content="Content",
            type=NoteType.TODO,
            status="open",
            created=datetime.now(),
            updated=datetime.now(),
        )
        mock_note.list_notes.return_value = [todo]
        mock_note.load_note_by_id.return_value = todo
        mock_note.update_note.return_value = True
        # 模拟用户输入: d (done), q (quit)
        mock_confirm.side_effect = [True, False]  # done=True, continue?=False

        result = _todo_review_impl(interactive=True, output_format="json")

        assert result["stats"]["completed"] == 1
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_todo_review.py -v`
Expected: FAIL (_todo_review_impl 不存在)

- [ ] **Step 3: 实现 review 命令**

在 `jfox/todo_cli.py` 中，在 `_todo_delete_impl` 后追加：

```python
def _todo_review_impl(
    interactive: bool,
    output_format: str,
) -> dict:
    """review 待办的内部实现"""
    from .formatters import OutputFormatter

    # 获取所有 todo
    all_todos = note.list_notes(note_type=NoteType.TODO)

    # 统计
    open_todos = [t for t in all_todos if t.status == "open"]
    done_todos = [t for t in all_todos if t.status == "done"]

    stats = {
        "total": len(all_todos),
        "open": len(open_todos),
        "done": len(done_todos),
    }

    # 非交互模式：返回列表（Agent 友好）
    if not interactive:
        data = []
        for t in open_todos:  # 默认只展示 open
            d = t.to_dict()
            d["status"] = t.status
            data.append(d)

        result = {
            "total": len(open_todos),
            "notes": data,
            "stats": stats,
        }

        if output_format == "json":
            print(OutputFormatter.to_json(result))
        elif output_format == "table":
            table = Table(title=f"Todo Review ({len(open_todos)} open / {len(all_todos)} total)")
            table.add_column("ID", style="dim")
            table.add_column("Title", style="cyan")
            table.add_column("Created", style="dim")
            table.add_column("Content Preview", style="white")

            for t in open_todos:
                created_str = t.created.strftime("%Y-%m-%d") if t.created else ""
                preview = t.content[:60] + "..." if len(t.content) > 60 else t.content
                table.add_row(t.id, t.title[:40], created_str, preview)
            console.print(table)

            console.print(f"\n[dim]Total: {len(all_todos)} | Open: {len(open_todos)} | Done: {len(done_todos)}[/dim]")
        else:
            print(OutputFormatter.to_yaml(result))

        return result

    # 交互模式：逐条 review
    completed_count = 0
    skipped_count = 0
    deleted_count = 0

    console.print(f"\n[bold]Todo Review[/bold] ({len(open_todos)} open items)\n")

    for i, t in enumerate(open_todos, 1):
        console.print(f"[{i}/{len(open_todos)}] [cyan]{t.title}[/cyan] ({t.created.strftime('%Y-%m-%d')})")
        if t.content:
            preview = t.content[:200] + "..." if len(t.content) > 200 else t.content
            console.print(f"  {preview}")
        console.print()

        action = typer.prompt(
            "Action: [d]one / [s]kip / [x]delete / [q]uit",
            default="s",
        ).lower().strip()

        if action in ("d", "done"):
            t.status = "done"
            t.updated = datetime.now()
            note.update_note(t, add_to_index=False)
            completed_count += 1
            console.print("  [green]✓ Marked as done[/green]\n")
        elif action in ("x", "delete", "del"):
            note.delete_note(t.id)
            deleted_count += 1
            console.print("  [red]✗ Deleted[/red]\n")
        elif action in ("q", "quit"):
            console.print("  [dim]Quitting review[/dim]\n")
            break
        else:
            skipped_count += 1
            console.print("  [dim]Skipped[/dim]\n")

    console.print(f"\n[bold]Review Complete[/bold]")
    console.print(f"  Done: {completed_count} | Skipped: {skipped_count} | Deleted: {deleted_count}")

    return {
        "total": len(open_todos),
        "stats": {
            **stats,
            "completed": completed_count,
            "skipped": skipped_count,
            "deleted": deleted_count,
        },
    }
```

然后在文件末尾追加 CLI 命令：

```python
@todo_app.command()
def review(
    interactive: bool = typer.Option(False, "--interactive", "-i", help="交互式逐条 review"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table, yaml"),
    json_output: bool = typer.Option(False, "--json", help="JSON 输出"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
):
    """Review 待办便签

    默认输出所有 open todo 的列表（Agent 友好）。
    加 --interactive 进入交互式逐条 review 模式。
    """
    try:
        if json_output:
            output_format = "json"

        with use_kb(kb):
            _todo_review_impl(interactive, output_format)
    except Exception as e:
        if output_format == "json":
            print(output_json({"success": False, "error": str(e)}))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_todo_review.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/todo_cli.py tests/unit/test_todo_review.py
git commit -m "feat(todo): add review command with interactive mode

- Default: lists open todos with stats (Agent-friendly)
- --interactive: step-through with [d]one/[s]kip/[x]delete/[q]uit
- Shows completion stats after review

Refs #230"
```

---

### Task 7: 集成测试

**Files:**

- Create: `tests/unit/test_todo_integration.py`

- [ ] **Step 1: 写集成测试**

```python
"""
测试类型: 单元测试（集成）
目标模块: todo 与 search/graph 的集成
预估耗时: < 1秒
依赖要求: 无外部依赖，使用 mock
"""

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from jfox.config import ZKConfig
from jfox.models import Note, NoteType
from jfox.note import create_note, save_note


class TestTodoIntegration:
    """测试 todo 与现有功能的集成"""

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_todo_links_to_other_notes(self, mock_global_config, mock_note_config, tmp_path):
        """todo 可以链接到其他笔记， backlinks 正常更新"""
        cfg = ZKConfig(base_dir=tmp_path)
        cfg.ensure_dirs()
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        # 创建一篇永久笔记
        permanent = create_note(
            "Python async patterns",
            title="Python Async",
            note_type=NoteType.PERMANENT,
            tags=["python"],
        )
        save_note(permanent, add_to_index=False)

        # 创建 todo 链接到永久笔记
        todo = create_note(
            "读完这篇文章",
            title="Read Python Async",
            note_type=NoteType.TODO,
            tags=["学习"],
            links=[permanent.id],
        )
        save_note(todo, add_to_index=False)

        # 验证 todo 的前向链接
        assert permanent.id in todo.links

        # 验证永久笔记的反向链接被更新
        from jfox.note import load_note_by_id

        reloaded = load_note_by_id(permanent.id, cfg=cfg)
        assert todo.id in reloaded.backlinks

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_todo_note_index_includes_todo(self, mock_global_config, mock_note_config, tmp_path):
        """NoteIndex 自动包含 todo 类型"""
        cfg = ZKConfig(base_dir=tmp_path)
        cfg.ensure_dirs()
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        todo = create_note("测试 todo", note_type=NoteType.TODO)
        save_note(todo, add_to_index=False)

        from jfox.note_index import NoteIndex

        idx = NoteIndex(cfg)
        idx.rebuild()

        # 验证索引中包含 todo
        all_meta = idx.get_all_meta()
        todo_meta = [m for m in all_meta if m.type == NoteType.TODO]
        assert len(todo_meta) == 1
        assert todo_meta[0].title == "测试 todo"

    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_todo_filepath_in_todo_dir(self, mock_global_config, mock_note_config, tmp_path):
        """todo 笔记文件保存在 notes/todo/ 目录"""
        cfg = ZKConfig(base_dir=tmp_path)
        cfg.ensure_dirs()
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir

        todo = create_note("测试 todo", note_type=NoteType.TODO)
        save_note(todo, add_to_index=False)

        assert "notes/todo/" in str(todo.filepath).replace("\\", "/")
        assert todo.filepath.exists()
```

- [ ] **Step 2: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_todo_integration.py -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_todo_integration.py
git commit -m "test(todo): add integration tests for todo type

- Verify backlinks work with todo notes
- Verify NoteIndex auto-includes todo type
- Verify todo files are stored in notes/todo/

Refs #230"
```

---

### Task 8: 验证与手动测试

**Files:**

- None (manual verification)

- [ ] **Step 1: 运行全部 todo 测试**

Run: `uv run pytest tests/unit/test_todo_*.py -v`
Expected: 全部 PASS

- [ ] **Step 2: 验证 CLI 注册**

Run: `uv run jfox todo --help`
Expected: 显示 add, list, done, open, delete, review 命令

- [ ] **Step 3: 端到端手动测试**

```bash
# 创建测试知识库（或使用现有）
uv run jfox init --name todo-test

# 添加 todo
uv run jfox todo add "测试待办" --content "这是内容" --tag "测试" --kb todo-test

# 列出 open todo
uv run jfox todo list --kb todo-test

# 标记完成
uv run jfox todo done "测试待办" --kb todo-test

# 验证 list 不再显示
uv run jfox todo list --kb todo-test

# --all 仍能看到
uv run jfox todo list --all --kb todo-test

# 删除
uv run jfox todo delete "测试待办" --kb todo-test
```

- [ ] **Step 4: 验证 search 包含 todo**

```bash
uv run jfox todo add "搜索测试" --content "关键词内容" --kb todo-test
uv run jfox search "关键词" --kb todo-test
```

Expected: 搜索结果包含 todo 笔记

- [ ] **Step 5: 验证 graph 包含 todo**

```bash
uv run jfox graph --kb todo-test
```

Expected: 图谱统计中包含 todo 节点

- [ ] **Step 6: 运行完整单元测试套件（快速）**

Run: `uv run pytest tests/unit/ -m "not embedding and not slow" -v`
Expected: 全部 PASS

- [ ] **Step 7: Final commit**

```bash
git commit --allow-empty -m "feat(todo): complete todo note type implementation (#230)

- New NoteType.TODO with open/done status
- jfox todo sub-command: add, list, done, open, delete, review
- Agent-friendly defaults: list shows open-only, review lists by default
- --interactive flag for human-friendly step-through review
- Full integration with search, graph, backlinks, and NoteIndex
- 4 test files covering CRUD, CLI, review, and integration

Closes #230"
```

---

## Self-Review

### 1. Spec Coverage

| 设计需求 | 对应 Task |
|----------|-----------|
| NoteType.TODO | Task 1 |
| Note.status 字段 | Task 1 |
| status 序列化/反序列化 | Task 1 |
| notes/todo/ 目录 | Task 2 |
| create_note 默认 status=open | Task 2 |
| get_stats 自动统计 | Task 2 (无需改动，遍历 NoteType) |
| CLI type 校验文案更新 | Task 3 |
| todo add 命令 | Task 4 |
| todo list（默认 open） | Task 4 |
| todo done/open/delete | Task 5 |
| todo review（默认列表） | Task 6 |
| todo review --interactive | Task 6 |
| search/graph 集成 | Task 7 (测试验证) |
| backlinks 集成 | Task 7 |

**无遗漏。**

### 2. Placeholder Scan

- 无 "TBD" / "TODO" / "implement later"
- 无 "add appropriate error handling"
- 所有步骤包含实际代码
- 每个 Task 的测试代码完整，不引用 "Similar to Task N"

### 3. Type Consistency

- `NoteType.TODO` 全计划一致
- `status` 字段类型始终为 `Optional[str]`
- `_todo_*_impl` 函数签名在测试和实现中一致
- `output_format` 参数值在所有命令中一致

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-06-02-todo-note-type.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
