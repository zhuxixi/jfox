# Skill 体系同步 #399（overview 清理 + jfox-judge）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 清理 `jfox-overview` 的 3 处 gem-synth 退役引用，新建端到端 `jfox-judge` skill（判断 prompt → 确认晋升笔记），使 skill 体系与 1.14.0 命令面一致。

**Architecture:** 纯文档 PR，不改代码。两个独立文件：新建 `skills-recommend/pi/jfox-judge/SKILL.md`（端到端操作手册），修改 `skills-recommend/pi/jfox-overview/SKILL.md`（退役引用清理 + 新增路由行）。验证为 static（grep 断言）+ build（markdownlint + CI）。

**Tech Stack:** Markdown（markdownlint-cli2 门禁）、jfox CLI 1.14.0 命令面。

## Global Constraints

- 命令与参数以 `docs/cli-descriptions.yaml` 和实际 `jfox --help` 输出为准，不编造（本 plan 中所有命令均已核实，照抄即可）。
- skill 命名只用简单英文词（考研词汇量内）：`jfox-judge`。
- 触发词必须覆盖：「判断 prompt」「prompts judge」「prompt 积压」「处置判断结果」。
- markdownlint 必须 0 issues（CI lint job 门禁）；不动 `docs/cli-descriptions.yaml`（drift gate 天然 CLEAN）。
- 不改 `packages/*`（plugin-inventory 不涉及 `skills-recommend/`）、不改 jfox-promote 内容。
- 不改写 overview 其他章节（仅 spec §4 清单内的 5 处）。
- 所有编辑在 worktree 内：`WT=/home/elling/git-repo/github/jfox/.pi/worktrees/issue-513-skill-sync-399-overview-jfox-judge`。
- commit 用 conventional commits；`git add <file>` 按文件 stage，禁止 `git add -A`。

---

### Task 1: 新建 jfox-judge skill（端到端）

**Files:**

- Create: `skills-recommend/pi/jfox-judge/SKILL.md`

**Interfaces:**

- Consumes: 无（独立新文件）
- Produces: `jfox-judge` skill 路径与 frontmatter（Task 2 的 overview 路由行引用该 skill 名与触发词）

- [ ] **Step 1: 创建 skill 全文**

创建目录与文件 `skills-recommend/pi/jfox-judge/SKILL.md`，内容如下（逐字）：

````markdown
---
name: jfox-judge
description: |
  把 jfox 采集的 user prompt 判断、合成 candidate 并确认晋升的端到端工作流。
  judge 仅手动触发，agent 只起草不晋升——new 类的草稿逐条给你确认后才 promote。
  Triggers on: "判断 prompt", "prompts judge", "prompt 积压", "处置判断结果",
  "待解决问题清单", "judge prompts", "prompt 合成笔记", "prompt 转笔记".
---

# 判断 prompt 并沉淀笔记（端到端）

本 skill 处理 jfox 采集的 user prompt：判断哪些值得沉淀，合成 candidate（候选笔记，破损级草稿），逐条确认晋升 permanent（永久笔记）或拒绝。judge 只在你调用时运行（无后台循环）；agent 只负责分类、取证、起草，**晋升决策始终由你做**。

日常增量（几条到几十条）用本 skill 端到端走完；**pending 积压超过 50 条或存量清理时切 `jfox-promote`**（三模式大积压过审，见末节分工）。

## 标准流程

### Step 1：看积压

```bash
jfox prompts status
```

输出计数：`total_prompts`（总记录）/ `unjudged`（未判断）/ `failed`（判断失败）/ `pending_disposition`（已判断待处置）/ `active_unresolved`（待解决问题）。`unjudged` 和 `pending_disposition` 都为 0 时无活可干。

### Step 2：触发判断

```bash
jfox prompts judge                    # 默认批量（配置 default_limit，默认 50 条）
jfox prompts judge --limit 20         # 小批量试跑
jfox prompts judge --all              # 不限批量
jfox prompts judge --retry-failed     # 连失败项一起重判
jfox prompts judge --session <session_id>   # 只判某个会话
```

judge 内部先 drain（把本地 spool 兜底队列灌库），再按 session 分组批量调用外部 runner（默认本地 pi，禁用工具/会话/扩展/skills/项目上下文；远程需 `--allow-remote`）。

输出逐条形如 `#12 new → candidate 202609101234567890`（成功）或 `#13 <错误>`（失败）。

四类判断结果：

- **new** — 有新知识，已起草 candidate 草稿
- **repeated** — 反复出现的澄清/痛点，候选「待解决问题」
- **recorded** — 已记录过，无需动作
- **needs_review** — 证据不足或非知识类；合法结果，不会被强行归类

### Step 3：逐条处置（确认环节）

**new 类：看草稿 → 你确认 → 晋升或拒绝**

```bash
jfox prompts show <ID> --full          # 看 prompt 原文与 judgment 详情
jfox candidates show <note_id>         # 看 candidate 完整正文（note_id 取自 judge 输出）
jfox prompts promote <ID>              # 确认：晋升该 candidate 为 permanent
jfox prompts ignore <ID> --reject-candidate   # 拒绝：忽略并归档草稿
```

**repeated 类：问用户 → 标记待解决**

```bash
jfox prompts unresolved <ID>           # 写入「待解决问题」清单笔记（仅 repeated；--force 可覆盖）
jfox prompts resolve-unresolved <ID>   # 问题解决后移除标记，闭环
```

**failed / needs_review 类**

```bash
jfox prompts retry <ID>                # 重置失败/证据不足状态，下次 judge 重判
jfox prompts ignore <ID>               # 确定无价值，忽略
```

处置命令有严格前置校验（如 `promote` 仅 new + candidate pending、`unresolved` 仅 repeated）；不满足时命令拒绝执行，确需覆盖用 `--force --reason "<理由>"` 留痕。

### Step 4：（可选）待解决问题闭环

`unresolved` 写入的清单聚合在一条带 `unresolved-problems` 标签的 permanent 聚合笔记里；问题解决后用 `resolve-unresolved` 移除标记。清单本身就是实践中的痛点信号，值得定期回看。

## 安全注意

- **仅手动触发**：hook 和 daemon 都不运行判断，每次 judge 由你显式发起。
- **runner 隔离**：默认本地 pi runner 禁用工具、会话、扩展、skills 和项目上下文，prompt 只走 stdin，被判断的 prompt 内容不会被 runner 执行。
- **隐私边界**：judge 会把 transcript（会话对话记录）上下文送给 runner；远程 runner 必须显式 `--allow-remote`——全文会离开本机。
- **前置校验与留痕**：默认动作前置不满足即拒绝；`--force --reason` 覆盖必须写明理由（留痕）。
- **不做自动决策**：judge 不做自动去重、自动合并、置信度过滤；candidate 是否晋升由你决定。

## 数据运维

```bash
jfox prompts drain                  # daemon 停机时把本地 spool 兜底灌库（judge 内部也会先 drain）
jfox prompts backfill --dry-run     # 预览从旧 session_fragments 回填历史 UserPromptSubmit
jfox prompts list --limit 50        # 浏览已记录 prompt（默认每页 20）
jfox prompts config                 # 查看/设置采集与判断配置（如 default_limit）
```

采集链路：hook（Claude Code）/ pi 扩展 → 本地 spool → POST daemon → `user_prompts` 表。daemon 不可用时 spool 保留不丢，用 `drain` 恢复。pi 会话来源标记为 `pi-coding-agent`，Claude Code 为 `claude-code`。

## 与 jfox-promote 的分工

- **本 skill**：日常增量（几条到几十条）——判断 + 逐条处置，端到端。
- **jfox-promote**：pending 积压超过 50 条或存量清理——三模式过审（客观去重扫描 / 簇级 triage / 单条 A/B/C）。
- judge 产出的 candidate 带 `source_prompts` 溯源字段，与存量 candidate 走同一过审队列；两边不要并行重复处置同一条。
````

- [ ] **Step 2: 验证 A2 / A3（static 断言）**

Run:

```bash
WT=/home/elling/git-repo/github/jfox/.pi/worktrees/issue-513-skill-sync-399-overview-jfox-judge
grep -q "^name: jfox-judge" "$WT/skills-recommend/pi/jfox-judge/SKILL.md" && echo "A2 name OK"
for kw in "判断 prompt" "prompts judge" "prompt 积压" "--allow-remote" "--force --reason" "jfox prompts drain" "jfox prompts backfill" "source_prompts" "jfox prompts promote" "jfox prompts retry" "jfox prompts unresolved"; do
  grep -q -- "$kw" "$WT/skills-recommend/pi/jfox-judge/SKILL.md" || { echo "MISSING: $kw"; exit 1; }
done && echo "A3 keywords OK"
```

Expected: `A2 name OK` + `A3 keywords OK`（无 MISSING 行）。

- [ ] **Step 3: markdownlint**

Run: `cd $WT && npx --yes markdownlint-cli2 "skills-recommend/pi/jfox-judge/SKILL.md"`
Expected: `0 issues`（或 summary 0 errors）。

- [ ] **Step 4: Commit**

```bash
git -C $WT add skills-recommend/pi/jfox-judge/SKILL.md
git -C $WT commit -m "docs(skill): add jfox-judge end-to-end prompt judgment skill (#513)"
```

---

### Task 2: overview 退役引用清理 + jfox-judge 路由新增

**Files:**

- Modify: `skills-recommend/pi/jfox-overview/SKILL.md`（5 处：L41 / L52 / L58 / L71 / L76）

**Interfaces:**

- Consumes: Task 1 产出的 skill 名 `jfox-judge` 与触发词（判断 prompt / prompts judge / prompt 积压）
- Produces: overview 中 jfox-judge 路由行（验收 A1 的目标状态）

- [ ] **Step 1: 修改路由表（L41 行改写 + 新增 jfox-judge 行）**

将：

```markdown
| 过审 gem-synth 候选宝石、晋升为 permanent 或拒绝归档 | `jfox-promote` | 过审 candidate / promote / L5 晋升 |
```

改为（新增 jfox-judge 行插在 promote 行之前）：

```markdown
| 判断采集的 prompt、处置判断结果、确认晋升笔记 | `jfox-judge` | 判断 prompt / prompts judge / prompt 积压 |
| 过审 candidate、晋升为 permanent 或拒绝归档（存量 / 大积压） | `jfox-promote` | 过审 candidate / promote / L5 晋升 |
```

- [ ] **Step 2: 更新计数与一句话职责（L52 / L58）**

将 L52 `15 个 skill 一句话职责：` 改为 `16 个 skill 一句话职责：`。

将 L58：

```markdown
- **jfox-promote** — gem-synth 候选宝石过审（三模式：客观去重 / 簇级 triage / 单条 A/B/C + 冗余维度）。
```

改为（新增 jfox-judge 行插在 jfox-promote 行之前）：

```markdown
- **jfox-judge** — prompt 判断与端到端沉淀：judge 生成 candidate → 确认晋升 permanent；待解决问题清单闭环。
- **jfox-promote** — candidate 过审（三模式：客观去重 / 簇级 triage / 单条 A/B/C + 冗余维度；存量与大积压清理）。
```

- [ ] **Step 3: 更新笔记模型引路与复合工作流（L71 / L76）**

将 L71 中：

```markdown
候选宝石的来龙去脉见 **jfox-promote** skill；
```

改为：

```markdown
候选宝石的生成与过审见 **jfox-judge** / **jfox-promote** skill；
```

将 L76：

```markdown
2. **知识闭环（含 AI 合成）**：碎片采集（后台）→ gem-synth 合成 candidate → `jfox-promote`（过审晋升 permanent）→ `jfox-search`。
```

改为：

```markdown
2. **知识闭环（prompt → 笔记）**：hook 全量记录 prompt（后台）→ `jfox-judge`（判断 + 确认晋升 permanent；待解决问题清单）→ `jfox-search`；存量 candidate 积压清理用 `jfox-promote`。
```

- [ ] **Step 4: 验证 A1（static 断言）**

Run:

```bash
WT=/home/elling/git-repo/github/jfox/.pi/worktrees/issue-513-skill-sync-399-overview-jfox-judge
! grep -n "gem-synth\|碎片采集\|后台合成" "$WT/skills-recommend/pi/jfox-overview/SKILL.md" && echo "A1 no retired refs OK"
grep -c "jfox-judge" "$WT/skills-recommend/pi/jfox-overview/SKILL.md"   # 期望 >= 4（路由表/职责/模型段/工作流）
grep -q "16 个 skill" "$WT/skills-recommend/pi/jfox-overview/SKILL.md" && echo "count OK"
```

Expected: `A1 no retired refs OK` + 计数 ≥4 + `count OK`。

- [ ] **Step 5: markdownlint**

Run: `cd $WT && npx --yes markdownlint-cli2 "skills-recommend/pi/jfox-overview/SKILL.md"`
Expected: `0 issues`。

- [ ] **Step 6: Commit**

```bash
git -C $WT add skills-recommend/pi/jfox-overview/SKILL.md
git -C $WT commit -m "docs(skill): clean retired gem-synth refs in overview, route jfox-judge (#513)"
```

---

### Task 3: 全量验证与收尾核对

**Files:**

- Test: 全仓 markdownlint + 验收矩阵核对（无文件产出）

**Interfaces:**

- Consumes: Task 1/2 的两个文件
- Produces: 验收矩阵 A1–A5 的核对记录（本地 CR 输入）

- [ ] **Step 1: 全仓 markdownlint（A4）**

Run: `cd $WT && npx --yes markdownlint-cli2`
Expected: `0 issues`（全仓，含新增文件）。

- [ ] **Step 2: 验收矩阵逐项核对（A1–A5）**

逐项执行 spec §5 的命令（A1 = Task 2 Step 4；A2/A3 = Task 1 Step 2；A4 = 上一步；A5 = CI lint job，push 后验证），把结果记录到 issue 评论。U1（用户实测）标记 pending，合并后执行。

- [ ] **Step 3: git log 核对**

Run: `git -C $WT log --oneline main..HEAD`
Expected: 3 个 commit（spec + judge skill + overview），无多余文件（`git -C $WT status --short` 干净）。

---

## Self-Review 记录

- **Spec coverage**：spec §4 改动清单 2 个文件 → Task 1（judge 新建）+ Task 2（overview 5 处）；spec §5 验收 A1–A5 → Task 1 Step 2/3（A2/A3）、Task 2 Step 4/5（A1）、Task 3 Step 1/2（A4/A5）；U1 → Task 3 Step 2 记录 pending。无遗漏。
- **Placeholder scan**：无 TBD/TODO；skill 全文与 overview 前后文本均为逐字内容。
- **Type consistency**：`jfox-judge` 命名、触发词、note_id 用法（`jfox candidates show <note_id>`）在两个 task 间一致；命令参数均来自实测 help 输出。
