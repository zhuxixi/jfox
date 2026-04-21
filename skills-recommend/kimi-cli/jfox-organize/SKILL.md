---
name: jfox-organize
description: |
  Organize, refine, and optimize a Zettelkasten knowledge base.
  Use when user wants to organize their knowledge base, process inbox, refine fleeting notes into permanent notes, add wiki links, merge notes, or optimize the knowledge graph.
  Triggers on: "整理知识库", "清理 inbox", "提炼笔记", "组织笔记", "看看有什么可以整理的", "合并笔记", "生成链接", "organize", "process inbox", "refine notes", "knowledge graph optimization", "clean up notes", "link notes".
---

# JFox Knowledge Base Organization & Refinement

Core refinement skill. Transform raw fleeting notes into well-structured, interlinked permanent knowledge.

Three-step flow: inbox analysis → refinement (fleeting → permanent with `[[wiki links]]`) → graph optimization.

Also supports direct note creation and editing during organization.

## Prerequisites

Knowledge base must have notes. If empty, suggest using `jfox-ingest` skill first.

## Step 1: Inbox Analysis

```bash
jfox inbox --json --limit 50
```

List all fleeting (unprocessed) notes. Group and analyze:

1. **Group by `source:*` tag**: e.g., all `source:git-log` notes together
2. **Identify mergeable subgroups**: related commits/issues form subgroups
3. Present refinement suggestions:

```
Inbox: N fleeting notes

Refinement suggestions:
1. [Merge] 15 jfox git-log commits → "JFox Recent Development Summary" (permanent)
2. [Merge] 5 jfox PRs → "JFox PR Technical Decisions Summary" (permanent)
3. [Individual] 3 manually entered notes → process one by one
4. [Delete] 2 outdated notes → clean up
```

Wait for user confirmation on which suggestions to execute.

## Step 2: Refinement (fleeting → permanent)

Core capability. For each user-confirmed suggestion:

1. **Analyze**: Read the group of fleeting notes; extract core knowledge points
2. **Find connections**:
   ```bash
   jfox suggest-links "<refined content summary>" --format json
   ```
   Filter results with score >= 0.6
3. **Generate permanent note**: Structure core knowledge with embedded `[[wiki links]]` to existing notes
4. **Cross-link within batch**: If creating multiple permanent notes in one batch, add `[[links]]` between them too
5. **Insert**:
   ```bash
   jfox add "<content with [[links]]>" --title "<title>" --type permanent --tag <tag1> --tag <tag2> [--kb <name>]
   ```
6. **Delete source fleeting**:
   ```bash
   jfox delete <original-id> --force
   ```

> All commands support `--format json` or `--json`. Examples use `--json`.

### Refinement Strategy Table

| Source | Strategy | Permanent Example |
|--------|----------|-------------------|
| git-log (multiple commits) | Merge by time/topic; extract technical decisions | "JFox v0.1.4 Technical Changes Summary" |
| github-pr (multiple PRs) | Extract core design decisions, debates, final solutions | "JFox PR#94 Edit Command Design Discussion" |
| github-issue (multiple issues) | Extract problem essence, solutions, lessons learned | "JFox BM25 Index Issue and Fix" |
| Manual input | Judge maturity; convert to permanent if substantial enough | — |

## Step 3: Graph Optimization

### Find Orphaned Notes

```bash
jfox graph --orphans --json
```

For each orphaned permanent note:
1. Read note content
2. Find connections:
   ```bash
   jfox suggest-links "<content>" --format json
   ```
3. If matches with score >= 0.6, suggest adding links:
   ```bash
   jfox edit <orphan-id> --content "Original content... [[Related Note Title]]"
   jfox edit <orphan-id> --content-file updated.md
   ```

### Verify Improvement

```bash
jfox graph --stats --json
```

Report before/after comparison:

| Metric | Meaning | Healthy Target |
|--------|---------|----------------|
| `avg_degree` | Avg links per note | > 2.0 |
| `isolated_nodes` | Notes with no links | < 20% of total |

## Direct Note Creation

Users may want to create or edit notes during organization:

**Create note:**
```bash
jfox add "<content>" --title "<title>" --type <fleeting|permanent> --tag <tags> [--kb <name>]
jfox add --content-file notes/draft.md --title "<title>" --type permanent --tag <tags> [--kb <name>]
echo "<content>" | jfox add --content-file - --title "<title>" --type fleeting
```

For permanent notes, run `jfox suggest-links` first to find `[[wiki links]]` before inserting.

**Edit existing note:**
```bash
jfox edit <note_id> --content "New content" --title "New Title" --tag <tag>
jfox edit <note_id> --kb <kb-name> --content "New content"
```

**Type selection guide:**

| Type | Use Case | Example |
|------|----------|---------|
| `fleeting` | Quick ideas, temporary records to refine later | "Sudden API design idea" |
| `permanent` | Mature knowledge, long-lasting insights | "Summarized design principle" |

Default type: `fleeting` (quick capture, refine later with this skill).

## Command Reference

```bash
jfox inbox --json --limit <N>
jfox add "<content>" --type permanent --title "<title>" --tag <tags>
jfox edit <id> --content "New content"
jfox delete <id> --force
jfox suggest-links "<content>" --format json
jfox graph --orphans --json
jfox graph --stats --json
jfox list --format json --limit <N>
jfox daily --json
jfox daily --date YYYY-MM-DD --json
jfox show <id_or_title>

# Speed up with daemon (optional)
jfox daemon start
jfox daemon stop
```

## Error Handling

- **Empty inbox**: Inform user "Inbox is empty, nothing to organize"; skip to Step 3 graph optimization
- **`jfox suggest-links` low score** (< 0.6): Skip link recommendation; do not force-add
- **`jfox delete` ID not found**: Report error; continue processing other notes
- **`jfox add` / `jfox edit` / `jfox delete`**: Support `--format json` or `--json`

## Usage Tips

- **Organize regularly**: Process inbox weekly to avoid > 30 fleeting notes
- **Link liberally**: Zettelkasten value comes from connections, not quantity. Use `[[links]]` generously
- **Tags group, links express thought**: `--tag` categorizes by topic; `[[links]]` expresses conceptual relationships
