# Issue #259 设计文档：笔记归档/软删除

## 背景与目标

用户在把 session 笔记提炼为 permanent 笔记后，希望这些源 session 笔记不再出现在默认列表和搜索结果中，但又不想被永久删除。因此需要引入类似邮箱"归档"的软删除机制。

目标：

- 不真正删除文件，仅通过 frontmatter 标记 `archived: true`。
- 默认的 `jfox list` / `jfox search` 隐藏已归档笔记。
- 提供显式命令查看/恢复归档笔记。
- `jfox show` 和 `jfox delete` 行为不受影响。

## 需求拆解

| 用户命令 | 行为 |
|---------|------|
| `jfox archive <note_id>` | 将笔记标记为 `archived: true`，更新 `updated` 时间戳 |
| `jfox unarchive <note_id>` | 将笔记标记为 `archived: false`（frontmatter 中移除该字段），更新 `updated` 时间戳 |
| `jfox list` | 默认只列出未归档笔记 |
| `jfox list --archived` | 只列出已归档笔记 |
| `jfox list --include-archived` | 列出全部笔记（包含归档） |
| `jfox search "关键词"` | 默认排除已归档笔记 |
| `jfox search "关键词" --include-archived` | 搜索时包含已归档笔记 |
| `jfox show <id>` | 不受归档状态影响，始终可查看 |
| `jfox delete <id>` | 真删除，不受归档状态影响 |

## 方案设计

### 1. 数据模型（`jfox/models.py`）

在 `Note` 数据类中新增字段：

```python
archived: bool = False
```

- `to_markdown()`：仅在 `archived=True` 时把 `archived: true` 写入 frontmatter，保持未归档笔记 frontmatter 干净。
- `from_markdown()`：读取 `archived` 字段，缺失时默认 `False`。
- `to_dict()`：增加 `"archived"` 字段，便于 JSON 输出。

### 2. 元数据索引（`jfox/note_index.py`）

在 `NoteMeta` 中新增 `archived: bool = False`。

索引构建时从 frontmatter 读取 `archived`，缺失默认 `False`。`list_meta()` 增加过滤参数：

```python
def list_meta(
    self,
    note_type: Optional[NoteType] = None,
    tags: Optional[List[str]] = None,
    limit: Optional[int] = None,
    archived_only: bool = False,
    include_archived: bool = False,
) -> List[NoteMeta]:
```

过滤规则：

- `archived_only=True`：只返回 `archived=True`。
- `include_archived=True`：返回全部。
- 默认：只返回 `archived=False`。

### 3. 笔记 CRUD（`jfox/note.py`）

新增：

```python
def archive_note(note_id: str) -> bool
def unarchive_note(note_id: str) -> bool
```

实现：

1. 通过 `load_note_by_id(note_id)` 加载笔记。
2. 设置 `note.archived = True/False`。
3. 调用 `update_note(note)` 持久化并同步索引（向量 + BM25）。

复用 `update_note` 可以自动处理：

- 原子写入；
- 文件名变化（归档不会改变文件名，但保留路径）；
- 索引更新（先删除旧向量/BM25，再添加新内容）。

`list_notes()` 增加参数 `archived_only` 和 `include_archived`，透传给 `NoteIndex.list_meta()`。

`search_notes()` 增加参数 `include_archived`，透传给搜索引擎。

### 4. 搜索引擎（`jfox/search_engine.py`）

`HybridSearchEngine.search()` 增加 `include_archived: bool = False`。

由于现有 ChromaDB 集合里的笔记元数据不一定包含 `archived` 字段，直接在 ChromaDB 层过滤会导致旧数据被误排除。因此采用**后过滤**策略：

1. 搜索时先按原逻辑获取结果，但 `exclude archived` 时多取一些结果（over-fetch）。
2. 使用 `NoteIndex` 判断每个结果是否归档（`meta.archived`）。
3. 过滤后取前 `top_k` 条。

over-fetch 策略：

- `_semantic_search` / `_keyword_search`：当 `not include_archived` 时，`search_k = max(top_k * 5, 20)`。
- `_hybrid_search`：同样 over-fetch，融合后再过滤。

这样可以在绝大多数场景下保证返回数量，同时避免旧索引数据兼容性问题。

### 5. CLI（`jfox/cli.py`）

新增命令：

```python
@app.command()
def archive(
    note_id: str = typer.Argument(..., help="笔记 ID"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(False, "--json", help="JSON 输出"),
):
    ...

@app.command()
def unarchive(...):
    ...
```

`list` 命令增加选项：

```python
archived_only: bool = typer.Option(False, "--archived", help="仅显示已归档笔记"),
include_archived: bool = typer.Option(False, "--include-archived", help="包含已归档笔记"),
```

`--archived` 与 `--include-archived` 互斥，同时指定时报错。

`search` 命令增加选项：

```python
include_archived: bool = typer.Option(False, "--include-archived", help="包含已归档笔记"),
```

`_list_impl` / `_search_impl` 相应增加参数透传。

### 6. 测试策略

新增 `tests/unit/test_archive.py`，覆盖：

- `Note.to_markdown()` / `from_markdown()` 正确读写 `archived`。
- `NoteIndex.list_meta()` 默认排除归档、支持 `archived_only` / `include_archived`。
- `archive_note()` / `unarchive_note()` 更新文件与索引。
- `list` CLI 默认排除归档、`--archived`、`--include-archived`。
- `search` CLI 默认排除归档、`--include-archived`。
- `show` / `delete` 对归档笔记行为不变。

使用现有 fixture（`temp_kb`、`cli_fast`）避免加载 embedding 模型。

## 兼容性

- 旧笔记没有 `archived` 字段，解析时默认视为未归档，行为不变。
- 已写入的 ChromaDB/BM25 索引不需要重建即可工作（后过滤）。
- 归档/取消归档会触发 `update_note()`，自动更新索引内容。

## 风险与回滚

- 风险：后过滤可能导致 `top_k` 返回数量不足（如果前 N 条中归档笔记很多）。通过 over-fetch（`*5` 且至少 20）缓解。
- 回滚：取消归档会移除 frontmatter 中的 `archived` 字段，恢复为未归档状态。
