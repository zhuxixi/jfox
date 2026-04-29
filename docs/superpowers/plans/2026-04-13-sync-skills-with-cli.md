# Sync jfox Skills with CLI #137 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update all 4 jfox skill files to accurately reflect the current CLI commands, parameters, and defaults.

**Architecture:** Pure documentation task — modify 3 Markdown skill files in `~/.claude/skills/jfox-*/SKILL.md`. No code changes. The skill files are outside the git repo but will be committed as a plan doc and a tracking issue comment.

**Tech Stack:** Markdown, jfox CLI (for verification)

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `~/.claude/skills/jfox-common/SKILL.md` | Major rewrite | Add CRUD commands, new params, new commands |
| `~/.claude/skills/jfox-ingest/SKILL.md` | Minor edit | Fix `--json` description |
| `~/.claude/skills/jfox-organize/SKILL.md` | Minor edit | Fix `--json` description, add `--content-file` |
| `~/.claude/skills/jfox-search/SKILL.md` | No change | Already accurate |

---

## Cross-cutting convention: `--json` vs `--format json`

**Current state:** jfox-ingest and jfox-organize say "不要用 `--format json`", implying it's wrong. In reality, `--json` is defined as a shorthand for `--format json` and they are equivalent.

**Fix:** Replace all instances of the misleading note with a neutral convention statement. The convention used throughout all skills should be:

> **约定**：所有命令均支持 `--format json` 输出 JSON，也可使用快捷方式 `--json`（两者等价）。下文示例统一使用 `--json`。

This applies to:
- `jfox-ingest/SKILL.md` lines 83, 179 (two note blocks)
- `jfox-organize/SKILL.md` lines 65, 96, 161 (three note blocks)

---

### Task 1: Fix `--json` descriptions in jfox-ingest

**Files:**
- Modify: `~/.claude/skills/jfox-ingest/SKILL.md`

- [ ] **Step 1: Replace first note block (around line 83)**

Replace:
```
> **注意**: `jfox ingest-log` 使用 `--json`（默认关闭）/`--format`（默认 table）控制输出。JSON 模式用 `--json`，不要用 `--format json`。
```

With:
```
> **约定**：`jfox ingest-log` 支持 `--format json` 输出 JSON，也可使用快捷方式 `--json`（两者等价）。下文示例统一使用 `--json`。
```

- [ ] **Step 2: Replace second note block (around line 179)**

Replace:
```
> **注意**: `jfox bulk-import` 使用 `--json`（默认开启）/`--no-json` 控制输出。不要使用 `--format json`。
```

With:
```
> **约定**：`jfox bulk-import` 默认输出 JSON。使用 `--no-json` 切换为 table 格式，或 `--format table` 显式指定。
```

- [ ] **Step 3: Verify changes are consistent**

Read the full file and confirm both note blocks are updated and no other "不要用" or "不要使用" warnings about `--format json` remain.

---

### Task 2: Fix `--json` descriptions and add `--content-file` in jfox-organize

**Files:**
- Modify: `~/.claude/skills/jfox-organize/SKILL.md`

- [ ] **Step 1: Replace first note block (around line 65)**

Replace:
```
> **注意**：`jfox add` 和 `jfox delete` 使用 `--json`/`--no-json`（默认开启），不要用 `--format json`。
```

With:
```
> **约定**：所有命令均支持 `--format json` 输出 JSON，也可使用快捷方式 `--json`（两者等价）。下文示例统一使用 `--json`。
```

- [ ] **Step 2: Replace second note block (around line 96)**

Replace:
```
> **注意**：`jfox edit` 使用 `--json`/`--no-json`（默认开启），不要用 `--format json`。
```

With:
```
> **约定**：`jfox edit` 支持 `--format json`，也可使用快捷方式 `--json`（两者等价）。
```

- [ ] **Step 3: Replace third note block in error handling (around line 161)**

Replace:
```
- **`jfox add` / `jfox edit` / `jfox delete` 使用 `--json`/`--no-json`**，不要用 `--format json`
```

With:
```
- **`jfox add` / `jfox edit` / `jfox delete`** 支持 `--format json`，也可使用快捷方式 `--json`
```

- [ ] **Step 4: Add `--content-file` to "直接创建笔记" section**

In the **创建笔记** subsection (around line 118-120), after the existing `jfox add` example, add:

```bash
# 从文件读取内容（适合长文本，避免 shell 转义问题）
jfox add --content-file notes/draft.md --title "<标题>" --type permanent --tag <tags> [--kb <name>]

# 从 stdin 读取
echo "内容" | jfox add --content-file - --title "<标题>" --type fleeting
```

- [ ] **Step 5: Add `--content-file` to edit example in Step 3 (around line 93)**

In the 图谱优化 section, after the existing `jfox edit` example, add:

```bash
# 使用文件内容编辑（适合长文本）
jfox edit <孤立笔记_id> --content-file updated.md
```

- [ ] **Step 6: Add `--date` to `jfox daily` in command reference (around line 153)**

Replace:
```bash
jfox daily --json                             # 查看今天的笔记
```

With:
```bash
jfox daily --json                             # 查看今天的笔记
jfox daily --date 2026-04-01 --json           # 查看指定日期的笔记
```

- [ ] **Step 7: Verify full file is consistent**

Read the full file and confirm no remaining "不要用" or "不要使用" warnings about `--format json`.

---

### Task 3: Major update to jfox-common

**Files:**
- Modify: `~/.claude/skills/jfox-common/SKILL.md`

This is the largest change. The skill currently covers only KB management and health check. It needs a new "笔记 CRUD" section and updates to the command reference.

- [ ] **Step 1: Add "笔记 CRUD" section after "管理命令" and before "删除知识库"**

Insert the following after the `jfox kb rename` / `jfox kb remove` block (after line ~87):

```markdown
## 笔记 CRUD

### 添加笔记

```bash
# 快速添加（内容直接作为参数）
jfox add "笔记内容，支持 [[其他笔记标题]] 链接" --title "笔记标题"

# 指定类型和标签
jfox add "内容" --title "标题" --type permanent --tag design --tag backend

# 从文件读取内容（v0.2.1+，适合长文本）
jfox add --content-file notes/draft.md --title "标题" --type literature

# 从 stdin 读取
cat notes.txt | jfox add --content-file - --title "标题"

# 使用模板
jfox add --template meeting --title "周会记录"
```

笔记类型：
- `fleeting`（默认）— 快速捕获，稍后提炼
- `literature` — 阅读笔记
- `permanent` — 已提炼的知识

### 编辑笔记

```bash
# 编辑内容和标题
jfox edit <note_id> --content "新内容" --title "新标题"

# 从文件读取内容（v0.2.1+，适合长文本）
jfox edit <note_id> --content-file updated.md

# 修改标签和类型
jfox edit <note_id> --tag new-tag1 --tag new-tag2 --type permanent

# 在指定知识库中编辑
jfox edit <note_id> --kb work --content "新内容"
```

编辑会保留原始笔记 ID 和创建时间。

### 删除笔记

```bash
jfox delete <note_id>               # 需确认
jfox delete <note_id> --force       # 跳过确认
```

### 查看笔记

```bash
jfox list --format json --limit 50              # 列出笔记
jfox list --type permanent --format json         # 按类型筛选
jfox daily --json                                # 今天的笔记
jfox daily --date 2026-04-01 --json              # 指定日期
jfox refs --search "<标题>" --format json        # 查看反向链接
```
```

- [ ] **Step 2: Update "命令参考" section to include all commands**

Replace the entire "命令参考" section (starting at "## 命令参考") with:

```markdown
## 命令参考

以下仅列出知识库管理、笔记 CRUD 和健康检查相关命令。所有命令支持 `--kb <name>` 指定知识库，省略时使用当前默认知识库。

**约定**：所有命令均支持 `--format json` 输出 JSON，也可使用快捷方式 `--json`（两者等价）。下文示例统一使用 `--json`。

### 知识库管理

```bash
jfox init --name <name> --desc "<desc>"     # 创建知识库
jfox kb list --format json                  # 列出所有知识库
jfox kb switch <name>                       # 切换知识库
jfox kb info <name> --format json           # 查看知识库详情
jfox kb current --format json               # 当前知识库
jfox kb rename <old> <new>                  # 重命名
jfox kb remove <name>                       # 注销（保留文件）
jfox kb remove <name> --force               # 删除（含文件，不可恢复）
jfox status --format json                   # 知识库状态
```

### 笔记 CRUD

```bash
jfox add "<content>" --title "<title>" --type <type> --tag <tags>  # 添加笔记
jfox add --content-file <path> --title "<title>"                   # 从文件添加
jfox edit <id> --content "<new>" --title "<title>"                 # 编辑笔记
jfox edit <id> --content-file <path>                               # 从文件编辑
jfox delete <id> --force                                           # 删除笔记
jfox list --format json --limit <N>                                # 列出笔记
jfox daily --json                                                  # 今天的笔记
jfox daily --date YYYY-MM-DD --json                                # 指定日期
jfox refs --search "<title>" --format json                         # 反向链接
```

### 数据导入

```bash
jfox ingest-log <repo-path> --limit <N> --type fleeting --kb <name>  # Git 仓库导入
jfox bulk-import <file.json> --type fleeting --kb <name>             # 批量导入
```

### 健康检查

```bash
jfox graph --stats --json                    # 图谱指标（与 --orphans 互斥，分开运行）
jfox graph --orphans --json                  # 孤立笔记列表
jfox index verify                            # 索引完整性验证
jfox index rebuild                           # 重建索引
jfox inbox --json --limit <N>                # 未处理笔记
```

> 搜索、导入、整理等高频操作命令见对应技能文档（jfox-search、jfox-ingest、jfox-organize）。
```

- [ ] **Step 3: Add `ingest-log` to "错误处理" table**

Add a row to the error handling table:

```
| `ingest-log` 报 "Not a git repository" | 提供正确的 Git 仓库路径 |
```

- [ ] **Step 4: Verify full file reads correctly**

Read the entire updated file end-to-end. Check:
1. Section order is logical: 前置条件 → 路径约定 → KB 管理 → 笔记 CRUD → 健康检查 → 命令参考 → 错误处理
2. No duplicate content
3. All CLI parameters match `jfox <cmd> --help` output
4. No "不要用" warnings about `--format json`

---

### Task 4: Final verification

- [ ] **Step 1: Verify each skill against CLI help**

For each of the 3 modified skills, cross-check every command and parameter mentioned in the skill against `uv run jfox <cmd> --help`:

```bash
uv run jfox add --help
uv run jfox edit --help
uv run jfox delete --help
uv run jfox daily --help
uv run jfox ingest-log --help
uv run jfox list --help
uv run jfox graph --help
uv run jfox inbox --help
uv run jfox index --help
uv run jfox suggest-links --help
uv run jfox bulk-import --help
uv run jfox refs --help
uv run jfox status --help
uv run jfox kb --help
```

- [ ] **Step 2: Comment on issue #137**

Post a comment on zhuxixi/jfox#137 linking to the plan and confirming completion:

```
Skills synced with CLI as of v0.2.1. Plan: `docs/superpowers/plans/2026-04-13-sync-skills-with-cli.md`
```

- [ ] **Step 3: Close issue #137**

```bash
gh issue close 137 --comment "All 4 skills audited and 3 updated to match CLI v0.2.1."
```
