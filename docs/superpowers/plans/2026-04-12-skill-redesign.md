# JFox Skill Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Redesign jfox skills from 5 independent skills (init, insert, organize, search, health) into 4 focused skills (ingest, organize, search, common) that better support the user's workflow: import → organize → search.

**Architecture:** Pure content authoring — write 4 SKILL.md files as Markdown. No code, no tests, no build steps. Each SKILL.md is a prompt template that tells an AI agent which jfox CLI commands to run and in what order.

**Tech Stack:** Markdown (SKILL.md frontmatter + body). Target directory: `skills-recommend/claude-code/`.

---

## File Structure

```
skills-recommend/claude-code/
├── jfox-ingest/SKILL.md       # NEW — data import from repos
├── jfox-organize/SKILL.md     # REWRITE — refine + enhance with wiki link generation
├── jfox-search/SKILL.md       # TRIM — remove literature references, dedup
├── jfox-common/SKILL.md       # NEW — merge of init + health
├── jfox-init/SKILL.md         # DELETE
├── jfox-insert/SKILL.md       # DELETE
└── jfox-health/SKILL.md       # DELETE
```

Each SKILL.md has:
- YAML frontmatter: `name`, `description` (with trigger phrases)
- Body: overview, prerequisites, workflow steps, command reference, error handling

---

### Task 1: Create jfox-ingest SKILL.md

**Files:**
- Create: `skills-recommend/claude-code/jfox-ingest/SKILL.md`

- [ ] **Step 1: Create the directory**

```bash
mkdir -p skills-recommend/claude-code/jfox-ingest
```

- [ ] **Step 2: Write jfox-ingest/SKILL.md**

Write the complete file with these sections:

**Frontmatter:**
```yaml
---
name: jfox-ingest
description: Use when user wants to import data from a local git repository into their Zettelkasten as fleeting notes. Triggers on "导入仓库", "导入 git log", "导入 PR", "导入 issues", "读一下这个仓库", "抓取仓库信息", "ingest repo", "import notes from repository", "bulk import from git", "导入项目信息".
---
```

**Body structure (write in Chinese, following existing skill conventions):**

1. **概述**: Briefly describe the skill's purpose — import git log, GitHub PRs, and GitHub Issues from a local repository as fleeting notes.

2. **前置条件**: Knowledge base must exist (`jfox kb list` to check). `git` must be available. For GitHub data, `gh cli` must be authenticated (`gh auth status`).

3. **工作流** — 7 steps:
   - **Step 1: 确定仓库信息** — User provides local path. Run `git -C <path> remote get-url origin` to detect if it's a GitHub repo (check for `github.com` in URL). Extract `owner/repo` from the URL.
   - **Step 2: 选择数据源** — Based on user's instruction, determine which sources to import: git-log, github-pr, github-issue, or all. If user says "导入这个仓库" without specifying, default to all available sources.
   - **Step 3: 采集 git log** — Run:
     ```bash
     git -C <path> log --format="%H|%s|%b|%an|%ad" --date=short -50
     ```
     Parse output: each line is one commit. Structure each into `{title, content, tags}` where title = commit subject, content = hash + body + author + date, tags = `source:<repo-name>`, `source:git-log`.
   - **Step 4: 采集 GitHub PRs** (only if GitHub repo detected):
     ```bash
     gh pr list --repo <owner/repo> --state all --limit 20 --json number,title,body,state,author,createdAt,updatedAt,labels
     ```
     For each PR, optionally fetch comments: `gh pr view <number> --repo <owner/repo> --json comments`. Structure each into `{title, content, tags}` where title = PR title, content = description + comments + metadata, tags = `source:<repo-name>`, `source:pr`.
   - **Step 5: 采集 GitHub Issues** (only if GitHub repo detected):
     ```bash
     gh issue list --repo <owner/repo> --state all --limit 30 --json number,title,body,state,author,createdAt,labels,comments
     ```
     Structure each into `{title, content, tags}` where title = Issue title, content = description + comments + metadata, tags = `source:<repo-name>`, `source:issue`.
   - **Step 6: 去重与导入** — Before importing, check for duplicates. Run `jfox search --tag "source:<repo-name>" --format json` to see what's already imported. Only import new records. Generate a temporary JSON file with the records array, then run:
     ```bash
     jfox bulk-import <temp-file.json> --type fleeting [--kb <name>]
     ```
     Note: `jfox bulk-import` uses `--json`/`--no-json` (default: on), NOT `--format json`.
   - **Step 7: 确认报告** — Report how many notes were imported, broken down by source type (e.g., "导入了 50 条 git log + 15 条 PR + 10 条 Issues，共 75 条 fleeting 笔记到 homework 知识库").

4. **手动输入支持**: If user directly pastes text (no repo path), structure it as a single fleeting note and insert with `jfox add "<content>" --title "<title>" --type fleeting --tag <tags>`.

5. **笔记格式规范**: Specify the format for each note type:
   - Git log note: title = commit subject, content includes hash, author, date, body
   - PR note: title = PR title, content includes PR number, state, description, key comments
   - Issue note: title = Issue title, content includes issue number, state, description, key comments
   - All notes get `source:<repo-name>` tag and a `source:git-log`/`source:pr`/`source:issue` tag
   - Fleeting notes do NOT get `[[wiki links]]`

6. **GitLab 预留**: Note that for non-GitHub repos (no `github.com` in remote URL), only git log is imported. GitLab CLI support is a future extension.

7. **命令参考**:
   ```bash
   # 检测仓库类型
   git -C <path> remote get-url origin
   gh auth status

   # 采集数据
   git -C <path> log --format="%H|%s|%b|%an|%ad" --date=short -50
   gh pr list --repo <owner/repo> --state all --limit 20 --json number,title,body,state,author,createdAt,updatedAt,labels
   gh pr view <number> --repo <owner/repo> --json comments
   gh issue list --repo <owner/repo> --state all --limit 30 --json number,title,body,state,author,createdAt,labels,comments

   # 去重检查
   jfox search --tag "source:<repo-name>" --format json

   # 导入
   jfox bulk-import <file.json> --type fleeting [--kb <name>]
   jfox add "<content>" --title "<title>" --type fleeting [--kb <name>]
   ```

8. **错误处理**:
   - "Not a git repository" → 提示用户提供正确的仓库路径
   - "gh: not found" 或 `gh auth status` 失败 → 跳过 GitHub PR/Issues 导入，只导入 git log
   - "Knowledge base not found" → 提示先运行 `jfox init` 或 `/jfox-common`
   - Bulk import 部分失败 → 报告成功/失败数量，失败记录不重试

- [ ] **Step 3: Verify the file was written correctly**

```bash
head -5 skills-recommend/claude-code/jfox-ingest/SKILL.md
```

Expected: YAML frontmatter with `name: jfox-ingest`

- [ ] **Step 4: Commit**

```bash
git add skills-recommend/claude-code/jfox-ingest/SKILL.md
git commit -m "feat(skills): add jfox-ingest skill for repo data import"
```

---

### Task 2: Create jfox-common SKILL.md

**Files:**
- Create: `skills-recommend/claude-code/jfox-common/SKILL.md`

- [ ] **Step 1: Create the directory**

```bash
mkdir -p skills-recommend/claude-code/jfox-common
```

- [ ] **Step 2: Write jfox-common/SKILL.md**

This skill merges the existing jfox-init and jfox-health content. Write the complete file with these sections:

**Frontmatter:**
```yaml
---
name: jfox-common
description: Use when user wants to create, manage, or check the health of a Zettelkasten knowledge base. Triggers on "创建知识库", "初始化", "知识库管理", "检查知识库", "知识库健康", "知识库体检", "health check", "create knowledge base", "init", "kb management", "知识库诊断".
---
```

**Body structure (write in Chinese):**

1. **概述**: Knowledge base lifecycle management and health monitoring. Combines KB creation/management with periodic health checks.

2. **前置条件**: `jfox` CLI installed (`jfox --version`). For GitHub health features, `gh cli` optional.

3. **知识库管理**:
   - **检查现有知识库**: `jfox kb list --format json`
   - **创建知识库**: `jfox init --name <name> --desc "<description>"`. If KB already exists, suggest `jfox kb switch <name>`.
   - **切换/管理**: `jfox kb switch <name>`, `jfox kb info <name> --format json`, `jfox kb current --format json`, `jfox kb rename <old> <new>`
   - **删除**: `jfox kb remove <name>` (保留文件) or `jfox kb remove <name> --force` (含文件，不可恢复)
   - **查看状态**: `jfox status --format json`

   All commands support `--kb <name>` to target a specific KB.

4. **健康检查** — Copy the health check system from the existing `jfox-health/SKILL.md` with these adjustments:
   - **6 项指标采集**: Same as existing health skill (status, graph stats, orphans, index verify, note list, inbox)
   - **健康指标表**: Keep the same thresholds (orphan ratio, avg degree, inbox backlog, index integrity, connectivity ratio, type balance)
   - **衰减信号**: Keep all 5 patterns (知识孤岛, Inbox 积压, 低连接度, 索引失效, Hub 依赖)
   - **评分系统**: Keep the same 0-100 scoring formula and A/B/C/D/F grades
   - **报告格式**: Keep the same emoji-based report format with `📊 知识库健康报告[KB: {kb_name}]`
   - **移除**: Remove any literature-specific references

5. **命令参考**: Consolidated command reference for both KB management and health check. Do NOT duplicate commands that belong to other skills (search, ingest, organize). Only include commands specific to KB lifecycle and health monitoring.

6. **错误处理**: From existing init + health skills, consolidated. Remove literature-specific errors.

- [ ] **Step 3: Verify the file was written correctly**

```bash
head -5 skills-recommend/claude-code/jfox-common/SKILL.md
```

Expected: YAML frontmatter with `name: jfox-common`

- [ ] **Step 4: Commit**

```bash
git add skills-recommend/claude-code/jfox-common/SKILL.md
git commit -m "feat(skills): add jfox-common skill merging init and health"
```

---

### Task 3: Rewrite jfox-organize SKILL.md

**Files:**
- Modify: `skills-recommend/claude-code/jfox-organize/SKILL.md` (full rewrite)

- [ ] **Step 1: Read the existing file for reference**

Read `skills-recommend/claude-code/jfox-organize/SKILL.md` to understand the current structure. Also read `skills-recommend/claude-code/jfox-insert/SKILL.md` to absorb the note creation commands that will move into organize.

- [ ] **Step 2: Rewrite jfox-organize/SKILL.md**

**Frontmatter (update):**
```yaml
---
name: jfox-organize
description: Use when user wants to organize their Zettelkasten, refine fleeting notes into permanent notes, add wiki links, or optimize the knowledge graph. Triggers on "整理知识库", "清理 inbox", "提炼笔记", "组织笔记", "看看有什么可以整理的", "合并笔记", "生成链接", "organize", "process inbox", "refine notes", "knowledge graph optimization".
---
```

**Body structure (write in Chinese):**

1. **概述**: The core refinement skill. Transforms raw fleeting notes into well-connected permanent knowledge. Three-step process: inbox analysis → refinement → graph optimization.

2. **前置条件**: Knowledge base has notes. If empty, suggest running `/jfox-ingest` first.

3. **Step 1: Inbox 分析**:
   - `jfox inbox --json --limit 50` to list all fleeting notes
   - Group notes by `source:*` tag (e.g., all `source:git-log` notes from the same repo together)
   - Within each group, identify mergeable sub-groups (similar topics, related commits in the same PR)
   - Present refinement suggestions to user in this format:
     ```
     收件箱: N 条 fleeting 笔记

     提炼建议:
     1. [合并] 15 条 jfox git-log commits → "JFox 近期开发总结" (permanent)
     2. [合并] 5 条 jfox PR → "JFox PR 技术决策汇总" (permanent)
     3. [逐条] 3 条手动输入笔记 → 逐条处理
     4. [删除] 2 条过时笔记 → 清理
     ```
   - Ask user to confirm which suggestions to execute

4. **Step 2: 提炼（fleeting → permanent）**:
   For each confirmed suggestion:
   - Analyze the grouped fleeting notes and extract core knowledge points
   - Run `jfox suggest-links "<content>" --format json` to find existing related notes (threshold >= 0.6)
   - Generate a permanent note with `[[wiki links]]` embedded for each related note found
   - Also check if other permanent notes being created in this batch are related — cross-link them
   - Insert the permanent note:
     ```bash
     jfox add "<content with [[links]]>" --title "<title>" --type permanent --tag <tag1> --tag <tag2> [--kb <name>]
     ```
   - Delete the source fleeting notes:
     ```bash
     jfox delete <original-id> --force
     ```
   Note: `jfox add` and `jfox delete` use `--json`/`--no-json` (default: on), NOT `--format json`.

   **提炼策略表**:
   | 来源 | 策略 | permanent 示例 |
   |------|------|---------------|
   | git-log (多个 commits) | 按时间段/主题合并，提取技术决策和变更摘要 | "JFox v0.1.4 技术变更总结" |
   | github-pr (多个 PRs) | 提取核心设计决策、争议点、最终方案 | "JFox PR#94 编辑命令的设计讨论" |
   | github-issue (多个 issues) | 提取问题本质、解决方案、经验教训 | "JFox BM25 索引问题及修复方案" |
   | 手动输入 | 根据内容判断是否值得提炼，可保留为 fleeting | — |

5. **Step 3: 图谱优化**:
   - `jfox graph --orphans --json` — find isolated notes
   - For each orphan permanent note, run `jfox suggest-links "<content>" --format json`
   - If good matches found (score >= 0.6), suggest adding `[[links]]`:
     ```bash
     jfox edit <orphan_id> --content "原内容... [[相关笔记标题]]"
     ```
   - `jfox graph --stats --json` — confirm improvement
   - Report: before/after comparison of avg_degree, isolated_nodes

6. **直接创建笔记** (absorbed from jfox-insert):
   During the organize workflow, the user may want to directly create a note without going through ingest. Support this:
   - `jfox add "<content>" --title "<title>" --type <fleeting|permanent> --tag <tags> [--kb <name>]`
   - For permanent notes, run `jfox suggest-links` first to find `[[wiki links]]` to embed
   - `jfox edit <note_id> --content "新内容" --title "新标题" --tag <tag>` for editing existing notes

7. **命令参考**:
   ```bash
   # Inbox 管理
   jfox inbox --json --limit <N>
   jfox add "<content>" --type permanent --title "<title>" --tag <tags>
   jfox edit <id> --content "新内容"
   jfox delete <id> --force

   # 链接与图谱
   jfox suggest-links "<content>" --format json
   jfox graph --orphans --json
   jfox graph --stats --json

   # 辅助
   jfox list --format json --limit <N>
   jfox daily --json
   ```
   Do NOT include commands that belong to other skills (search queries, health checks, KB management, data ingestion).

8. **错误处理**:
   - Empty inbox → "收件箱为空，无需整理"
   - `jfox suggest-links` 返回低分 → 跳过链接推荐，不影响提炼
   - `jfox delete` on non-existent ID → 报告错误，跳过继续
   - Note: `jfox add` and `jfox edit` use `--json`/`--no-json` (default: on), NOT `--format json`

- [ ] **Step 3: Verify the file was written correctly**

```bash
head -5 skills-recommend/claude-code/jfox-organize/SKILL.md
```

Expected: Updated frontmatter with new description including "refine", "wiki links"

- [ ] **Step 4: Commit**

```bash
git add skills-recommend/claude-code/jfox-organize/SKILL.md
git commit -m "feat(skills): rewrite jfox-organize with refinement and wiki link generation"
```

---

### Task 4: Trim jfox-search SKILL.md

**Files:**
- Modify: `skills-recommend/claude-code/jfox-search/SKILL.md`

- [ ] **Step 1: Read the existing file**

Read `skills-recommend/claude-code/jfox-search/SKILL.md` to understand what to keep and what to trim.

- [ ] **Step 2: Trim the file**

Specific changes:
- Remove any literature-related search filters or examples
- Remove `--type literature` from command examples
- Remove the literature note type from any type selection tables
- Keep ALL search strategy content (hybrid, keyword, semantic, graph query, backlinks, link suggestions)
- Keep ALL command references for search/query/refs/suggest-links
- Keep multi-KB search support (`--kb <name>`)
- Keep error handling
- Do NOT add commands from other skills
- Keep the frontmatter description as-is (it doesn't mention literature)

- [ ] **Step 3: Verify the file has no literature references**

```bash
grep -i "literature" skills-recommend/claude-code/jfox-search/SKILL.md
```

Expected: No output (no matches)

- [ ] **Step 4: Commit**

```bash
git add skills-recommend/claude-code/jfox-search/SKILL.md
git commit -m "refactor(skills): trim jfox-search, remove literature references"
```

---

### Task 5: Delete obsolete skills and update README

**Files:**
- Delete: `skills-recommend/claude-code/jfox-init/SKILL.md`
- Delete: `skills-recommend/claude-code/jfox-insert/SKILL.md`
- Delete: `skills-recommend/claude-code/jfox-health/SKILL.md`
- Delete: `skills-recommend/claude-code/jfox-init/` (empty directory)
- Delete: `skills-recommend/claude-code/jfox-insert/` (empty directory)
- Delete: `skills-recommend/claude-code/jfox-health/` (empty directory)
- Modify: `skills-recommend/README.md`

- [ ] **Step 1: Delete the three obsolete skill directories**

```bash
rm -rf skills-recommend/claude-code/jfox-init
rm -rf skills-recommend/claude-code/jfox-insert
rm -rf skills-recommend/claude-code/jfox-health
```

- [ ] **Step 2: Verify deletion**

```bash
ls skills-recommend/claude-code/
```

Expected: Only `jfox-common`, `jfox-ingest`, `jfox-organize`, `jfox-search`

- [ ] **Step 3: Update README.md**

Read `skills-recommend/README.md`. Rewrite it to reflect the new 4-skill structure:
- Update the directory tree to show the 4 new skills
- Update the skill list (`/jfox-common`, `/jfox-ingest`, `/jfox-organize`, `/jfox-search`)
- Update the usage instructions (copy to `~/.claude/skills/`)
- Update the platform adaptation table if needed
- Remove references to deleted skills (init, insert, health)

- [ ] **Step 4: Commit**

```bash
git add -A skills-recommend/
git commit -m "refactor(skills): remove obsolete init/insert/health skills, update README"
```

---

### Task 6: Final verification

**Files:** None (verification only)

- [ ] **Step 1: Verify directory structure**

```bash
ls -R skills-recommend/claude-code/
```

Expected: Exactly 4 directories, each with exactly 1 SKILL.md:
```
jfox-common/SKILL.md
jfox-ingest/SKILL.md
jfox-organize/SKILL.md
jfox-search/SKILL.md
```

- [ ] **Step 2: Verify all frontmatter is valid**

```bash
for f in skills-recommend/claude-code/*/SKILL.md; do
  echo "=== $f ==="
  head -3 "$f"
  echo
done
```

Expected: Each file starts with `---` and has `name:` and `description:` fields.

- [ ] **Step 3: Verify no literature references remain in any skill**

```bash
grep -ri "literature" skills-recommend/claude-code/
```

Expected: No output (literature has been removed from all skills as specified).

- [ ] **Step 4: Verify no cross-skill command duplication**

Spot-check: `jfox suggest-links` should appear in both organize (for refinement) and search (for discovery) — this is OK since they serve different purposes. `jfox init` should ONLY appear in common. `jfox bulk-import` should ONLY appear in ingest.

- [ ] **Step 5: Verify README matches reality**

```bash
ls skills-recommend/claude-code/ | sort
```

Compare output with the directory tree in README.md — they must match exactly.
