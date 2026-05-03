# #190 list_notes() 元数据索引设计

## 问题

`list_notes()` 每次全量加载所有 `.md` 文件的完整内容（frontmatter + 正文），13 个调用者中 7 个只需要 id+title。知识库上万条时内存和延迟显著膨胀。

附加 bug：`limit` 在带 `tags` 过滤时失效，必须先全量加载再过滤。

## 方案

新增纯 Python 内存元数据索引 `NoteIndex`。CLI 模式每次命令启动时重建，只解析 frontmatter 不读正文。`list_notes()` 保持签名不变，内部通过索引减少 `load_note()` 调用次数。

daemon 增量更新留作后续迭代。

## 架构

### NoteIndex（新模块 `jfox/note_index.py`）

```python
@dataclass
class NoteMeta:
    id: str
    title: str
    type: NoteType
    tags: List[str]
    created: str
    updated: str
    filepath: str
    links: List[str]
    backlinks: List[str]

class NoteIndex:
    """轻量级元数据索引，CLI 模式每次启动时重建"""

    def __init__(self, cfg: ZKConfig): ...
    def rebuild(self) -> None: ...

    # 查询接口
    def find_by_id(self, note_id: str) -> Optional[NoteMeta]: ...
    def find_by_title(self, title: str) -> Optional[NoteMeta]: ...
    def find_by_title_prefix(self, prefix: str) -> List[NoteMeta]: ...
    def list_meta(self, note_type=None, tags=None, limit=None) -> List[NoteMeta]: ...
    def get_all_meta(self) -> List[NoteMeta]: ...
    def get_invalid_files(self) -> List[str]: ...
```

### 内部数据结构

```python
_by_id: Dict[str, NoteMeta]              # id -> meta
_by_title: Dict[str, NoteMeta]           # title.lower() -> meta
_by_type: Dict[NoteType, List[NoteMeta]] # type -> [meta, ...]
```

### rebuild() 实现

1. 按类型目录遍历 `*.md` 文件
2. 每个文件只读 frontmatter（到第二个 `---` 停止），不走 `Note.from_markdown()` 全文解析
3. frontmatter 解析失败或缺失的文件记录到 `_invalid_files`，不中断构建
4. 构建完成后 `logging.debug` 输出统计（总数、耗时、无效文件数）

### 错误处理

- 空文件（0 字节）：跳过，计入 invalid
- frontmatter 缺失/格式错误：跳过，计入 invalid
- 文件名不符合 ID 格式：跳过
- `get_invalid_files()` 暴露无效文件信息，供 `jfox check` 等使用

## 调用者迁移

### list_notes() 改造（签名不变）

```python
def list_notes(note_type=None, limit=None, cfg=None, tags=None) -> List[Note]:
    # 1. 用 NoteIndex.list_meta() 拿到匹配的 NoteMeta 列表
    # 2. 只对匹配到的文件调用 load_note()，而非全量加载
    # 3. limit 在 list_meta 阶段就生效（修复 tags 场景 limit 失效 bug）
```

收益：原来扫描 N 文件 → 全部 load_note → 过滤 → 截断。现在索引查 meta → 只 load 匹配文件 → 返回。

### 调用者变更

| 调用者 | 当前 | 改造后 |
|--------|------|--------|
| `find_note_id_by_title_or_id` (cli.py:247) | `list_notes()` 全量 | `NoteIndex.find_by_id()` / `find_by_title()` |
| `add` wiki link 解析 (cli.py:319) | 传全量 list 给 find | 同上 |
| `edit` wiki link 解析 (cli.py:1202) | 传全量 list 给 find | 同上 |
| `refs` 统计 (cli.py:903, 981) | `list_notes()` | `NoteIndex.list_meta()` |
| `daily` (cli.py:1574) | `list_notes()` | `NoteIndex.list_meta()` |
| `inbox` (cli.py:1637) | `list_notes(note_type=...)` | `NoteIndex.list_meta(note_type=...)` |
| `list` 命令 (cli.py:768) | `list_notes()` | 保持 `list_notes()`（需要内容摘要，受益于减少 load） |
| `index rebuild` (cli.py:1777, 1860) | `list_notes(limit=10000)` | 保持 `list_notes()`（需要全文） |
| `suggest_links` (note.py:650) | `list_notes(limit=200)` | 保持 `list_notes()`（需要 content 片段） |
| `search_engine.py:254` rebuild_bm25 | `list_notes(limit=10000)` | 保持 `list_notes()`（需要全文） |

### NoteIndex 实例化位置

在 `ZKConfig` 或模块级别维护一个单例，确保同一命令内只构建一次。调用者通过 `get_note_index(cfg)` 获取。

## 测试

- `tests/unit/test_note_index.py` — 纯单元测试
  - 构建索引、按 id/title/type/tags 查询
  - 空文件/损坏文件跳过
  - limit 提前截断（含 tags 场景）
  - find_by_title 大小写不敏感
- 改造后的 `list_notes()` — 复用现有集成测试验证兼容性
- `find_note_id_by_title_or_id` 迁移 — 复用现有 `show`/`add`/`edit` 测试

## 范围界定

- 本期：CLI 模式，每次启动重建索引
- 后续：daemon 模式下增量更新（文件变更时更新 `_by_id`/`_by_title`/`_by_type`）
- 不涉及：SQLite 持久化（#61）、全文搜索引擎改造

## 相关 Issue

- #190 — 本 issue
- #61 — SQLite 索引（长期方向，本方案不冲突）
- #189 — `jfox check` 命令（可消费 `get_invalid_files()`）
