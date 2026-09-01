# CI Docs Drift Gate Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a CI drift gate to the existing `lint` job that regenerates `docs/cli-reference.md` and fails PRs when the committed copy is stale, plus the path-filter and README changes that make the gate unbypassable and discoverable.

**Architecture:** No new code. One shell step appended to the `lint` job of `.github/workflows/integration-test.yml` runs the existing generator and fails on `git diff --exit-code` with an actionable `::error::` annotation. Two path-filter entries close the bypass hole (`scripts/**`, `docs/cli-descriptions.yaml`). README gains a maintenance note. Verification is red/green self-proof inside the PR.

**Tech Stack:** GitHub Actions YAML, existing `scripts/generate_docs.py` (Phase 2A), git.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-01-ci-docs-drift-gate-design.md` (issue #476, parent #456).
- Do not create a new workflow; do not modify `quality-gate` needs; branch protection stays untouched.
- Do not modify `scripts/generate_docs.py`, `docs/cli-descriptions.yaml` semantics (a comment-only touch is used for filter proof), or anything under `jfox/` / `tests/`.
- The gate verifies only — it never commits, pushes, or opens PRs.
- **Never push or open a PR from this plan.** Pushing requires the user's explicit permission (AGENTS.md hard rule); the red/green CI evidence completes after the push step, outside this plan.
- All commands run inside the worktree at `/home/elling/git-repo/github/jfox/.pi/worktrees/issue-476-ci-docs-drift-gate` (call it `$WT`).
- Stage files explicitly with `git add <file>`; never `git add -A`.
- Commit messages use conventional commits and reference `(#476)`.
- Single platform (Ubuntu) for the gate; no new dependencies.

---

## File Structure

| File | Responsibility |
|---|---|
| `.github/workflows/integration-test.yml` (modify) | Drift gate step + two path-filter entries per trigger |
| `README.md` (modify) | Maintenance note under `### Run checks` |
| `docs/cli-reference.md` (regenerated) | Red/green self-proof commits only |
| `docs/cli-descriptions.yaml` (comment-only touch) | Path-filter trigger proof (A3) |

---

### Task 1: Drift gate step and path filters in integration-test.yml

**Files:**

- Modify: `.github/workflows/integration-test.yml`

**Interfaces:**

- Consumes: nothing new; relies on the existing `lint` job environment (`uv sync --extra dev` already installs everything `generate_docs.py` needs).
- Produces: the gate step consumed by CI on every matching PR/push; path filters consumed by GitHub's workflow trigger engine.

**Acceptance IDs:** A1 (red path lives here), A2 (green path lives here), A3 (filter entries), A4 (existing steps untouched), A5 (simulated locally).

- [ ] **Step 1: Add the two path-filter entries to the `push` trigger**

In `$WT/.github/workflows/integration-test.yml`, locate the first `paths:` block (under `push:`, around line 13). After the existing `'**/*.md'` line, insert:

```yaml
      - 'scripts/**'
      - 'docs/cli-descriptions.yaml'
```

- [ ] **Step 2: Add the same two entries to the `pull_request` trigger**

Locate the second `paths:` block (under `pull_request:`, around line 21) and apply the identical insertion after its `'**/*.md'` line.

- [ ] **Step 3: Append the drift gate step to the `lint` job**

At the end of the `lint` job's `steps:` list, directly after the `Run markdownlint` step, append:

```yaml
    - name: Check generated docs are up to date
      run: |
        uv run python scripts/generate_docs.py
        if ! git diff --exit-code; then
          echo "::error::Generated docs are stale. Regenerate locally with:"
          echo "::error::  uv run python scripts/generate_docs.py"
          echo "--- Changed files ---"
          git diff --name-only
          exit 1
        fi
```

The step must sit at the same indentation as the other `- name:` entries in the job (4 spaces), and the `run:` body lines at 8/10-space indent as shown.

- [ ] **Step 4: Verify YAML syntax**

Run in `$WT`:

```bash
uv run python -c "import yaml; yaml.safe_load(open('.github/workflows/integration-test.yml')); print('YAML syntax OK')"
```

Expected: prints `YAML syntax OK`, no exception. (PyYAML parses the `on:` key as a boolean — harmless for syntax checking; GitHub's parser treats it as the trigger key.)

- [ ] **Step 5: Simulate the gate locally on a clean tree (A5)**

Run in `$WT`:

```bash
uv run python scripts/generate_docs.py && git diff --exit-code && echo "GATE GREEN"
```

Expected: `Generated docs/cli-reference.md` followed by `GATE GREEN` (exit 0 — the committed reference on this branch is already fresh).

- [ ] **Step 6: Commit**

```bash
git add .github/workflows/integration-test.yml
git commit -m "ci: add generated-docs drift gate to lint job (#476)"
```

---

### Task 2: README maintenance note

**Files:**

- Modify: `README.md` (extend the `### Run checks` section, no new heading)

**Interfaces:**

- Consumes: the generator command contract from Phase 2A (`uv run python scripts/generate_docs.py`).
- Produces: contributor-facing documentation consumed by humans only.

**Acceptance IDs:** A6, A4 (README must stay markdownlint-clean).

- [ ] **Step 1: Append the maintenance paragraph**

In `$WT/README.md`, inside `### Run checks` (around line 289), directly after the code block ending with the `npx --yes markdownlint-cli2 "**/*.md" "#node_modules" "#.venv"` line and before the blank line that precedes `## Privacy`, add:

````markdown
The CLI reference at [docs/cli-reference.md](docs/cli-reference.md) is generated
from the live Typer command tree and `docs/cli-descriptions.yaml`. After
changing CLI commands or command descriptions, regenerate it and commit the
result:

```bash
uv run python scripts/generate_docs.py
```

CI fails when the committed reference is stale.
````

- [ ] **Step 2: Verify the instruction is present (A6)**

Run in `$WT`:

```bash
grep -n "generate_docs.py" README.md
```

Expected: the command appears in the new paragraph (plus the existing README link areas if any).

- [ ] **Step 3: Verify markdownlint stays green on README (A4)**

Run in `$WT`:

```bash
npx --yes markdownlint-cli2@0.23.2 README.md
```

Expected: exit 0, no findings.

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: document CLI reference regeneration under Run checks (#476)"
```

---

### Task 3: Red/green self-proof commit sequence

**Files:**

- Modify (temporarily): `docs/cli-reference.md` — red commit
- Modify: `docs/cli-reference.md` — green commit (regenerated)
- Modify (comment only): `docs/cli-descriptions.yaml` — filter-proof commit

**Interfaces:**

- Consumes: the gate step built in Task 1; the generator as-is.
- Produces: three commits in PR history that serve as A1/A2/A3 evidence once pushed; the working tree ends fresh and clean.

**Acceptance IDs:** A1 (red simulation), A2 (green simulation), A3 (filter trigger proof).

- [ ] **Step 1: Make the reference deliberately stale (red commit)**

In `$WT/docs/cli-reference.md`, delete the line `Do not edit manually.` from the generated-file marker at the top of the file (the third line of the file, inside the `<!--` block). Nothing else changes — this is a content-only removal that markdownlint cannot flag.

Commit the stale file:

```bash
git add docs/cli-reference.md
git commit -m "test(docs): deliberately stale cli reference (drift-gate red proof) (#476)"
```

- [ ] **Step 2: Prove the gate would fail on this commit (A1, local simulation)**

Run in `$WT`:

```bash
uv run python scripts/generate_docs.py; git diff --exit-code; echo "exit=$?"
```

Expected: the generator restores the deleted line, so `git diff --exit-code` reports the difference against the red commit and prints `exit=1`. This is exactly what the CI gate will do on the red commit: regenerate, see a diff, emit the `::error::` annotation, and fail.

- [ ] **Step 3: Commit the regenerated file (green commit)**

After Step 2 the working tree already holds the fresh reference. Commit it:

```bash
git add docs/cli-reference.md
git commit -m "docs: regenerate cli reference (drift-gate green proof) (#476)"
```

- [ ] **Step 4: Prove the gate would pass on this commit (A2, local simulation)**

Run in `$WT`:

```bash
uv run python scripts/generate_docs.py && git diff --exit-code && echo "GATE GREEN"
```

Expected: `Generated docs/cli-reference.md` then `GATE GREEN` (exit 0). This is exactly what CI will do on the green commit.

- [ ] **Step 5: Prove the new YAML path filter has a trigger (A3)**

Append one comment line to the end of `$WT/docs/cli-descriptions.yaml` (comment-only, no semantic change):

```yaml
# Trigger check for the Phase 3 drift-gate path filter.
```

Confirm the generator output is unaffected:

```bash
uv run python scripts/generate_docs.py && git diff --exit-code && echo "NO CHANGE"
```

Expected: `Generated docs/cli-reference.md` then `NO CHANGE` (exit 0 — comments are not parsed by `load_descriptions`).

Commit:

```bash
git add docs/cli-descriptions.yaml
git commit -m "docs: comment-only touch of cli-descriptions.yaml (path-filter proof) (#476)"
```

- [ ] **Step 6: Verify final branch state**

Run in `$WT`:

```bash
git log --oneline -5
git status --short
```

Expected: latest five commits are the four plan commits (Task 1, Task 2, red, green, filter-proof) on top of `07c1b76`; `git status --short` prints nothing (clean tree).

---

### Task 4: Final local verification and acceptance reconciliation

**Files:** none (verification only)

**Interfaces:**

- Consumes: all commits from Tasks 1–3.
- Produces: a verification record in the PR description (written at push time, outside this plan).

**Acceptance IDs:** A4, A5, A6, plus the local halves of A1/A2/A3.

- [ ] **Step 1: Full local lint pass**

Run in `$WT`:

```bash
npx --yes markdownlint-cli2@0.23.2 "**/*.md" "#node_modules" "#.venv"
```

Expected: exit 0. (Skip `ruff`/`black`: this branch changes no Python files.)

- [ ] **Step 2: Whole-tree freshness check**

Run in `$WT`:

```bash
uv run python scripts/generate_docs.py && git diff --exit-code && echo "GATE GREEN"
```

Expected: `GATE GREEN` on the final branch state — the branch itself must satisfy the gate.

- [ ] **Step 3: Acceptance reconciliation**

Confirm against the spec matrix: A1/A2 local simulations done in Task 3 Steps 2/4 (CI-side evidence completes after push); A3 filter entries exist (Task 1) and the comment commit proves triggering (Task 3 Step 5, CI-side after push); A4 existing lint steps untouched and markdownlint verified (Tasks 1/2/4); A5 verified (Task 1 Step 5 and Task 4 Step 2); A6 verified (Task 2 Step 2); U1 (`workflow_dispatch` smoke) remains for the user, optionally exercised on the PR branch.

- [ ] **Step 4: Stop**

Report completion and stop. Pushing/opening the PR is the next workflow step (issue-driven step 9) and requires the user's explicit permission.
