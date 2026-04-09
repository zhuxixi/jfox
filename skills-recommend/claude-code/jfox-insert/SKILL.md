---
name: jfox-insert
description: Use when user wants to add, capture, or record a note into their Zettelkasten knowledge base. Triggers on "添加笔记", "记录", "记一下", "add note", "capture", "insert note".
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
- **title**: Summarize in a short phrase (required for literature/permanent)
- **content**: The actual note text
- **tags**: Topics or categories mentioned
- **source**: URL, book name, or reference (for literature notes)
- **links**: Mentions of existing concepts → `[[Note Title]]`

### Step 2: Check for Link Opportunities

Before inserting, find related existing notes:
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

The command returns JSON with the created note's ID, title, type, and file path. Confirm success to the user.

## Link Syntax

Use `[[Note Title]]` within content to create bidirectional links:
```bash
jfox add "React 的状态管理可以参考 [[Redux 设计模式]] 和 [[Context API 对比]]" --title "React 状态管理" --type permanent
```

## Bulk Import

For inserting multiple notes at once:

**Step 1: Create JSON file**
```bash
cat > /tmp/notes.json << 'EOF'
[
  {"title": "笔记1", "content": "内容1", "tags": ["tag1", "tag2"]},
  {"title": "笔记2", "content": "内容2"},
  {"title": "笔记3", "content": "带有 [[笔记1]] 链接", "tags": ["tag3"]}
]
EOF
```

**Step 2: Import**
```bash
jfox bulk-import /tmp/notes.json --type permanent --batch-size 32
```

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

# Link suggestions before insert
jfox suggest-links "<content>" --top 5 --threshold 0.6 --format json
```

## Error Handling

- **"Notes directory not found"**: Run `jfox init` first.
- **Content too short**: Jfox accepts any content length, but recommend at least a sentence.
- **Tag not found**: Tags are auto-created, no pre-registration needed.
