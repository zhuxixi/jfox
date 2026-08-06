# session-to-permanent CC + Kimi 适配 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans (inline 执行，本 session 内)。Steps use checkbox (`- [ ]`)。

**Goal:** 把 pi 的 session-to-permanent skill 适配到 CC + Kimi 两平台，一个 PR 合并后关闭 #317。

**Architecture:** 以 pi `skills-recommend/pi/jfox-session-to-permanent/SKILL.md`（#366）为基底，CC/Kimi 各出一版 SKILL.md（改交叉引用前缀、审阅交互改 AskUserQuestion、`--kb` 显式），并同步 CC `using-jfox` + Kimi `README.md` + Kimi `using-jfox` 三个入口文件。纯文档改动，无代码、无测试。

**Tech Stack:** Markdown skill 文件（YAML frontmatter + 正文），jfox CLI 命令引用。

## Global Constraints

- 纯文档 skill：不改 jfox CLI 代码、不改 manifest（`plugin.json`/`kimi.plugin.json`）、不动 pi 版文件
- 三平台核心内容一致：五步流程（提取→去重→起草→审阅→落库）+ 去重/审阅两硬约束 + clear-reports 写作规范
- 命名：CC 无前缀 `session-to-permanent`；Kimi 带 `jfox-` 前缀 `jfox-session-to-permanent`
- 交叉引用：CC `/jfox:xxx`；Kimi `/skill:jfox-xxx`
- 审阅交互（Step 4）：两平台均改用 **AskUserQuestion** 四选项（全部写入/跳过某条/改某条/其他），保留 pi 的分批 ≤5、二次选择、批次间确认；用概念描述（`question`+`options[{label,description}]`），不写死平台 API
- `--kb`：CC/Kimi 显式 `--kb <kb-name>`（跟 session-summary 一致），不沿用 pi 写死默认库；命令示例保持 `--json`
- 所有产物在 worktree 内产生并提交，**禁碰 main**；`git add <file>` 按文件 stage，不用 `git add -A`

## File Structure

**新增：**
- `packages/cc-plugin/skills/session-to-permanent/SKILL.md` — CC 版（无前缀）
- `packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md` — Kimi 版（jfox- 前缀）

**修改：**
- `packages/cc-plugin/skills/using-jfox/SKILL.md` — 路由表 + 职责列表 + 会话沉淀工作流
- `packages/kimi-plugin/README.md` — 9→10 skill 表 + 文件结构树 + 差异表核心技能清单
- `packages/kimi-plugin/skills/using-jfox/SKILL.md` — 术语映射表 + 跨 skill 引用语法

**只读基底/参照：**
- `skills-recommend/pi/jfox-session-to-permanent/SKILL.md`（pi 范本，#366）
- `packages/cc-plugin/skills/session-summary/SKILL.md`、`packages/kimi-plugin/skills/jfox-session-summary/SKILL.md`（frontmatter 风格参照）

---

## Task 0: 落 spec + plan 进 worktree（首 commit）

**Files:**
- Create: `docs/superpowers/specs/2026-08-07-session-to-permanent-cc-kimi-design.md`（从 `~/.claude/.../spec.md` 搬入）
- Create: `docs/superpowers/plans/2026-08-07-session-to-permanent-cc-kimi.md`（从 `~/.claude/.../plan.md` 搬入）

- [ ] Step 1: `EnterWorktree` name=`issue-317-session-to-permanent-cc-kimi`
- [ ] Step 2: 把 spec + plan 内容写入 worktree 的 docs/superpowers/{specs,plans}/
- [ ] Step 3: `git add docs/superpowers/specs/... docs/superpowers/plans/...` + commit `docs(skill): session-to-permanent CC+Kimi 适配 spec 与 plan`

---

## Task 1: CC 版 SKILL.md

**Files:**
- Create: `packages/cc-plugin/skills/session-to-permanent/SKILL.md`
- 只读基底: `skills-recommend/pi/jfox-session-to-permanent/SKILL.md`

**Interfaces:** 产出 CC 版完整 SKILL.md；Task 3 同步 `using-jfox` 时引用本 skill 名 `session-to-permanent`。

**改动点（相对 pi 范本，逐条）：**
1. frontmatter `name: jfox-session-to-permanent` → `name: session-to-permanent`（CC 无前缀）；description 英文+触发词保持不变
2. 正文所有 `/skill:jfox-common` → `/jfox:manage`（§4.1/§4.2/§4.5/§6 共享约定、add 参数、写入验证、daemon）
3. `/skill:jfox-promote` → `/jfox:promote`（含 §6 suggest-links 误命中坑引用）
4. `/skill:jfox-organize` → `/jfox:organize`（Step 3 图谱健康度目标）
5. 「前置条件」里 pi 的「默认知识库，下文命令一律不带 `--kb`（与原 #365 一致）」整段 → 改为「确认目标知识库（通过 `--kb` 或当前默认）」，呼应 `/jfox:manage` §4.1；命令示例一律补 `--kb <kb-name>`
6. Step 4 审阅交互：pi 的 `question(question=..., options=[...])` 伪代码块 → 改写为 AskUserQuestion 概念描述。保留四选项语义（全部写入/跳过某条/改某条/其他）、二次选择列草稿编号、分批 ≤5、批次间继续确认。措辞参照：「展示完草稿后，调用 AskUserQuestion 出选择题（每个选项给 label 和 description）」
7. 「关键约束」末条「默认知识库：pi 平台默认不带 `--kb`」→ 删除或改为 CC 的 `--kb` 显式约定
8. 命令示例 `--json` 保持不变（与 `/jfox:manage` §4.1 公共约定一致）

**验证（grep，worktree 根目录）：**
- `grep -rn '/skill:jfox' packages/cc-plugin/skills/session-to-permanent/` → 零命中
- `grep -rn 'question(' packages/cc-plugin/skills/session-to-permanent/` → 零命中
- `grep -rn '/jfox:manage\|/jfox:promote\|/jfox:organize' packages/cc-plugin/skills/session-to-permanent/` → 有命中

- [ ] Step 1: 读 pi 范本全文作基底
- [ ] Step 2: 生成 CC 版 SKILL.md（上述 8 点）
- [ ] Step 3: 跑三条 grep 校验
- [ ] Step 4: `git add packages/cc-plugin/skills/session-to-permanent/SKILL.md` + commit `feat(cc-plugin): add session-to-permanent skill (#317)`

---

## Task 2: Kimi 版 SKILL.md

**Files:**
- Create: `packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md`
- 只读基底: 同 Task 1

**改动点（相对 pi 范本）：**
1. frontmatter `name: jfox-session-to-permanent`（Kimi 带前缀，与 pi 同名、目录不同）；description 保持
2. 正文所有 `/skill:jfox-common` → `/skill:jfox-manage`（Kimi 无 common，对应 manage）
3. `/skill:jfox-promote`、`/skill:jfox-organize` → 保持（Kimi 也是这名）
4. 「前置条件」默认库段 → 显式 `--kb`（同 Task 1 点 5），引用 `/skill:jfox-manage` §4.1
5. Step 4 `question(...)` → AskUserQuestion 概念描述（同 Task 1 点 6）
6. 「关键约束」默认库条 → 改为 Kimi 的 `--kb` 显式约定
7. 命令 `--json` 保持

**验证（grep）：**
- `grep -rn '/skill:jfox-common' packages/kimi-plugin/skills/jfox-session-to-permanent/` → 零命中（Kimi 无 common）
- `grep -rn 'question(' packages/kimi-plugin/skills/jfox-session-to-permanent/` → 零命中
- `grep -rn '/skill:jfox-manage\|/skill:jfox-promote\|/skill:jfox-organize' packages/kimi-plugin/skills/jfox-session-to-permanent/` → 有命中

- [ ] Step 1: 读 pi 范本作基底
- [ ] Step 2: 生成 Kimi 版 SKILL.md（上述 7 点）
- [ ] Step 3: 跑三条 grep 校验
- [ ] Step 4: `git add packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md` + commit `feat(kimi-plugin): add jfox-session-to-permanent skill (#317)`

---

## Task 3: 同步 CC `using-jfox`

**Files:** Modify `packages/cc-plugin/skills/using-jfox/SKILL.md`

**改动：**
1. 路由表「我该用哪个 skill」（当前 5 行）加第 6 行：
   `| 从当前会话提炼可复用知识为 permanent | \`session-to-permanent\` | 提炼到永久笔记 / session to permanent |`
2. 「N 个 skill 一句话职责」5 → 6，在 session-summary 后加：
   `- **session-to-permanent** — 当前会话 → permanent（先比对已有 permanent 去重，审阅后落库）。`
3. 复合工作流「会话沉淀」当前 `session-summary（存入）→ organize（提炼要点为 permanent）` → 改为按需分流：
   `2. **会话沉淀**：会话末尾按需选择——\`session-summary\`（整段对话存档）或 \`session-to-permanent\`（提炼可复用知识为 permanent，先去重再审阅落库）。`

**验证：**
- `grep -c 'session-to-permanent' packages/cc-plugin/skills/using-jfox/SKILL.md` → ≥3

- [ ] Step 1: 三处 Edit
- [ ] Step 2: grep 校验
- [ ] Step 3: commit `docs(cc-plugin): using-jfox 路由表加 session-to-permanent (#317)`

---

## Task 4: 同步 Kimi `README.md`

**Files:** Modify `packages/kimi-plugin/README.md`

**改动：**
1. 第 7 行「9 个核心 skill」→「10 个核心 skill」
2. 功能表在 `jfox-session-summary` 行后加：
   `| \`jfox-session-to-permanent\` | 从当前会话提炼可复用知识为 permanent（先去重、审阅后落库） | "提炼到永久笔记"、"session to permanent" |`
3. 文件结构树在 `jfox-session-summary/` 块后加：
   ```
       ├── jfox-session-to-permanent/
       │   └── SKILL.md
   ```
4. 「与 Claude Code 插件的差异」表「核心技能」行：CC 列追加 `session-to-permanent`，Kimi 列追加 `jfox-session-to-permanent`

**验证：**
- `grep -c 'jfox-session-to-permanent' packages/kimi-plugin/README.md` → ≥3
- `grep '10 个核心 skill' packages/kimi-plugin/README.md` → 有命中

- [ ] Step 1: 四处 Edit
- [ ] Step 2: grep 校验
- [ ] Step 3: commit `docs(kimi-plugin): README 加 jfox-session-to-permanent (#317)`

---

## Task 5: 同步 Kimi `using-jfox`

**Files:** Modify `packages/kimi-plugin/skills/using-jfox/SKILL.md`

**改动：**
1. 术语映射表（当前 6 行）在 `保存会话` 行后加：
   `| 会话提炼永久笔记、session to permanent | \`/skill:jfox-session-to-permanent\` |`
2. 「跨 Skill 引用语法」列表在 `/skill:jfox-session-summary` 后加：
   `/skill:jfox-session-to-permanent`

**验证：**
- `grep -c 'jfox-session-to-permanent' packages/kimi-plugin/skills/using-jfox/SKILL.md` → ≥2

- [ ] Step 1: 两处 Edit
- [ ] Step 2: grep 校验
- [ ] Step 3: commit `docs(kimi-plugin): using-jfox 术语表加 session-to-permanent (#317)`

---

## Task 6: 整体一致性校验 + 本地 CR

**Files:** 全仓 grep 核对

- [ ] Step 1: `grep -rn 'session-to-permanent' packages/ skills-recommend/ docs/` 输出位置清单，核对三平台 + 入口文件无遗漏、无残留旧副本
- [ ] Step 2: 三平台交叉引用一致性核对（CC `/jfox:`、Kimi `/skill:jfox-`、pi 不动）
- [ ] Step 3: frontmatter name 三平台正确（CC `session-to-permanent` / Kimi+pi `jfox-session-to-permanent`）
- [ ] Step 4: 触发词覆盖（`session to permanent` / `提炼到永久笔记` / `会话沉淀永久笔记` 三平台都在）
- [ ] Step 5: 本地 CR——`superpowers:requesting-code-review` 或 `/code-review`（必做，深度自定）
- [ ] Step 6: 按 CR 反馈修，lint 不涉及（纯 md）

---

## Task 7: 开 PR + 打 Zima 标签

- [ ] Step 1: `git push -u origin issue-317-session-to-permanent-cc-kimi`
- [ ] Step 2: `gh pr create`（title: `feat(skills): add session-to-permanent skill for CC + Kimi (#317)`，body 含验收对照 + 关闭说明）
- [ ] Step 3: `gh pr edit <N> --add-label zima:needs-review`
- [ ] Step 4: 进入 zima-pr-monitor 监听双 Bot CR

---

## Self-Review（对照 spec）

- **spec 覆盖**：三差异维度（交叉引用 Task1/2、审阅交互 Task1/2 点6、--kb Task1/2 点5/7）✓；新增 2 SKILL.md（Task1/2）✓；同步 3 入口（Task3/4/5）✓；不改 manifest（Global Constraints）✓；验收 8 条（Task6 校验）✓
- **placeholder 扫描**：无 TBD/TODO；改动点均给出具体替换规则与表格行原文；pi 范本为现成基底非占位 ✓
- **一致性**：skill 名 CC `session-to-permanent` / Kimi `jfox-session-to-permanent` 全 plan 统一 ✓
