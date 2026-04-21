---
name: jfox-common
description: |
  Manage and maintain Zettelkasten knowledge bases through jfox CLI.
  Use when user wants to create a knowledge base, switch between knowledge bases, check knowledge base status, run health checks, diagnose problems, or perform any knowledge base management operations.
  Triggers on: "创建知识库", "初始化", "知识库管理", "检查知识库", "知识库健康", "知识库体检", "health check", "create knowledge base", "init", "kb management", "知识库诊断", "switch kb", "list kb", "remove kb".
---

# JFox Knowledge Base Management & Health Check

Manage the full lifecycle of knowledge bases: create, switch, inspect status, and run periodic health checks with decay signal detection.

## Prerequisites

Confirm jfox is installed:
```bash
jfox --version
```
If not installed: `uv tool install jfox-cli`

## Knowledge Base Path Convention

All knowledge bases live under `~/.zettelkasten/`:

| Command | KB Name | Path |
|---------|---------|------|
| `jfox init` | default | `~/.zettelkasten/default/` |
| `jfox init --name work` | work | `~/.zettelkasten/work/` |
| `jfox init --name research` | research | `~/.zettelkasten/research/` |

Custom paths must be under `~/.zettelkasten/` (enforced by CLI).

## Knowledge Base Management

### List Existing Knowledge Bases

```bash
jfox kb list --format json
```

If knowledge bases exist, inform the user and ask whether to use an existing one or create a new one.

### Create Knowledge Base

**Default (first-time use):**
```bash
jfox init
```

**Named knowledge base:**
```bash
jfox init --name <name> --desc "<description>"
```

Examples:
```bash
jfox init --name work --desc "Work notes"
jfox init --name research --desc "Research notes"
jfox init --name personal --desc "Personal knowledge base"
```

**Custom path (must be under ~/.zettelkasten/):**
```bash
jfox init --name <name> --path ~/.zettelkasten/<custom-path>
```

### Verify After Creation

```bash
jfox kb current --format json
jfox status --format json
```

Confirm the KB is registered, directory structure is created, and status shows 0 notes.

### Management Commands

```bash
jfox kb switch <name>               # Switch active KB
jfox kb info <name> --format json   # View details
jfox kb current --format json       # Current KB
jfox kb rename <old> <new>          # Rename
jfox kb remove <name>               # Unregister (keep files)
jfox kb remove <name> --force       # Delete (irreversible)
```

## Note CRUD

### Add Note

```bash
# Quick add
jfox add "Note content with [[Other Note Title]] links" --title "Note Title"

# Specify type and tags
jfox add "Content" --title "Title" --type permanent --tag design --tag backend

# From file (v0.2.1+, for long text)
jfox add --content-file notes/draft.md --title "Title" --type literature

# From stdin
cat notes.txt | jfox add --content-file - --title "Title"

# Use template
jfox add --template meeting --title "Weekly Meeting Notes"
```

Note types:
- `fleeting` (default) — quick capture, refine later
- `literature` — reading notes
- `permanent` — distilled knowledge

### Edit Note

```bash
jfox edit <note_id> --content "New content" --title "New Title"
jfox edit <note_id> --content-file updated.md
jfox edit <note_id> --tag new-tag1 --tag new-tag2 --type permanent
jfox edit <note_id> --kb work --content "New content"
```

Editing preserves original note ID and creation time.

### Delete Note

```bash
jfox delete <note_id>               # Confirm required
jfox delete <note_id> --force       # Skip confirmation
```

### List & View Notes

```bash
jfox list --format json --limit 50
jfox list --type permanent --format json
jfox daily --json
jfox daily --date 2026-04-01 --json
jfox refs --search "<title>" --format json
jfox show <id_or_title>
```

All commands support `--kb <name>` to target a specific KB.

## Health Check

Collect metrics from multiple jfox commands and synthesize a health assessment. No single "health" command exists — data must be gathered and analyzed.

> If user specifies a target KB name, append `--kb <name>` to all commands below. Omit if unspecified to use the current default KB.

### 6 Metric Collection Commands

```bash
# 1. Overall status
jfox status --format json [--kb <name>]

# 2. Graph metrics
jfox graph --stats --json [--kb <name>]

# 3. Orphaned notes
jfox graph --orphans --json [--kb <name>]

# 4. Index integrity
jfox index verify [--kb <name>]

# 5. Note inventory
jfox list --format json --limit 500 [--kb <name>]

# 6. Unprocessed inbox
jfox inbox --json --limit 100 [--kb <name>]
```

### Health Metrics Table

| Metric | Source | Healthy | Warning | Danger |
|--------|--------|---------|---------|--------|
| **Orphan ratio** | `isolated_nodes / total_nodes` | < 20% | 20-40% | > 40% |
| **Avg degree** | `avg_degree` (graph stats) | > 2.0 | 1.0-2.0 | < 1.0 |
| **Inbox backlog** | fleeting note count | < 10 | 10-30 | > 30 |
| **Index integrity** | `jfox index verify` result | All pass | — | Any failure |
| **Connectivity** | `(total - isolated) / total` | > 0.8 | 0.6-0.8 | < 0.6 |
| **Type balance** | fleeting / total ratio | < 30% | 30-50% | > 50% |

### Decay Signal Detection

Analyze metrics to detect 5 decay patterns:

**1. Knowledge islands (high orphan ratio)**
- Signal: > 40% notes have no links
- Cause: Notes recorded but not connected to existing knowledge
- Fix: Use `jfox-organize` skill to find and add links

**2. Inbox backlog (too many unprocessed)**
- Signal: > 30 fleeting notes
- Cause: Capturing ideas without reflection
- Fix: Use `jfox-organize` skill to process inbox

**3. Low connectivity (avg degree too low)**
- Signal: Avg links per note < 1.0
- Cause: Not using `[[links]]` syntax when adding notes
- Fix: Use `jfox suggest-links` to find connections

**4. Index stale (out of sync)**
- Signal: `jfox index verify` reports mismatches
- Cause: Files modified outside jfox CLI
- Fix: `jfox index rebuild`

**5. Hub dependency (fragile structure)**
- Signal: Top 3 hubs hold > 50% of all edges
- Cause: Over-reliance on few hub notes
- Fix: Create intermediate notes to distribute connections

### Scoring System

```
Score = 100
- min(orphan_ratio * 100, 40)
- min(max(0, 2.0 - avg_degree) * 10, 20)
- min(max(0, inbox_count - 10), 20)
- (0 if verify_result["healthy"] else 20)
```

| Score | Grade | Status |
|-------|-------|--------|
| 90-100 | A | Excellent — healthy and well-connected |
| 75-89 | B | Good — minor issues |
| 60-74 | C | Fair — decay signals detected |
| 40-59 | D | Poor — significant decay |
| 0-39 | F | Critical — immediate action needed |

### Report Format

```
📊 Knowledge Base Health Report [KB: {kb_name}]

Overall Score: {grade} ({score}/100)

✅ Index Integrity: {pass/fail}
✅ Total Notes: {N} (permanent: {X}, fleeting: {Y})
⚠️ Orphaned Notes: {orphans}/{total} ({ratio}%) — {recommendation}
⚠️ Avg Degree: {degree} — {recommendation}
⚠️ Inbox: {inbox_count} unprocessed — {recommendation}

Detailed Metrics:
- Clusters: {clusters}
- Top Hubs: {hub_list}
- Connectivity: {connectivity_ratio}

Recommended Actions:
1. {highest priority action}
2. {secondary action}
3. {optional optimization}
```

Use emoji indicators: ✅ healthy, ⚠️ warning, ❌ danger.

### When to Run

- **Weekly**: Regular knowledge management health check
- **After bulk import**: Verify index and connections
- **Before organizing**: Identify priority areas
- **When stuck**: Detect specific decay patterns

## Command Reference

```bash
# KB Management
jfox init --name <name> --desc "<desc>"
jfox kb list --format json
jfox kb switch <name>
jfox kb info <name> --format json
jfox kb current --format json
jfox kb rename <old> <new>
jfox kb remove <name>
jfox kb remove <name> --force
jfox status --format json

# Note CRUD
jfox add "<content>" --title "<title>" --type <type> --tag <tags>
jfox add --content-file <path> --title "<title>"
jfox edit <id> --content "<new>" --title "<title>"
jfox edit <id> --content-file <path>
jfox delete <id> --force
jfox show <id_or_title>
jfox list --format json --limit <N>
jfox daily --json
jfox daily --date YYYY-MM-DD --json
jfox refs --search "<title>" --format json

# Import & Health
jfox ingest-log <repo-path> --limit <N> --type fleeting --kb <name>
jfox bulk-import <file.json> --type fleeting --kb <name>
jfox graph --stats --json
jfox graph --orphans --json
jfox index verify
jfox index rebuild
jfox inbox --json --limit <N>

# Daemon
jfox daemon start
jfox daemon stop
jfox daemon status
```

All commands support `--kb <name>` and `--format json` (or `--json`).

## Error Handling

| Scenario | Resolution |
|----------|------------|
| "Knowledge base already exists" | Use `jfox kb switch <name>` or create with a different name |
| "Path is outside managed directory" | All KBs must be under `~/.zettelkasten/` |
| `jfox: command not found` | Install: `uv tool install jfox-cli` |
| Index stale or verify failure | Run `jfox index rebuild` |
| `ingest-log` "Not a git repository" | Provide correct Git repository path |
