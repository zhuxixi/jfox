# English README Baseline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rewrite the root `README.md` into an accurate English, dual-audience, local-first Zettelkasten entry point while keeping exhaustive CLI documentation and automation for later phases.

**Architecture:** Keep `README.md` as a human-curated landing page organized around the user journey. Preserve only a small, representative command overview and explain that complete command help comes from the Typer CLI until a later generated reference is introduced. Represent the current product through conceptual workflows rather than an exhaustive Python module map.

**Tech Stack:** Markdown, Mermaid (optional), Typer CLI verification, `markdownlint-cli2`, Python standard-library link checking, Git.

## Global Constraints

- Modify the root `README.md` as the primary deliverable.
- Do not change `jfox/cli.py`, runtime Typer help text, application behavior, `.github/workflows/*`, `scripts/*`, `AGENTS.md`, or `CLAUDE.md`.
- Do not create `docs/cli-reference.md`, a generator, a CI drift gate, an automated PR workflow, or an AI-generated README workflow.
- Write all user-facing prose in `README.md` in English.
- Position JFox as a **local-first Zettelkasten knowledge management CLI**.
- Serve first-time knowledge-management users before CLI users, developers, and contributors.
- Document exactly six current note types: `fleeting`, `literature`, `permanent`, `session`, `candidate`, and `structure`.
- Document exactly five current gem levels: `chipped`, `flawed`, `normal`, `flawless`, and `perfect`.
- Describe candidate notes as reviewable proposals that require human review before promotion.
- Keep the README command section curated and explicitly non-exhaustive.
- Do not use unqualified “all offline” wording; distinguish local core operations from optional `claude -p` transmission for auto-summary.
- Do not hard-code plugin skill counts or `cli.py` line counts.
- Follow `.markdownlint-cli2.jsonc` and the existing `markdownlint-cli2` command.
- Do not add a `LICENSE` file in this phase; the current repository has MIT metadata but no tracked `LICENSE` target, so the README must not retain a broken `LICENSE` link.

---

## File Map

- Modify: `README.md` — the English, human-curated project landing page and user documentation baseline.
- Create: `docs/superpowers/specs/2026-08-29-english-readme-baseline-design.md` — the approved design spec copied into the implementation worktree before implementation.
- Create: `docs/superpowers/plans/2026-08-29-english-readme-baseline.md` — this implementation plan.
- Do not modify runtime code or automation files.

## Source-of-Truth Inventory

Use these sources while implementing; do not infer current facts from the old README:

| Fact | Source |
|---|---|
| CLI top-level and nested command names | `jfox/cli.py` and the registered Typer sub-app modules; verify with `uv run jfox --help` and relevant subcommand help. |
| Note types and gem levels | `jfox/models.py` (`NoteType` and `GemLevel`). |
| Package version, Python requirement, dependency metadata | `pyproject.toml` and `jfox/__init__.py`. |
| Claude Code skill inventory | `packages/cc-plugin/skills/` and its manifest/package files. |
| Kimi Code skill inventory | `packages/kimi-plugin/skills/` and `packages/kimi-plugin/README.md`. |
| pi skill inventory | `skills-recommend/pi/` and `skills-recommend/README.md`. |
| Installation and troubleshooting links | `docs/installation.md` and `docs/troubleshooting.md`. |
| Existing repository verification commands | `.github/workflows/integration-test.yml` and `AGENTS.md`; read-only reference only. |

---

### Task 1: Freeze the README facts and remove unsupported claims

**Files:**

- Read: `README.md`
- Read: `jfox/models.py`
- Read: `jfox/cli.py`
- Read: `pyproject.toml`
- Read: `packages/cc-plugin/skills/`
- Read: `packages/kimi-plugin/skills/`
- Read: `skills-recommend/pi/`
- Modify: `README.md`

**Interfaces:**

- Consumes: The current repository source-of-truth inventory above.
- Produces: A rewrite checklist used by every later task; no runtime-code changes.

- [ ] **Step 1: Capture current model facts.**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-457-english-readme
sed -n '35,65p' jfox/models.py
```

Expected: the output contains the six `NoteType` values and the five `GemLevel` values. Use these exact code identifiers in the README tables and lifecycle description.

- [ ] **Step 2: Capture current CLI surface.**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-457-english-readme
uv run jfox --help
for command in init add search list show edit archive unarchive query graph refs index kb model fragments candidates gem-synth bookshelf moc auto-summary backup; do
  uv run jfox "$command" --help >/tmp/jfox-readme-"$command"-help.txt
done
```

Expected: every listed command exits successfully. Use only commands that are confirmed by this output in the curated overview; do not copy the complete generated help output into `README.md`.

- [ ] **Step 3: Capture package facts and link targets.**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-457-english-readme
printf '%s\n' '--- package metadata ---'
grep -n -E '^(version|readme|license|requires-python)\s*=' pyproject.toml
printf '%s\n' '--- user-facing links ---'
for path in pyproject.toml docs/installation.md docs/troubleshooting.md packages/kimi-plugin/README.md; do
  test -e "$path" && printf 'exists: %s\n' "$path" || printf 'missing: %s\n' "$path"
done
printf '%s\n' '--- license target ---'
test -e LICENSE && echo 'LICENSE exists' || echo 'LICENSE is absent; do not link to it'
```

Expected: `LICENSE` is reported absent; `docs/installation.md`, `docs/troubleshooting.md`, and `packages/kimi-plugin/README.md` are reported present. Use only existing targets in README links.

- [ ] **Step 4: Record the rewrite constraints before editing.**

Use this checklist while rewriting:

```text
README identity: local-first Zettelkasten CLI
Primary reading order: value → first workflow → advanced workflows → technical entry points
NoteType coverage: fleeting, literature, permanent, session, candidate, structure
GemLevel coverage: chipped, flawed, normal, flawless, perfect
Major workflows: notes/links, search/graph/MOC, gem refinement, bookshelf, preservation
Runtime help: unchanged and not translated in this phase
Exhaustive CLI reference: deferred; no docs/cli-reference.md link yet
Plugin counts: omitted
Implementation line counts: omitted
Privacy: local core separated from optional auto-summary network transmission
```

Expected: subsequent README edits follow this list without expanding Phase 1 into automation or runtime localization.

---

### Task 2: Rewrite the project identity, user value, and feature overview

**Files:**

- Modify: `README.md` (header through the feature overview)

**Interfaces:**

- Consumes: Task 1's verified product facts and the approved terminology in `docs/superpowers/specs/2026-08-29-english-readme-baseline-design.md`.
- Produces: An English landing section that a new user can scan without reading implementation details.

- [ ] **Step 1: Replace the opening with the approved positioning.**

Use the following content direction near the top of `README.md`:

```markdown
# JFox

![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)
[![Python](https://img.shields.io/badge/python-3.10%2B-blue.svg)](pyproject.toml)
![Platform](https://img.shields.io/badge/platform-Windows%20%7C%20macOS%20%7C%20Linux-lightgrey.svg)

> A local-first Zettelkasten knowledge management CLI.

JFox keeps your knowledge in plain Markdown files, connects notes with `[[wiki links]]`, and makes the resulting knowledge base searchable and navigable through local indexes and graph analysis.
```

Keep the valid Python, platform, and MIT badges only if their links resolve. Do not link the MIT badge to the absent `LICENSE` file.

- [ ] **Step 2: Add a concise `What is JFox?` section.**

Explain, in English and in user terms, that JFox:

- applies the Zettelkasten method to a local knowledge base;
- stores notes as plain Markdown with YAML frontmatter;
- uses `[[wiki links]]` and backlinks to connect knowledge;
- supports keyword and semantic retrieval;
- provides graph and MOC navigation;
- is local-first rather than a hosted knowledge service.

Do not introduce ChromaDB, BM25, NetworkX, or source-file names before the reader understands the user value.

- [ ] **Step 3: Consolidate the feature overview into one non-repetitive section.**

Use a single `## Features` or `## What you can do` section, not two duplicate bullet lists. Cover these user-facing capabilities:

```markdown
- Capture and refine notes through distinct note types.
- Connect ideas with wiki links and automatically maintained backlinks.
- Search by exact terms and meaning through hybrid search.
- Navigate related knowledge with graph analysis and structure notes (MOCs).
- Refine session fragments into candidate knowledge gems for human review.
- Manage PDFs, extracted bundles, and metadata as local bookshelf assets.
- Separate work, personal, and research content into multiple knowledge bases.
- Run optional background services, backups, and Claude Code session auto-summary.
```

Each item must state the benefit before the implementation term. Keep the descriptions short enough to remain a landing-page overview.

- [ ] **Step 4: Remove stale identity claims.**

Delete or rewrite all of the following from the old opening and feature area:

- `Three note types`;
- unqualified `all offline` wording;
- source-file line-count claims;
- implementation modules presented as the primary product explanation;
- any stale model name or dimension not confirmed by Task 1.

Expected: a first-time reader can understand what JFox does without reading the architecture section.

---

### Task 3: Rewrite Quick Start and explain the core user workflows

**Files:**

- Modify: `README.md` (Quick Start and workflow sections)

**Interfaces:**

- Consumes: Verified CLI command names from Task 1.
- Produces: A runnable first-use path and concise explanations of current product workflows.

- [ ] **Step 1: Keep Quick Start to one complete user journey.**

Use this command sequence, adapting only syntax confirmed by `uv run jfox --help`:

```bash
# Install from the repository
uv tool install "git+https://github.com/zhuxixi/jfox.git"

# Initialize the default knowledge base
jfox init

# Create a permanent note
jfox add "Atomic notes become useful when they are connected." \\
  --title "Connected Notes" --type permanent

# Create a second note with a wiki link
jfox add "See [[Connected Notes]] for the starting principle." \\
  --title "A Linked Note" --type permanent

# Search the knowledge base
jfox search "connected notes"
```

Keep `docs/installation.md` as the destination for upgrade, uninstall, PATH, and model-download details. Do not duplicate that entire guide.

- [ ] **Step 2: Add a `Core Workflows` section.**

Explain the following workflows with one short purpose paragraph and one representative command/example where useful:

1. **Capture and connect notes** — distinguish fleeting, literature, and permanent notes; explain wiki links and backlinks.
2. **Search and navigate knowledge** — explain keyword search, semantic search, hybrid search, graph traversal, refs, and MOCs without promising unstable latency or ranking details.
3. **Refine knowledge with the gem pipeline** — introduce the exact flow below and explain the human-review boundary.
4. **Organize and preserve knowledge** — cover archive/unarchive, multiple knowledge bases, backup/restore, the embedding daemon, and optional auto-summary.
5. **Manage books as local assets** — explain PDFs, extracted bundles, JFox metadata, and that bookshelf assets are not automatically note-indexed.

Use this exact conceptual pipeline:

```text
session fragments
    → gem synthesis
    → candidate notes
    → human review
    → permanent notes
```

State that a candidate is a reviewable proposal, not trusted permanent knowledge, and that current L3 synthesis produces a `flawed` candidate when the implementation detail is mentioned.

- [ ] **Step 3: Make the privacy boundary visible inside the workflow explanation.**

Add a concise note that:

- notes, indexes, and core search/graph operations run locally by default;
- embedding models may be downloaded on first use;
- optional auto-summary invokes `claude -p` and sends session text to Anthropic;
- auto-summary is opt-in.

Expected: a user can distinguish JFox's local-first core from the optional network-dependent summarization path.

---

### Task 4: Add the accurate note model and a curated command overview

**Files:**

- Modify: `README.md` (Note Model and command sections)

**Interfaces:**

- Consumes: `jfox/models.py` enum values and Task 1's CLI help verification.
- Produces: Accurate data-model documentation and a non-exhaustive command map that will not compete with the future generated reference.

- [ ] **Step 1: Add the six-note-type table.**

Use a table with these exact values and meanings:

```markdown
| Value | Meaning |
|---|---|
| `fleeting` | A quick capture or temporary idea. |
| `literature` | Notes derived from reading or source material. |
| `permanent` | Refined knowledge intended to remain useful. |
| `session` | A record of an AI-agent session. |
| `candidate` | A synthesized proposal awaiting human review. |
| `structure` | A Map of Content (MOC) used to organize related notes. |
```

Confirm the final table against `jfox/models.py` before saving.

- [ ] **Step 2: Add the five-level GemLevel lifecycle.**

Use:

```text
chipped → flawed → normal → flawless → perfect
```

Explain:

- `chipped` represents raw fragments and is not a note-file state;
- `flawed` is the current L3 candidate output;
- later levels represent increasing maturity;
- promotion to `permanent` is a human review decision.

Do not state that every candidate automatically becomes permanent.

- [ ] **Step 3: Replace the exhaustive command tables with `Common Commands`.**

Keep representative command groups and examples, including:

```text
Knowledge base: jfox init, jfox kb list, jfox kb info
Notes: jfox add, jfox list, jfox show, jfox edit, jfox archive, jfox unarchive, jfox delete
Search and navigation: jfox search, jfox query, jfox refs, jfox graph, jfox moc
Refinement: jfox fragments, jfox candidates, jfox gem-synth
Assets and preservation: jfox bookshelf, jfox index, jfox backup, jfox daemon, jfox auto-summary
Maintenance: jfox config, jfox model, jfox check, jfox update, jfox redirect
```

Do not claim that this list is exhaustive. Do not manually reproduce every option or nested command.

- [ ] **Step 4: Add the future-reference boundary without a broken link.**

Add this English explanation after the curated overview:

```markdown
For the complete current command and option list, run `jfox --help` or `jfox <command> --help`. An exhaustive generated CLI reference is planned for a later documentation phase.
```

Do not link to `docs/cli-reference.md` because it is not created in Phase 1.

Expected: the README covers the current command families without becoming a second, manually maintained CLI manual.

---

### Task 5: Replace implementation-heavy architecture and refresh integrations, development, and closing sections

**Files:**

- Modify: `README.md` (Architecture through the end)

**Interfaces:**

- Consumes: The stable conceptual boundary in the approved spec and verified links from Task 1.
- Produces: A concise technical entry point that does not encode fragile file counts or stale inventories.

- [ ] **Step 1: Replace the old module map with conceptual architecture.**

Use a short conceptual explanation and, only if it remains readable, a Mermaid diagram based on:

```text
Users and agent integrations
            ↓
CLI and workflow orchestration
            ↓
Markdown notes and bookshelf assets
            ↓
Local indexes and embedding services
            ↓
Search, graph/MOC, refinement, and preservation workflows
```

Remove the old exhaustive `Module Map` table and any `cli.py` line-count statement. Do not list every current package as an architectural layer.

- [ ] **Step 2: Remove stale detailed sequence diagrams or rewrite them as stable user flows.**

Review the old note-creation, index-rebuild, hybrid-search, and graph-traversal diagrams. Keep only diagrams whose behavior is still a stable user-facing contract. If a diagram depends on implementation details such as a specific internal call sequence, replace it with a short prose workflow rather than preserving a misleading diagram.

- [ ] **Step 3: Refresh `Agent Integrations` without hard-coded counts.**

Describe these integration surfaces:

- Claude Code plugin — knowledge-base management, search, ingest, organization, promotion, session capture/refinement, and related skills as currently provided by the package.
- Kimi Code plugin — the maintained plugin package, with a link to `packages/kimi-plugin/README.md`.
- pi Agent Skills — the repository's recommended skills under `skills-recommend/pi/`.

Describe capability categories and links. Do not write “5 skills”, “6 skills”, or any other fixed count.

- [ ] **Step 4: Keep installation and development concise and accurate.**

Retain:

```bash
uv sync --extra dev
uv run pytest tests/ -m "not embedding and not slow"
```

Link to existing `docs/installation.md` and `docs/troubleshooting.md`. Keep the Python requirement aligned with `pyproject.toml`. Do not change the installation guide in this phase unless a README link contradiction is discovered and the PR explicitly records that separate correction.

- [ ] **Step 5: Add or revise Privacy, License, and Acknowledgments.**

Use the precise privacy wording from Task 3. Keep MIT licensing as plain text or link only to an existing valid target; do not retain `[MIT](LICENSE)` while `LICENSE` is absent. Preserve valid dependency acknowledgments and links. Keep the closing sections short.

Expected: the end of README provides contributor and privacy context without introducing new undocumented promises.

---

### Task 6: Validate the README baseline and prepare the implementation diff

**Files:**

- Read: `README.md`
- Read: `jfox/models.py`
- Read: `pyproject.toml`
- Read: relevant CLI help output
- Modify: `README.md` only if validation finds an issue

**Interfaces:**

- Consumes: The complete README rewrite from Tasks 2–5.
- Produces: A verified README-only implementation diff ready for review.

- [ ] **Step 1: Run Markdown lint.**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-457-english-readme
npx --yes markdownlint-cli2 README.md
```

Expected: exit code 0 and `Summary: 0 issues in 0 files`.

- [ ] **Step 2: Verify all relative README links.**

Run this exact standard-library checker from the worktree:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-457-english-readme
python - <<'PY'
from pathlib import Path
import re

readme = Path("README.md")
text = readme.read_text(encoding="utf-8")
links = re.findall(r"\[[^\]]+\]\(([^)]+)\)", text)
errors = []
for target in links:
    if target.startswith(("http://", "https://", "#", "mailto:")):
        continue
    target_path = (readme.parent / target.split("#", 1)[0]).resolve()
    if not target_path.exists():
        errors.append(f"{target} -> {target_path}")
if errors:
    print("Broken README links:")
    print("\n".join(errors))
    raise SystemExit(1)
print(f"Checked {len(links)} README links; all relative targets exist.")
PY
```

Expected: exit code 0 and no missing target. This check must confirm that `LICENSE` is not linked unless a valid target has been added separately.

- [ ] **Step 3: Verify CLI examples and runtime-help isolation.**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-457-english-readme
uv run jfox --help >/tmp/jfox-readme-final-help.txt
uv run jfox init --help >/tmp/jfox-readme-init-help.txt
uv run jfox add --help >/tmp/jfox-readme-add-help.txt
uv run jfox search --help >/tmp/jfox-readme-search-help.txt
git diff -- jfox/cli.py
```

Expected: all help commands exit successfully and `git diff -- jfox/cli.py` is empty. Run additional help commands for any extra command used as a copy-paste example.

- [ ] **Step 4: Verify model facts and drift-prone wording.**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-457-english-readme
for value in fleeting literature permanent session candidate structure chipped flawed normal flawless perfect; do
  grep -Fq "\`$value\`" README.md || { echo "Missing documented value: $value"; exit 1; }
done
! grep -Fq 'Three note types' README.md
! grep -Eiq 'all offline|100% offline|completely offline' README.md
! grep -Eiq '[0-9]+ (skills|skill directories)' README.md
! grep -Eiq 'cli\.py.*[0-9]{3,4}|[0-9]{3,4}.*cli\.py' README.md
```

Expected: every required enum value is present and all four stale-claim checks succeed.

- [ ] **Step 5: Check diff hygiene and scope.**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-457-english-readme
git diff --check
git status --short
git diff --stat
git diff -- README.md
```

Expected:

- no whitespace errors;
- the implementation diff contains `README.md` as the only application/documentation file changed;
- the approved spec and this plan are present in the worktree as the pre-implementation design trail;
- no runtime code, workflow, generated-reference, or unrelated file changes appear.

- [ ] **Step 6: Report verification evidence in the PR and parent issue.**

Record:

```text
- README language and information architecture reviewed
- NoteType: 6/6 values documented
- GemLevel: 5/5 values documented
- CLI examples/help checks: passed
- Relative README links: passed
- markdownlint: passed
- git diff --check: passed
- Runtime CLI help changed: no
- Automation/generator files changed: no
```

Do not claim completion until the commands in this task have been run on the final diff.

---

## Review Handoff

After the plan is approved for execution, use the repository's implementation workflow in the isolated worktree. Because this task is documentation-only, a single writer should own `README.md`; do not dispatch multiple concurrent writers against the same file. Request a focused review that checks:

1. English readability for both audiences;
2. factual accuracy against `jfox/models.py`, CLI help, and package directories;
3. privacy and local-first wording;
4. curated/generated boundary;
5. Markdown and relative-link verification;
6. README-only scope.

The next automation phase must start from this baseline and must not reintroduce exhaustive hand-maintained CLI tables into the README.
