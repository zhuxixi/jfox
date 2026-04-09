---
name: jfox-organize
description: Use when user wants to organize, tidy up, or review their Zettelkasten knowledge base. Triggers on "整理知识库", "清理", "看看inbox", "organize notes", "tidy up", "review inbox".
---

# JFox Knowledge Base Organization

Review, organize, and connect notes in the Zettelkasten knowledge base.

## Prerequisites

Knowledge base must have notes (`jfox init` + some `jfox add` operations).

## 4-Step Organization Process

### Step 1: Inbox Review — Process Fleeting Notes

```bash
jfox inbox --json --limit 50
```

List all fleeting (unprocessed) notes. For each note, decide:

1. **Convert to permanent** — The idea is mature enough to become lasting knowledge
2. **Convert to literature** — It's a reading/learning note with a source
3. **Delete** — No longer relevant
4. **Keep as fleeting** — Still needs time to develop

**Conversion workflow (fleeting → permanent):**
1. Note the original content and ID from the inbox listing
2. Help the user refine and expand the content into a well-structured permanent note
3. Insert the refined note:
   ```bash
   jfox add "<refined content>" --title "<title>" --type permanent --tag <tags>
   ```
4. Delete the original fleeting note:
   ```bash
   jfox delete <original-id> --force
   ```

### Step 2: Find Orphaned Notes

```bash
jfox graph --orphans --json
```

Notes with zero links are orphans — disconnected from the knowledge graph.

For each orphan:
1. Get its content from the listing output
2. Find potential connections:
   ```bash
   jfox suggest-links "<content>" --format json
   ```
3. If good matches found (score >= 0.5), suggest adding `[[links]]` to connect the note

### Step 3: Analyze Graph Connectivity

```bash
jfox graph --stats --json
```

Key metrics to interpret:

| Metric | Meaning | Target |
|--------|---------|--------|
| `total_nodes` | Total notes | Growing over time |
| `total_edges` | Total links | Should grow with nodes |
| `avg_degree` | Average links per note | > 2.0 (healthy connectivity) |
| `isolated_nodes` | Notes with no links | < 20% of total |
| `clusters` | Topic groups | Natural grouping |
| `top_hubs` | Most-connected notes | Core knowledge anchors |

**Health signals:**
- High `isolated_nodes` → needs more linking (go to Step 2)
- Low `avg_degree` (< 1.5) → add more `[[links]]` between notes
- Few `clusters` → knowledge may be too fragmented or too uniform

### Step 4: Process Recommendations

For each actionable item from Steps 1-3, present to the user:

```
整理建议：

📥 收件箱: 23 条未处理的临时笔记
   → 建议: 逐条处理，转化为 permanent 或删除

🔗 孤立笔记: 15 条没有链接的笔记
   → 建议: 为每条找到相关笔记并添加 [[链接]]

📊 图谱指标:
   平均连接度: 1.3 (偏低)
   → 建议: 在笔记中多使用 [[链接]] 语法连接相关概念
```

## Note Type Reference

| Type | Path | Purpose |
|------|------|---------|
| `fleeting` | `notes/fleeting/` | Quick capture, to be processed |
| `literature` | `notes/literature/` | Reading notes with source |
| `permanent` | `notes/permanent/` | Refined, lasting knowledge |

## Command Reference

```bash
jfox inbox --json --limit <N>              # 查看临时笔记
jfox graph --orphans --json                 # 查找孤立笔记
jfox graph --stats --json                   # 图谱统计
jfox suggest-links "<content>" --format json # 推荐链接
jfox refs --search "<title>" --format json  # 查看引用关系
jfox list --format json --limit <N>         # 列出笔记
jfox add "<content>" --type permanent       # 添加精炼笔记
jfox delete <id> --force                    # 删除原始笔记
jfox daily --json                           # 查看今天的笔记
```

## Tips

- **Process inbox weekly**: Don't let fleeting notes accumulate past 30.
- **Link liberally**: The value of Zettelkasten is in connections, not volume.
- **Convert, don't edit**: Instead of editing fleeting notes in-place, create a new permanent note and delete the fleeting original. This preserves the audit trail.
- **Use tags for topics, links for ideas**: Tags group by topic; `[[links]]` connect by thought.
