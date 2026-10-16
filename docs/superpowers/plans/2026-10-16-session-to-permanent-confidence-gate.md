# session-to-permanent 高置信度分级闸门 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 `jfox-session-to-permanent` 的三平台 SKILL.md 加「高确信度分级闸门」：用户会话内授权后，S1–S5 全过的笔记免人工确认自动落库（带审计 tag + 审计清单 + 熔断），**默认行为不变**。

**Architecture:** 纯文档改动（三个 SKILL.md），无代码。闸门条款以本文档的 Canonical 块 A–E 为单一来源，三平台逐字复用语义条款、只保留各平台既有的确认工具措辞差异。验收 = markdownlint（A1）+ 条款矩阵 grep（A2）+ jfox 命令存在性（A3）+ 默认行为 grep（A4）+ 用户实测 U1–U4（post-implementation）。

**Tech Stack:** Markdown；markdownlint-cli2 v0.23.x；jfox CLI 1.16.x；grep。

**Spec:** `docs/superpowers/specs/2026-10-16-session-to-permanent-confidence-gate-design.md`（issue #575 步 4 定稿，sha256 `87f58668…`）

## Global Constraints

- 只改三个文件：`skills-recommend/pi/jfox-session-to-permanent/SKILL.md`、`packages/cc-plugin/skills/session-to-permanent/SKILL.md`、`packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md`。不改 CLI / 测试 / README（spec §9、§8）。
- 所有编辑在 worktree 内进行：`WT=/home/elling/git-repo/github/jfox/.pi/worktrees/issue-575-session-to-permanent-confidence-gate`；文件路径一律以 `$WT` 开头；git 操作用 `git -C "$WT"`。
- 闸门语义条款（S1–S5、三级分流、审计/熔断、fail-closed、默认关、空结果降级、自评 confidence 不参与判定）三平台必须一致（spec §9 / A2）。
- 默认关：不授权时全文流程与现状一致（A4）。
- markdownlint 必须通过（`npx --yes markdownlint-cli2`，仓库 `.markdownlint-cli2.jsonc` 配置）。
- commit message 用 conventional commits 并带 `（#575）`。
- 不传 `--force`；不引入自动晋升；不动 candidate 流程与 gem_synth/prompts 相关文本。

## Canonical Gate Text（三平台共用的单一来源）

### 插入块 A「闸门节」— 插在 `### Step 4` 之前

````markdown
### Step 3.5: 高确信度闸门（默认关，仅当用户会话内授权时启用）

**默认行为不变**：除非用户在当前会话明确授权（如「本次高置信度笔记直接写」），本步骤整节省略，所有草稿照旧走 Step 4 人工确认；授权仅对当前会话生效，后续会话需重新授权。

授权后，对本批每条草稿逐一评估五个信号；**全部通过 = 高确信度**，可直接落库；任一不通过按表中规则降级。判定只用可核验的机械信号，**不采信任何自评置信度**（自评值至多作报告字段，不参与分档）。

| 信号 | 判定标准 | 失败时 |
|------|----------|--------|
| S1 证据锚点 | 每条核心事实有出处：文件路径类事实用 `test -e <path>` 实测存在；命令类须本会话实际执行过；issue/PR 号真实可查；用户原话会话中有 | 降人工档 |
| S2 去重余量 | ① `jfox search --type permanent` 无「已覆盖」命中；② 追加 `jfox search "<草稿一句话摘要>" --mode semantic --json` 读最高分（cosine 量纲）：<0.5 通过；0.5–0.65 灰色区降人工；≥0.65 降人工并按「可补充/已覆盖」走原流程（阈值为初始值，dogfood 校准）；**空结果或无 score 字段 = 信号缺失 → 降人工，不得当作「无重复」通过**；③ 补查 `jfox search --type candidate` 无同主题 pending；④ 落库前重跑一次 search（防并行会话窗口） | 灰色区/异常降人工 |
| S3 类型白名单 | 仅放行：现状快照（文件/脚本/配置位置）、工具/命令用法、已发生且可验证的事实。排除：ADR/决策、偏好、推测、待办、概念解释、冲突信息——**S3 排除 ≠ 不沉淀**，这些照常提炼并走 Step 4 人工确认，只是不进自动档 | 降人工档 |
| S4 只新增不覆盖 | 仅 `jfox add` 新笔记可自动；`jfox edit` 追加存量一律人工 | edit 类永远人工 |
| S5 fail-closed | 任一通道退化/异常/拿不准 → 降人工。检测动作：跑 `jfox daemon status` 确认 embedding daemon 在跑；抽查 `jfox search --json` 结果的 `search_mode` 是否全为 `keyword`（健康态为 `hybrid`）。注意：`--json` 的 `warnings` 仅在组件缺失时写入，「成功且无 warnings」≠ 通道健康 | 降人工档 |

三级分流：

| 档位 | 条件 | 处置 |
|------|------|------|
| 高确信 | S1–S5 全过 | 直接落库（见 Step 5「自动档落库」），不弹确认 |
| 中确信 | S1/S3/S4 过，S2 灰色区或证据偏弱 | 走 Step 4 人工确认 |
| 低/排除 | S3 排除类、S1/S2 失败、S5 触发 | 走 Step 4 人工确认 |

审计与熔断：自动落库笔记必须带 `--tag auto-distilled`，会话末输出审计清单（每条一行：标题 | ID | 档位依据摘要）。用户 veto 或要求修改任一自动放行条 → **本会话剩余候选全部降回人工确认**。随时回查：`jfox list --tag auto-distilled`。
````

### 替换块 B「Step 4 首句」

old（三副本同款）：

```text
**严禁未经审阅直接 `jfox add`。** 把草稿完整展示给用户，等明确确认。
```

new：

```text
**默认严禁未经审阅直接 `jfox add`。** 仅当当前会话已获用户明确授权、且该条经 Step 3.5 判定为高确信度时，可免确认自动落库（须带 `auto-distilled` tag 并入审计清单）；其余草稿一律把草稿完整展示给用户、等明确确认。
```

### 追加块 C「Step 5 自动档落库」— 追加在 Step 5 节内、`**MOC 归属挂载` 行之前

````markdown
**自动档落库（仅 Step 3.5 判定为高确信的笔记）**

```bash
# 落库前重跑一次 search 复核去重结论（S2④，防并行会话窗口）
jfox search "<草稿一句话摘要>" --mode semantic --json

# 写入 permanent：带审计 tag；正文含「## 依据」锚点段
jfox add --content-file /tmp/note-draft.md --title "<标题>" --type permanent \
  --tag auto-distilled --tag <主题tag> --json
```

- **不传 `--force`**：若返回 `skipped: duplicate`（#383 防重闸门命中），该条降级人工确认，其余候选不受影响。
- 自动档跳过 MOC 归属问询；落库后在审计清单里提示用户可用 `jfox moc update` 批量兜底归属。
- 判断不了档位时按中/低档处理（fail-closed）。
````

### 替换块 D「关键约束 bullet」

old：

```text
- **审阅是硬约束**：所有草稿必须完整展示给用户确认后才能落库，严禁直接 `jfox add`。
```

new：

```text
- **审阅默认是硬约束**：仅 Step 3.5 高确信度（S1–S5 全过）且用户会话内明确授权的笔记可免确认自动落库（必须带 `auto-distilled` 并输出审计清单）；其余一律完整展示并等用户确认，严禁直接 `jfox add`。
```

### 替换块 E「frontmatter description 追加句」— 追加在 `Triggers on:` 行之前

```text
  支持会话内授权后对高确信度笔记免人工确认自动落库（分级闸门，默认关）。
```

## File Structure

- Modify: `$WT/skills-recommend/pi/jfox-session-to-permanent/SKILL.md`（Task 1）
- Modify: `$WT/packages/cc-plugin/skills/session-to-permanent/SKILL.md`（Task 2）
- Modify: `$WT/packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md`（Task 3）
- 无新增文件；无 CLI / 测试改动。

## Task 1: pi 副本闸门改造

**Files:**

- Modify: `$WT/skills-recommend/pi/jfox-session-to-permanent/SKILL.md`
- 验收引用：A1、A2、A3、A4（spec §10）

**Interfaces:**

- Consumes：Canonical 块 A–E（本文档）
- Produces：pi 定稿文本（Task 4 跨平台比对的基准）

- [ ] **Step 1: 插入闸门节（块 A）**

在 `### Step 4: 用户审阅（硬约束）` 行之前插入块 A 全文，块 A 与 Step 4 之间留一个空行。

- [ ] **Step 2: 替换 Step 4 首句（块 B）**

- [ ] **Step 3: 追加 Step 5 自动档落库（块 C）**

追加位置：`### Step 5: 落库` 节内、`**MOC 归属挂载（Step 4 确认过归属的新笔记）**` 行之前。

- [ ] **Step 4: 替换关键约束 bullet（块 D）**

- [ ] **Step 5: description 追加句（块 E）**

- [ ] **Step 6: markdownlint（A1）**

Run: `cd "$WT" && npx --yes markdownlint-cli2 skills-recommend/pi/jfox-session-to-permanent/SKILL.md`
Expected: 0 issues

- [ ] **Step 7: 条款 grep 预检（A2 单文件）**

```bash
f=skills-recommend/pi/jfox-session-to-permanent/SKILL.md
for clause in "Step 3.5" "S1 证据锚点" "S2 去重余量" "S3 类型白名单" "S4 只新增不覆盖" "S5 fail-closed" "auto-distilled" "熔断" "空结果或无 score 字段" "自评置信度" "默认行为不变" "moc update"; do
  grep -q "$clause" "$f" && echo "OK: $clause" || echo "MISSING: $clause"
done
```

Expected: 全部 OK

- [ ] **Step 8: commit**

```bash
git -C "$WT" add skills-recommend/pi/jfox-session-to-permanent/SKILL.md
git -C "$WT" commit -m "feat(skill): pi session-to-permanent 加高置信度分级闸门（#575）"
```

## Task 2: cc-plugin 副本同步

**Files:**

- Modify: `$WT/packages/cc-plugin/skills/session-to-permanent/SKILL.md`
- 验收引用：A1、A2、A3

**Interfaces:**

- Consumes：Canonical 块 A–E；pi 定稿文本（Task 1）
- Produces：cc 定稿文本

平台差异说明：本副本的确认工具是 `AskUserQuestion`（块 A–E 为工具中立文本，不需要因平台改写）；**五处改动与 Task 1 逐字相同**。

- [ ] **Step 1: 插入闸门节（块 A）** — 锚点 `### Step 4: 用户审阅（硬约束）`
- [ ] **Step 2: 替换 Step 4 首句（块 B）**
- [ ] **Step 3: 追加 Step 5 自动档落库（块 C）** — 锚点 `**MOC 归属挂载（Step 4 确认过归属的新笔记）**`
- [ ] **Step 4: 替换关键约束 bullet（块 D）**
- [ ] **Step 5: description 追加句（块 E）**
- [ ] **Step 6: markdownlint（A1）**：`npx --yes markdownlint-cli2 packages/cc-plugin/skills/session-to-permanent/SKILL.md` → 0 issues
- [ ] **Step 7: 条款 grep 预检（A2 单文件）**：同 Task 1 Step 7，路径换 cc 文件 → 全部 OK
- [ ] **Step 8: commit**：`git -C "$WT" commit -m "feat(skill): cc-plugin session-to-permanent 同步分级闸门（#575）"`

## Task 3: kimi-plugin 副本同步

**Files:**

- Modify: `$WT/packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md`
- 验收引用：A1、A2、A3

**Interfaces:**

- Consumes：Canonical 块 A–E；pi 定稿文本
- Produces：kimi 定稿文本

- [ ] **Steps 1–8：同 Task 2，仅路径换 `packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md`**
- [ ] **Step 8: commit**：`git -C "$WT" commit -m "feat(skill): kimi-plugin session-to-permanent 同步分级闸门（#575）"`

## Task 4: 跨平台一致性 + 验收汇总（A1–A4）

**Files:** 无新文件（只读核对；如发现缺口则修正对应 SKILL.md 并追加 commit）

- [ ] **Step 1: 全量 markdownlint（A1）**

Run: `cd "$WT" && npx --yes markdownlint-cli2 skills-recommend/pi/jfox-session-to-permanent/SKILL.md packages/cc-plugin/skills/session-to-permanent/SKILL.md packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md`
Expected: 0 issues

- [ ] **Step 2: 条款矩阵（A2，三平台）**

```bash
for f in skills-recommend/pi/jfox-session-to-permanent/SKILL.md packages/cc-plugin/skills/session-to-permanent/SKILL.md packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md; do
  echo "== $f"
  for clause in "Step 3.5" "S1 证据锚点" "S2 去重余量" "S3 类型白名单" "S4 只新增不覆盖" "S5 fail-closed" "auto-distilled" "熔断" "空结果或无 score 字段" "自评置信度" "默认行为不变" "moc update" "本次高置信度笔记直接写"; do
    grep -q "$clause" "$f" || echo "  MISSING: $clause"
  done
done
```

Expected: 无任何 MISSING

- [ ] **Step 3: 命令存在性（A3）**

```bash
jfox add --help 2>&1 | grep -q -- "--tag" && echo "OK add --tag"
jfox list --help 2>&1 | grep -q -- "--tag" && echo "OK list --tag"
jfox search --help 2>&1 | grep -q "semantic" && echo "OK search semantic"
jfox search --help 2>&1 | grep -q -- "--type" && echo "OK search --type"
jfox candidates list --help 2>&1 | grep -q -- "--min-confidence" && echo "OK candidates --min-confidence"
jfox moc update --help >/dev/null 2>&1 && echo "OK moc update"
jfox daemon --help >/dev/null 2>&1 && echo "OK daemon"
jfox edit --help >/dev/null 2>&1 && echo "OK edit"
jfox delete --help >/dev/null 2>&1 && echo "OK delete"
```

Expected: 全部 OK

- [ ] **Step 4: 默认行为（A4）**

```bash
for f in skills-recommend/pi/jfox-session-to-permanent/SKILL.md packages/cc-plugin/skills/session-to-permanent/SKILL.md packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md; do
  echo "$f 严禁未经审阅 命中数: $(grep -c '严禁未经审阅' "$f")"
done
grep -l "默认关" skills-recommend/pi/jfox-session-to-permanent/SKILL.md packages/cc-plugin/skills/session-to-permanent/SKILL.md packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md
```

Expected: 每份「严禁未经审阅」命中 1；三份均含「默认关」相关条款

- [ ] **Step 5: 缺口修正（如有）**：修正后追加 commit `fix(skill): 闸门条款三平台一致性修正（#575）`

- [ ] **Step 6: 汇总验收输出**：把以上命令与输出原文写入执行报告（供 PR 描述与 issue 评论使用）

## Task 5（post-implementation manual verification）: U1–U4 用户实测包

**Files:** 无（准备执行步骤与记录模板；U1–U4 为「用户实测」验收项）

- [ ] **Step 1: 部署前置**：把 `$WT/skills-recommend/pi/jfox-session-to-permanent/SKILL.md` 同步到 `~/.pi/agent/skills/jfox-session-to-permanent/SKILL.md`（或以 `pi install` 方式加载 worktree 副本）；确认会话实际加载新文本（让 agent 复述 S1–S5 条款）
- [ ] **Step 2: U1（授权 dogfood）**：新会话中说「本次高置信度笔记直接写」，跑一次真实沉淀。检查：高确信自动落库带 `auto-distilled`；无 MOC 归属问询且提示 `jfox moc update`；审计清单输出；中/低档仍弹确认。累计 N≥20 条自动放行后核对准确率 ≥95%（不足 20 条标 pending 继续累计）
- [ ] **Step 3: U2（默认关回归）**：不开授权跑一次沉淀，行为与改动前一致（每批确认）
- [ ] **Step 4: U3（#383 兜底）**：构造同标题的高确信条目，验证被拦并降级人工（未 `--force`）
- [ ] **Step 5: U4（通道退化）**：构造退化态（停 daemon 且无本地模型回退——轻量安装无 embed 组件，或本地模型不可用），授权后验证自动档判定全部降人工、零自动写入；无法构造则记「S5 仅静态验证（A2 grep）」并如实上报
- [ ] **Step 6: 结果回填**：U1–U4 结果写入 issue #575 评论；未执行项标 pending，不假称通过

---

## 自检记录（Self-Review）

- **Spec 覆盖**：spec §3 信号 → 块 A；§4 分流 → 块 A 第三张表；§5 审计/熔断 → 块 A 末段 + 块 C；§6 默认关 → 块 A 首段 + 块 E；§7 D7 → 块 C；§10 A1–A4 → Tasks 1–4，U1–U4 → Task 5。无遗漏。
- **落点说明**：spec §2 数据流中「Step 2 去重（新增：补查 candidate）」统一实现在 Gate 的 S2③（仅授权会话执行），Step 2 主体不变——与 spec §3 S2③ 一致，避免默认路径多跑查询。
- **占位符扫描**：无 TBD/TODO；所有插入文本为成稿。
- **一致性**：块 A–E 中的命令与标签（`auto-distilled`、`--mode semantic`、`moc update`、`daemon status`）与 spec §3/§5/§10 完全一致。
