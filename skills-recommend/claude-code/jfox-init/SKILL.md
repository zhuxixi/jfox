---
name: jfox-init
description: Use when user wants to initialize, create, or set up a Zettelkasten knowledge base with jfox CLI. Triggers on "初始化知识库", "创建知识库", "新建知识库", "知识库初始化", "配置 jfox", "setup jfox", "init knowledge base", "create knowledge base", "new knowledge base", "jfox init", "start using jfox".
---

# JFox Knowledge Base Initialization

Initialize a new Zettelkasten knowledge base using the jfox CLI.

## Prerequisites

Verify jfox is installed:
```bash
jfox --version
```
If not installed: `uv tool install jfox-cli`

## Knowledge Base Path Convention

All knowledge bases live under `~/.zettelkasten/`:

| Command | KB Name | Path |
|---------|---------|------|
| `jfox init` | default | `~/.zettelkasten/default/` |
| `jfox init --name work` | work | `~/.zettelkasten/work/` |
| `jfox init --name research` | research | `~/.zettelkasten/research/` |

Custom paths via `--path` must be under `~/.zettelkasten/` (enforced by CLI).

## Workflow

### Step 1: Check Existing Knowledge Bases

```bash
jfox kb list --format json
```

If KBs already exist, inform user and ask whether to use an existing one or create new.

### Step 2: Create Knowledge Base

**Default KB (first-time users):**
```bash
jfox init
```

**Named KB:**
```bash
jfox init --name <name> --desc "<description>"
```

Examples:
```bash
jfox init --name work --desc "工作笔记"
jfox init --name research --desc "研究笔记"
jfox init --name personal --desc "个人知识库"
```

**With custom path (must be under ~/.zettelkasten/):**
```bash
jfox init --name <name> --path ~/.zettelkasten/<custom-path>
```

### Step 3: Verify Initialization

```bash
jfox kb current --format json
jfox status --format json
```

Confirm KB is registered, directory structure created, and status shows 0 notes.

### Step 4: Suggest First Note

```
知识库已初始化！建议创建第一条笔记：
  jfox add "我的第一个想法" --title "开始使用 JFox" --type fleeting
```

## Multi-KB Management

```bash
jfox kb list                        # 列出所有知识库
jfox kb switch <name>               # 切换知识库
jfox kb info <name> --format json   # 查看详情
jfox kb current --format json       # 当前知识库
jfox kb remove <name> --force       # ⚠️ 删除知识库（含笔记文件，不可恢复）
jfox kb remove <name>               # 仅注销知识库，保留笔记文件
jfox kb rename <old> <new>          # 重命名
```

## Error Handling

- **"Knowledge base already exists"**: Use `jfox kb switch <name>` or create with a different name.
- **"Path is outside managed directory"**: All KBs must be under `~/.zettelkasten/`.
- **Command not found**: Install with `uv tool install jfox-cli`.

## Import Existing Notes

```bash
# JSON backup
jfox bulk-import /path/to/backup.json --type permanent --batch-size 32
jfox bulk-import /path/to/backup.json --kb work --type permanent

# Raw markdown files (default KB uses ~/.zettelkasten/default/, named KB uses ~/.zettelkasten/<name>/)
cp /path/to/notes/*.md ~/.zettelkasten/default/notes/permanent/
jfox index rebuild
```
