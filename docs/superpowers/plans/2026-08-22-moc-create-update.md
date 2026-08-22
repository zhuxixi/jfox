# MOC Create/Update Commands Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> 注：本文档为执行摘要版（完整版含逐步骤代码，见 SDD 会话记录；git 历史 3631ddd 曾含完整版）。

**Goal:** Add `NoteType.STRUCTURE` and `jfox moc create` / `jfox moc update` commands that turn diagnose clusters into maintainable MOC notes.

**Architecture:** Pure logic (draft/diff) lives in `jfox/moc/draft.py`; disk-write + backlinks backfill lives in `jfox/moc/generate.py`; CLI shells live in `jfox/moc/cli.py` reusing the existing `diagnose_moc_density` service (which already provides the read-only Chroma snapshot path). CLI commands stay thin; all business logic is in testable impl functions that take an explicit `ZKConfig`.

**Tech Stack:** Python 3.10+, Typer, Rich, dataclasses, pytest + unittest.mock, CliRunner (typer.testing).

## Global Constraints

- Line length 100; format with `black`; lint with `ruff` (project defaults from pyproject.toml).
- Chinese docstrings/comments (project convention); English commit messages (conventional commits).
- CLI error paths exit code 1 via `_fail(message, output_format)` and raise `typer.Exit(code=1)`; JSON errors are `{"success": false, "error": "..."}`.
- Help-text contract tests assert exact strings — any help text change must update its contract test in the same task.
- `jfox moc` group is registered on the root app via `app.add_typer(moc_app, ...)`; import of `jfox.cli` must not load chromadb/networkx/numpy (lazy import, keep `TYPE_CHECKING` pattern). All heavy imports (draft/generate/cluster) go inside function bodies or lazy wrapper functions.
- Run tests single-process; quick unit tests may run standalone, never the full suite.
- Never `git add -A`; stage exact file paths per task.

---

### Task 1: Add NoteType.STRUCTURE and dynamic type lists in CLI help/errors

**Files:** Modify `jfox/models.py`; Modify `jfox/cli.py` (5 hardcoded type-list sites); Test `tests/unit/test_note_type_structure.py`.

**Interfaces:**

- Produces: `NoteType.STRUCTURE = "structure"`; `cli.py` constants `_NOTE_TYPE_VALUES = ", ".join(t.value for t in NoteType)` and `_NOTE_TYPE_SLASH = "/".join(t.value for t in NoteType)`.

**Steps (TDD):**

1. Write 6 tests: enum member + count 6; `Note.filename` slug branch for structure; `to_markdown`/`from_markdown` roundtrip keeping `links`; constants cover all 6 values; `add --type nope` error message lists all 6 (strip ANSI); `add --help` contains slash list. Help tests pass `env={"COLUMNS": "200"}` to avoid Rich 80-col wrapping.
2. RED (import error for constants), then implement: enum member with comment `# 地图型笔记（MOC），导航/组织层`; constants after the NoteType import; replace error messages `Use: fleeting, literature, permanent, session` → `Use: {_NOTE_TYPE_VALUES}` (3 sites: `_add_note_impl`, `_list_impl`, `_edit_note_impl`) and help texts → `help=f"笔记类型 ({_NOTE_TYPE_SLASH})"` / `help=f"新类型 ({_NOTE_TYPE_SLASH})"` (2 sites).
3. GREEN, then commit `feat(models): add NoteType.STRUCTURE and dynamic CLI type lists`.

### Task 2: Pure draft/diff logic in jfox/moc/draft.py

**Files:** Create `jfox/moc/draft.py`; Test `tests/unit/test_moc_draft.py`.

**Interfaces (load-bearing for Tasks 4/5):**

- `DraftGroup(name: str, members: List[ClusterMember])`
- `MocCreateDraft(title: str, groups: List[DraftGroup], orphan_bucket: List[OrphanNote], total_members: int)`
- `build_moc_draft(cluster, tags_by_id, max_size, orphans=None, title=None) -> MocCreateDraft` — raises `ValueError("Cluster size N exceeds --max-size M; raise --threshold to split the cluster or pass a larger --max-size explicitly")` when size > max_size; grouping: tag count >= max(2, int(0.1 * size)) forms a group; groups sorted by coverage count descending; hub first in its group, then mean_similarity descending; leftovers → `其他`; default title `<hub.title> MOC`.
- `render_moc_content(draft) -> str` — body sections: `## <tag>`, `- [[<title>]] — <link_degree> links`, `## 待归类` (orphans, only if any), `## 近期活动` (always).
- `MocUpdateDiff(add: List[ClusterMember], remove: List[str], kept: int)`
- `build_update_diff(current_links, cluster_members, existing_ids) -> MocUpdateDiff` — `existing_ids` = ids that exist on disk (any live note type, not archived); `remove` = link id not in existing_ids; `add` = cluster member not in current links AND in existing_ids; `kept` = intersection size.

**Steps (TDD):** 7+ tests (grouping/hub-first/title/max-size/orphans/render/diff), RED → implement pure module (no I/O) → GREEN → commit `feat(moc): add pure draft/diff logic for MOC create and update`.

### Task 3: Disk-write + backlinks backfill in jfox/moc/generate.py

**Files:** Create `jfox/moc/generate.py`; Test `tests/unit/test_moc_generate.py`.

**Interfaces:**

- `MOC_TAG = "moc"`
- `write_moc(draft) -> Note` — render content, `create_note(content, title, NoteType.STRUCTURE, tags=[MOC_TAG], links=sorted(member_ids))` where member_ids includes group members AND orphan bucket ids; then `if not save_note(moc): raise OSError(...)`; `get_note_index().update_note_meta(moc)`; `backfill_moc_backlinks(moc, member_ids)`; return moc.
- `backfill_moc_backlinks(moc_note, member_ids) -> None` — mirrors `promote_note` incremental pattern: guard membership, `_atomic_write` + `update_note_meta` per member inside try/except that only warns.
- `remove_moc_backlinks(moc_id, member_ids) -> None` — strips moc id from member backlinks, same tolerant pattern.
- `verify_members_on_disk(member_ids) -> tuple[set[str], list[str]]` — returns (existing ids, missing warnings `"skipped ghost member <id> (<title>)"`); disk truth via `load_note_by_id` + `filepath.exists()` (note index may be stale, #391).

**Steps (TDD):** tests for write/backfill/remove + save-failure raise + verify-on-disk; fixture mutates the config singleton in place (NOT `monkeypatch.setattr("jfox.config.config", cfg)` — note.py/vector_store.py bind config at import time) + `_reset_singletons()` + local `_MockBackend` with `encode_single` (conftest mock lacks it). RED → implement → GREEN → commit `feat(moc): add MOC disk write with backlinks backfill`.

### Task 4: `jfox moc create` command

**Files:** Modify `jfox/moc/cli.py`; Test `tests/unit/test_moc_create_cli.py`.

**Interfaces:**

- `draft_to_dict(threshold, cluster, draft, created) -> dict` — JSON contract: `threshold`, `cluster{size, hub}`, `draft{title, groups[{name, members[]}], orphan_bucket, total_members}`, `created` (None or `{id, filepath}`), `warnings` (ghost-skip entries).
- `_create_impl(active_config, threshold, cluster_index, max_size, title, include_orphans, write) -> (payload, moc, draft, cluster)` — diagnose once with `thresholds=[threshold]`, `suggest_threshold=threshold`, `top=cluster_index+1`; missing cluster → `MocDiagnoseError`; build draft; coarse filter via index live ids + fine filter via `verify_members_on_disk` (warnings → payload); `write=True` → `write_moc(draft)` → `created={id, filepath}`.
- `create_cmd` — options `--threshold 0.65 / --cluster 0 / --max-size 50 / --title / --include-orphans / --yes / --kb / --format table|json`; validation via `_fail`; dry-run default; table branch prints `Cluster size N; hub: X`, `MOC title: Y`, group sections, and after `--yes` write: `Created MOC {id} at {filepath}`; `Warning: <text>` lines for payload warnings.

**Steps (TDD):** help contract + group-help contract + dry-run table strings + `--yes` JSON (mock write_moc) + oversized rejection + ghost-warning flow. Lazy imports only. RED → implement → GREEN → commit `feat(moc): add moc create command with dry-run and --yes`.

### Task 5: `jfox moc update` command

**Files:** Modify `jfox/moc/cli.py`; Test `tests/unit/test_moc_update_cli.py`.

**Interfaces:**

- `_update_impl(active_config, moc_id, threshold, apply) -> (payloads, changed)` — load target MOC(s) (`load_note_by_id` or `list_notes(NoteType.STRUCTURE)`); diagnose once (`top=100`); per MOC: match the cluster with largest `|links ∩ cluster members|`; overlap 0 → payload with `warning: "no matching cluster; skipped"`; diff via `build_update_diff` with disk-verified `existing_ids` (candidate set = current links ∪ cluster member ids, verified by `verify_members_on_disk`); payload keys `moc_id, moc_title, add, remove, kept` (+ `warning` when applicable); `apply` → `moc.links = sorted(set(links + add) - set(remove))`, `if not update_note(moc): payload warning "update failed; backlinks untouched", continue` else `backfill_moc_backlinks` + `remove_moc_backlinks` + append to `changed`.
- `update_cmd` — options `--id / --threshold 0.65 / --yes / --kb / --format`; JSON wrapper `{success, updates, applied}`; table branch prints `[id] title`, `+ [[title]] (id)`, `- id (dead link)`, `(no changes)`, `Warning: ...`.

**Steps (TDD):** help contract + group-help lists create AND update + dry-run JSON (add/remove/kept) + dry-run table + no-match skip + `--yes` apply (mock update_note/backfill/remove) + update_note-failure warning. RED → implement → GREEN → commit `feat(moc): add moc update command with cluster diff`.

### Task 6: Integration test + README docs

**Files:** Test `tests/unit/test_moc_integration.py`; Modify `README.md`.

**Steps:**

1. Integration test `test_create_then_update_end_to_end`: seeded KB fixture (config singleton in-place mutation + `_reset_singletons` + `_MockBackend`); mock only `diagnose_moc_density`; `_create_impl(write=True)` → assert structure file on disk, links correct, **member backlinks contain moc.id**; add 3rd permanent + inject dead link; `update_note` + index rebuild; `_update_impl(apply=True)` → assert add=[3rd], remove=[dead], updated links, **3rd member backlinks contain moc.id**.
2. README: 3 rows under `### Search & Analysis` (after graph rows): `jfox moc diagnose`, `jfox moc create --yes`, `jfox moc update`, matching existing table style.
3. Quick subset green (8 moc test files), commit `test(moc): add create/update end-to-end test and README docs`.

## Self-Review Notes

- Spec coverage: D1 (T1), D2 (T4/5), D3 (T4), D4 (T2), D5 (T2), D6 (T2 orphans + T4/5 disk verification), D7 (T5), D8 (T3 backfill/remove + T6 assertions), D9 (T4/5 reuse diagnose).
- CR round-1 follow-ups baked in: update_note return guard (T5), dead-link = disk-existence scope (T2/T5), ghost member filter with warnings (T3/T4), orphan ids join links/backlinks (T3), table confirmation line (T4).
