# Permanent 笔记模板重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `jfox-session-to-permanent` Step 3 的固定三段式模板（事实/Why/How to apply）替换为三层结构（稳定核 + 类型段 + 易变细节），三平台 skill body 逐字一致。

**Architecture:** 单骨架 + 可选类型段。替换三个 skill 文件（pi / cc / kimi）Step 3 里同一段「内容结构」code block，并在其后、写作规范段之前插入「类型段目录 + 选标题原则 + 自检」。替换文字在三个文件中**逐字一致**（靠 Task 4 三方 diff 兜底）。不碰任何 `.py`、不碰 `jfox-promote`、不碰 Step 1/2/4/5、不碰写作规范与 wiki links 段。

**Tech Stack:** Markdown（skill 散文层）。无代码、无测试套件——验证靠 grep 锚点 + 三方 diff。

## Global Constraints

（摘自 spec `docs/superpowers/specs/2026-08-11-permanent-note-template-design.md`，每个任务隐式遵守）

- 纯文档改动：不碰任何 `.py`、不碰 `pyproject.toml`/版本号；`packages/**/*.md` 不触发 CI（memory: docs-pr-no-ci-admin-merge）。
- 三文件 body（内容结构块 + 类型段目录 + 选标题原则 + 自检）**逐字一致**；各文件其余本平台特性不动（审阅交互 question vs AskUserQuestion、`--kb` 默认、交叉引用 `/skill:jfox-common` vs `/jfox:manage` vs `/skill:jfox-manage`）。
- 「写作规范（遵循 clear-reports 段落写作法）」5 条与「嵌入 wiki links」段**逐字保留不动**。
- 不改 `jfox-promote`（调研确认它不引用本模板）。
- 不回填历史永久笔记（仅对新沉淀生效）。
- commit 前 `git branch --show-current` 守卫（memory: concurrent-git-branch-hijack），须在 `issue-375-permanent-note-template` 分支。

## File Structure

| 文件 | 改动 | 责任 |
|---|---|---|
| `skills-recommend/pi/jfox-session-to-permanent/SKILL.md` | Step 3 替换 + 插入 | pi 平台 skill |
| `packages/cc-plugin/skills/session-to-permanent/SKILL.md` | 同上（逐字一致） | cc-plugin skill |
| `packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md` | 同上（逐字一致） | kimi-plugin skill |

三文件改的是**同一段**，替换文字完全相同——这是设计要求，不是省事。

---

## Canonical 替换文本（三个 Task 共用，逐字一致）

**要被替换的旧文本**（三个文件里逐字相同，grep 锚点 `**内容结构**（事实 → Why → How to apply）：`）：

````
**内容结构**（事实 → Why → How to apply）：

```markdown
<一句话核心事实。开门见山，把这条笔记最重要的结论放第一句。>

## Why
<这个事实为什么成立、背景是什么。每段只讲一个子主题，段首给概要句。>

## How to apply
<什么场景下用、具体怎么操作。结合示例或命令。>
```
````

**替换为下面这段新文本**（三个文件逐字一致，注意内层是 3 个反引号的 code block）：

````
**内容结构**（稳定核 + 类型段 + 易变细节）：

```markdown
<一句话结论。这条笔记最稳定、最值得未来记住的那句话，开门见山放第一句。>

## 为什么（背景与依据）
<这条知识回答的是什么问题；成立的前提/约束/假设。
 若是决策类：写当时的背景、选它的主要原因、以及认真考虑过但没选的替代方案——依据很大程度上在于"被丢弃的选项"。
 没东西可写就整段省略，别硬凑。>

## <类型段，选 0–1 个，标题写实>
<按笔记内容从下方"类型段目录"选一个标题，或整段省略。>

## 怎么用
<什么场景下用、具体步骤或命令。结合示例或命令。>
```

> **易变细节处理（写作指导，不是每条笔记的固定段）**：路径、版本号、端口、文件位置归到「## 怎么用」，它们是易变的"实现决策"，核（结论 + 为什么）不写具体值、保持常青。只有当「## 怎么用」里确实出现了这类易变值时，才在该段末尾加一句具体的核对提醒（如「端口以 docker-compose.yml 为准」）；没出现就不加——固定的模板话重复进每条笔记会掩盖该条的重点。

**选标题的原则**：标题要写实、具体——写这条笔记实际在讲的主题，不套抽象类别名；一段一个主题，不用「A与B」复合标题（如不要「运行速度与耗电量」，要拆成两段或选其一）。

**类型段目录**：按笔记内容选 0–1 个标题；方法/调试类通常省略，直接并进「## 怎么用」。

| 笔记内容 | 类型段标题 | 这一段写什么 |
|---|---|---|
| 机制 / 原理 | `## 它怎么工作` | 系统/工具的运作机制、各部分如何配合 |
| 现状快照 | `## 当前现状` | 脚本/文件/端口/配置的当前位置与状态 |
| 自动化链路 | `## 链路与组件` | 多组件串联的链路与各组件职责 |
| 纯概念 | `## 概念` | 可复用的概念、原理、术语解释 |
| 方法 / 调试 | （省略） | 直接写进「## 怎么用」 |

> **链路类的提醒**：一条笔记若在画多个组件的关系，本质是「迷你 structure note」——组件多了应考虑拆成一个 MOC（见 #376）+ 各组件独立笔记，而不是把所有组件塞进一条 fat note。

**自检**：把「## 怎么用」整段遮住，剩下的「结论 + 为什么 + 类型段」是否还独立成立、还有价值？是→分层成功；否→核里写进了易变细节，把具体路径/版本挪到「## 怎么用」。
````

> 替换范围说明：旧文本从 `**内容结构**（事实 → Why → How to apply）：` 起，到内层 code block 结束的 ` ``` ` 止（不含其后的空行和「写作规范」段）。新文本替换到「**自检**：……挪到「## 怎么用」。」止。替换后紧跟原有的「**写作规范（遵循 clear-reports 段落写作法）**」段——**写作规范段及其后内容一律不动**。

---

### Task 1: 替换 pi 平台 skill 的 Step 3 模板

**Files:**

- Modify: `skills-recommend/pi/jfox-session-to-permanent/SKILL.md`（Step 3「内容结构」块，约 L103–113）

**Interfaces:** 本任务建立 canonical 替换结果，Task 2/3 必须与其逐字一致（Task 4 diff 验证）。

- [ ] **Step 1: 守卫 + 定位旧块**

```bash
cd /home/elling/git-repo/github/jfox
git branch --show-current   # 必须: issue-375-permanent-note-template
grep -n "内容结构" skills-recommend/pi/jfox-session-to-permanent/SKILL.md
```

Expected: 命中 `**内容结构**（事实 → Why → How to apply）：`

- [ ] **Step 2: 替换**

用 Edit 工具，把本 plan「Canonical 替换文本」里的**旧文本**整段替换为**新文本**。`old_string` = 旧文本（从 `**内容结构**（事实 → Why → How to apply）：` 到内层 ``` 止），`new_string` = 新文本（到「**自检**」段止）。

- [ ] **Step 3: 验证替换正确**

```bash
# 旧锚点 0 命中
grep -c "事实 → Why → How to apply\|## How to apply" skills-recommend/pi/jfox-session-to-permanent/SKILL.md
# 新锚点命中
grep -c "稳定核 + 类型段 + 易变细节\|类型段目录\|选标题的原则\|自检：把" skills-recommend/pi/jfox-session-to-permanent/SKILL.md
# 写作规范段仍在
grep -c "写作规范（遵循 clear-reports" skills-recommend/pi/jfox-session-to-permanent/SKILL.md
```

Expected: 第 1 条 = 0；第 2 条 ≥ 4；第 3 条 = 1。

- [ ] **Step 4: Commit**

```bash
git add skills-recommend/pi/jfox-session-to-permanent/SKILL.md
git commit -m "refactor(skill): session-to-permanent 模板改三层结构（pi, #375）"
```

---

### Task 2: 替换 cc-plugin skill 的 Step 3 模板（与 pi 逐字一致）

**Files:**

- Modify: `packages/cc-plugin/skills/session-to-permanent/SKILL.md`（Step 3，约 L97–107）

**Interfaces:** 替换文字必须与 Task 1 结果逐字一致。

- [ ] **Step 1: 守卫 + 定位**

```bash
git branch --show-current   # issue-375-permanent-note-template
grep -n "内容结构" packages/cc-plugin/skills/session-to-permanent/SKILL.md
```

Expected: 命中旧锚点 `**内容结构**（事实 → Why → How to apply）：`

- [ ] **Step 2: 替换**

同 Task 1 Step 2——用本 plan「Canonical 替换文本」的旧/新文本做 Edit（同一份文字）。

- [ ] **Step 3: 验证**

```bash
grep -c "事实 → Why → How to apply\|## How to apply" packages/cc-plugin/skills/session-to-permanent/SKILL.md   # =0
grep -c "稳定核 + 类型段 + 易变细节\|类型段目录\|选标题的原则\|自检：把" packages/cc-plugin/skills/session-to-permanent/SKILL.md  # ≥4
```

- [ ] **Step 4: Commit**

```bash
git add packages/cc-plugin/skills/session-to-permanent/SKILL.md
git commit -m "refactor(skill): session-to-permanent 模板改三层结构（cc, #375）"
```

---

### Task 3: 替换 kimi-plugin skill 的 Step 3 模板（与 pi 逐字一致）

**Files:**

- Modify: `packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md`（Step 3，约 L97–107）

**Interfaces:** 替换文字必须与 Task 1 结果逐字一致。

- [ ] **Step 1: 守卫 + 定位**

```bash
git branch --show-current   # issue-375-permanent-note-template
grep -n "内容结构" packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md
```

Expected: 命中旧锚点。

- [ ] **Step 2: 替换**

同 Task 1 Step 2。

- [ ] **Step 3: 验证**

```bash
grep -c "事实 → Why → How to apply\|## How to apply" packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md   # =0
grep -c "稳定核 + 类型段 + 易变细节\|类型段目录\|选标题的原则\|自检：把" packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md  # ≥4
```

- [ ] **Step 4: Commit**

```bash
git add packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md
git commit -m "refactor(skill): session-to-permanent 模板改三层结构（kimi, #375）"
```

---

### Task 4: 三方 diff + 全局验证

**Files:** 无新改动；只读验证，必要时回修。

**Interfaces:** 消费 Task 1/2/3 的产物。

- [ ] **Step 1: 三方 body 逐字一致性**

抽取三文件「内容结构 → 写作规范」之间的区段，两两 diff：

```bash
cd /home/elling/git-repo/github/jfox
A=skills-recommend/pi/jfox-session-to-permanent/SKILL.md
B=packages/cc-plugin/skills/session-to-permanent/SKILL.md
C=packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md
extract() { sed -n '/\*\*内容结构\*\*/,/\*\*写作规范（遵循/p' "$1"; }
diff <(extract "$A") <(extract "$B")
diff <(extract "$A") <(extract "$C")
```

Expected: 两个 diff 均**无输出**（区段逐字一致）。若有差异，回对应 Task 修正到一致。

- [ ] **Step 2: 全局旧锚点 0 命中（排除 worktrees）**

```bash
grep -rn "事实 → Why → How to apply" --include="*.md" . | grep -v "/.worktrees/"
grep -rn "## How to apply" --include="*.md" . | grep -v "/.worktrees/"
```

Expected: 均无命中（session-to-permanent 三处已改；其它文件本就没有）。

- [ ] **Step 3: 写作规范 5 条 + wiki links 段仍在（抽查一处即可，三处一致）**

```bash
grep -c "写作规范（遵循 clear-reports" skills-recommend/pi/jfox-session-to-permanent/SKILL.md  # =1
grep -c "嵌入 wiki links" skills-recommend/pi/jfox-session-to-permanent/SKILL.md               # =1
grep -c "先给结论，再展开" skills-recommend/pi/jfox-session-to-permanent/SKILL.md              # =1（5条之1）
```

- [ ] **Step 4: jfox-promote 未受影响**

```bash
grep -rn "稳定核 + 类型段\|类型段目录" packages/cc-plugin/skills/promote packages/kimi-plugin/skills/jfox-promote skills-recommend/pi/jfox-promote 2>/dev/null
```

Expected: 无命中（promote 没被碰）。

- [ ] **Step 5: 若 Step 1–4 全过则无需 commit；若有回修则 commit 修正**

```bash
git status   # 应 clean（除非有回修）
```

---

## Self-Review（writing-plans 自检，已完成）

- **Spec coverage**：spec §3.1（新模板块）→ Task 1/2/3 Step 2；§3.2（类型段目录 + 选标题原则）→ 同一 canonical 新文本；§3.3（自检）→ 同一；§3.4（写作规范/wiki 不动）→ Task 1/3/4 Step 3 验证；§4（三平台一致 + 各保留特性）→ Task 4 Step 1 diff + Global Constraints；§6 验收→ Task 4。无遗漏。
- **Placeholder scan**：canonical 文本是最终稿，无 TBD/TODO。grep 期望值都给了具体数字。
- **Type consistency**：三个文件 grep 锚点字符串统一（`稳定核 + 类型段 + 易变细节` / `类型段目录` / `选标题的原则` / `自检：把`），Task 4 diff 兜底。
- **docs-only 适配**：原 TDD 模板的「写失败测试/跑测试」对纯 markdown 不适用，替换为「grep 锚点 + diff」机械验证，每步都给了可执行命令与期望值。
