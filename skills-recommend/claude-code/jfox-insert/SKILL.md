---
name: jfox-insert
description: Use when user wants to add, capture, or record a note into their Zettelkasten knowledge base. Triggers on "添加笔记", "记录", "记一下", "写下", "新建笔记", "快速记录", "add note", "capture", "insert note", "create note", "new note", "quick note", "jot down".
---

# JFox Knowledge Base Insert

Add notes to the Zettelkasten knowledge base.

## Prerequisites

Knowledge base must be initialized (`jfox init`).

## Note Type Selection

Choose the note type based on the nature of the content:

| Type | Flag | When to Use | Example |
|------|------|-------------|---------|
| **fleeting** | `--type fleeting` | Quick thought, temporary capture, idea | "突然想到一个API设计思路" |
| **literature** | `--type literature` | Notes from reading, with a source | "读了某篇文章，记下要点" |
| **permanent** | `--type permanent` | Refined knowledge, lasting insight | "总结出一条设计原则" |

**Default**: `fleeting` (quick capture, process later with `/jfox-organize`).

## Workflow

### Step 1: Extract Note Components

From the user's message, extract:
- **title**: Summarize in a short phrase (recommended for literature/permanent)
- **content**: The actual note text
- **tags**: Topics or categories mentioned
- **source**: URL, book name, or reference (for literature notes)
- **links**: Mentions of existing concepts → `[[Note Title]]`

### Step 2: Check for Link Opportunities

When content involves concepts that may relate to existing notes, find related notes:
```bash
jfox suggest-links "<content>" --format json
```

If matches with score >= 0.6 are found, suggest adding `[[Note Title]]` links in the content.

### Step 3: Insert the Note

**Single note:**
```bash
jfox add "<content>" --title "<title>" --type <type> --tag <tag1> --tag <tag2>
```

**With source (literature notes):**
```bash
jfox add "<content>" --title "<title>" --type literature --source "<source>"
```

**With template:**
```bash
jfox add "<content>" --template quick
jfox add "<content>" --template meeting
jfox add "<content>" --template literature
```

**To a specific knowledge base:**
```bash
jfox add "<content>" --kb <kb-name> --title "<title>"
```

### Step 4: Verify

The command returns JSON with `id`, `title`, `type`, `filepath`, and `links` (resolved link IDs). If wiki links in content don't match existing notes, a `warnings` field lists unresolved links. Report any warnings to the user.

> **Note**: `jfox add` and `jfox bulk-import` use `--json`/`--no-json` (default: on), NOT `--format json`. Do not append `--format json` to these commands.

## Link Syntax

Use `[[Note Title]]` within content to create bidirectional links:
```bash
jfox add "React 的状态管理可以参考 [[Redux 设计模式]] 和 [[Context API 对比]]" --title "React 状态管理" --type permanent
```

## Bulk Import

For inserting multiple notes at once:

**Step 1: Create JSON file**
```json
[
  {"title": "笔记1", "content": "内容1", "tags": ["tag1", "tag2"]},
  {"title": "笔记2", "content": "内容2"},
  {"title": "笔记3", "content": "带有 [[笔记1]] 链接", "tags": ["tag3"]}
]
```
Save to a temporary file (use a cross-platform path).

**Step 2: Import**
```bash
jfox bulk-import <path-to-file.json> --type permanent --batch-size 32
jfox bulk-import <path-to-file.json> --kb work --type permanent
```

## Editing Existing Notes

Modify existing notes while preserving ID and creation timestamp:

```bash
# Edit content
jfox edit <note_id> --content "新内容"

# Edit title
jfox edit <note_id> --title "新标题"

# Edit multiple fields at once
jfox edit <note_id> --content "新内容" --title "新标题" --tag tag1 --tag tag2

# Edit in a specific knowledge base
jfox edit <note_id> --kb <kb-name> --content "新内容"
```

**Workflow**: Find note ID via `jfox list --format json` or `jfox inbox --json`, then edit.

> **Note**: `jfox edit` uses `--json`/`--no-json` (default: on), NOT `--format json`.

## Command Reference

```bash
# Single note
jfox add "<content>" --title "<title>" --type <fleeting|literature|permanent> --tag <tag>

# With source
jfox add "<content>" --source "<source>" --type literature

# With template
jfox add "<content>" --template <quick|meeting|literature>

# Bulk
jfox bulk-import <file.json> --type <type> --batch-size <N>

# Edit existing note
jfox edit <note_id> --content "新内容" --title "新标题" --tag <tag>

# Link suggestions before insert
jfox suggest-links "<content>" --top 5 --threshold 0.6 --format json
```

## Error Handling

- **"Notes directory not found"** / **KB not initialized**: Run `jfox init` first.
- **"Invalid note type"**: Must be `fleeting`, `literature`, or `permanent`.
- **"Template not found"**: Check available templates with `jfox template list`.
- **Content too short**: Jfox accepts any content length, but recommend at least a sentence.
- **Tag not found**: Tags are auto-created, no pre-registration needed.
