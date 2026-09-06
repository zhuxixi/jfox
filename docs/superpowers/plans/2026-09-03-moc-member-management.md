# MOC Member Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement reliable single-member MOC add/remove operations and connect new permanent-note capture to MOC membership across the three supported skill distributions.

**Architecture:** Keep Markdown mutation logic as pure functions in `jfox/moc/draft.py`; keep filesystem, NoteIndex, index, and backlink orchestration in `jfox/moc/cli.py` and `jfox/moc/generate.py`. Change `render_moc_content` to emit ID-canonical links, add two JSON/table CLI commands, then update the pi/Claude Code/Kimi skill documents with per-note, multi-MOC confirmation and retry behavior.

**Tech Stack:** Python 3.10+, Typer, pytest, temporary knowledge-base fixtures, mock embedding backend, Markdown skill documents, markdownlint-cli2.

## Global Constraints

- Work only in `WT=/home/elling/git-repo/github/jfox/.pi/worktrees/issue-484-moc-member-management`; do not edit the main checkout.
- Preserve the approved spec at `docs/superpowers/specs/2026-09-03-moc-member-management-design.md`; every implementation task below cites its acceptance IDs.
- Keep Markdown body operations in pure functions with no filesystem, NoteIndex, embedding, or global-config access.
- Use active-KB configuration and exact IDs; do not resolve add/remove CLI arguments as titles or substrings.
- New MOC member rows use an ID as the link target and a safe title alias when possible; do not create new title-only MOC links.
- Keep `moc update` semantics unchanged: it remains a batch fallback and does not become a body re-render or move operation.
- Use the existing `--kb`, `--format table|json`, and `--json` command conventions.
- Preserve existing callers when extending backlink helper return values; callers may ignore the returned result.
- Use the existing project test commands and mock embedding backend; do not run the full approximately 50-minute test suite autonomously.
- Do not commit, push, or open a PR without explicit user permission.

## Files and Responsibilities

- Modify: `jfox/moc/draft.py` — canonical create rendering plus pure section/member-row upsert and removal functions.
- Modify: `jfox/moc/generate.py` — return structured backlink changed/failed IDs while preserving existing side effects.
- Modify: `jfox/moc/cli.py` — exact loading, validation, add/remove orchestration, JSON/table output, and partial-status reporting.
- Modify: `tests/unit/test_moc_draft.py` — pure rendering/upsert/removal cases.
- Modify: `tests/unit/test_moc_generate.py` — backlink helper result and failure cases.
- Modify: `tests/unit/test_moc_cli.py` — expanded MOC help listing.
- Create: `tests/unit/test_moc_member_cli.py` — focused CLI implementation and output-contract tests.
- Create: `tests/integration/test_moc_member_commands.py` — temporary-KB add/remove consistency tests; keep the existing create/update fixture focused.
- Create: `tests/unit/test_moc_skill_docs.py` — static assertions for the four modified skill documents.
- Modify: `skills-recommend/pi/jfox-session-to-permanent/SKILL.md` — pi capture workflow.
- Modify: `packages/cc-plugin/skills/session-to-permanent/SKILL.md` — Claude Code capture workflow.
- Modify: `packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md` — Kimi capture workflow.
- Modify: `skills-recommend/pi/jfox-moc/SKILL.md` — new commands, canonical link guidance, and primary/fallback positioning.

---

### Task 1: Lock the canonical MOC body format

**Acceptance IDs:** A1, A7

**Files:**

- Modify: `jfox/moc/draft.py:render_moc_content`
- Test: `tests/unit/test_moc_draft.py:test_render_content_has_groups_orphans_and_recent_section`

**Interfaces:**

- Consumes: Existing `MocCreateDraft`, `DraftGroup`, `ClusterMember`, and `OrphanNote` objects.
- Produces: `render_moc_content(draft)` that emits `[[member.id|member.title]]` for safe titles and `[[member.id]]` otherwise, while preserving existing group/orphan/recent-section layout and the ordinary-member `— N links` suffix.

- [ ] **Step 1: Write the failing test**

Extend the existing render test with concrete ID assertions. Reuse the existing `_cluster()` and `_tags()` helpers from `tests/unit/test_moc_draft.py`:

```python
def test_render_content_uses_id_canonical_member_links():
    draft = build_moc_draft(_cluster(), _tags(), max_size=50)
    content = render_moc_content(draft)

    assert "- [[1|Zima Hub]] — 10 links" in content
    assert "- [[Zima Hub]] — 10 links" not in content
```

Add a second test named `test_render_content_uses_id_only_for_unsafe_titles`:

```python
def test_render_content_uses_id_only_for_unsafe_titles():
    member = ClusterMember(id="1", title="Unsafe ]] title", link_degree=1, mean_similarity=0.8)
    draft = MocCreateDraft(title="Unsafe MOC", groups=[DraftGroup("misc", [member])])

    content = render_moc_content(draft)

    assert "- [[1]] — 1 links" in content
    assert "Unsafe ]] title" not in content
```

Import `MocCreateDraft` and `DraftGroup` alongside the existing draft imports.

- [ ] **Step 2: Run test to verify it fails**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-484-moc-member-management
uv run pytest tests/unit/test_moc_draft.py::test_render_content_uses_id_canonical_member_links -v
```

Expected: FAIL because the current renderer uses title-only links.

- [ ] **Step 3: Write minimal implementation**

Add the private pure formatter `_member_link` in `draft.py`:

```python
def _member_link(note_id: str, title: str) -> str:
    if "\n" in title or "\r" in title or "]]" in title:
        return f"[[{note_id}]]"
    return f"[[{note_id}|{title}]]"
```

Use it for ordinary members and orphan members. Keep all existing group order, suffixes, and `## 近期活动` output unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-484-moc-member-management
uv run pytest tests/unit/test_moc_draft.py -v
```

Expected: PASS, with existing render/group tests updated only where they assert the old title-only syntax.

- [ ] **Step 5: Review the focused diff**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-484-moc-member-management
git diff -- jfox/moc/draft.py tests/unit/test_moc_draft.py
```

Expected: Only canonical rendering and its direct assertions changed; no CLI or I/O logic is introduced.

---

### Task 2: Implement pure member-row scanning, upsert, and removal

**Acceptance IDs:** A2, A3

**Files:**

- Modify: `jfox/moc/draft.py` near `render_moc_content` and `build_update_diff`
- Test: `tests/unit/test_moc_draft.py`

**Interfaces:**

- Consumes: `content: str`, explicit note ID/title/tags/group, and `legacy_title_unique: bool`.
- Produces:
  - `MemberUpsertResult(content, resolved_group, changed, rows_added, rows_canonicalized, had_existing_row, matched_groups, ambiguous_legacy)`.
  - `MemberRemovalResult(content, changed, removed_rows, removed_groups, ambiguous_legacy)`.
  - `upsert_member_line(...) -> MemberUpsertResult`.
  - `remove_member_lines(...) -> MemberRemovalResult`.

- [ ] **Step 1: Write failing table-driven tests**

Add cases covering every pure-function boundary in the spec:

```python
@pytest.mark.parametrize(
    ("content", "tags", "group", "expected_group"),
    [
        ("## zima\n\n## 近期活动\n", ["zima"], None, "zima"),
        ("## zima\n\n## 近期活动\n", ["other"], None, "其他"),
        ("## zima\n\n## 近期活动\n", ["zima"], "manual", "manual"),
    ],
)
def test_upsert_selects_group_and_inserts_before_system_section(
    content, tags, group, expected_group
):
    result = upsert_member_line(content, "20260820000003", "New Note", tags, group, legacy_title_unique=True)
    assert result.resolved_group == expected_group
    assert "[[20260820000003|New Note]]" in result.content
    assert result.content.index("[[20260820000003|New Note]]") < result.content.index("## 近期活动")
```

Add explicit tests for:

- first matching ordinary group in body order when multiple tags match;
- `其他`, `待归类`, and `近期活动` exclusion rules;
- explicit reserved-group rejection at the CLI boundary (Task 4);
- fallback/new-group insertion with and without a system section;
- existing canonical `[[ID]]` and `[[ID|alias]]` rows are not duplicated or moved;
- the CLI-level links-only repair is covered in Task 4 rather than represented as a pure-function input;
- unique legacy `- [[Title]]` rows are canonicalized in place, preserving suffixes and all matching rows;
- ambiguous legacy rows remain unchanged and cause canonical ID insertion plus `ambiguous_legacy=True`;
- removal across multiple ordinary/system sections, duplicate canonical rows, ID-only/ID+alias forms;
- unique legacy removal, ambiguous legacy preservation, missing target title behavior;
- empty ordinary group removal only when its body is whitespace; groups with prose, nested heading, code, or other Markdown remain;
- fenced code blocks do not count as headings or member rows;
- title containing `#`, `|`, newline, or `]]` follows the safe alias rules.

- [ ] **Step 2: Run the new tests to verify they fail**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-484-moc-member-management
uv run pytest tests/unit/test_moc_draft.py -k "member or canonical" -v
```

Expected: FAIL because the result dataclasses and pure functions do not exist, and rendering still has legacy expectations.

- [ ] **Step 3: Implement the scanner and pure transformations**

Implement a single line-preserving scanner with these exact rules:

1. Track fenced-code state; ignore headings and list rows inside fences.
2. Recognize only top-level H2 lines as sections; H3 and ordinary text stay in the current section.
3. Recognize member rows as an optionally indented Markdown short-dash list item whose first wiki-link target is an exact ID or exact legacy title.
4. Use structured parsing or escaped matching; never use ID-prefix matching.
5. For upsert, return existing canonical/unique-legacy state without moving it; only insert when no reusable row exists.
6. For new/fallback groups, insert before the first system section, or after the final ordinary group if no system section exists.
7. For removal, process every section and remove all matching rows; remove only whitespace-only ordinary groups after row deletion.
8. Preserve untouched text and line endings as far as possible.

Use `dataclass(frozen=True)` result objects with the exact fields in the spec. Do not import NoteIndex, Note, config, or any filesystem module into the pure transformation path.

- [ ] **Step 4: Run all pure-function tests**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-484-moc-member-management
uv run pytest tests/unit/test_moc_draft.py -v
```

Expected: PASS, including the original build/update/render tests and all new member-row cases.

- [ ] **Step 5: Review the focused diff**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-484-moc-member-management
git diff -- jfox/moc/draft.py tests/unit/test_moc_draft.py
```

Expected: Section parsing and transformations remain pure; no CLI orchestration appears in `draft.py`.

---

### Task 3: Return structured backlink update results

**Acceptance IDs:** A6

**Files:**

- Modify: `jfox/moc/generate.py:backfill_moc_backlinks,remove_moc_backlinks`
- Modify: `tests/unit/test_moc_generate.py`

**Interfaces:**

- Consumes: Existing `Note`/member ID inputs and an optional active `ZKConfig`.
- Produces: `BacklinkUpdateResult(changed_ids: tuple[str, ...], failed_ids: tuple[str, ...])`; existing callers may ignore it. The exact signatures are `backfill_moc_backlinks(moc_note: Note, member_ids: Sequence[str], cfg: Optional[ZKConfig] = None)` and `remove_moc_backlinks(moc_id: str, member_ids: Sequence[str], cfg: Optional[ZKConfig] = None)`.

- [ ] **Step 1: Write failing tests**

Extend helper tests with concrete result assertions:

```python
def test_backfill_returns_changed_ids(seeded_kb):
    moc = write_moc(_draft(seeded_kb))
    remove_moc_backlinks(moc.id, MEMBER_IDS, cfg=seeded_kb)

    result = backfill_moc_backlinks(moc, MEMBER_IDS, cfg=seeded_kb)

    assert result.changed_ids == tuple(MEMBER_IDS)
    assert result.failed_ids == ()


def test_remove_returns_failed_ids_and_continues(seeded_kb, monkeypatch):
    moc = write_moc(_draft(seeded_kb))
    failing_id = MEMBER_IDS[1]
    from jfox import note as note_module

    original_atomic_write = note_module._atomic_write

    def fail_one(path, content):
        if failing_id in str(path):
            raise OSError("test write failure")
        return original_atomic_write(path, content)

    monkeypatch.setattr(note_module, "_atomic_write", fail_one)
    result = remove_moc_backlinks(moc.id, MEMBER_IDS, cfg=seeded_kb)

    assert MEMBER_IDS[0] in result.changed_ids
    assert failing_id in result.failed_ids
```

Also assert that missing targets and already-clean backlinks are neither changed nor failed.

- [ ] **Step 2: Run tests to verify they fail**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-484-moc-member-management
uv run pytest tests/unit/test_moc_generate.py -k "backlink" -v
```

Expected: FAIL because helpers currently return `None`.

- [ ] **Step 3: Implement result collection**

Add the frozen result dataclass in `generate.py`. Add `cfg: Optional[ZKConfig] = None` to both helper signatures; use `cfg or config` for `load_note_by_id` and `get_note_index`, while retaining the current default behavior for existing callers. Preserve the current per-member loop and logging behavior:

- append an ID to `changed_ids` only after its backlink write and index update succeed;
- append an ID to `failed_ids` on real load/write/index exceptions;
- skip missing targets and already-correct backlinks without classifying them as failures;
- continue processing later IDs after an individual failure.

Do not change the existing `write_moc` or `moc update` semantics beyond allowing them to ignore the return value.

- [ ] **Step 4: Run helper and existing MOC tests**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-484-moc-member-management
uv run pytest tests/unit/test_moc_generate.py tests/unit/test_moc_update_cli.py -v
```

Expected: PASS with old callers still functioning.

- [ ] **Step 5: Review the focused diff**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-484-moc-member-management
git diff -- jfox/moc/generate.py tests/unit/test_moc_generate.py
```

Expected: Return-value/reporting changes only; no change to update diff selection.

---

### Task 4: Add exact-ID CLI orchestration and JSON/table contracts

**Acceptance IDs:** A4, A5, A6, A7

**Files:**

- Modify: `jfox/moc/cli.py`
- Create: `tests/unit/test_moc_member_cli.py`
- Create: `tests/integration/test_moc_member_commands.py`
- Modify: `tests/unit/test_moc_cli.py` for the expanded MOC help listing

**Interfaces:**

- Consumes: Task 2 pure functions, Task 3 `BacklinkUpdateResult`, active `ZKConfig`, `NoteIndex`, `Note`, `update_note`.
- Produces:
  - `_add_member_impl(active_config: ZKConfig, moc_id: str, note_id: str, group: Optional[str]) -> dict[str, Any]`.
  - `_remove_member_impl(active_config: ZKConfig, moc_id: str, note_id: str) -> dict[str, Any]`.
  - Typer commands `jfox moc add-member` and `jfox moc remove-member` with `--kb`, `--group` (add only), `--format`, and `--json`.
  - Fixed success/error contracts from the approved spec.

- [ ] **Step 1: Write failing CLI unit tests**

Create focused tests with mocked `NoteIndex`, exact loader, pure functions, `update_note`, and backlink helpers. Cover:

- missing/non-structure/archived MOC rejection;
- missing/archived/ghost member rejection;
- exact ID mismatch and invalid ID rejection;
- self-link rejection;
- reserved/empty/newline `--group` rejection;
- active non-permanent warning and nested-structure warning;
- links-only, backlink-only, body-only, and fully-consistent add states;
- duplicate frontmatter links normalized;
- ambiguous legacy produces `partial=true` and warning;
- update failure prevents backlink helper calls;
- helper failed IDs produce `partial=true`, warnings, and `applied` based on actual persistent changes;
- remove missing target cleanup by ID and unique/ambiguous legacy behavior;
- repeated add does not add another body row or link;
- JSON output has exactly the required stable fields and table output remains human-readable;
- `moc --help`, `moc add-member --help`, and `moc remove-member --help` expose the command contracts.

Use representative fake notes with IDs matching `^[A-Za-z0-9][A-Za-z0-9_-]*$` and a temporary or patched active config. Do not test body parsing again here; assert the pure helper result is consumed correctly.

- [ ] **Step 2: Run CLI tests to verify they fail**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-484-moc-member-management
uv run pytest tests/unit/test_moc_member_cli.py -v
```

Expected: FAIL because the commands and implementation functions are not registered.

- [ ] **Step 3: Implement exact loading and command orchestration**

Implement the following order in each command:

1. Validate IDs using the approved regex and obtain a fresh `idx = get_note_index(active_config); idx.rebuild()` snapshot.
2. Load by `idx.find_by_id()` filepath and verify the loaded object ID exactly matches the argument.
3. Apply MOC/member type, archive, ghost, and self-link rules.
4. Count exact case-insensitive titles from `idx.get_all_meta()` for legacy safety.
5. Call the pure body function; compute pre-operation `links_has_member` and `backlink_has_member`.
6. Normalize or remove all target IDs in MOC links.
7. Persist the MOC only when body or links changed; do not call backlink helpers after failed persistence.
8. Call the relevant backlink helper when the member exists and backlink state needs repair/removal; translate `changed_ids` and `failed_ids` to `applied`, `partial`, and warnings.
9. Preserve no-op semantics when all three states are already consistent.
10. Render the stable JSON response or table output, and route invalid inputs through `_fail` with exit code 1.

Use the active config consistently in loaders, NoteIndex, and helper calls. If existing helper signatures require an active config for correctness, extend them with an optional config parameter while preserving existing callers.

- [ ] **Step 4: Run unit and integration tests**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-484-moc-member-management
uv run pytest tests/unit/test_moc_member_cli.py -v
uv run pytest tests/integration/test_moc_member_commands.py -v
```

Expected: PASS. Integration tests must use a temporary KB and `mock_embedding_backend`, assert frontmatter/body/member-backlink state, and avoid real model loading and clustering.

- [ ] **Step 5: Run existing MOC regression tests**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-484-moc-member-management
uv run pytest tests/unit/test_moc_cli.py tests/unit/test_moc_create_cli.py tests/unit/test_moc_update_cli.py tests/unit/test_moc_integration.py -v
```

Expected: PASS; create/update/diagnose behavior remains unchanged except for the intentionally updated canonical create-body assertions.

- [ ] **Step 6: Review the focused diff**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-484-moc-member-management
git diff -- jfox/moc/cli.py tests/unit/test_moc_member_cli.py tests/integration/test_moc_member_commands.py
```

Expected: CLI contains orchestration only; no duplicated Markdown section parser exists outside the pure helpers.

---

### Task 5: Update all skill documentation with MOC ownership flow

**Acceptance IDs:** A8

**Files:**

- Modify: `skills-recommend/pi/jfox-session-to-permanent/SKILL.md`
- Modify: `packages/cc-plugin/skills/session-to-permanent/SKILL.md`
- Modify: `packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md`
- Modify: `skills-recommend/pi/jfox-moc/SKILL.md`
- Create: `tests/unit/test_moc_skill_docs.py` — static assertions for the four modified skill documents.

**Interfaces:**

- Consumes: Task 4 command contract; existing platform-specific interaction conventions.
- Produces: Three synchronized session-to-permanent workflows and one pi jfox-moc workflow that document candidate signals, per-note multi-MOC confirmation, post-add calls, errors/retries, canonical body links, and update fallback positioning.

- [ ] **Step 1: Write static content checks**

Create `tests/unit/test_moc_skill_docs.py` so the four concrete files are checked for the required concepts, not merely one keyword:

```python
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SESSION_SKILLS = [
    REPO_ROOT / "skills-recommend/pi/jfox-session-to-permanent/SKILL.md",
    REPO_ROOT / "packages/cc-plugin/skills/session-to-permanent/SKILL.md",
    REPO_ROOT / "packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md",
]
MOC_SKILL = REPO_ROOT / "skills-recommend/pi/jfox-moc/SKILL.md"


def test_session_skill_docs_describe_moc_ownership():
    for path in SESSION_SKILLS:
        text = path.read_text(encoding="utf-8")
        assert "type: structure" in text
        assert "jfox moc add-member" in text
        assert "每条新笔记" in text or "each new note" in text
        assert "失败" in text or "retry" in text.lower()


def test_moc_skill_doc_describes_member_commands():
    text = MOC_SKILL.read_text(encoding="utf-8")
    assert "jfox moc add-member" in text
    assert "jfox moc remove-member" in text
    assert "moc update" in text
```

- [ ] **Step 2: Run the static checks to verify they fail**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-484-moc-member-management
uv run pytest tests/unit/test_moc_skill_docs.py -v
```

Expected: FAIL because the current documents have no MOC ownership section or commands.

- [ ] **Step 3: Update the three session-to-permanent documents**

In each platform document:

1. Extend Step 2 to inspect `suggestions[].type` and retain active `structure` candidates by MOC ID/title/score.
2. State that after the final draft changes, suggestions must be recomputed.
3. Extend Step 4 per new note: signal means ask; no signal means no forced question; a note can select zero or multiple MOCs; each batch note gets an independent mapping.
4. Use the platform’s existing question mechanism; pi uses sequential questions rather than an unsupported `multiSelect` parameter.
5. Extend Step 5: run `jfox add`, then one `jfox moc add-member <MOC_ID> <NEW_NOTE_ID> --json` per selected MOC with the same `--kb`; report failures and retry commands without rolling back the note.
6. Explicitly exclude existing-note supplements from this new ownership prompt.

- [ ] **Step 4: Update the pi jfox-moc document**

Add both command examples, ID-canonical link guidance, safe legacy behavior, and this positioning: session-time ownership is the primary path; `moc update` remains the batch fallback for missed/older notes and semantic diff review.

- [ ] **Step 5: Run lint and static checks**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-484-moc-member-management
npx --yes markdownlint-cli2
uv run pytest tests/integration/test_plugin_inventory.py -v
```

Run the focused content check from Step 1 as well. Expected: PASS with all four files present and all required concepts documented.

- [ ] **Step 6: Review the documentation diff**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-484-moc-member-management
git diff -- skills-recommend/pi/jfox-session-to-permanent/SKILL.md packages/cc-plugin/skills/session-to-permanent/SKILL.md packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md skills-recommend/pi/jfox-moc/SKILL.md
```

Expected: Platform-specific tool names remain correct; command semantics and failure behavior are equivalent across the three session skills.

---

### Task 6: Full targeted verification and manual acceptance handoff

**Acceptance IDs:** A1–A9, U1, U2

**Files:**

- Test: all files from Tasks 1–5
- Review: `docs/superpowers/specs/2026-09-03-moc-member-management-design.md`

**Interfaces:**

- Consumes: Completed implementation and documentation changes from Tasks 1–5.
- Produces: Fresh verification evidence, an acceptance ledger for A1–A9, and explicit U1/U2 instructions/status; no automatic commit/push/PR.

- [ ] **Step 1: Run the targeted automated acceptance matrix**

Run each command and record its exit code and result against the exact acceptance ID:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-484-moc-member-management
uv run pytest tests/unit/test_moc_draft.py -v
uv run pytest tests/unit/test_moc_member_cli.py -v
uv run pytest tests/unit/test_moc_generate.py tests/unit/test_moc_member_cli.py -v
uv run pytest tests/integration/test_moc_member_commands.py -v
uv run pytest tests/unit/test_moc_cli.py tests/unit/test_moc_create_cli.py tests/unit/test_moc_update_cli.py -v
npx --yes markdownlint-cli2
uv run pytest tests/ -m "not embedding and not slow" -q
```

Expected: Every command exits 0. If any command fails, record the failing test and repair it before claiming that automated acceptance is complete.

- [ ] **Step 2: Verify the final spec/plan traceability**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-484-moc-member-management
rg -n "A[1-9]|U[12]|add-member|remove-member|partial|legacy|multi MOC|active-config" docs/superpowers/specs/2026-09-03-moc-member-management-design.md docs/superpowers/plans/2026-09-03-moc-member-management.md
```

Review that every spec acceptance ID maps to at least one plan task and every plan task cites one or more acceptance IDs.

- [ ] **Step 3: Prepare U1 manual verification**

Use a disposable/test KB with two active MOCs and two new permanent drafts: one semantically related to both MOCs and one unrelated. Run the selected platform’s session-to-permanent flow:

1. Run Step 2 and confirm only the related draft receives active `structure` signals.
2. Confirm the related draft receives a per-note MOC question and the unrelated draft does not receive a forced MOC question.
3. Set shell variables `MOC_ID_1` and `MOC_ID_2` to the two selected MOC IDs, then select both for the related draft.
4. Complete Step 5 and record the new note ID.
5. Set shell variable `NEW_NOTE_ID` to the ID printed by `jfox add`; run `jfox show "$MOC_ID_1" --json`, `jfox show "$MOC_ID_2" --json`, and `jfox refs --note "$NEW_NOTE_ID" --json`.
6. Pass only if both MOC links/body rows and all new-note backlinks are present.

Record U1 as `pending` if the platform interaction or a two-MOC test fixture is unavailable; do not substitute automated tests for this manual item.

- [ ] **Step 4: Prepare U2 manual verification**

Use a disposable/test MOC and temporary notes:

Before running the commands, set shell variables `MOC_ID` to the disposable structure-note ID and `NOTE_ID` to the disposable permanent-note ID.

1. Run `jfox moc add-member "$MOC_ID" "$NOTE_ID" --json` twice; confirm the second response is a no-op and adds no duplicate body row/link.
2. Run `jfox moc remove-member "$MOC_ID" "$NOTE_ID" --json`; confirm body, MOC links, and member backlink are cleared.
3. Test a unique-title legacy row and confirm add canonicalizes it and remove deletes it.
4. Test a same-title legacy row with another note and confirm add/remove preserve the ambiguous old row and return warning/partial state.
5. Test invalid, archived, self-link, and reserved-group inputs using the same `MOC_ID`/`NOTE_ID` variables; confirm exit code 1 and no file changes.

Record each observation, command, and pass/fail/pending status separately.

- [ ] **Step 5: Review final status without publishing**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-484-moc-member-management
git status --short
git diff --stat
git diff --check
```

Expected: All intended files are in the issue-484 worktree; no main-checkout changes, no generated temporary files, and no claims of full completion until all automated evidence and manual statuses are recorded.
