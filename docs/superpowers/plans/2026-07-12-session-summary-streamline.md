# session-summary skill 精简 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 4 个 `session-summary` SKILL.md 的两步 `AskUserQuestion`（内容确认 + 类型选择）删掉，固定 `--type session`，改为「生成 → 普通文本展示 → 直接写入」。反掉 #154 的摩擦，保留 #202 的 `session` 类型作默认。

**Architecture:** 纯 skill 文档改动，无 Python/CLI 变更。4 个变体各自保留平台措辞 / namespace / JSON 标志，只统一去掉确认流程并硬编码 `session` 类型。

**Tech Stack:** Markdown（SKILL.md）

**Spec:** `docs/superpowers/specs/2026-07-12-session-summary-streamline-design.md`
**Issue:** #311

## Global Constraints

- **分支**：`feat/issue-311-session-summary-streamline`（已建并提交 spec）。main 受保护，所有改动 PR 合入。
- **不抹平台特征**：每个变体的措辞（Claude Code / Kimi Code / 当前会话）、namespace（`/jfox:manage` / `/skill:jfox-manage` / `/jfox-common` / `/skill:jfox-common`）、JSON 标志（`--format json` / `--json`）必须原样保留，只动确认流程。
- **Step 编号连续**：改完不得出现「Step 3 选定的类型」之类悬挂引用。
- **中文注释/文档**。

## File Structure

| 文件 | 平台 | 动作 |
|---|---|---|
| `packages/cc-plugin/skills/session-summary/SKILL.md` | Claude Code | 改 |
| `packages/kimi-plugin/skills/jfox-session-summary/SKILL.md` | Kimi Code | 改 |
| `skills-recommend/pi/jfox-session-summary/SKILL.md` | pi agent | 改 |
| `skills-recommend/kimi-cli/jfox-session-summary/SKILL.md` | Kimi CLI（旧） | 改 |

每个文件 5 个统一改动点（详见 spec §4）：①开篇描述行；②删原 Step 2；③删原 Step 3；④原 Step 4→新 Step 2（`--type session`）；⑤原 Step 5→新 Step 3 + 命令参考段（`--type session`）。

---

## Task 1: cc-plugin 版

**Files:** `packages/cc-plugin/skills/session-summary/SKILL.md`

- [ ] 第 9 行描述：「（支持用户确认和笔记类型选择）」→「（session 类型，生成后直接写入）」
- [ ] 删原 Step 2「用户确认」整段（含 `AskUserQuestion` + 循环说明）
- [ ] 删原 Step 3「选择笔记类型」整段（含 4 选项）
- [ ] 原 Step 4 → 新 Step 2「展示总结并写入知识库」：普通文本输出 + 直接写入；`--type <Step 3 选定的类型>` → `--type session`；补「内容已在上方以普通文本展示，如需修改事后 `jfox edit`」
- [ ] 原 Step 5 → 新 Step 3「处理长内容」：`--content-file` 示例里 `--type <Step 3 选定的类型>` → `--type session`
- [ ] 命令参考段：`--type <type>` → `--type session`

---

## Task 2: kimi-plugin 版

**Files:** `packages/kimi-plugin/skills/jfox-session-summary/SKILL.md`

保留：措辞「Kimi Code」、namespace `/skill:jfox-manage`、JSON 标志 `--json`。

- [ ] 第 9 行描述同上改法
- [ ] 删原 Step 2 / Step 3（与 cc-plugin 同构）
- [ ] 原 Step 4 → 新 Step 2，`--type session`，保留 `--json`
- [ ] 原 Step 5 → 新 Step 3，`--type session`，保留 `--json`
- [ ] 命令参考段 `--type <type>` → `--type session`，保留 `--json`

---

## Task 3: skills-recommend/pi 版

**Files:** `skills-recommend/pi/jfox-session-summary/SKILL.md`

保留：措辞「Claude Code」、namespace `/jfox-common`、JSON 标志 `--format json`、独立「验证写入」段（`jfox show`）。

- [ ] 第 11 行描述同上改法
- [ ] 删原 Step 2 / Step 3
- [ ] 原 Step 4 → 新 Step 2，`--type session`，保留 `--format json`
- [ ] 原 Step 5 → 新 Step 3，`--type session`，保留 `--format json`
- [ ] 命令参考段 `--type <type>` → `--type session`

---

## Task 4: skills-recommend/kimi-cli 版（旧版，防漂移）

**Files:** `skills-recommend/kimi-cli/jfox-session-summary/SKILL.md`

保留：措辞「当前会话」、namespace `/skill:jfox-common`、JSON 标志 `--json`、多行 description frontmatter。

- [ ] 第 11 行描述同上改法
- [ ] 删原 Step 2 / Step 3
- [ ] 原 Step 4 → 新 Step 2，`--type session`，保留 `--json`
- [ ] 原 Step 5 → 新 Step 3，`--type session`，保留 `--json`
- [ ] 命令参考段 `--type <type>` → `--type session`

---

## Task 5: 验证 + PR

- [ ] `grep -rn "AskUserQuestion\|内容是否 OK\|选择笔记类型\|Step 3 选定的类型\|--type <type>" packages/cc-plugin/skills/session-summary packages/kimi-plugin/skills/jfox-session-summary skills-recommend/pi/jfox-session-summary skills-recommend/kimi-cli/jfox-session-summary` → 0 命中
- [ ] 4 文件均含 `--type session`
- [ ] 人工通读 cc-plugin 版，确认 Step 编号连续、无悬挂引用
- [ ] commit（spec + plan + 4 SKILL.md）
- [ ] push + `gh pr create`，PR 描述链接 #311，说明动机（撤销 #154 摩擦，保留 #202 session 默认）
- [ ] 快速自检：`uv run jfox add --help` 确认 `--type session` / `--topic` 参数仍在（应不变，#202 已实现）
