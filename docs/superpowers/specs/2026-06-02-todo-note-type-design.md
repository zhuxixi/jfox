# Design: Todo 便签笔记类型

日期: 2026-06-02
Issue: #230

---

## 背景

当前笔记类型（fleeting/literature/permanent/session）都是知识类。用户想在工作知识库中快速记录待办/备忘，类似黄色便签，定期 review 这些 todo list。

**关键约束**：该 CLI 的主要使用者是 Coding Agent，因此设计以 Agent 友好为优先，人类交互为可选增强。

---

## 目标

1. 新增 `todo` 笔记类型，支持 `open` / `done` 两种状态
2. 提供独立的 `jfox todo` 命令族，便于 Agent 程序化操作
3. 与现有功能（search、graph、backlinks）无缝集成
4. 不破坏现有模型和架构

---

## Section 1: 数据模型与存储层

### 1.1 NoteType 扩展

在 `models.py` 的 `NoteType` 枚举中新增：

```python
class NoteType(Enum):
    FLEETING = "fleeting"
    LITERATURE = "literature"
    PERMANENT = "permanent"
    SESSION = "session"
    TODO = "todo"  # 新增
```

### 1.2 Note 模型（最小侵入）

采用与现有 `source`（literature 专用）、`topic`（session 专用）相同的模式：

```python
@dataclass
class Note:
    # ... 现有字段 ...
    status: Optional[str] = None  # 仅 todo 使用: "open" | "done"
```

- `to_markdown()` 在 `type == "todo"` 时输出 `status` 到 frontmatter
- `from_markdown()` 解析 frontmatter 中的 `status`（非 todo 类型则为 None）
- 其他类型完全无感知

### 1.3 存储路径

- 存储路径：`~/.zettelkasten/<kb>/notes/todo/`
- `config.py` 的 `ensure_dirs()` 新增 `self.notes_dir / "todo"`
- `note.py` 的 `get_stats()` 自动统计 todo 类型（遍历 `NoteType` 枚举）

### 1.4 文件名规则

采用 `permanent`/`literature` 模式：

```
{id}-{slug}.md
# 例如: 20260522143000-跟进客户反馈.md
```

---

## Section 2: CLI 接口设计

采用 Typer sub-app 模式：

```python
todo_app = typer.Typer(name="todo", help="待办便签管理")
app.add_typer(todo_app, name="todo")
```

### 2.1 命令族

| 命令 | 作用 | 输出格式 |
|------|------|----------|
| `jfox todo add "标题" [--content "正文"] [--tag t1] [--link [[笔记]]]` | 快速创建 todo | 成功/失败 + note ID |
| `jfox todo list [--all] [--tag t1] [--format json]` | 列出 todo（默认只显示 open） | 表格/JSON |
| `jfox todo done <id_or_title>` | 标记完成 | 成功/失败 |
| `jfox todo open <id_or_title>` | 重新打开 | 成功/失败 |
| `jfox todo delete <id_or_title>` | 删除 todo | 成功/失败 |
| `jfox todo review [--interactive]` | 批量 review | 列表 / 交互式 |

### 2.2 关键设计决策

**`list` 默认过滤 open**：与 `jfox list`（列出所有类型）不同，`jfox todo list` 默认只显示 `status=open` 的 todo，加 `--all` 才显示全部。

**`review` 的行为（Agent 优先）**：
- 默认（无 `--interactive`）：输出所有 open todo 的结构化列表，等价于 `jfox todo list`，供 Agent 消费
- `jfox todo review --interactive`：进入交互模式，逐条展示：
  ```
  [1/5] 跟进客户反馈 (2026-05-22)
  客户提出了三个问题需要回复...
  操作: [d]one / [s]kip / [x]delete / [q]uit >
  ```
  交互结束后输出统计。

**`done`/`open` 的实现**：
- 复用 `note.update_note()`，但只修改 `status` 和 `updated` 字段
- 为避免重命名文件（标题没变），`update_note()` 在检测到新旧路径相同时跳过 `unlink()`

### 2.3 错误处理

- `done` 一个已经是 done 的 todo → 提示警告，不报错
- `open` 一个已经是 open 的 todo → 同理
- 找不到 todo → 使用 `find_note_id_by_title_or_id()` 的模糊匹配，失败时报错

---

## Section 3: 集成与测试

### 3.1 与现有功能的集成

| 功能 | 集成方式 | 是否需要代码改动 |
|------|----------|------------------|
| **Search** (`jfox search`) | `note_type="todo"` 自动可用；搜索结果包含 todo | 无需改动 |
| **Graph** (`jfox graph`) | `rglob("*.md")` 自动包含 todo 目录；`[[links]]` 正常解析 | 无需改动 |
| **Index** (`note_index.py`) | `NoteIndex.rebuild()` 遍历所有 `NoteType`，自动包含 | 无需改动 |
| **Backlinks** | `jfox todo add --link [[笔记]]` 正常更新目标笔记的 `backlinks` | 复用现有逻辑 |
| **Vector Store / BM25** | `save_note()` 自动添加到索引 | 无需改动 |
| **`jfox show <id>`** | 复用 `find_note_id_by_title_or_id`，可定位 todo | 无需改动 |

**唯一需要的文案更新**：`jfox list` 和 `jfox add` 的 type 参数校验文案，从 `"Use: fleeting, literature, permanent, session"` 改为 `"Use: fleeting, literature, permanent, session, todo"`。

### 3.2 测试策略

| 测试文件 | 覆盖内容 |
|----------|----------|
| `tests/unit/test_todo_crud.py` | `create_note(type=TODO)`, `save_note`, `load_note`, `status` 序列化/反序列化 |
| `tests/unit/test_todo_cli.py` | `todo add`, `todo list`, `todo done`, `todo open`, `todo delete` 命令参数与输出 |
| `tests/unit/test_todo_review.py` | `review` 默认列表输出、`--interactive` 交互流程（mock 输入） |
| `tests/unit/test_todo_integration.py` | todo 的 `[[links]]` 能否被 graph/search 正确索引 |

### 3.3 不在范围内（YAGNI）

- todo 不单独建索引，复用现有 BM25 + 向量索引
- todo 不支持模板（`jfox todo add --template` 暂不支持）
- todo 不支持 `source`/`topic` 字段
- 不实现重复检测（如"是否已有同名 open todo"）

---

## 影响范围

| 文件 | 改动内容 |
|------|----------|
| `jfox/models.py` | `NoteType` 新增 `TODO`；`Note` 新增 `status` 字段；`to_markdown()`/`from_markdown()` 处理 `status` |
| `jfox/note.py` | `create_note()` 支持 todo 默认值；`get_stats()` 自动统计 |
| `jfox/config.py` | `ensure_dirs()` 新增 `todo` 目录 |
| `jfox/cli.py` | 新增 `todo` sub-app 及 6 个命令 |
| `tests/unit/test_todo_*.py` | 4 个新测试文件 |

---

## 执行顺序

1. 数据层（models.py + config.py + note.py）
2. CLI 命令（cli.py：add/list/done/open/delete）
3. Review 命令（cli.py：review + --interactive）
4. 测试（4 个测试文件）
5. 验证（手动运行 todo 命令族）
