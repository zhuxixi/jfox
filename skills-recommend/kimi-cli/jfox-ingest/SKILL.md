---
name: jfox-ingest
description: |
  Import data from local git repositories into a Zettelkasten knowledge base as fleeting notes.
  Use when user wants to ingest a repository, import git log, import GitHub PRs, import GitHub Issues, or bulk import project information.
  Triggers on: "导入仓库", "导入 git log", "导入 PR", "导入 issues", "读一下这个仓库", "抓取仓库信息", "ingest repo", "import notes from repository", "bulk import from git", "导入项目信息", "ingest repository", "import git history".
---

# JFox Repository Data Ingestion

Ingest git log, GitHub PRs, and GitHub Issues from local repositories as fleeting notes.

## Prerequisites

1. Knowledge base exists:
   ```bash
   jfox kb list --format json
   ```
   If none exists, prompt user to use `jfox-common` skill to create one first.

2. `git` command available.

3. For GitHub PR/Issues: `gh` CLI authenticated:
   ```bash
   gh auth status
   ```

## Workflow

### Step 1: Detect Repository

User provides a local repository path.

Detect if GitHub repository:
```bash
git -C <path> remote get-url origin
```

Check output for `github.com`. If present, extract `owner/repo`:
- `git@github.com:owner/repo.git` → `owner/repo`
- `https://github.com/owner/repo.git` → `owner/repo`

Extract repo name for tags: `source:<repo-name>`.

### Step 2: Select Data Source

| Source | Scenario | Needs GitHub |
|--------|----------|--------------|
| git-log | Commit history | No |
| github-pr | Pull Requests | Yes |
| github-issue | Issues | Yes |

If user says "import this repo" without specifying source, import all available sources (all three for GitHub repos; only git-log for non-GitHub).

### Step 3: Ingest Git Log

Single command for extraction + conversion + import:

```bash
jfox ingest-log path/to/repo --limit 50 --kb <name> --type fleeting
```

This command:
- Calls `git log` to extract commit history
- Parses structured data (hash, subject, author, date, body)
- Converts to fleeting notes and bulk imports
- Auto-adds tags: `source:<repo-name>`, `source:git-log`

Example generated note:
```
Commit: a1b2c3d
Author: Zhang San
Date: 2026-04-10

feat: add user authentication module

Implemented JWT authentication with refresh token support.
```

> All commands support `--format json` or `--json`. Examples below use `--json`.

### Step 4: Collect GitHub PRs

Only for GitHub repositories.

```bash
gh pr list --repo <owner/repo> --state all --limit 20 --json number,title,body,state,author,createdAt,updatedAt,labels
```

Optional: fetch comments per PR:
```bash
gh pr view <number> --repo <owner/repo> --json comments
```

Transform to note structure:
- **title**: PR title
- **content**: PR number, state, description, key comments, metadata
- **tags**: `source:<repo-name>`, `source:pr`

### Step 5: Collect GitHub Issues

Only for GitHub repositories.

```bash
gh issue list --repo <owner/repo> --state all --limit 30 --json number,title,body,state,author,createdAt,labels,comments
```

Transform to note structure:
- **title**: Issue title
- **content**: Issue number, state, description, comments, metadata
- **tags**: `source:<repo-name>`, `source:issue`

### Step 6: Import GitHub Data

Git-log was already imported in Step 3. This step handles PRs/Issues only.

**Deduplication**: Check for existing data before importing:
```bash
jfox search "<repo-name>" --format json
```

If records exist, only import new entries (by PR/Issue number).

**Build JSON array** for PRs/Issues:

```json
[
  {
    "title": "Add user authentication",
    "content": "PR #42: Add user authentication\nState: merged\nAuthor: zhangsan\n...",
    "tags": ["source:my-app", "source:pr"]
  },
  {
    "title": "Login page crashes on mobile",
    "content": "Issue #15: Login page crashes on mobile\nState: closed\n...",
    "tags": ["source:my-app", "source:issue"]
  }
]
```

Save to temp file, then import:
```bash
jfox bulk-import temp-file.json --type fleeting --kb <name>
```

> `jfox bulk-import` defaults to table output. Use `--json` for JSON format.

### Step 7: Confirmation Report

```
Ingestion complete!
  - git log: 50 entries
  - GitHub PRs: 15 entries
  - GitHub Issues: 10 entries
  - Total: 75 fleeting notes imported to <kb-name>
```

## Manual Input Support

If user pastes text without a repository path, organize as a single fleeting note:
```bash
jfox add "<content>" --title "<title>" --type fleeting --tag <tags> [--kb <name>]
```

## Note Format Reference

| Source | Title | Content | Extra Tags |
|--------|-------|---------|------------|
| git-log | commit subject | hash, author, date, body | `source:<repo>`, `source:git-log` |
| PR | PR title | number, state, description, comments | `source:<repo>`, `source:pr` |
| Issue | Issue title | number, state, description, comments | `source:<repo>`, `source:issue` |

All notes include `source:<repo-name>` for later retrieval by repository.
**Fleeting notes do NOT contain `[[wiki links]]`** — they are raw data capture. Links are added during refinement (use `jfox-organize` skill).

## GitLab Note

For non-GitHub repos, only import git log. GitLab CLI support is a future extension.

## Full Command Reference

```bash
# Detect repository type
git -C path/to/repo remote get-url origin
gh auth status

# Ingest git log
jfox ingest-log path/to/repo --limit 50 --kb <name> --type fleeting

# Collect GitHub data
gh pr list --repo owner/repo --state all --limit 20 --json number,title,body,state,author,createdAt,updatedAt,labels
gh pr view <number> --repo owner/repo --json comments
gh issue list --repo owner/repo --state all --limit 30 --json number,title,body,state,author,createdAt,labels,comments

# Deduplication check
jfox search "<repo-name>" --format json

# Import GitHub data
jfox bulk-import file.json --type fleeting --kb <name>

# Manual single note
jfox add "<content>" --title "<title>" --type fleeting --kb <name>

# Verify import
jfox show <note_id> --kb <name>

# Speed up with daemon (optional)
jfox daemon start
jfox daemon stop
```

## Error Handling

- **"Not a git repository"**: `jfox ingest-log` will error; prompt for correct path
- **`gh` not found or `gh auth status` fails**: Skip PR/Issue import; use git-log only
- **"Knowledge base not found"**: Prompt user to create KB first via `jfox-common`
- **Partial bulk import failure**: Report success/failure counts; do not retry failures
