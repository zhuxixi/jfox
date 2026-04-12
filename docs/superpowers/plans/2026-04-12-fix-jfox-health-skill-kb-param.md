# Fix: jfox-health Skill Multi-KB Support Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Update jfox-health skill to support multi-KB scenarios by adding `--kb <name>` parameter to all 6 data collection commands.

**Architecture:** Documentation-only change to `SKILL.md`. Add KB parameter instructions and update command examples. All 6 target commands (`status`, `graph`, `index`, `list`, `inbox`) already support `--kb` in code (verified: `cli.py` lines 607, 1338, 1727, 685, 1558). No code changes needed.

**Tech Stack:** Markdown only

---

### Task 1: Update SKILL.md — Data Collection and Command Reference sections

**Files:**
- Modify: `skills-recommend/claude-code/jfox-health/SKILL.md`

- [ ] **Step 1: Add KB parameter instruction to Data Collection section**

Replace lines 14-36 (the entire Data Collection section including the heading) with:

```markdown
## Data Collection

Run these 6 commands to gather all metrics:

> 如果用户指定了目标知识库名称，在以下所有命令中追加 `--kb <name>` 参数。未指定时省略，使用当前默认知识库。

```bash
# 1. Overall KB status
jfox status --format json [--kb <name>]

# 2. Graph metrics (note: --stats and --orphans are mutually exclusive, run separately)
jfox graph --stats --json [--kb <name>]

# 3. Orphan list (separate from stats)
jfox graph --orphans --json [--kb <name>]

# 4. Index integrity
jfox index verify [--kb <name>]

# 5. Note inventory (for type distribution and date analysis)
jfox list --format json --limit 500 [--kb <name>]

# 6. Unprocessed inbox count
jfox inbox --json --limit 100 [--kb <name>]
```
```

- [ ] **Step 2: Update Command Reference section to show --kb support**

Replace lines 133-143 (the entire Command Reference section) with:

```markdown
## Command Reference

All commands support `--kb <name>` to target a specific knowledge base. Omit to use the current default KB.

```bash
jfox status --format json [--kb <name>]     # KB 总体状态
jfox graph --stats --json [--kb <name>]     # 图谱指标（与 --orphans 互斥，分开运行）
jfox graph --orphans --json [--kb <name>]   # 孤立笔记列表
jfox index verify [--kb <name>]             # 索引完整性
jfox index rebuild [--kb <name>]            # 重建索引
jfox list --format json --limit <N> [--kb <name>]  # 笔记列表
jfox inbox --json --limit <N> [--kb <name>]        # 未处理笔记
```
```

- [ ] **Step 3: Update Report Format section to include KB name**

Replace lines 104-126 (the Report Format section) with:

```markdown
## Report Format

Present the health report in this format:

```
📊 知识库健康报告[KB: {kb_name}]

总体评分: {grade} ({score}/100)

✅ 索引完整性: {通过/未通过}
✅ 笔记总数: {N} (permanent: {X}, literature: {Y}, fleeting: {Z})
⚠️ 孤立笔记: {orphans}/{total} ({ratio}%) — {建议}
⚠️ 平均连接度: {degree} — {建议}
⚠️ 收件箱: {inbox_count} 条未处理 — {建议}

详细指标:
- 集群数: {clusters}
- Top hubs: {hub_list}
- 连通率: {connectivity_ratio}

建议操作:
1. {最优先的操作}
2. {次要操作}
3. {可选优化}
```
```

The only change in the report format is adding `[KB: {kb_name}]` to the title line. When using the default KB, show `[KB: default]`.

- [ ] **Step 4: Commit**

```bash
git add skills-recommend/claude-code/jfox-health/SKILL.md
git commit -m "fix(skill): add --kb parameter support to jfox-health skill

All 6 data collection commands now show optional --kb <name> parameter.
Data Collection section adds instruction for KB targeting.
Command Reference updated with --kb syntax.
Report format includes KB name in header. Closes #107."
```

---

### Task 2: Manual verification

- [ ] **Step 1: Verify default KB (no --kb) — behavior unchanged**

Run each command without `--kb` and confirm they work as before:

```bash
jfox status --format json
jfox graph --stats --json
jfox graph --orphans --json
jfox index verify
jfox list --format json --limit 10
jfox inbox --json --limit 10
```

Expected: All commands execute normally, operating on the default KB.

- [ ] **Step 2: Verify multi-KB scenario with --kb**

```bash
# 创建测试 KB
jfox kb create test-health-107

# 添加测试数据
jfox add "测试笔记 for health check" --kb test-health-107

# 重建索引
jfox index rebuild --kb test-health-107

# 验证全部 6 条命令均支持 --kb
jfox status --format json --kb test-health-107
jfox graph --stats --json --kb test-health-107
jfox graph --orphans --json --kb test-health-107
jfox index verify --kb test-health-107
jfox list --format json --limit 10 --kb test-health-107
jfox inbox --json --limit 10 --kb test-health-107
```

Expected: All commands execute without error, operating on `test-health-107` KB.

- [ ] **Step 3: Verify error handling**

```bash
jfox index verify --kb nonexistent-kb
```

Expected: Error message about KB not found.

- [ ] **Step 4: Cleanup**

```bash
jfox kb remove test-health-107
```

---

## Self-Review

**Spec coverage:** All requirements from issue #107 covered:
- Data Collection section updated with --kb → Task 1 Step 1
- Command Reference section updated with --kb → Task 1 Step 2
- Report Format includes KB name → Task 1 Step 3
- Default KB backward compatibility → Task 2 Step 1
- Multi-KB scenario → Task 2 Step 2
- Error handling → Task 2 Step 3

**Placeholder scan:** No TBD/TODO found. All steps contain complete content with exact old/new text.

**Type consistency:** N/A — documentation-only change, no code types involved.
