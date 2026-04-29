# Make Daemon Dependencies Required — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move `fastapi` and `uvicorn` from optional `[daemon]` extras to required dependencies so `jfox daemon start` works out of the box after `uv tool install jfox`.

**Architecture:** Config-only change (no code changes). Move two packages in `pyproject.toml`, then update all documentation that references `[daemon]` as an optional extra.

**Tech Stack:** Python packaging (pyproject.toml), Markdown docs

---

## File Structure

| File | Change | Responsibility |
|------|--------|---------------|
| `pyproject.toml` | Modify | Move fastapi/uvicorn to required deps, remove `[daemon]` extra |
| `uv.lock` | Regenerate | `uv lock` updates lockfile after pyproject.toml change |
| `README.md` | Modify | Update daemon description (remove "可选依赖") |
| `CLAUDE.md` | Modify | Update daemon description (remove "可选依赖") |
| `docs/installation.md` | Modify | Add fastapi/uvicorn to Requirements list |
| `skills-recommend/claude-code/jfox-common/SKILL.md` | Modify | Remove `[daemon]` optional note |
| `skills-recommend/claude-code/jfox-search/SKILL.md` | Modify | Remove `[daemon]` optional note |
| `skills-recommend/claude-code/jfox-ingest/SKILL.md` | Modify | Remove `[daemon]` optional note |
| `skills-recommend/claude-code/jfox-organize/SKILL.md` | Modify | Remove `[daemon]` optional note |
| `docs/superpowers/plans/2026-04-14-sync-docs-daemon-show.md` | Modify | Remove `[daemon]` optional notes |

---

### Task 1: Move daemon deps to required in pyproject.toml

**Files:**
- Modify: `pyproject.toml:26-37,39-54`

- [ ] **Step 1: Edit `pyproject.toml` — add fastapi and uvicorn to dependencies**

Change the `dependencies` list in `pyproject.toml` from:

```toml
dependencies = [
    "typer>=0.12.0",
    "rich>=13.0.0",
    "sentence-transformers>=3.0",
    "chromadb>=0.5.0",
    "networkx>=3.0",
    "watchdog>=3.0",
    "pyyaml>=6.0",
    "pydantic>=2.0",
    "rank-bm25>=0.2.2",
    "jinja2>=3.0",
]
```

to:

```toml
dependencies = [
    "typer>=0.12.0",
    "rich>=13.0.0",
    "sentence-transformers>=3.0",
    "chromadb>=0.5.0",
    "networkx>=3.0",
    "watchdog>=3.0",
    "pyyaml>=6.0",
    "pydantic>=2.0",
    "rank-bm25>=0.2.2",
    "jinja2>=3.0",
    "fastapi>=0.110.0",
    "uvicorn[standard]>=0.27.0",
]
```

Then delete the entire `[daemon]` section under `[project.optional-dependencies]`:

```toml
daemon = [
    "fastapi>=0.110.0",
    "uvicorn[standard]>=0.27.0",
]
```

The `[project.optional-dependencies]` section should end up with only the `dev` entry.

- [ ] **Step 2: Regenerate uv.lock**

Run: `uv lock`

Expected: Lockfile updated with fastapi/uvicorn resolution.

- [ ] **Step 3: Verify installation**

Run: `uv sync --extra dev`

Expected: fastapi and uvicorn installed (visible in output).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "chore: move daemon deps (fastapi, uvicorn) to required dependencies

Closes #150"
```

---

### Task 2: Update README.md

**Files:**
- Modify: `README.md:57,70,88`

- [ ] **Step 1: Update Mermaid diagram — remove "(可选)" from daemon label**

In `README.md` line 57, change:

```
daemon["daemon/<br/>HTTP Server (可选)"]
```

to:

```
daemon["daemon/<br/>HTTP Server"]
```

- [ ] **Step 2: Update module table — daemon description**

In `README.md` line 88, change:

```
| `daemon/` | Embedding HTTP 守护进程（可选依赖 `[daemon]`），常驻模型避免重复加载 |
```

to:

```
| `daemon/` | Embedding HTTP 守护进程，常驻模型避免重复加载 |
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: remove optional daemon references from README"
```

---

### Task 3: Update CLAUDE.md

**Files:**
- Modify: `CLAUDE.md:70`

- [ ] **Step 1: Update daemon description in module table**

In `CLAUDE.md` line 70, change:

```
| `daemon/` | Embedding 模型 HTTP 守护进程（可选依赖 `[daemon]`），`jfox daemon start/stop/status` |
```

to:

```
| `daemon/` | Embedding 模型 HTTP 守护进程，`jfox daemon start/stop/status` |
```

- [ ] **Step 2: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: remove optional daemon references from CLAUDE.md"
```

---

### Task 4: Update docs/installation.md

**Files:**
- Modify: `docs/installation.md:44`

- [ ] **Step 1: Add fastapi and uvicorn to Requirements list**

In `docs/installation.md` line 44, change:

```
- Dependencies: typer, rich, sentence-transformers, chromadb, networkx, watchdog, pyyaml
```

to:

```
- Dependencies: typer, rich, sentence-transformers, chromadb, networkx, watchdog, pyyaml, fastapi, uvicorn
```

- [ ] **Step 2: Commit**

```bash
git add docs/installation.md
git commit -m "docs: add fastapi/uvicorn to installation requirements"
```

---

### Task 5: Update skills-recommend/ SKILL.md files

**Files:**
- Modify: `skills-recommend/claude-code/jfox-common/SKILL.md:350`
- Modify: `skills-recommend/claude-code/jfox-search/SKILL.md:108`
- Modify: `skills-recommend/claude-code/jfox-ingest/SKILL.md:246`
- Modify: `skills-recommend/claude-code/jfox-organize/SKILL.md:166`

- [ ] **Step 1: Update jfox-common/SKILL.md**

In `skills-recommend/claude-code/jfox-common/SKILL.md` line 350, change:

```
注意：daemon 是可选依赖 `[daemon]`，未安装时自动 fallback 到本地模型加载。
```

to:

```
注意：daemon 依赖（fastapi、uvicorn）已作为必选依赖安装，`jfox daemon start` 可直接使用。
```

- [ ] **Step 2: Update jfox-search/SKILL.md**

In `skills-recommend/claude-code/jfox-search/SKILL.md` line 108, change:

```
- **Slow search**: First search loads embedding model (30-60s). Subsequent searches are fast. 可通过 `jfox daemon start`（需安装 `[daemon]` 依赖）启动守护进程避免重复加载。
```

to:

```
- **Slow search**: First search loads embedding model (30-60s). Subsequent searches are fast. 可通过 `jfox daemon start` 启动守护进程避免重复加载。
```

- [ ] **Step 3: Update jfox-ingest/SKILL.md**

In `skills-recommend/claude-code/jfox-ingest/SKILL.md` line 246, change:

```
# 批量导入加速（可选，需安装 [daemon] 依赖）
```

to:

```
# 批量导入加速（可选）
```

- [ ] **Step 4: Update jfox-organize/SKILL.md**

In `skills-recommend/claude-code/jfox-organize/SKILL.md` line 166, change:

```
# 批量整理加速（可选，需安装 [daemon] 依赖）
```

to:

```
# 批量整理加速（可选）
```

- [ ] **Step 5: Commit**

```bash
git add skills-recommend/
git commit -m "docs: remove [daemon] optional dependency notes from skills"
```

---

### Task 6: Update existing plan doc

**Files:**
- Modify: `docs/superpowers/plans/2026-04-14-sync-docs-daemon-show.md:64,169,245`

- [ ] **Step 1: Update all three occurrences**

Line 64 — change:

```
| `daemon/` | Embedding HTTP 守护进程（可选依赖 `[daemon]`），常驻模型避免重复加载 |
```

to:

```
| `daemon/` | Embedding HTTP 守护进程，常驻模型避免重复加载 |
```

Line 169 — change:

```
注意：daemon 是可选依赖 `[daemon]`，未安装时自动 fallback 到本地模型加载。
```

to:

```
注意：daemon 依赖（fastapi、uvicorn）已作为必选依赖安装，`jfox daemon start` 可直接使用。
```

Line 245 — change:

```
+ - **Slow search**: First search loads embedding model (30-60s). Subsequent searches are fast. 可通过 `jfox daemon start`（需安装 `[daemon]` 依赖）启动守护进程避免重复加载。
```

to:

```
+ - **Slow search**: First search loads embedding model (30-60s). Subsequent searches are fast. 可通过 `jfox daemon start` 启动守护进程避免重复加载。
```

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-04-14-sync-docs-daemon-show.md
git commit -m "docs: remove [daemon] optional notes from plan doc"
```

---

### Task 7: Final verification

**Files:** None (verification only)

- [ ] **Step 1: Verify no remaining `[daemon]` optional references**

Run: `grep -rn "\[daemon\]" --include="*.md" --include="*.toml" .`

Expected: Zero matches (or only historical changelog entries that are fine to keep).

- [ ] **Step 2: Verify pyproject.toml correctness**

Run: `uv run python -c "import fastapi; import uvicorn; print('OK')"`

Expected: `OK`

- [ ] **Step 3: Run fast tests to confirm no breakage**

Run: `uv run pytest tests/ -m "not slow and not embedding" -x`

Expected: All tests pass. Hand this command to the user for manual execution if it's too slow.

---

## Self-Review

1. **Spec coverage:** Issue #150 acceptance criteria all covered — pyproject.toml change (Task 1), installation.md (Task 4), all `[daemon]` doc references (Tasks 2-6), verification (Task 7).
2. **Placeholder scan:** All steps contain exact code/commands. No TBD/TODO placeholders.
3. **Type consistency:** N/A — this is a config/doc-only change, no types involved.
