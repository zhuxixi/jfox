# JFox Claude Code Plugin Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add standard Claude Code plugin packaging to the jfox repo so users can install via marketplace.

**Architecture:** Add `.claude-plugin/` manifest and `commands/` slash commands at repo root. Existing `skills-recommend/claude-code/` skills are referenced by relative path, not moved.

**Tech Stack:** Claude Code plugin format (JSON manifests + Markdown commands)

**Spec:** `docs/superpowers/specs/2026-05-09-jfox-plugin-design.md`

---

## File Structure

| Action | File | Purpose |
|--------|------|---------|
| Create | `.claude-plugin/plugin.json` | Plugin manifest listing skills and commands |
| Create | `.claude-plugin/marketplace.json` | Marketplace index for `/plugin marketplace add` |
| Create | `commands/jfox-common.md` | Slash command → jfox-common skill |
| Create | `commands/jfox-ingest.md` | Slash command → jfox-ingest skill |
| Create | `commands/jfox-organize.md` | Slash command → jfox-organize skill |
| Create | `commands/jfox-search.md` | Slash command → jfox-search skill |
| Create | `commands/jfox-session-summary.md` | Slash command → jfox-session-summary skill |
| Create | `.gitignore` entry | Ignore nothing new — no changes needed |

No existing files are modified.

---

### Task 1: Create plugin manifest

**Files:**
- Create: `.claude-plugin/plugin.json`
- Create: `.claude-plugin/marketplace.json`

- [ ] **Step 1: Create `.claude-plugin/` directory and `plugin.json`**

```bash
mkdir -p .claude-plugin
```

Write `.claude-plugin/plugin.json`:

```json
{
  "name": "jfox",
  "description": "JFox 知识管理 CLI 的 Claude Code 集成——搜索、导入、整理、会话总结",
  "version": "0.1.0",
  "author": { "name": "zhuxixi" },
  "license": "MIT",
  "keywords": ["zettelkasten", "knowledge-management", "cli"],
  "skills": [
    "./skills-recommend/claude-code/jfox-common",
    "./skills-recommend/claude-code/jfox-ingest",
    "./skills-recommend/claude-code/jfox-organize",
    "./skills-recommend/claude-code/jfox-search",
    "./skills-recommend/claude-code/jfox-session-summary"
  ],
  "commands": [
    "./commands/jfox-common",
    "./commands/jfox-ingest",
    "./commands/jfox-organize",
    "./commands/jfox-search",
    "./commands/jfox-session-summary"
  ]
}
```

- [ ] **Step 2: Create `marketplace.json`**

Write `.claude-plugin/marketplace.json`:

```json
{
  "name": "jfox-skills",
  "id": "jfox-skills",
  "owner": { "name": "zhuxixi" },
  "metadata": {
    "description": "JFox Zettelkasten 知识管理工具的 Claude Code 集成",
    "version": "0.1.0"
  },
  "plugins": [
    {
      "name": "jfox",
      "source": "./",
      "description": "JFox 知识管理 CLI 的 Claude Code 集成——搜索、导入、整理、会话总结",
      "version": "0.1.0",
      "author": { "name": "zhuxixi" },
      "keywords": ["zettelkasten", "knowledge-management"],
      "category": "workflow"
    }
  ]
}
```

- [ ] **Step 3: Validate JSON**

Run: `python -c "import json; json.load(open('.claude-plugin/plugin.json')); json.load(open('.claude-plugin/marketplace.json')); print('OK')"`
Expected: `OK`

---

### Task 2: Create slash commands

**Files:**
- Create: `commands/jfox-common.md`
- Create: `commands/jfox-ingest.md`
- Create: `commands/jfox-organize.md`
- Create: `commands/jfox-search.md`
- Create: `commands/jfox-session-summary.md`

Each command file follows this pattern: YAML frontmatter with `name` and `description`, then a one-line instruction to invoke the corresponding skill.

- [ ] **Step 1: Create `commands/` directory**

```bash
mkdir -p commands
```

- [ ] **Step 2: Create `commands/jfox-common.md`**

```markdown
---
name: jfox-common
description: 管理知识库（创建、切换、健康检查）和笔记 CRUD
---

请调用 jfox-common skill 来完成用户的请求。传递用户提供的参数。
```

- [ ] **Step 3: Create `commands/jfox-ingest.md`**

```markdown
---
name: jfox-ingest
description: 从 Git 仓库导入数据（git log、PR、Issues）为 fleeting 笔记
---

请调用 jfox-ingest skill 来完成用户的请求。传递用户提供的参数。
```

- [ ] **Step 4: Create `commands/jfox-organize.md`**

```markdown
---
name: jfox-organize
description: 整理知识库、提炼 fleeting 笔记为 permanent、生成 wiki links
---

请调用 jfox-organize skill 来完成用户的请求。传递用户提供的参数。
```

- [ ] **Step 5: Create `commands/jfox-search.md`**

```markdown
---
name: jfox-search
description: 搜索笔记、图谱查询、链接推荐
---

请调用 jfox-search skill 来完成用户的请求。传递用户提供的参数。
```

- [ ] **Step 6: Create `commands/jfox-session-summary.md`**

```markdown
---
name: jfox-session-summary
description: 保存会话总结到知识库作为 fleeting 笔记
---

请调用 jfox-session-summary skill 来完成用户的请求。传递用户提供的参数。
```

---

### Task 3: Verify plugin loads correctly

This task is manual verification — no code to write.

- [ ] **Step 1: Add jfox repo as marketplace source**

In a Claude Code session (with the branch checked out and pushed):

```bash
/plugin marketplace add https://github.com/zhuxixi/jfox
```

Expected: Marketplace added successfully.

- [ ] **Step 2: Install jfox plugin**

```bash
/plugin marketplace install jfox
```

Expected: Plugin installed, 5 skills and 5 commands listed.

- [ ] **Step 3: Test a slash command**

```bash
/jfox-search 测试搜索
```

Expected: The jfox-search skill is triggered and searches the knowledge base.

---

### Task 4: Commit and update symlink

- [ ] **Step 1: Remove old symlinks from `~/.claude/skills/`**

```bash
rm ~/.claude/skills/jfox-common
rm ~/.claude/skills/jfox-ingest
rm ~/.claude/skills/jfox-organize
rm ~/.claude/skills/jfox-search
rm ~/.claude/skills/jfox-session-summary
```

These are no longer needed once the plugin is installed via marketplace.

- [ ] **Step 2: Commit all new files**

```bash
git add .claude-plugin/ commands/
git commit -m "feat: add Claude Code plugin packaging for jfox skills (#209)"
```

---

## Self-Review

**Spec coverage:** All sections covered — plugin.json (Task 1), marketplace.json (Task 1), commands (Task 2), installation flow (Task 3), symlink cleanup (Task 4).

**Placeholder scan:** No TBD/TODO. All file contents are fully specified.

**Type consistency:** Skill paths in plugin.json match actual directory names. Command names match skill names.
