---
name: jfox-ingest
description: Use when user wants to import data from a local git repository into their Zettelkasten as fleeting notes. Triggers on "导入仓库", "导入 git log", "导入 PR", "导入 issues", "读一下这个仓库", "抓取仓库信息", "ingest repo", "import notes from repository", "bulk import from git", "导入项目信息".
---

# JFox 仓库数据导入

将本地 Git 仓库的 git log、GitHub PRs、GitHub Issues 批量导入为 Zettelkasten 知识库中的 fleeting 笔记。

## 概述

本技能从本地 Git 仓库采集数据，转化为 fleeting 笔记批量导入知识库。支持三种数据源：git log（本地提交记录）、GitHub Pull Requests、GitHub Issues。

## 前置条件

1. 知识库已存在：
   ```bash
   jfox kb list --format json
   ```
   如果没有知识库，提示用户先运行 `/jfox-common` 创建。

2. `git` 命令可用。

3. 如需导入 GitHub PR/Issues，`gh` CLI 必须已认证：
   ```bash
   gh auth status
   ```

## 工作流

### Step 1: 确定仓库信息

用户提供本地仓库路径（如 `/home/user/projects/my-app` 或 `C:\Users\me\code\project`）。

检测是否为 GitHub 仓库：
```bash
git -C <path> remote get-url origin
```

检查输出是否包含 `github.com`。如果是，从 URL 中提取 `owner/repo`：
- `git@github.com:owner/repo.git` → `owner/repo`
- `https://github.com/owner/repo.git` → `owner/repo`

同时提取仓库名称（`repo` 部分）用于标签，如 `source:my-app`。

### Step 2: 选择数据源

根据用户指令确定导入的数据源：

| 数据源 | 适用场景 | 需要 GitHub |
|--------|---------|-------------|
| git-log | 导入提交记录 | 否 |
| github-pr | 导入 Pull Requests | 是 |
| github-issue | 导入 Issues | 是 |

如果用户说"导入这个仓库"但未指定数据源，默认导入所有可用数据源（GitHub 仓库导入全部三种，非 GitHub 仓库仅导入 git-log）。

### Step 3: 采集 git log

使用 `jfox ingest-log` 命令（基于 `jfox/git_extractor.py` 模块），一行完成提取 + 转换 + 导入：

```bash
jfox ingest-log path/to/repo --limit 50 --kb name --type fleeting
```

该命令会：
- 调用 `git log` 提取 commit 历史
- 自动解析为结构化数据（hash, subject, author, date, body）
- 转换为 fleeting 笔记并批量导入知识库
- 自动添加标签：`source:repo-name`, `source:git-log`

生成笔记示例：
```
Commit: a1b2c3d
Author: 张三
Date: 2026-04-10

feat: add user authentication module

实现了 JWT 认证，支持 refresh token 机制。
```

> **注意**: `jfox ingest-log` 使用 `--json`（默认关闭）/`--format`（默认 table）控制输出。JSON 模式用 `--json`，不要用 `--format json`。

### Step 4: 采集 GitHub PRs

仅当 Step 1 检测到 GitHub 仓库时执行。

```bash
gh pr list --repo <owner/repo> --state all --limit 20 --json number,title,body,state,author,createdAt,updatedAt,labels
```

对于每个 PR，可选获取评论详情：
```bash
gh pr view <number> --repo <owner/repo> --json comments
```

转化为笔记结构：

- **title**: PR 标题
- **content**: 包含 PR 编号、状态、描述、关键评论、元数据（作者、创建/更新时间、标签）
- **tags**: `source:<repo-name>`, `source:pr`

示例笔记内容：
```
PR #42: Add user authentication
State: merged
Author: zhangsan
Created: 2026-04-01
Labels: feature, backend

实现了 JWT 认证模块...

Key Comments:
- @lisi: 建议增加 refresh token 机制
```

### Step 5: 采集 GitHub Issues

仅当 Step 1 检测到 GitHub 仓库时执行。

```bash
gh issue list --repo <owner/repo> --state all --limit 30 --json number,title,body,state,author,createdAt,labels,comments
```

转化为笔记结构：

- **title**: Issue 标题
- **content**: 包含 Issue 编号、状态、描述、评论、元数据
- **tags**: `source:<repo-name>`, `source:issue`

示例笔记内容：
```
Issue #15: Login page crashes on mobile
State: closed
Author: wangwu
Created: 2026-03-20
Labels: bug, mobile

在移动端访问登录页面时出现白屏...

Comments:
- @zhangsan: 已修复，请验证
```

### Step 6: 导入 GitHub 数据（git-log 已在 Step 3 完成）

git-log 数据已通过 `jfox ingest-log` 完成导入，此步骤仅处理 GitHub PR/Issues 数据。

**去重检查**：导入前检查知识库中是否已有该仓库的数据：
```bash
jfox search "repo-name" --format json
```

如果已有记录，只导入新增的条目（通过 PR 编号、Issue 编号判断）。

**生成临时 JSON 文件**：将 PR/Issues 数据组装为 JSON 数组（仅 GitHub 数据）：

```json
[
  {
    "title": "Add user authentication",
    "content": "PR #42: Add user authentication\nState: merged\nAuthor: zhangsan\n...",
    "tags": ["source:my-app", "source:pr"]
  },
  {
    "title": "Login page crashes on mobile",
    "content": "Issue #15: Login page crashes on mobile\nState: closed\n...",
    "tags": ["source:my-app", "source:issue"]
  }
]
```

保存到临时文件（使用跨平台路径），然后执行导入：
```bash
jfox bulk-import temp-file.json --type fleeting --kb name
```

> **注意**: `jfox bulk-import` 使用 `--json`（默认开启）/`--no-json` 控制输出。不要使用 `--format json`。

### Step 7: 确认报告

导入完成后，向用户报告结果：

```
导入完成！
  - git log: 50 条
  - GitHub PRs: 15 条
  - GitHub Issues: 10 条
  - 总计: 75 条 fleeting 笔记已导入到 <知识库名称>
```

## 手动输入支持

如果用户直接粘贴文本（未提供仓库路径），将文本整理为单条 fleeting 笔记并导入：
```bash
jfox add "<content>" --title "<title>" --type fleeting --tag <tags> [--kb <name>]
```

> **注意**: `jfox add` 使用 `--json`（默认关闭）/`--format`（默认 table）控制输出。JSON 模式用 `--json`，不要用 `--format json`。

## 笔记格式规范

> git-log 格式由 `jfox ingest-log` 自动处理，以下规范主要供理解输出结构参考，以及手动处理 GitHub PR/Issues 数据时使用。

| 数据源 | title 来源 | content 内容 | 额外标签 |
|--------|-----------|-------------|---------|
| git-log | commit subject | hash, author, date, body | `source:<repo-name>`, `source:git-log` |
| PR | PR 标题 | PR 编号, state, 描述, 关键评论 | `source:<repo-name>`, `source:pr` |
| Issue | Issue 标题 | Issue 编号, state, 描述, 评论 | `source:<repo-name>`, `source:issue` |

- 所有笔记都带有 `source:<repo-name>` 标签用于后续按仓库检索
- **Fleeting 笔记不含 `[[wiki links]]`** — 它们是原始数据捕获，链接在后续整理/精炼阶段添加（使用 `/jfox-organize`）

## GitLab 预留

对于非 GitHub 仓库（remote URL 中不包含 `github.com`），仅导入 git log。GitLab CLI 支持是未来的扩展方向。

## 命令参考

```bash
# 检测仓库类型
git -C path/to/repo remote get-url origin
gh auth status

# 采集 git log（一行完成提取+导入）
jfox ingest-log path/to/repo --limit 50 --kb name --type fleeting

# 采集 GitHub 数据
gh pr list --repo owner/repo --state all --limit 20 --json number,title,body,state,author,createdAt,updatedAt,labels
gh pr view number --repo owner/repo --json comments
gh issue list --repo owner/repo --state all --limit 30 --json number,title,body,state,author,createdAt,labels,comments

# 去重检查
jfox search "repo-name" --format json

# 导入 GitHub 数据
jfox bulk-import file.json --type fleeting --kb name

# 手动添加单条笔记
jfox add "content" --title "title" --type fleeting --kb name
```

## 错误处理

- **"Not a git repository"**: `jfox ingest-log` 会报错，提示用户提供正确的仓库路径
- **`gh: not found`** 或 `gh auth status` 失败: 跳过 GitHub PR/Issues 导入，仅用 `jfox ingest-log` 导入 git log
- **"Knowledge base not found"**: 提示用户先运行 `/jfox-common` 创建知识库
- **Bulk import 部分失败**: 报告成功/失败数量，失败记录不重试
