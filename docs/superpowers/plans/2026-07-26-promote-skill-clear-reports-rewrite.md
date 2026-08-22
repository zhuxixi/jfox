# promote SKILL.md clear-reports 重写 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (推荐) 或 superpowers:executing-plans 逐 task 实现。步骤用 checkbox（`- [ ]`）跟踪。本文档为文档重写计划，"测试"= grep 断言 + 人工通读（skill 是 markdown，无单测）。

**Goal:** 按 clear-reports 七规则重写 promote（cc）+ jfox-promote（kimi）两个 SKILL.md 的散文解释层，不动命令/脚本/骨架。

**Architecture:** 两个文件同 PR 同步改。先 cc（过审核心，精简），再 kimi（同步 cc 改动 + kimi 独有章节）。每文件改完跑 grep 验收。设计依据见 `docs/superpowers/specs/2026-07-26-promote-skill-clear-reports-rewrite-design.md`。

**Tech Stack:** Markdown（SKILL.md）。无代码、无单测。

## Global Constraints（所有 task 隐含遵守）

- **只动散文解释层**：命令块、Python 脚本（dedup_scan、clean_for_promote）的逻辑 / 触发词、frontmatter、错误处理表「场景-处理」骨架——原样保留。脚本内仅 print 输出标签和代码注释随去重档改名同步（与 spec §2 一致）。
- **去重档改名映射**（全文档统一）：`L1 → 精确`、`L2 → 高度相似`、`L3 → 中度相似`。改名后正文「L3」只指合成层。脚本逻辑 / 控制流 / 变量名（l1/l2/l3 等）不动；仅 print 输出标签和代码注释随改名同步，避免散文与脚本输出术语不一致。
- **平台差异保留**：cc promote 自身无跨 skill 引用；kimi 跨 skill 引用 `/skill:jfox-manage`（共享约定）和 `/skill:jfox-session-summary`（kimi 不自引用 `/skill:jfox-promote`）。
- **commit message**：中文，type(scope): 描述（#341），结尾 `Co-Authored-By: Claude <noreply@anthropic.com>`。
- **stage 按文件**：`git add <具体文件>`，不用 `git add -A`。

## File Structure

- Modify: `packages/cc-plugin/skills/promote/SKILL.md`（225 行 → 重写散文层）
- Modify: `packages/kimi-plugin/skills/jfox-promote/SKILL.md`（315 行 → 同步 + kimi 独有章节润色）
- 无新建文件（spec 已 commit 2471a20）。

## 改写规则（所有 task 共用，来源 spec §3/§4/§5）

- **心智模型段**：直接用 spec §3 定稿文本（精简版 3 条），插到开篇 H1 标题下、原黑话段位置。
- **电报体→完整句**：每句补主语动词；术语首次出现带半句解释；`→` 操作流水改「先…再…最后…」或有序列表。前后对照范例见 spec §4。
- **术语首现解释清单**（spec §5）：candidate、pending/flawed、permanent、grounded_by、grounding、dedup、content_hash、cosine、keep-best、fold/merge、confidence、leading H1、reject=archive。
- **表格补结论引导句**：每张表上方加一句「看完这张表记住什么」。

---

## Task 1: cc-plugin promote 重写

**Files:**

- Modify: `packages/cc-plugin/skills/promote/SKILL.md`

**Consumes:** spec §3 心智模型定稿文本、§4 改写范例、§5 术语清单、§6 改名映射。
**Produces:** cc 版重写完成，供 Task 2 kimi 版对照同步。

- [ ] **Step 1: 开篇心智模型段**

  把现 H1 下两行黑话段（`把 L3 合成产出的 candidate...对应 #249...#319 重写...`）替换为 spec §3 定稿文本（精简版 3 条）。保留 H1 标题 `# 过审 candidate（破损→完整，支持大积压）`。

- [ ] **Step 2: §0 决策树**

  段首加概要句（「按 pending 积压量选入口模式」）。把「先看 pending 积压量（注意 candidates list 默认分页 50 是上限...）」改完整句，解释 `pending` 在此指 candidate 过审状态、`candidates list` 分页 50 是坑。保留两条 bash 命令块不动。

- [ ] **Step 3: §1 模式1（去重扫描）**

  - 三档改名：`L1 content_hash 精确 → 精确去重`、`L2 cosine ≥ 0.95 → 高度相似`、`L3 cosine 0.88–0.95 → 中度相似`。
  - 电报条款改完整句，用 spec §4 范例（「第一档是精确去重：把清理后的正文逐字节比对……」）。
  - `content_hash`（正文逐字节哈希）、`cosine`（余弦相似度，衡量正文语义接近度）首现解释。
  - Python 脚本块（dedup_scan）原样保留——只改脚本上下的散文描述。

- [ ] **Step 4: §2 模式2（簇级 triage）**

  「已被覆盖 → keep-best + reject 其余」「未被覆盖 → promote-merge」改完整句。`keep-best`（簇内留信息最全的一条）、`fold`（折进现有 permanent）、`merge`（簇内多条合并成一条）、`grounding`（candidate 合成时依据的永久笔记，`grounded_by` 是其 frontmatter 字段）首现解释。

- [ ] **Step 5: §3 模式3（单条 A/B/C）**

  三档 `→` 流水改有序步骤完整陈述，用 spec §4 范例（A 档：「先读 candidate 及它依据的永久笔记 grounded_by，再微调正文……」）。`grounded_by`（candidate 合成时依据的永久笔记）首现解释。三档结构统一（规则 6）。

- [ ] **Step 6: §4 冗余 verdict**

  段首概要句。「verdict = 冗余」处置（fold/merge/reject）完整解释。「纪律：promote 前强制查……」改完整句。

- [ ] **Step 7: §5 机械清理**

  四步电报改完整句，用 spec §4 范例（「2+H1 降级 H2」→「如果剥掉首个标题后正文里仍有独立标题……降级为二级，或交人工确认」）。`leading H1`（正文首个一级标题）首现解释。Python 片段（clean_for_promote）原样保留。

- [ ] **Step 8: §6 已知坑**

  每条电报改完整句，保留「条条实踩」的全部信息量（wiki link 悬空、suggest-links 误命中、confidence≠质量、reject=archive、批量 reject 后台跑）。`confidence`（合成器自评置信度）首现解释。

- [ ] **Step 9: §7 输出格式 + 关键约束**

  输出格式表上方加结论引导句。关键约束四条电报改完整句（「promote 不改正文」「补链阈值 ≥ 0.6」「用户最终决定权」「溯源不丢」）。

- [ ] **Step 10: grep 验收（cc 版）**

  Run:

  ```bash
  grep -nE "直接清|留 1|2\+H1|降级 H2|keep-best|reject 其余" packages/cc-plugin/skills/promote/SKILL.md
  grep -nE "\bL1\b|\bL2\b|\bL3\b" packages/cc-plugin/skills/promote/SKILL.md
  ```

  Expected: 第一条无命中（或仅保留并已配解释的）；第二条「L3」只出现在指合成层处（如「L3 合成」），去重档已改名。基线对照：`git show main:packages/cc-plugin/skills/promote/SKILL.md` 取改写前版本，比对命令数与脚本完整性。

- [ ] **Step 11: 人工通读 cc 版**

  不依赖 #249/#319 能读懂整体流程；命令块、脚本块未被动过。

- [ ] **Step 12: commit**

  ```bash
  git add packages/cc-plugin/skills/promote/SKILL.md
  git commit -m "docs(cc-plugin): promote skill 按 clear-reports 重写散文层（#341）" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
  ```

---

## Task 2: kimi-plugin jfox-promote 同步重写

**Files:**

- Modify: `packages/kimi-plugin/skills/jfox-promote/SKILL.md`

**Consumes:** Task 1 cc 版重写结果（作同步基准）、spec。
**Produces:** kimi 版重写完成，两版风格一致。

- [ ] **Step 1–9: 同步 cc 改动**

  按 Task 1 Step 1–9 的同样改写，应用到 kimi 版对应章节。引用语法用 `/skill:jfox-promote`、`/skill:jfox-manage`。kimi 版 §0–§7 与 cc 同构，直接对照改。

- [ ] **Step 10: kimi 独有章节润色**

  kimi 版多出的章节按同方法论润色（不改行为，只改表达）：
  - 「监控 L3 合成」章：`pending`/`success`/`failed`/`duplicate`/`merged` 字段解释改完整句；点明这是合成进度、≠ 过审队列（与心智模型段呼应）。
  - 「命令参考」：bash 块不动；上方加概要句。
  - 「错误处理」表：上方加结论引导句；「场景-处理」骨架保留，处理列电报改完整句。
  - 「使用建议」：电报改完整句。

- [ ] **Step 11: grep 验收（kimi 版）**

  Run:

  ```bash
  grep -nE "直接清|留 1|2\+H1|降级 H2|keep-best|reject 其余" packages/kimi-plugin/skills/jfox-promote/SKILL.md
  grep -nE "\bL1\b|\bL2\b|\bL3\b" packages/kimi-plugin/skills/jfox-promote/SKILL.md
  ```

  Expected: 同 Task 1 Step 10。

- [ ] **Step 12: commit**

  ```bash
  git add packages/kimi-plugin/skills/jfox-promote/SKILL.md
  git commit -m "docs(kimi-plugin): jfox-promote 同步按 clear-reports 重写散文层（#341）" -m "Co-Authored-By: Claude <noreply@anthropic.com>"
  ```

---

## Task 3: 整体自检

**Files:** 无改动（仅验证）。

- [ ] **Step 1: 两版结构对照**

  心智模型段、三模式（模式1/2/3）、机械清理四步、输出格式、关键约束——cc 和 kimi 都在、结构一致。差异仅在 kimi 独有章节 + 引用语法。

- [ ] **Step 2: 全 grep 验收**

  Run（两条文件都跑）：电报体残留 + L3 残留 + 去重档新名命中。
  Expected: 电报体无残留；L3 只指合成层；「精确/高度相似/中度相似」三档名都在。

- [ ] **Step 3: 命令/脚本完整性核查**

  ```bash
  grep -c "jfox candidates\|jfox gem-synth\|jfox edit\|jfox suggest-links" packages/{cc,kimi}-plugin/skills/{promote,jfox-promote}/SKILL.md
  ```

  Expected: 命令数量与改写前一致（基线 `git show main:<path>` 对照；命令块未被误删/误改）。Python 脚本块逻辑逐字未动（仅 print 输出标签 + 代码注释随去重档改名同步）。

- [ ] **Step 4: 人工通读 cc 版**

  新读者（不查 #249/#319）能读懂 candidate 是什么、过审做什么、三模式怎么选。

---

## Self-Review

**1. Spec 覆盖**：spec §1 问题（电报体/无心智模型/术语裸露/L3 冲突/表格无结论）→ Task 1 Step 1-9 + Task 2 覆盖；§3 心智模型 → Task 1/2 Step 1；§4 改写范例 → Task 1 Step 3/5/7；§5 术语 → 各 Step 首现处；§6 改名 → Task 1 Step 3、Global Constraints；§7 cc/kimi 同步 → Task 2；§8 grep 验收 → Task 1/2 Step 10、Task 3。无遗漏。

**2. Placeholder 扫描**：各 Step 均指向 spec 具体定稿文本或前后对照范例，无「TODO/适当处理/类似 Task N」。文档重写的 "how" = 改写规则 + spec 范例引用（DRY，不重复贴整段）。

**3. 一致性**：去重档新名「精确/高度相似/中度相似」在 Global Constraints、Task 1 Step 3、Task 3 Step 2 一致；引用语法 cc/kimi 区分贯穿；commit message 格式统一。
