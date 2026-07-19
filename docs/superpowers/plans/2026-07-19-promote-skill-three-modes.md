# promote skill 三模式过审重写 实现计划（#319）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 promote skill（cc + kimi 两版）从「逐条 A/B/C」重写为「三模式过审 + 冗余 verdict + 固化机械清理」，应对大积压——纯文档 PR，不动 Python。

**Architecture:** 重写两个 SKILL.md（结构统一：三模式决策树 + 冗余 verdict + 机械清理标准流程 + 已知坑 + 输出格式），模式1（dedup 存量扫描）以 skill 内嵌可跑临时脚本落地（命令版是 follow-up）。spec/plan doc 落 `docs/superpowers/`。

**Tech Stack:** Markdown（skill 文档）+ 少量 python（模式1 临时脚本、cleaning regex 验证，跑完不入库或入 docs）。

## Global Constraints（来自 spec + CLAUDE.md）
- **main 受保护**：所有改动在 worktree（从 origin/main 建），新分支 + PR，禁直接动 main
- **基线 origin/main HEAD = `e97e749`**（工作 clone `<jfox-repo>` 已同步 origin/main、工作树干净，可直接建 worktree）
- **路径为作者本地示例**：文中绝对路径（`/home/elling/...`、`~/.claude/...`）按实际仓库/工作树位置调整
- **不动 Python 代码**：本 PR 只改 markdown + 加 docs
- **plugin 版本三处同改**（若 bump）：`packages/cc-plugin/.claude-plugin/plugin.json(version)` + `.claude-plugin/marketplace.json(metadata.version + plugins[0].version)`
- **skill 文档中文**（与现有一致），行宽不约束 markdown
- **快速验证可自主跑**；全量/集成测试（~50min）不自主跑（本 PR 不涉及）
- 模式1 临时脚本依赖 embedding daemon（`jfox daemon` 不可用→降级只做 L1 content_hash）

## File Structure
- **Create:** `docs/superpowers/specs/2026-07-19-promote-skill-three-modes-design.md`（spec 落地，内容来自 `<issue-research-dir>/issue-319/spec-draft.md`）
- **Create:** `docs/superpowers/plans/2026-07-19-promote-skill-three-modes.md`（本 plan 落地）
- **Modify:** `packages/cc-plugin/skills/promote/SKILL.md`（精简版 → 三模式完整版）
- **Modify:** `packages/kimi-plugin/skills/jfox-promote/SKILL.md`（详细版 → 三模式 + 保留监控/命令参考/错误处理）
- **Modify（若 bump）:** `packages/cc-plugin/.claude-plugin/plugin.json` + `.claude-plugin/marketplace.json`

---

### Task 1: 建 worktree + 基线确认

**Files:** 无（环境准备）

- [ ] **Step 1: 从 origin/main 建 worktree**

```bash
cd <jfox-repo>
git fetch origin main
git worktree add -b feat/issue-319-promote-skill-three-modes \
  <jfox-worktree> origin/main
cd <jfox-worktree>
```

- [ ] **Step 2: 确认基线 = origin/main e97e749**

Run: `git log --oneline -1`
Expected: `e97e749 refactor(gem-synth): dedup 生命周期解耦...`

- [ ] **Step 3: 确认两版 SKILL.md + docs 目录存在**

Run: `ls packages/cc-plugin/skills/promote/SKILL.md packages/kimi-plugin/skills/jfox-promote/SKILL.md docs/superpowers/specs/ docs/superpowers/plans/`
Expected: 4 个路径都存在（若 specs/plans 目录不存在，Task 2 创建）

- [ ] **Step 4: 读两版现状作重写参照**

Run: `cat packages/cc-plugin/skills/promote/SKILL.md` + `cat packages/kimi-plugin/skills/jfox-promote/SKILL.md`
（确认现有命令引用、章节，重写时保留正确部分）

---

### Task 2: 落地 spec doc

**Files:**
- Create: `docs/superpowers/specs/2026-07-19-promote-skill-three-modes-design.md`

- [ ] **Step 1: 复制 spec 草稿到项目**

```bash
cp <issue-research-dir>/issue-319/spec-draft.md \
   docs/superpowers/specs/2026-07-19-promote-skill-three-modes-design.md
```
（若 specs 目录不存在先 `mkdir -p docs/superpowers/specs`）

- [ ] **Step 2: 校对开头（草稿 banner 删除）**

编辑文件，删除首行 `> 草稿。worktree 阶段落到...` banner（那是调研期注释）。

- [ ] **Step 3: Commit**

```bash
git add docs/superpowers/specs/2026-07-19-promote-skill-three-modes-design.md
git commit -m "docs(spec): promote skill 三模式过审设计 (#319)"
```

---

### Task 3: 重写 cc 版 SKILL.md

**Files:**
- Modify: `packages/cc-plugin/skills/promote/SKILL.md`

**新结构（章节顺序 + 每节要点）：**

```
---
name: promote
description: <保留现有 description，补触发词 "批量过审"、"簇级去重"、"dedup 扫描"、"冗余">
---
# 过审 candidate（破损→完整，支持大积压）
> 对应 #249 L5 晋升层。重写自 #319：逐条 → 三模式。

## 0. 何时用哪种模式（决策树）
- 大积压（pending > 50）→ 模式1 砍精确/高重复 → 模式2 处理剩余簇 → 模式3 高价值/模糊单条
- 小积压（≤50）→ 直接模式2 / 模式3
- 查积压量：`jfox candidates list --status pending --format json | jq '.candidates | length'`（分页内 ≤50，返回 50 即大积压；注意 `.total` = `len(rows)` 也是分页内，不是真实总数）；真实文件总数 `ls "$(jfox kb current --format json | jq -r .path)/notes/candidate/" | wc -l`（含 rejected 软删除）

## 1. 模式1：客观去重扫描（大积压第一步）
<内嵌临时脚本 python 代码块，见 Step 2 实际内容>
三档：L1 content_hash 精确 / L2 cosine≥0.95 / L3 0.88–0.95
dry-run 默认，--apply 批量 reject(keep-best)。daemon 挂→降级 L1。
> 临时脚本：待 `jfox candidates dedup-scan` 命令（follow-up）落地后替换。

## 2. 模式2：簇级 triage
1. 每簇先查「是否已被现有 permanent 覆盖」(jfox search / suggest-links)
2. 覆盖 → keep-best(grounding 最实/信息最全) + reject 其余
3. 未覆盖 → promote-merge 成 1 条

## 3. 模式3：单条深度 triage（A/B/C，次要）
A 准确: 微调(清元段落+补链+title)→确认→promote
B 局部问题: 列待澄清批量回答→改写→promote
C 不可信: 给依据→reject

## 4. 「冗余」verdict（跨模式维度，与 A/B/C 并列）
判定被现有 permanent 覆盖 → verdict=冗余 → fold/merge/reject。
纪律：promote 前强制查覆盖。

## 5. 机械清理标准流程（固化，别每批重写）
<可复制 python 片段，见 Step 3 实际内容>
1. 剥 frontmatter 字段：promote 自动清 status/gem_level/confidence/knowledge_type/reject_reason（保留 source_fragments/grounded_by 溯源）
2. 删元段落：regex 截断（覆盖 ## 来源/参考的永久笔记/置信度.*/可信度.* 变体）
3. 去双/多H1：剥首个 leading H1；2+H1（剥首个后仍有正文 H1）（LLM 用 H1 分节）→ 降级 H2 或人审
4. 修 exact-link：精确标题匹配(关联 #275)；suggest-links 阈值 0.4–0.5 + 手动按概念补链

## 6. 已知坑
- wiki link 要精确标题（[[短链]] 悬空实踩）；promote 未解析链 warning+跳过
- suggest-links 常关键词误命中/漏语义邻居，需手动补链
- confidence 是合成器自评、≠质量/冗余，别按它排序或决定能否直接升
- reject=archive（文件保留、unarchive 可恢复）
- 批量 reject(>40)：增量但每条触发 embedding，大批量累积耗时→后台跑；while read 注意尾换行

## 7. 标准输出格式
verdict + 证据 + wiki-link 报告 + 处置(promote/reject/merge/fold) + 确认

## 关键约束
- promote 不改正文：晋升前先 `jfox edit <id> --content-file cleaned.md` 写回清理后正文，再 `jfox candidates promote <id>`
- 补链阈值 ≥0.6（organize 一致）；模式1/改写放宽 0.4–0.5
- 用户始终最终决定权
```

- [ ] **Step 1: 重写 cc 版 SKILL.md 为上述结构**

用 Write 工具整体替换 `packages/cc-plugin/skills/promote/SKILL.md`，按上面结构填实际中文内容（每节展开 2–5 句，命令用代码块）。

- [ ] **Step 2: 模式1 临时脚本（嵌入 SKILL.md §1）**

脚本以 SKILL.md §1 为准（**直读文件版**：`parse_md` 解析 frontmatter 取 status + `clean` 剥元段落/首 H1 + `content_hash` 做 L1 精确 + embedding daemon 算 L2/L3 cosine；用 `jfox kb current` 的 `path` 字段定位 candidate 目录，支持自定义 `--path` KB）。此处不重复嵌入——见 `packages/cc-plugin/skills/promote/SKILL.md` §1 的 python 代码块，cc/kimi 两版同一份。

> 注：不要用 `jfox candidates list` 取正文（list 返回 `{candidates,total}` 包裹且无 content 字段，且分页 50）——直读 `notes/candidate/*.md`。

- [ ] **Step 3: 机械清理片段（嵌入 SKILL.md §5）**

片段以 SKILL.md §5 为准（`clean_for_promote(content)`：META_RE 删元段落含变体 + LEADING_H1_RE 剥首 H1 + `re.search(r"(?m)^# ")` 检测剩余行首 H1 降级 H2 + `content[: max(0, m.start()-1)]` 防 off-by-one；无 `title` 参数）。此处不重复嵌入——见 `packages/cc-plugin/skills/promote/SKILL.md` §5，cc/kimi 两版同一份。

- [ ] **Step 4: 验证 markdown 结构 + 命令引用**

Run: `grep -c '^##' packages/cc-plugin/skills/promote/SKILL.md`（确认章节齐全，预期 ≥7）
Run: `grep -E 'jfox (candidates|edit|search|suggest-links|gem-synth|fragments)' packages/cc-plugin/skills/promote/SKILL.md`（命令引用都在）
Expected: 列出所有引用的命令，无拼写错误

- [ ] **Step 5: Commit**

```bash
git add packages/cc-plugin/skills/promote/SKILL.md
git commit -m "feat(cc-plugin): promote skill 重写为三模式过审 (#319)"
```

---

### Task 4: 重写 kimi 版 SKILL.md

**Files:**
- Modify: `packages/kimi-plugin/skills/jfox-promote/SKILL.md`

**结构 = cc 版（Task 3）+ 额外保留 kimi 现有章节：**
- 保留前置条件（`jfox --version` / `kb current`）
- 保留「监控 L3 合成」章节（`gem-synth status` / `fragments list/show`）——放在三模式之前（过审前先看合成状态）
- 三模式（1/2/3）+ 冗余 verdict + 机械清理 + 已知坑 + 输出格式 ——与 cc 版**逐节同步**
- 保留「命令参考」总表 + 「错误处理」表 ——更新为含模式1/dedup 相关行
- 保留「使用建议」——更新（去掉"按 confidence 降序"，改为"大积压先模式1"）

- [ ] **Step 1: 重写 kimi 版，三模式核心与 cc 版一致**

用 Write 替换 `packages/kimi-plugin/skills/jfox-promote/SKILL.md`。三模式/冗余/机械清理/已知坑/输出格式 5 节内容**与 cc 版逐字相同**（同步），前后包裹 kimi 专属的监控/命令参考/错误处理章节。模式1 脚本和 cleaning 片段与 cc 版**同一份**（不重复维护）。

- [ ] **Step 2: 验证两版核心结构一致**

Run: `diff <(sed -n '/## 1. 模式1/,/## 7. 标准输出/p' packages/cc-plugin/skills/promote/SKILL.md) <(sed -n '/## 1. 模式1/,/## 7. 标准输出/p' packages/kimi-plugin/skills/jfox-promote/SKILL.md)`
Expected: 空输出（两版 §1–§7 完全一致）。若不一致，同步到一致。

- [ ] **Step 3: 验证 kimi 专属章节保留**

Run: `grep -E '监控 L3 合成|命令参考|错误处理|前置条件' packages/kimi-plugin/skills/jfox-promote/SKILL.md`
Expected: 4 个章节都在

- [ ] **Step 4: Commit**

```bash
git add packages/kimi-plugin/skills/jfox-promote/SKILL.md
git commit -m "feat(kimi-plugin): jfox-promote skill 重写为三模式过审 (#319)"
```

---

### Task 5: 模式1 脚本 + cleaning regex 验证

**Files:** 无（验证跑完不入库；若发现脚本 bug 回 Task 3/4 修 SKILL.md 内脚本）

- [ ] **Step 1: cleaning regex 覆盖验证**

Run（在 worktree 跑临时 python，不入库）:
```bash
cd <jfox-worktree>
uv run python -c "
import re
META_RE = re.compile(r'\n## (来源|参考的永久笔记|置信度.*|可信度.*)\n')
samples = ['\n## 来源\n', '\n## 参考的永久笔记\n', '\n## 置信度\n', '\n## 置信度说明\n', '\n## 可信度说明\n', '\n## 置信度评估\n']
for s in samples:
    assert META_RE.search(s), f'漏匹配: {s!r}'
print('6 样本（3 标准 marker + 3 变体）全覆盖 OK')
# 负例：正文标题不误删
assert not META_RE.search('\n## 核心原则\n'), '误匹配正文标题'
print('正文标题不误删 OK')
"
```
Expected: `6 样本（3 标准 marker + 3 变体）全覆盖 OK` + `正文标题不误删 OK`。若失败，修 SKILL.md 里 META_RE（Task 3/4）。

- [ ] **Step 2: 模式1 脚本 dry-run（真实 KB，不 apply）**（提取 SKILL.md §1 的 python 代码块存临时文件跑；或直接用 `$CLAUDE_JOB_DIR/tmp/dedup_scan.py` 已验证副本——内容与 SKILL §1 直读版一致）

Run:
```bash
cd <jfox-worktree>
# 把 SKILL.md §1 脚本存成临时文件跑 dry-run
jfox daemon status  # 确认 daemon（影响 L2/L3）
uv run python /tmp/dedup_scan.py --threshold 0.95  # L2 dry-run
```
Expected: 输出 L1 精确重复簇数 + L2 cosine 簇报告，无报错。若 daemon 挂→确认降级 L1。若脚本报错→修 SKILL.md §1 脚本（Task 3/4）后重跑。

- [ ] **Step 3: 若修了脚本，amend/补 commit**

```bash
# 若 Task 5 发现 SKILL.md 内脚本需修：
git add packages/cc-plugin/skills/promote/SKILL.md packages/kimi-plugin/skills/jfox-promote/SKILL.md
git commit -m "fix(skill): 模式1 扫描脚本 dry-run 修正 (#319)"
```

---

### Task 6: follow-up 登记

**Files:** 无（issue 评论 / 开新 issue）

- [ ] **Step 1: 在 #319 评论登记 6 个 follow-up**

```bash
gh issue comment 319 --repo zhuxixi/jfox --body '## Follow-up 登记（本 PR 不做，各自开 issue）

本 PR（纯 skill 重写）已落地。以下各自开 issue 跟进：
1. `jfox candidates dedup-scan` 命令（模式1 治本，替换 skill 内临时脚本）
2. promote `--strip-scaffolding`（机械清理治本，扩 promote_note）
3. 208 存量双 H1 candidate backfill（#320 甩来）
4. 跨版本 dedup 口径（#320 issue-4）
5. promote 回填 backlinks 不同步 chroma（现存 bug）
6. ~~unarchive 不复位 status~~（已核实非 bug，note.py 已复位，见 spec）'
```

- [ ] **Step 2: （可选）逐个开 follow-up issue**

对 1–6 用 `gh issue create` 开 issue，body 引用 #319 调研结论。若用户希望批量开，本步执行；否则评论登记即可。

---

### Task 7: plugin 版本 bump（待确认）

**Files:**
- Modify: `packages/cc-plugin/.claude-plugin/plugin.json`
- Modify: `.claude-plugin/marketplace.json`

- [ ] **Step 1: 确认是否 bump**

决策点：纯 skill 文档重写是否 bump cc-plugin 版本（现 0.5.1）。
- 若 bump → Step 2
- 若不 bump（skill 内容变更不算 plugin 发版）→ 跳过本 task

> 默认推荐 bump patch 0.5.1→0.5.2（skill 是 plugin 组成部分，实质性内容重写）。**执行前可问用户。**

- [ ] **Step 2: 三处同改 0.5.1→0.5.2**

改 `packages/cc-plugin/.claude-plugin/plugin.json` 的 `version` + `.claude-plugin/marketplace.json` 的 `metadata.version` 和 `plugins[0].version`，三处都 0.5.1→0.5.2。

- [ ] **Step 3: kimi-plugin 版本（独立确认）**

检查 `packages/kimi-plugin/kimi.plugin.json`（kimi-plugin 用 `kimi.plugin.json` 非 `plugin.json`，当前 0.13.0，与 cc-plugin 0.5.1 独立管理）是否同步 bump。

- [ ] **Step 4: 验证三处一致**

Run: `grep -rn "0.5.2" packages/cc-plugin/.claude-plugin/plugin.json .claude-plugin/marketplace.json`
Expected: 3 处命中（plugin.json 1 + marketplace.json 2）

- [ ] **Step 5: Commit**

```bash
git add packages/cc-plugin/.claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "chore(cc-plugin): bump version 0.5.1 → 0.5.2 for promote skill rewrite (#319)"
```

---

### Task 8: 落地 plan doc + 终检

**Files:**
- Create: `docs/superpowers/plans/2026-07-19-promote-skill-three-modes.md`

- [ ] **Step 1: 落地 plan doc**

```bash
cp <issue-research-dir>/issue-319/plan-draft.md \
   docs/superpowers/plans/2026-07-19-promote-skill-three-modes.md
```
（删首行调研 banner）

- [ ] **Step 2: Commit plan**

```bash
git add docs/superpowers/plans/2026-07-19-promote-skill-three-modes.md
git commit -m "docs(plan): promote skill 三模式重写实现计划 (#319)"
```

- [ ] **Step 3: 终检 diff**

Run: `git log --oneline main..HEAD`（确认所有 commit）
Run: `git diff main --stat`（确认只改 SKILL.md×2 + docs×2 + 版本号×2）
Expected: 无 Python 文件改动；改的都是 markdown/json

- [ ] **Step 4: 转本地 CR（高层 Task 4）**

本 plan 完成 → 进 github-issue-driven 步骤 7（本地 CR：`/code-review` 或 feature-dev:code-reviewer）→ 步骤 8 PR + Zima。

---

## Self-Review（writing-plans 要求，已完成）

- **Spec coverage**：spec 的三模式/冗余 verdict/机械清理/已知坑/输出格式/两版差异/follow-up 全部映射到 Task 3/4/6；模式1 内嵌脚本→Task 3 Step 2 + Task 5 验证；非目标(follow-up)→Task 6。✓
- **Placeholder scan**：模式1 脚本 L2/L3 cosine 给了骨架 + 关键 API（`get_backend().encode_single`、numpy cosine），标注完整实现在 follow-up 命令——这是 spec 明确的范围边界（非占位）。cleaning regex 给完整可跑代码。无 TBD。✓
- **Type consistency**：两版 SKILL.md §1–§7 用 `diff` 强制同步（Task 4 Step 2），命名一致（`clean_for_promote`、`META_RE`、`MARKER_RE`）。✓
