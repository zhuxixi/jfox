# jfox-ingest Skill 与 ingest-log 命令打通 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 更新 jfox-ingest skill 文档，将 git log 采集步骤从手动 `git log` + 解析 + `bulk-import` 简化为调用 `jfox ingest-log` CLI 命令。

**Architecture:** 纯文档更新，不涉及代码变更。修改项目内 `skills-recommend/` 目录的 SKILL.md，然后同步到全局 `~/.claude/skills/`。

**Tech Stack:** Markdown (SKILL.md)

---

## File Structure

| 文件 | 操作 | 职责 |
|------|------|------|
| `skills-recommend/claude-code/jfox-ingest/SKILL.md` | 修改 | 项目内的 skill 定义 |
| `~/.claude/skills/jfox-ingest/SKILL.md` | 同步 | 全局 skill（与项目保持一致） |

不涉及 `jfox/git_extractor.py`、`jfox/cli.py` 或任何 Python 代码变更。

---

### Task 1: 更新 Step 3 — 用 `jfox ingest-log` 替代手动 git log

**Files:**
- Modify: `skills-recommend/claude-code/jfox-ingest/SKILL.md:58-79`

- [ ] **Step 1: 替换 Step 3 的内容**

将原文（第 58-79 行）：

```
### Step 3: 采集 git log

\`\`\`bash
git -C <path> log --format="%H|%s|%b|%an|%ad" --date=short -50
\`\`\`

解析每条 commit，转化为笔记结构：

- **title**: commit subject（第一行 `%s`）
- **content**: 包含 commit hash、完整 body、作者、日期
- **tags**: `source:<repo-name>`, `source:git-log`

示例笔记内容：
\`\`\`
Commit: a1b2c3d
Author: 张三
Date: 2026-04-10

feat: add user authentication module

实现了 JWT 认证，支持 refresh token 机制。
\`\`\`
```

替换为：

```
### Step 3: 采集 git log

使用 `jfox ingest-log` 命令（基于 `jfox/git_extractor.py` 模块），一行完成提取 + 转换 + 导入：

\`\`\`bash
jfox ingest-log <path> --limit 50 [--kb <name>] [--type fleeting]
\`\`\`

该命令会：
- 调用 `git log` 提取 commit 历史
- 自动解析为结构化数据（hash, subject, author, date, body）
- 转换为 fleeting 笔记并批量导入知识库
- 自动添加标签：`source:<repo-name>`, `source:git-log`

生成笔记示例：
\`\`\`
Commit: a1b2c3d
Author: 张三
Date: 2026-04-10

feat: add user authentication module

实现了 JWT 认证，支持 refresh token 机制。
\`\`\`

> **注意**: `jfox ingest-log` 使用 `--json`/`--no-json`（默认开启），不要使用 `--format json`。输出格式控制用 `--format`。
```

- [ ] **Step 2: 验证修改后文档的 Markdown 格式正确**

Run: `cat skills-recommend/claude-code/jfox-ingest/SKILL.md`

Expected: Step 3 部分显示 `jfox ingest-log` 命令，不再有手动 `git log` 解析步骤。

---

### Task 2: 更新 Step 6 — 简化 git-log 导入，保留 PR/Issues 的 bulk-import

**Files:**
- Modify: `skills-recommend/claude-code/jfox-ingest/SKILL.md:142-173`

- [ ] **Step 1: 替换 Step 6 的内容**

将原文（第 142-173 行）：

```
### Step 6: 去重与导入

**去重检查**：导入前检查知识库中是否已有该仓库的数据：
\`\`\`bash
jfox search "<repo-name>" --format json
\`\`\`

如果已有记录，只导入新增的条目（通过 commit hash、PR 编号、Issue 编号判断）。

**生成临时 JSON 文件**：将所有待导入记录组装为 JSON 数组：

\`\`\`json
[
  {
    "title": "feat: add user authentication module",
    "content": "Commit: a1b2c3d\\nAuthor: 张三\\nDate: 2026-04-10\\n\\n实现了 JWT 认证，支持 refresh token 机制。",
    "tags": ["source:my-app", "source:git-log"]
  },
  {
    "title": "Add user authentication",
    "content": "PR #42: Add user authentication\\nState: merged\\nAuthor: zhangsan\\n...",
    "tags": ["source:my-app", "source:pr"]
  }
]
\`\`\`

保存到临时文件（使用跨平台路径），然后执行导入：
\`\`\`bash
jfox bulk-import <temp-file.json> --type fleeting [--kb <name>]
\`\`\`

> **注意**: `jfox bulk-import` 使用 `--json`/`--no-json`（默认开启），不要使用 `--format json`。
```

替换为：

```
### Step 6: 导入 GitHub 数据（git-log 已在 Step 3 完成）

git-log 数据已通过 `jfox ingest-log` 完成导入，此步骤仅处理 GitHub PR/Issues 数据。

**去重检查**：导入前检查知识库中是否已有该仓库的数据：
\`\`\`bash
jfox search "<repo-name>" --format json
\`\`\`

如果已有记录，只导入新增的条目（通过 PR 编号、Issue 编号判断）。

**生成临时 JSON 文件**：将 PR/Issues 数据组装为 JSON 数组（仅 GitHub 数据）：

\`\`\`json
[
  {
    "title": "Add user authentication",
    "content": "PR #42: Add user authentication\\nState: merged\\nAuthor: zhangsan\\n...",
    "tags": ["source:my-app", "source:pr"]
  },
  {
    "title": "Login page crashes on mobile",
    "content": "Issue #15: Login page crashes on mobile\\nState: closed\\n...",
    "tags": ["source:my-app", "source:issue"]
  }
]
\`\`\`

保存到临时文件（使用跨平台路径），然后执行导入：
\`\`\`bash
jfox bulk-import <temp-file.json> --type fleeting [--kb <name>]
\`\`\`

> **注意**: `jfox bulk-import` 使用 `--json`/`--no-json`（默认开启），不要使用 `--format json`。
```

- [ ] **Step 2: 验证修改后文档的 Markdown 格式正确**

Run: `cat skills-recommend/claude-code/jfox-ingest/SKILL.md`

Expected: Step 6 标题改为"导入 GitHub 数据"，JSON 示例中不再包含 git-log 数据，说明仅处理 PR/Issues。

---

### Task 3: 更新命令参考和错误处理

**Files:**
- Modify: `skills-recommend/claude-code/jfox-ingest/SKILL.md:211-237`

- [ ] **Step 1: 替换命令参考部分**

将原文（第 211-230 行）：

```
## 命令参考

\`\`\`bash
# 检测仓库类型
git -C <path> remote get-url origin
gh auth status

# 采集数据
git -C <path> log --format="%H|%s|%b|%an|%ad" --date=short -50
gh pr list --repo <owner/repo> --state all --limit 20 --json number,title,body,state,author,createdAt,updatedAt,labels
gh pr view <number> --repo <owner/repo> --json comments
gh issue list --repo <owner/repo> --state all --limit 30 --json number,title,body,state,author,createdAt,labels,comments

# 去重检查
jfox search "<repo-name>" --format json

# 导入
jfox bulk-import <file.json> --type fleeting [--kb <name>]
jfox add "<content>" --title "<title>" --type fleeting [--kb <name>]
\`\`\`
```

替换为：

```
## 命令参考

\`\`\`bash
# 检测仓库类型
git -C <path> remote get-url origin
gh auth status

# 采集 git log（一行完成提取+导入）
jfox ingest-log <path> --limit 50 [--kb <name>] [--type fleeting]

# 采集 GitHub 数据
gh pr list --repo <owner/repo> --state all --limit 20 --json number,title,body,state,author,createdAt,updatedAt,labels
gh pr view <number> --repo <owner/repo> --json comments
gh issue list --repo <owner/repo> --state all --limit 30 --json number,title,body,state,author,createdAt,labels,comments

# 去重检查
jfox search "<repo-name>" --format json

# 导入 GitHub 数据
jfox bulk-import <file.json> --type fleeting [--kb <name>]

# 手动添加单条笔记
jfox add "<content>" --title "<title>" --type fleeting [--kb <name>]
\`\`\`
```

- [ ] **Step 2: 替换错误处理部分**

将原文（第 232-237 行）：

```
## 错误处理

- **"Not a git repository"**: 提示用户提供正确的仓库路径
- **\`gh: not found\`** 或 \`gh auth status\` 失败: 跳过 GitHub PR/Issues 导入，仅导入 git log
- **"Knowledge base not found"**: 提示用户先运行 \`/jfox-common\` 创建知识库
- **Bulk import 部分失败**: 报告成功/失败数量，失败记录不重试
```

替换为：

```
## 错误处理

- **"Not a git repository"**: `jfox ingest-log` 会报错，提示用户提供正确的仓库路径
- **\`gh: not found\`** 或 \`gh auth status\` 失败: 跳过 GitHub PR/Issues 导入，仅用 `jfox ingest-log` 导入 git log
- **"Knowledge base not found"**: 提示用户先运行 \`/jfox-common\` 创建知识库
- **Bulk import 部分失败**: 报告成功/失败数量，失败记录不重试
```

- [ ] **Step 3: 验证修改后文档完整**

Run: `cat skills-recommend/claude-code/jfox-ingest/SKILL.md`

Expected: 命令参考中 `git log` 原生命令被 `jfox ingest-log` 替代，错误处理中提到 `jfox ingest-log` 的报错行为。

---

### Task 4: 更新笔记格式规范说明

**Files:**
- Modify: `skills-recommend/claude-code/jfox-ingest/SKILL.md:196-205`

- [ ] **Step 1: 在笔记格式规范表格前添加说明**

在表格上方（第 196 行前）添加一行说明：

```
> git-log 格式由 `jfox ingest-log` 自动处理，以下规范主要供理解输出结构参考，以及手动处理 GitHub PR/Issues 数据时使用。
```

- [ ] **Step 2: 验证格式正确**

Expected: 笔记格式规范表格上方出现说明文字，注明 git-log 部分由 `ingest-log` 自动处理。

---

### Task 5: 同步到全局 skills 目录

**Files:**
- Copy to: `~/.claude/skills/jfox-ingest/SKILL.md`

- [ ] **Step 1: 复制更新后的 SKILL.md 到全局目录**

```bash
cp skills-recommend/claude-code/jfox-ingest/SKILL.md ~/.claude/skills/jfox-ingest/SKILL.md
```

- [ ] **Step 2: 验证两边内容一致**

```bash
diff skills-recommend/claude-code/jfox-ingest/SKILL.md ~/.claude/skills/jfox-ingest/SKILL.md
```

Expected: 无输出（文件完全一致）。

---

### Task 6: Commit

**Files:**
- Commit: `skills-recommend/claude-code/jfox-ingest/SKILL.md`

- [ ] **Step 1: 提交变更**

```bash
git add skills-recommend/claude-code/jfox-ingest/SKILL.md
git commit -m "refactor(skills): jfox-ingest 使用 ingest-log 替代手动 git log 流程

- Step 3: 替换手动 git log 解析为 jfox ingest-log 命令
- Step 6: 简化为仅处理 GitHub PR/Issues 的 bulk-import
- 更新命令参考和错误处理
- 添加笔记格式规范说明

Closes #131"
```
