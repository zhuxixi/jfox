---
name: jfox-health
description: Use when user wants to check knowledge base health, detect stale or decayed knowledge, audit the Zettelkasten. Triggers on "检查知识库健康", "腐化检测", "知识库状态", "health check", "decay detection", "audit knowledge base".
---

# JFox Knowledge Base Health Check

Detect knowledge decay and audit the overall health of the Zettelkasten.

## Overview

This skill composes multiple jfox commands to produce a comprehensive health report. There is no single "health" command — the skill collects metrics from several sources and synthesizes them.

## Data Collection

Run these 5 commands to gather all metrics:

```bash
# 1. Overall KB status
jfox status --format json

# 2. Graph metrics and orphans
jfox graph --stats --orphans --json

# 3. Index integrity
jfox index verify

# 4. Note inventory (for type distribution and date analysis)
jfox list --format json --limit 500

# 5. Unprocessed inbox count
jfox inbox --json --limit 100
```

## Health Indicators

Compute these metrics from the collected data:

| Metric | Source Field | Healthy | Warning | Critical |
|--------|-------------|---------|---------|----------|
| **Orphan ratio** | `isolated_nodes / total_nodes` | < 20% | 20-40% | > 40% |
| **Avg degree** | `avg_degree` from graph stats | > 2.0 | 1.0-2.0 | < 1.0 |
| **Inbox backlog** | Count of fleeting notes | < 10 | 10-30 | > 30 |
| **Index integrity** | `jfox index verify` result | All valid | — | Any invalid |
| **Cluster density** | `clusters / total_nodes` (if > 0) | > 0.1 | 0.05-0.1 | < 0.05 |
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
- (orphan_ratio * 100)          # up to -40 points
- (max(0, 2.0 - avg_degree) * 20)  # up to -20 points
- (inbox_backlog > 10 ? (inbox - 10) : 0)  # up to -20 points
- (index_issues * 20)            # up to -20 points
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
📊 知识库健康报告

总体评分: {grade} ({score}/100)

✅ 索引完整性: {通过/未通过}
✅ 笔记总数: {N} (permanent: {X}, literature: {Y}, fleeting: {Z})
⚠️ 孤立笔记: {orphans}/{total} ({ratio}%) — {建议}
⚠️ 平均连接度: {degree} — {建议}
⚠️ 收件箱: {inbox_count} 条未处理 — {建议}

详细指标:
- 集群数: {clusters}
- Top hubs: {hub_list}
- 集群密度: {density}

建议操作:
1. {最优先的操作}
2. {次要操作}
3. {可选优化}
```

Use emoji indicators:
- ✅ Healthy / passing
- ⚠️ Warning / needs attention
- ❌ Critical / failing

## Command Reference

```bash
jfox status --format json                # KB 总体状态
jfox graph --stats --orphans --json       # 图谱指标 + 孤立笔记
jfox index verify                         # 索引完整性
jfox index rebuild                        # 重建索引
jfox list --format json --limit <N>       # 笔记列表
jfox inbox --json --limit <N>             # 未处理笔记
jfox daily --json                         # 今日笔记
```

## When to Run

- **Weekly**: Quick health check as part of regular knowledge management routine
- **After bulk import**: Verify index and connections are healthy
- **Before organizing**: Identify priority areas to focus on
- **When KB feels stale**: Detect specific decay patterns to address
