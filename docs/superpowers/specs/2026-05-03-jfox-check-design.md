# jfox check 命令 — 检测和清理损坏文件 (#189)

## 问题

知识库中可能残留空文件（0 字节）或 frontmatter 损坏的 `.md` 文件。
`list_notes()` (#188) 已能汇总跳过数量，但用户无法定位具体是哪些文件。

## 修复

**命令**: `jfox check [--clean] [--format table|json] [--kb <name>]`

### 检测逻辑

扫描 `notes/{fleeting,literature,permanent}/*.md` 下的所有文件，分类为：

- **empty** — 文件大小为 0 字节
- **corrupt** — 文件非空但 `load_note()` 返回 `None`（frontmatter 缺失、YAML 格式错误等）

### 输出

每个问题文件显示：相对路径、问题类型（empty/corrupt）、文件大小。

**Table 格式（默认）**：

```
 Found 2 issues in knowledge base

 ┏━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━┳━━━━━━━━━┳━━━━━━━┓
 ┃ File                                ┃ Issue   ┃ Size  ┃
 ┡━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━╇━━━━━━━━━╇━━━━━━━┩
 │ notes/permanent/empty.md            │ empty   │ 0 B   │
 │ notes/fleeting/corrupt.md           │ corrupt │ 128 B │
 └─────────────────────────────────────┴─────────┴───────┘
```

无问题时：`No issues found. Knowledge base is clean.`

**JSON 格式**：

```json
{
  "total": 2,
  "issues": [
    {"file": "notes/permanent/empty.md", "issue": "empty", "size": 0},
    {"file": "notes/fleeting/corrupt.md", "issue": "corrupt", "size": 128}
  ]
}
```

### --clean 行为

- 仅删除 **empty** 类型文件（0 字节）
- **corrupt 但非空文件不自动删除**（可能包含有价值内容，用户应手动检查）
- 执行前提示用户确认：`Delete 1 empty file(s)? [y/N]`
- 确认后删除，输出 `Deleted 1 empty file(s).`

### 退出码

- `0`：无问题文件
- `1`：发现问题文件

### 实现位置

纯 CLI 层实现。在 `cli.py` 中新增 `check` 命令 + `_check_impl()` helper。
复用 `load_note()` 已有的解析逻辑判断文件是否损坏。

不新增 note.py 函数 — YAGNI，诊断工具调用场景单一。

## 设计决策

- **纯 CLI 层**：调用场景单一（CLI 诊断），不额外抽象。后续如果需要程序化调用再抽取。
- **--clean 只删空文件**：非空损坏文件可能包含有价值内容，宁可保守。
- **退出码非零**：方便脚本化使用 `jfox check && echo "clean"` 模式。
- **复用 load_note()**：不重复实现 frontmatter 解析，保持检测逻辑与实际加载逻辑一致。

## 不在本次范围

- 自动修复损坏文件（如重建 frontmatter）
- 检查孤立链接/断链
- 检查索引与文件系统一致性
- 检查笔记内容质量
