# jfox-moc Skill + organize 密度交接 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 jfox-moc skill 编排 MOC 生成/维护人工确认环节，并在 jfox-organize 与 jfox-overview 各加最小衔接改动（issue #417）。

**Architecture:** 纯文档改动，零 CLI 代码。三个 markdown 文件：新增 `skills-recommend/pi/jfox-moc/SKILL.md`（核心交付物），修改 `skills-recommend/pi/jfox-organize/SKILL.md`（仅 Step 3 末尾一处插入），修改 `skills-recommend/pi/jfox-overview/SKILL.md`（路由表 + 计数 + 笔记模型 + 工作流）。

**Tech Stack:** Markdown skill 文件（frontmatter + 命令示例），依赖 jfox CLI v1.9.0（`moc diagnose/create/update` 已就绪）。

## Global Constraints

- 所有文件改动在 worktree `/home/elling/git-repo/github/jfox/.pi/worktrees/issue-417-jfox-moc-skill` 内，git 命令用 `git -C <worktree>`
- 只动 pi 版 skill（`skills-recommend/pi/`）；kimi-cli 不动
- jfox-organize 的 description / 触发词**不得修改**（方案 C 初衷）
- jfox-moc 触发词刻意不含「整理」「组织」类词，避免与 organize 路由歧义
- 中文正文（项目约定：skill 正文中文）；frontmatter description 中英文混合（与现有 skill 一致）
- CLI 契约以 v1.9.0 实测为准：`moc diagnose` JSON 字段 `coverage / threshold_sweep / suggest / orphans`；`create --cluster --threshold --title --max-size --include-orphans --yes`；`update --id --yes`；全部支持 `--kb` / `--format json`

---

### Task 1: 新增 skills-recommend/pi/jfox-moc/SKILL.md

**Files:**

- Create: `skills-recommend/pi/jfox-moc/SKILL.md`

**Interfaces:**

- Consumes: jfox CLI v1.9.0 `moc` 命令组（diagnose/create/update）；jfox-common §4.1 共享约定（`--kb` / `--format json`）
- Produces: 独立 skill `jfox-moc`，供 jfox-overview 路由（Task 3）与 jfox-organize 交接（Task 2）引用

- [ ] **Step 1: 创建 SKILL.md 完整内容**

```markdown
---
name: jfox-moc
description: |
  Build and maintain MOC (Map of Content) structure notes for a Zettelkasten
  knowledge base. Diagnose topic cluster density, semi-automatically generate
  structure notes from clusters, and keep members in sync as notes evolve.
  Triggers on: "建 MOC", "MOC", "知识地图", "地图", "structure note",
  "主题导航", "主题簇", "生成地图", "moc create", "moc update",
  "moc diagnose".
---

# JFox MOC 地图层

为知识库建立「主题地图层」：诊断永久笔记的主题簇密度，半自动生成 MOC（structure note），并随笔记演化持续维护。

**半自动原则：机器出草稿、人确认落盘**——所有生成/更新先 dry-run 展示 diff，人工确认后才 `--yes` 落盘，绝不静默创建。

> 复用 `/skill:jfox-common` §4.1 共享约定（`--kb` / `--format json`）。注意：moc 命令组中 `diagnose` 支持 `--json` 简写，`create` / `update` 需用 `--format json`。

## 何时用

- 知识库 permanent 笔记超过 500–700 条，或某主题笔记靠搜索/双链已「找不全」
- `/skill:jfox-organize` 图谱优化阶段发现主题密集/孤儿多（密度交接）
- 用户说「建 MOC」「做个知识地图」「这个主题有哪些笔记」

**涌现原则**：不预先为所有主题建 MOC——先跑 diagnose 看密度信号，只对有真实规模的主题簇逐个建。

## Step 1: 诊断

```bash
jfox moc diagnose --json --top 10
```

输出解读（JSON 契约）：

- `coverage`：三口径计数（filesystem / vector / bm25）+ `warnings`——口径不一致（如 `vector_orphans` 异常偏高）时先修复索引（见 jfox-common §5），别在 stale 索引上建 MOC
- `threshold_sweep`：各阈值下的簇数与最大簇——用于调阈值
- `suggest`：建议主题簇（`size` / `hub` / `members`，按语义相似度聚类）
- `orphans`：无链接孤儿清单（MOC 收纳候选）

向用户呈现：哪些主题簇已达建 MOC 规模、建议主题名、孤儿情况。

## Step 2: 草稿与确认

选定簇后 dry-run 生成草稿（默认不落盘）：

```bash
jfox moc create --cluster <i> --threshold <t> --title "<主题名>" --format json
```

- `--cluster`：簇序号（从 0 起，对应 diagnose 输出顺序）
- `--threshold`：默认 0.65；簇过大被拒时提高阈值（如 0.7）拆细子簇再建
- `--title`：MOC 标题（缺省自动从簇内归纳）

展示草稿给用户确认（hub 置顶、按共享 tag 分组、成员清单）。**人工确认主题名与成员取舍**，需修改时用 `--title` / 换簇 / 换阈值重跑 dry-run。

**规模护栏**：簇超过 `--max-size`（默认 50）时拒绝生成——这是特性不是 bug，提高 `--threshold` 拆细再建。

## Step 3: 落盘

用户确认后加 `--yes`：

```bash
jfox moc create --cluster <i> --threshold <t> --title "<主题名>" --yes
```

自动完成：生成 structure note + 成员 backlinks 回填。孤儿可收纳：加 `--include-orphans`（并入「待归类」小节，孤儿 id 同样进 links）。

## Step 4: 维护

新笔记加入主题后 MOC 会过时，定期 diff 维护：

```bash
jfox moc update --format json                # 全部 structure note 与最新簇 diff（dry-run 默认）
jfox moc update --id <moc_id> --format json  # 单条 MOC
```

- diff 语义：`add` 新增成员、`remove` 死链（仅以磁盘存在性判定，防 stale index）、`kept` 保留
- **只摘死链，语义漂移不自动摘除**——笔记偏离主题不自动移除，交人工判断
- 确认 diff 后加 `--yes` 应用

维护节奏建议：每批次新笔记落库后跑一次，或随 organize 定期整理一起做。

## 关键原则

- MOC 稳定骨架只链接 permanent；session 不固化进骨架（近期活动动态引用，不入 links）
- structure 类型默认可被 hybrid search 命中——检索到 MOC 即获主题鸟瞰图，顺 links 定位具体笔记
- MOC 成员即 `links`（笔记 ID 列表），改成员就是改 links

## 错误处理

- `No structure notes found` → 先 `jfox moc create` 建第一条
- 簇超过 `--max-size` 被拒 → 提高 `--threshold` 拆细（Step 2）
- coverage 三口径不一致 → 先修索引（jfox-common §5），stale 索引会产出错误成员
- 孤儿过多（> 总 permanent 20%）→ 先走 `/skill:jfox-organize` 图谱优化补链，剩余再 `--include-orphans` 收纳

## 与 jfox-organize 的边界

- organize 管单条笔记加链接（inbox 提炼 + 图谱补链）
- jfox-moc 管主题簇地图（诊断 → 生成 → 维护）
- 组织中发现密度信号 → 移交本 skill；本 skill 发现孤儿太多 → 移交 organize

```

- [ ] **Step 2: 验证命令契约与 CLI 实测一致**

Run:
```bash
jfox moc --help
jfox moc diagnose --top 3 --json 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(sorted(d.keys())); print(sorted(d['coverage'].keys()))"
```

Expected: 三命令 create/update/diagnose 存在；JSON 顶层键含 `coverage, orphans, suggest, threshold_sweep`；`coverage` 键含 `filesystem, vector, bm25, vector_orphans, warnings`。

- [ ] **Step 3: 触发词自检（与全部 pi skill 无冲突）**

Run:

```bash
WT=/home/elling/git-repo/github/jfox/.pi/worktrees/issue-417-jfox-moc-skill
for f in $WT/skills-recommend/pi/*/SKILL.md; do echo "== $f"; grep -o '"[^"]*"' "$f" | head -30; done | sort | uniq -d
```

Expected: 新增触发词「MOC」「知识地图」「structure note」「主题簇」等与现有 skill 触发词无重复行输出（`uniq -d` 为空或仅通用词）。

- [ ] **Step 4: Commit**

```bash
git -C $WT add skills-recommend/pi/jfox-moc/SKILL.md
git -C $WT commit -m "feat(skill): add jfox-moc skill for MOC map layer (#417)"
```

---

### Task 2: jfox-organize 密度交接（唯一改动点）

**Files:**

- Modify: `skills-recommend/pi/jfox-organize/SKILL.md`（Step 3「确认改善」表格之后、「## 直接创建笔记」之前插入）

**Interfaces:**

- Consumes: 无（引用 Task 1 产出的 skill 名 `jfox-moc`）
- Produces: organize Step 3 末尾的「密度交接」小节，形成 organize → moc 接力点

- [ ] **Step 1: 插入密度交接小节**

在「## 直接创建笔记」标题前插入（原文锚点：`## 直接创建笔记`）：

```markdown
### 密度交接（MOC 触发点）

图谱优化发现某主题笔记数量多（靠搜索/双链找不全）或孤儿笔记密集时，说明该主题已达建 MOC 阈值——移交 `/skill:jfox-moc`（moc diagnose → create）。

职责边界：organize 管单条笔记加链接；jfox-moc 管主题簇地图。

```

- [ ] **Step 2: 验证 diff 只有一处新增**

Run: `git -C $WT diff skills-recommend/pi/jfox-organize/SKILL.md`
Expected: 仅一处插入（9 行左右新增），无删除行，frontmatter description 未变。

- [ ] **Step 3: Commit**

```bash
git -C $WT add skills-recommend/pi/jfox-organize/SKILL.md
git -C $WT commit -m "feat(skill): organize Step 3 adds density handoff to jfox-moc (#417)"
```

---

### Task 3: jfox-overview 路由更新

**Files:**

- Modify: `skills-recommend/pi/jfox-overview/SKILL.md`（4 处）

**Interfaces:**

- Consumes: Task 1 产出的 skill 名 `jfox-moc` 及其职责描述
- Produces: 路由表 + 计数 + 笔记模型 + 工作流四处同步，保证 overview 与新 skill 一致

- [ ] **Step 1: 四处修改**

修改点 1 — 路由表（`jfox-organize` 行后加一行）：

```markdown
| 诊断主题簇密度、生成/维护 MOC 地图（structure note） | `jfox-moc` | 建 MOC / 知识地图 / structure |
```

修改点 2 — 「14 个 skill 一句话职责」→「15 个 skill 一句话职责」，并在列表加一行：

```markdown
- **jfox-moc** — MOC 地图层：诊断主题簇密度、半自动生成/维护 structure note（dry-run 确认制）。
```

修改点 3 — 笔记模型段（「另有 session / candidate」）：

原文：`JFox 笔记分 fleeting / literature / permanent 三类（另有 session / candidate），靠 [[wiki link]] 互链。`
改为：`JFox 笔记分 fleeting / literature / permanent 三类（另有 session / candidate / structure——MOC 地图笔记），靠 [[wiki link]] 互链。`
并在该段末尾追加一句：`structure 类型的地图层管理见 **jfox-moc** skill。`

修改点 4 — 典型复合工作流第 4 条（知识库维护）：

原文：`4. **知识库维护**：jfox-common（§5 体检 / 衰减信号检测）→ jfox-organize（清理 orphans / 补链接）。`
改为：`4. **知识库维护**：jfox-common（§5 体检 / 衰减信号检测）→ jfox-organize（清理 orphans / 补链接；图谱优化发现主题密集时交接 jfox-moc）→ jfox-moc（建/维护主题地图）。`

- [ ] **Step 2: 验证无残留旧计数**

Run: `grep -n "14 个 skill\|candidate）" $WT/skills-recommend/pi/jfox-overview/SKILL.md`
Expected: 无输出（旧计数已改；candidate 后已跟 structure）。

- [ ] **Step 3: Commit**

```bash
git -C $WT add skills-recommend/pi/jfox-overview/SKILL.md
git -C $WT commit -m "feat(skill): overview routes to jfox-moc, sync counts and workflows (#417)"
```

---

### Task 4: 端到端验证（真实 KB 不落盘）

**Files:**

- 无文件改动（验证 + 修问题如有）

**Interfaces:**

- Consumes: Task 1–3 的产物
- Produces: 验证报告；如有问题修复并 commit

- [ ] **Step 1: diagnose → create dry-run → update dry-run 全链路**

Run:

```bash
jfox moc diagnose --top 3 --json 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print('clusters:', [(c['size'], c['hub']['title'][:20]) for c in d['suggest']['clusters'][:3]] if d['suggest'] else 'none')"
jfox moc create --cluster 0 --format json 2>/dev/null | head -40
jfox moc update --format json 2>/dev/null | head -20
```

Expected: 三步均成功输出 JSON（create/update 保持 dry-run 不落盘）；无 structure note 时 update 输出「No structure notes found」错误也算通过（skill 错误处理已覆盖该场景）。

- [ ] **Step 2: skill 文件内容终检**

Run: `grep -c "jfox moc" $WT/skills-recommend/pi/jfox-moc/SKILL.md && grep -rn "jfox-moc" $WT/skills-recommend/pi/jfox-organize/SKILL.md $WT/skills-recommend/pi/jfox-overview/SKILL.md | wc -l`
Expected: 数字均 > 0（moc 命令示例 ≥ 3 处；organize/overview 各 ≥ 1 处引用）。

- [ ] **Step 3: 完整 diff 终检**

Run: `git -C $WT diff main --stat`
Expected: 4 个文件（1 spec + 1 plan + 3 skill 文件），无意外文件混入。

- [ ] **Step 4: 如需修复则 commit，否则任务完成**

```bash
git -C $WT status --short
git -C $WT log --oneline main..HEAD
```

Expected: 3 个 skill commit + spec commit，working tree 干净。
