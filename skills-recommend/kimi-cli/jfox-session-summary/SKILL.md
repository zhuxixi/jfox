---
name: jfox-session-summary
description: |
  Save the current conversation or session summary into a Zettelkasten knowledge base.
  Use when user wants to save session summary, log conversation to knowledge base, write discussion to notes, or summarize chat into the knowledge base.
  Triggers on: "保存会话", "总结到知识库", "记录这次对话", "写入知识库", "save session", "summarize to knowledge base", "log this conversation", "save chat", "conversation to notes".
---

# JFox Session Summary

Save the current session summary into the jfox knowledge base (with user confirmation and note type selection).

## Prerequisites

- Knowledge base initialized (`jfox init`)
- Confirm target KB (via `--kb` or current default)

## Workflow

### Step 1: Generate Session Summary

Review current conversation and generate structured summary:

```markdown
## Session Summary

### Topic
[One-sentence description of main topic]

### Completed Work
- [Specific completed task 1]
- [Specific completed task 2]
- ...

### Key Decisions
- [Decision 1 and rationale]
- [Decision 2 and rationale]

### TODO / Follow-up
- [Incomplete items]
- [Next steps]
```

### Step 2: User Confirmation

Output the generated summary as plain text for user review. Then use `AskUserQuestion`:

- Question: `Is the summary content OK?`
- Options:
  - `Content is fine` → proceed to Step 3
  - `Needs changes` → user inputs modifications in "Other", adjust summary and return to Step 2

Loop until user is satisfied.

### Step 3: Select Note Type

After user confirms content, use `AskUserQuestion`:

- Question: `Select note type`
- Options:
  - `fleeting` (recommended) — session records are temporary; can be refined to permanent later
  - `literature` — if session has clear reference sources
  - `permanent` — if summary is already mature knowledge

### Step 4: Write to Knowledge Base

Use the selected type:

```bash
jfox add "<markdown-escaped-summary>" \
  --title "Session: <topic>" \
  --type <selected-type> \
  --tag session \
  --kb <kb-name> \
  --format json
```

**Notes**:
- Title format: `Session: <short topic>`
- Type: use Step 3 selection, do not hardcode `fleeting`
- Tag: always `session`
- Escape double quotes in content, or use `--content-file`

### Step 5: Handle Long Content

If summary exceeds 500 chars or contains special characters, prefer `--content-file`:

```bash
# Write to temp file
cat > /tmp/session-summary.md << 'EOF'
<summary content>
EOF

# Import from file
jfox add --content-file /tmp/session-summary.md \
  --title "Session: <topic>" \
  --type <selected-type> \
  --tag session \
  --kb <kb-name> \
  --format json
```

On Windows, use a temp path like `$env:TEMP\session-summary.md`.

## Command Reference

```bash
# Direct add (short content)
jfox add "<summary>" --title "Session: <topic>" --type <type> --tag session --kb <name>

# From file (long content or special characters)
jfox add --content-file <path> --title "Session: <topic>" --type <type> --tag session --kb <name>

# Verify write
jfox show <note_id>
```

## Error Handling

- **"Knowledge base not found"**: Prompt user to create KB first via `jfox-common`
- **Content too long for shell**: Switch to `--content-file` approach
- **Special character escaping issues**: Use single quotes or write to temp file
