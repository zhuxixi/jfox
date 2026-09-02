# jfox-moc Skill 批量建设与成员质量审查章节 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 jfox-moc skill 增补「批量建设与成员质量审查」章节并上提 3 条通用规则（issue #485）。

**Architecture:** 纯文档改动，唯一修改文件 `skills-recommend/pi/jfox-moc/SKILL.md`。混合组织：3 条通用规则（簇序号时效/成员时效/管道铁律）嵌入现有 Step 1-3（单一来源），新章节置于 Step 4 之后、「关键原则」之前，章节内引用规则不复述。

**Tech Stack:** Markdown（markdownlint-cli2 门禁）、YAML frontmatter、jfox CLI 命令引用。

**Spec:** `docs/superpowers/specs/2026-09-03-jfox-moc-batch-quality-chapter-design.md`（验收矩阵 ID：A1/A2/A3 自动化，U1/U2 用户实测）

## Global Constraints

- **只在 worktree 内作业**：`WT=/home/elling/git-repo/github/jfox/.pi/worktrees/issue-485-jfox-moc-batch-quality-chapter`，所有编辑路径以 `$WT` 开头，git 操作用 `git -C $WT`，禁止碰主 checkout。
- 唯一修改文件：`skills-recommend/pi/jfox-moc/SKILL.md`；不碰任何 `.py`、其他 skill、KB 笔记。
- commit message 用英文 conventional 格式；`git add <file>` 按文件 stage，禁止 `git add -A`。
- 文档用中文；新增章节标题层级 `##`，章节内小节用 `###`（与现有结构一致）。
- 新增触发词一律带 MOC 前缀（spec F1 决定）。
- 每个 task 结束前跑 `npx --yes markdownlint-cli2 "skills-recommend/pi/jfox-moc/SKILL.md"`（在 `$WT` 根目录执行），必须无错误（CI 门禁同款工具）。

---

### Task 1: frontmatter 触发词 + Step 1-3 通用规则上提

对应 spec 验收 ID：A2（issue 条目 1/3/4/5）、A3（规则全文单点出现）

**Files:**
- Modify: `skills-recommend/pi/jfox-moc/SKILL.md`（frontmatter description 尾部；Step 1 尾部；Step 2「展示草稿」段后；Step 3 尾部）

**Interfaces:**
- Produces: Task 2 新章节将引用的两个规则锚点——「Step 2 审成员时效性」「Step 3 管道语法铁律」。锚点短语（`不认旧序号`、`标题包含`）全文件各只出现一次，Task 2 不得重复。

- [ ] **Step 1: frontmatter description 追加触发词**

定位当前结尾：

```yaml
  "主题导航", "主题簇", "生成地图", "moc create", "moc update",
  "moc diagnose".
```

改为：

```yaml
  "主题导航", "主题簇", "生成地图", "moc create", "moc update",
  "moc diagnose", "批量建 MOC", "MOC 冷启动", "MOC 重构",
  "MOC 覆盖度", "MOC 合并", "MOC 归档".
```

- [ ] **Step 2: Step 1（诊断）尾部追加簇序号时效规则**

定位锚点行：

```markdown
向用户呈现：哪些主题簇已达建 MOC 规模、建议主题名、孤儿情况。
```

在其后追加新段落：

```markdown
**簇序号时效**：`seed=42` 只保证同一知识库状态下的结果可复现；库一变动（新建/归档 MOC、改笔记标题）Louvain 重跑结果即变，旧簇序号全部失效。每次 create 前重新 diagnose，用 hub 标题确认目标簇，不认旧序号（实测：知识库变动后差点把 CR 簇当 skill 簇建）。
```

- [ ] **Step 3: Step 2（草稿与确认）插入成员时效性规则**

定位锚点段（「展示草稿给用户确认……重跑 dry-run。」整段）之后、「**规模护栏**」之前，插入：

```markdown
**审成员时效性**：确认草稿前先读成员笔记全文，识别失效/过时笔记——先归档或更新成员，再落盘。直接建 MOC 会把过时结论固化进地图（实测：双 bot 时代的笔记在单 bot 化后已失效）。
```

- [ ] **Step 4: Step 3（落盘）尾部追加管道语法铁律**

定位锚点行：

```markdown
自动完成：生成 structure note + 成员 backlinks 回填。孤儿可收纳：加 `--include-orphans`（并入「待归类」小节，孤儿 id 同样进 links）。
```

在其后追加：

```markdown
**管道语法铁律**：MOC 正文一律用 `[[ID|标题]]`（管道左侧 ID 是解析目标，右侧标题仅作显示）。一条规则挡两个坑：

- **同名标题歧义**：`[[标题]]` 解析走「精确标题 → 标题包含」fallback，同名笔记（session-to-permanent 重复产出是主因）会解析到非预期的那条
- **标题含 `#` 截断**：`#` 是锚点分隔符，标题含 issue 号的笔记会被截断，静默丢成员（实测丢 #158/#195 两条）

#458 修复前，`moc create` 产物正文仍是 `[[标题]]`——`--yes` 落盘前检查成员清单，把标题含 `#` 或有同名风险的成员改写为 `[[ID|标题]]`；#458 修复后 create 产物自动免疫，手写正文仍须遵守。
```

- [ ] **Step 5: lint 验证（A1 局部）**

```bash
cd "$WT" && npx --yes markdownlint-cli2 "skills-recommend/pi/jfox-moc/SKILL.md"
```

Expected: 0 errors。

- [ ] **Step 6: 规则单点断言（A3 局部）**

```bash
cd "$WT/skills-recommend/pi/jfox-moc"
test "$(grep -c '不认旧序号' SKILL.md)" = "1" && \
test "$(grep -c '标题包含' SKILL.md)" = "1" && \
test "$(grep -c 'MOC 冷启动' SKILL.md)" = "1" && echo "A3-local PASS" || echo "A3-local FAIL"
```

Expected: `A3-local PASS`（每个规则机制短语/触发词恰好出现一次）。

- [ ] **Step 7: Commit**

```bash
git -C "$WT" add skills-recommend/pi/jfox-moc/SKILL.md
git -C "$WT" commit -m "docs(skill): hoist MOC quality rules into lifecycle steps (#485)"
```

---

### Task 2: 新章节「批量建设与成员质量审查（冷启动/重构）」

对应 spec 验收 ID：A2（issue 条目 2/6/7 + bonus limit 坑）、A3（章节内仅引用规则）

**Files:**
- Modify: `skills-recommend/pi/jfox-moc/SKILL.md`（Step 4 维护之后、「## 关键原则」之前）

**Interfaces:**
- Consumes: Task 1 产出的规则锚点「Step 2 审成员时效性」「Step 3 管道语法铁律」——本章节只引用，不重复机制解释。

- [ ] **Step 1: 插入新章节**

定位锚点行（Step 4 末尾）：

```markdown
维护节奏建议：每批次新笔记落库后跑一次，或随 organize 定期整理一起做。
```

在其后、`## 关键原则` 之前插入完整章节：

```markdown
## 批量建设与成员质量审查（冷启动/重构）

适用场景：从 0 批量建多个 MOC，或大规模重构现有地图层（归档/合并旧 MOC）。单 MOC 日常生命周期走 Step 1-4；批量场景在每一步上多一道质量闸。

### 批量主流程

diagnose → 逐簇 dry-run + 审成员时效性（Step 2 规则）→ 落盘并执行管道铁律（Step 3 规则）→ 覆盖度核查 →（可选）合并/归档。每建完一个 MOC 立即做覆盖度核查，不要攒到全部建完。

### 无独立簇时：手动建 MOC

语义聚类聚不出簇的主题（平台层笔记被大簇吸收、provider 配置散落各簇等）走手动路径：

1. 关键词搜索收集候选成员（多组关键词覆盖同义表述）
2. 与现有 MOC 成员做差集，排除已归属笔记
3. 分组呈现给用户确认主题名与成员取舍
4. 确认后落盘：`jfox add --type structure --tag moc --title "<主题名>" --content-file <草稿.md>`，正文成员一律 `[[ID|标题]]`（Step 3 铁律）

手动建的 MOC 与 create 产物同受 `moc update` 管理（update 按 type=structure 扫描，与创建方式无关）。#484（moc add-member 命令）落地后手动补成员可简化；落地前手动加成员会踩 #470（edit 用正文解析结果覆盖 frontmatter links 且不去重）——正文 wiki-links 与 frontmatter links 必须同步维护。

### 覆盖度核查

语义聚类会漏掉主题相关笔记（实测：CR MOC 初版漏 16 条，含 2 条核心根笔记）。每个 MOC 建完后必做：

1. 主题关键词 `jfox search "<关键词>" --mode hybrid --type permanent`，多组关键词各取 top 20-50
2. 搜索结果与 MOC 成员 links 做差集
3. 差集中确实属于主题的，按手动路径补入

附：`jfox list --type structure` 默认 limit 10 会漏 MOC，盘点全量 MOC 时 `--limit 20` 起步。

### 合并与归档处置

- **旧 MOC 无意义 → 归档**：`jfox archive <moc_id>`。structure note 归档不影响成员笔记（实测：2026-08-27 测试批次 7 个 MOC 全部归档）
- **两 MOC 主题重叠 → 合并**：保留主题更准确的 MOC，把另一 MOC 的独有成员按手动路径补入，然后归档被并者（实测：TUI MOC 并入 pi-agent-board 大 MOC）
```

- [ ] **Step 2: lint 验证（A1 局部）**

```bash
cd "$WT" && npx --yes markdownlint-cli2 "skills-recommend/pi/jfox-moc/SKILL.md"
```

Expected: 0 errors。

- [ ] **Step 3: 7 条增量覆盖断言（A2）**

```bash
cd "$WT/skills-recommend/pi/jfox-moc"
miss=0
for kw in "时效" "add --type structure" "同名" "锚点" "簇序号" "覆盖度核查" "archive" "--limit 20" "MOC 冷启动"; do
  grep -q -- "$kw" SKILL.md && echo "OK: $kw" || { echo "MISSING: $kw"; miss=1; }
done
[ "$miss" = "0" ] && echo "A2 PASS" || echo "A2 FAIL"
```

Expected: 全部 OK + `A2 PASS`（映射：时效=条目1，add --type structure=条目2，同名=条目3，锚点=条目4，簇序号=条目5，覆盖度核查=条目6，archive=条目7，--limit 20=bonus，MOC 冷启动=触发词）。

- [ ] **Step 4: 规则不重复断言（A3）**

```bash
cd "$WT/skills-recommend/pi/jfox-moc"
test "$(grep -c '不认旧序号' SKILL.md)" = "1" && \
test "$(grep -c '标题包含' SKILL.md)" = "1" && echo "A3 PASS" || echo "A3 FAIL"
```

Expected: `A3 PASS`（机制解释只在 Step 1/3 出现一次；新章节出现的是「Step 2 规则」「Step 3 铁律」引用语，不算重复）。

- [ ] **Step 5: Commit**

```bash
git -C "$WT" add skills-recommend/pi/jfox-moc/SKILL.md
git -C "$WT" commit -m "docs(skill): add batch cold-start and quality review chapter (#485)"
```

---

### Task 3: 验收对账（A1/A2/A3 终验 + U1/U2 挂起记录）

对应 spec 验收 ID：A1/A2/A3（终验）；U1/U2（标记 pending，转用户实测）

**Files:**
- 只读：`skills-recommend/pi/jfox-moc/SKILL.md`（本 task 正常无文件改动；若终验失败，回到 Task 1/2 修复）

**Interfaces:**
- Consumes: Task 1/2 完成的 SKILL.md。
- Produces: 验收对账结果（写入 PR body / issue 评论，供 github-issue-driven Step 9 使用）。

- [ ] **Step 1: A1 终验（全仓 lint，与 CI 门禁同款）**

```bash
cd "$WT" && npx --yes markdownlint-cli2
```

Expected: 0 errors（与 CI lint job 一致）。

- [ ] **Step 2: A2/A3 终验**

重跑 Task 2 Step 3-4 的两条断言链，均须 PASS。

- [ ] **Step 3: 对账记录与 U1/U2 挂起**

按 spec 验收矩阵逐项登记结果：

| ID | 结果 |
|----|------|
| A1 | 自动化通过（记录实际命令与输出） |
| A2 | 自动化通过（记录实际命令与输出） |
| A3 | 自动化通过（记录实际命令与输出） |
| U1 | **pending**——新会话说「批量建 MOC」观察 skill 路由，由用户实测 |
| U2 | **pending**——下次 MOC 整理按新章节走一遍，由用户实测 |

U1/U2 为 pending，不得宣称全部验收完成；对账表写入 PR body 与 issue #485 评论。

- [ ] **Step 4: Commit（仅当终验引发修复时）**

```bash
git -C "$WT" add skills-recommend/pi/jfox-moc/SKILL.md
git -C "$WT" commit -m "docs(skill): fix acceptance findings (#485)"
```
