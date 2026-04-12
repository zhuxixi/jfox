---
name: jfox-health
description: Use when user wants to check knowledge base health, detect stale or decayed knowledge, audit the Zettelkasten. Triggers on "检查知识库健康", "腐化检测", "知识库状态", "知识库体检", "知识库诊断", "health check", "decay detection", "audit knowledge base", "orphan detection", "knowledge graph health".
---

# JFox Knowledge Base Health Check

Detect knowledge decay and audit the overall health of the Zettelkasten.

## Overview

This skill composes multiple jfox commands to produce a comprehensive health report. There is no single "health" command — the skill collects metrics from several sources and synthesizes them.

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

## Health Indicators

Compute these metrics from the collected data:

| Metric | Source Field | Healthy | Warning | Critical |
|--------|-------------|---------|---------|----------|
| **Orphan ratio** | `isolated_nodes / total_nodes` | < 20% | 20-40% | > 40% |
| **Avg degree** | `avg_degree` from graph stats | > 2.0 | 1.0-2.0 | < 1.0 |
| **Inbox backlog** | Count of fleeting notes | < 10 | 10-30 | > 30 |
| **Index integrity** | `jfox index verify` result | All valid | — | Any invalid |
| **Connectivity ratio** | `(total_nodes - isolated_nodes) / total_nodes` | > 0.8 | 0.6-0.8 | < 0.6 |
| **Type balance** | fleeting vs permanent ratio | fleeting < 30% | 30-50% | > 50% |

## Decay Signal Detection

Analyze the metrics for these specific decay patterns:

### 1. Knowledge Silos (high orphan ratio)
- **Signal**: > 40% of notes have zero links
- **Cause**: Notes captured but never connected to existing knowledge
- **Fix**: Run `/jfox-organize` to find and add links to orphans

### 2. Inbox Accumulation (high fleeting count)
- **Signal**: > 30 unprocessed fleeting notes
- **Cause**: Capturing ideas but not reflecting and refining them
- **Fix**: Run `/jfox-organize` Step 1 to process inbox

### 3. Poor Connectivity (low avg degree)
- **Signal**: Average links per note < 1.0
- **Cause**: Not using `[[links]]` syntax when adding notes
- **Fix**: Use `jfox suggest-links` to find connections for existing notes

### 4. Stale Index (index out of sync)
- **Signal**: `jfox index verify` reports mismatches
- **Cause**: Files added/modified outside jfox CLI
- **Fix**: `jfox index rebuild` to rebuild search index

### 5. Hub Dependency (fragile graph)
- **Signal**: Top 3 hubs hold > 50% of all edges
- **Cause**: Over-reliance on a few "hub" notes
- **Fix**: Create intermediate notes to distribute connections

## Scoring

Compute an overall score (0-100):

```
Score = 100
- min(orphan_ratio * 100, 40)                        # up to -40 points
- min(max(0, 2.0 - avg_degree) * 10, 20)             # up to -20 points
- min(max(0, inbox_count - 10), 20)                   # up to -20 points
- (0 if verify_result["healthy"] else 20)             # -20 if unhealthy
```

Map score to grade:

| Score | Grade | Status |
|-------|-------|--------|
| 90-100 | A | Excellent — healthy, well-connected |
| 75-89 | B | Good — minor issues to address |
| 60-74 | C | Fair — some decay detected |
| 40-59 | D | Poor — significant decay |
| 0-39 | F | Critical — needs immediate attention |

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

When using the default KB, show `[KB: default]`.

Use emoji indicators:
- ✅ Healthy / passing
- ⚠️ Warning / needs attention
- ❌ Critical / failing

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

## When to Run

- **Weekly**: Quick health check as part of regular knowledge management routine
- **After bulk import**: Verify index and connections are healthy
- **Before organizing**: Identify priority areas to focus on
- **When KB feels stale**: Detect specific decay patterns to address
