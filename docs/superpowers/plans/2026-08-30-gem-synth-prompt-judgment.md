# gem-synth Prompt Judgment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the daemon-driven gem-synth anchor synthesis path with lossless Claude Code user-prompt recording, manual batch judgment through a configurable external runner, candidate drafts, and explicit human disposition commands.

**Architecture:** Keep `fragments.db` as the local SQLite store, but isolate the new prompt domain in `jfox/prompts/`. A durable per-event spool feeds `user_prompts`; manual `jfox prompts judge` groups records by session, gathers bounded transcript/KB/history evidence, invokes a locked-down external runner, and persists a judgment before any user action. Extract candidate operations into `jfox/candidates/`, retain historical fragment/candidate data, and remove the old daemon synthesis path only after the new CLI flow and migration are covered.

**Tech Stack:** Python 3.10+, SQLite/WAL, Typer, FastAPI, Rich, pytest, existing JFox note/index/search infrastructure, POSIX subprocess process-group cleanup with the repository's Windows fallbacks, and pi print mode as the default external runner.

## Global Constraints

- Preserve full prompt text: neither the prompt record nor the spool may apply the legacy 500-character `content` limit.
- Record only Claude Code `UserPromptSubmit` in this issue; pi-coding-agent capture remains in issue #462.
- Keep prompt recording independent of embedding-model and external-LLM availability; judgment remains manual and never runs from a hook or daemon loop.
- New judgment must not auto-deduplicate, auto-merge, auto-reject, auto-promote, or filter candidates by confidence/cosine thresholds.
- Every `new` result is a pending `NoteType.CANDIDATE`; only explicit user commands can promote, reject, ignore, or add unresolved items.
- Scope judgments and unresolved items by `(kb_name, prompt_id)`; prompt records themselves are shared across KBs.
- Use argv with `shell=False`; pass task JSON through stdin; never place prompt text or credentials in argv/logs/config files.
- Default pi runner must disable tools, session persistence, extensions, skills, project context, approval, and thinking; user-configured models remain supported.
- Preserve `session_fragments`, `synthesis_log.db`, `dedup_embeddings`, historical candidate files, `jfox fragments`, `jfox candidates`, and the existing jfox-promote three-mode workflow.
- Use atomic file writes and SQLite transactions for spool, judgment claims, candidate provenance, and the unresolved aggregate note; all user actions must be idempotent.
- Run focused fast tests during implementation. Do not run the repository's full/integration suite autonomously; provide the manual integration commands in the final report.
- Do not commit, push, or force-push to `main`; each task commit must stage only the files named in that task.

---

## File Map and Ownership

| Area | Files to create | Files to modify | Files to remove or migrate |
|---|---|---|---|
| Prompt domain | `jfox/prompts/__init__.py`, `store.py`, `transcript.py`, `grounding.py`, `runner.py`, `judge.py`, `lifecycle.py`, `cli.py` | `jfox/cli.py`, `jfox/global_config.py`, `jfox/daemon/server.py` | None until final cutover |
| Candidate domain | `jfox/candidates/__init__.py`, `service.py`, `cli.py` | `jfox/cli.py`, `jfox/models.py`, existing note lifecycle wiring | Candidate code is extracted from `jfox/gem_synth/cli.py`; the entire `jfox/gem_synth/` directory (including `cli.py` and `__init__.py`) is removed in Task 8 (Task 10 is verification-only) |
| Capture integration | None | `packages/cc-plugin/hooks/hooks.json`, `packages/cc-plugin/hooks/fragment-capture.sh`, `jfox/fragment/store.py`, `jfox/fragment/service.py`, `jfox/fragment/__init__.py`, `jfox/fragment/internal_sources.py` | `jfox/fragment/detector.py` is removed in Task 8 Step 4 together with detector-based collection (historical rows stay readable) |
| Tests | New focused `tests/unit/test_prompts_*.py`, `tests/unit/test_prompt_*.py`, and integration coverage | Existing fragment/gem-synth/candidate tests | Obsolete auto-synthesis tests only after replacement coverage exists |
| Docs | `docs/superpowers/specs/2026-08-30-gem-synth-prompt-judgment-design.md` already committed | README/skill help only where command behavior changes | Old plan/spec history remains as historical documentation |

All new Python public objects use type hints and focused responsibilities. Existing `FragmentStore` continues to own historical `session_fragments`; `PromptStore` owns the three new tables and all new prompt semantics.

## Task 1: Add PromptStore schemas, prompt records, judgment claims, and unresolved index

**Files:**

- Create: `jfox/prompts/__init__.py`
- Create: `jfox/prompts/store.py`
- Modify: `jfox/fragment/store.py: FragmentStore connection pragmas and schema initialization`
- Test: `tests/unit/test_prompt_store.py`

**Interfaces:**

- Produces `PromptStore(db_path: Optional[Path] = None)`, `default_prompt_db_path()`, `insert_prompt(event: Dict[str, Any], source_key: str, capture_id: Optional[str]) -> Dict[str, Any]`, `get_prompt(prompt_id: int) -> Optional[Dict[str, Any]]`, `list_prompts(...)`, `count_prompts(...)`, `claim_prompts(kb_name: str, prompt_ids: List[int], claim_token: str, now: str) -> List[int]`, `finish_judgment(...)`, `fail_judgment(...)`, `get_judgment(kb_name: str, prompt_id: int)`, and unresolved index CRUD/reconciliation methods for later tasks.
- Consumes the existing `JFOX_FRAGMENTS_DB` path convention and writes all new tables into that same database file.

- [x] **Step 1: Write failing schema and record tests**

  Cover the exact `user_prompts` fields from the spec, complete prompt round-trip, `source_key` uniqueness, capture duplicate return, source-fragment uniqueness, transcript occurrence uniqueness, prompt hash normalization, and per-session sequence allocation. Add tests for two independent identical prompts remaining separate rows.

  ```python
  def test_insert_prompt_preserves_long_unicode_text(prompt_store):
      prompt = "中文" * 400 + "\n```python\nprint('x')\n```"
      result = prompt_store.insert_prompt(
          {
              "hook_event_name": "UserPromptSubmit",
              "session_id": "s1",
              "prompt": prompt,
          },
          source_key="capture:c1",
          capture_id="c1",
      )
      assert result["prompt"] == prompt
      assert len(prompt_store.get_prompt(result["prompt_id"])["prompt"]) == len(prompt)
  ```

- [x] **Step 2: Run the focused tests and verify they fail**

  Run: `uv run pytest tests/unit/test_prompt_store.py -q`

  Expected: FAIL because `jfox.prompts` and `PromptStore` do not exist.

- [x] **Step 3: Implement the schema and transaction-safe store**

  Add the `user_prompts`, `prompt_judgments`, and `unresolved_items` schemas exactly as specified. Configure `busy_timeout=10000`, WAL, and `synchronous=NORMAL`. Validate event fields before insert, calculate normalized SHA-256 prompt hashes, allocate `session_seq` inside `BEGIN IMMEDIATE`, and return `stored` or `duplicate` without replacing an existing row. Use a stable row-level claim lease: claim only rows with no judgment or eligible failed/needs-review state, increment `attempt_count`, set `claim_token`/`claimed_at`, and clear both fields on success/failure.

- [x] **Step 4: Implement unresolved index helpers and reconciliation primitives**

  Keep the SQLite index keyed by `(kb_name, prompt_id)` and the permanent-note ID in `note_id`. Expose helpers for active/resolved transitions but do not write Markdown yet. Store JSON arrays in judgment evidence fields and validate all state values at the store boundary.

- [x] **Step 5: Run focused tests and verify they pass**

  Run: `uv run pytest tests/unit/test_prompt_store.py -q`

  Expected: PASS with coverage for long text, duplicate capture, duplicate prompt preservation, sequence allocation, claims, stale claims, and state transitions.

- [x] **Step 6: Commit**

  ```bash
  git add jfox/prompts/__init__.py jfox/prompts/store.py jfox/fragment/store.py tests/unit/test_prompt_store.py
  git commit -m "feat: add prompt recording and judgment store"
  ```

## Task 2: Implement durable CC prompt spool, daemon API, and history backfill

**Files:**

- Modify: `packages/cc-plugin/hooks/hooks.json`
- Modify: `packages/cc-plugin/hooks/fragment-capture.sh`
- Modify: `jfox/fragment/service.py`, `jfox/fragment/__init__.py`, `jfox/fragment/internal_sources.py`
- Modify: `jfox/daemon/server.py`
- Modify: `jfox/global_config.py`
- Create: `tests/unit/test_prompt_capture.py`
- Create: `tests/unit/test_prompt_backfill.py`
- Modify: `tests/integration/test_fragment_capture_flow.py`

**Interfaces:**

- Consumes `PromptStore.insert_prompt()` and `default_db_path()` from Task 1.
- Produces `ingest_prompt(event: Dict[str, Any], store: Optional[PromptStore] = None) -> Dict[str, Any]`, `POST /api/prompt`, `jfox prompts drain`/backfill store primitives, and the plugin environment contract `JFOX_DAEMON_URL`/`JFOX_PROMPT_SPOOL_DIR`.

- [x] **Step 1: Write failing capture tests**

  Test that only UserPromptSubmit is accepted, full prompt text survives, internal sources (`auto-summary`, `gem-synth`, `prompt-judge`) are skipped, daemon failure leaves a `.json` spool file, repeated drain is idempotent, and old `session_fragments.metadata_json.prompt` is used for backfill instead of truncated `content`.

- [x] **Step 2: Run the focused capture tests and verify they fail**

  Run: `uv run pytest tests/unit/test_prompt_capture.py tests/unit/test_prompt_backfill.py -q`

  Expected: FAIL because the new endpoint, spool, and PromptStore ingestion path do not exist.

- [x] **Step 3: Add prompt capture configuration and schema migration**

  Add `prompt_capture` fields (`enabled`, `spool_dir`, `endpoint_url`, timeout, payload/spool limits, raw-event retention, transcript roots) with backward-compatible loading from `fragment_capture.enabled`. Preserve unknown config fields. Initialize the prompt/fragment store before embedding model loading so prompt ingestion remains available when the embedding model fails.

- [x] **Step 4: Replace the CC hook hot path**

  Keep `hooks.json` on UserPromptSubmit only. Make `fragment-capture.sh` validate the event, create a UUID capture ID, write JSON to a user-private temp file, flush/fsync, atomically rename, then POST to `/api/prompt`. Delete a spool file only after an exact `stored`/`duplicate` response. Keep spool error sidecars free of prompt text; never log the prompt. Remove PostToolUse/Stop handling and legacy Stop summaries.

- [x] **Step 5: Add service and API validation**

  Add `ingest_prompt()` and `POST /api/prompt` with structured 4xx errors for invalid event objects, missing/empty session IDs, non-string/empty prompts, bad capture IDs, unsafe transcript paths, and payloads above the configured limit. Record unsafe paths but prevent later transcript reads. Retain `/api/fragment` only as a compatibility adapter for old UserPromptSubmit and return retired/410 for old PostToolUse/Stop without inserting new fragments.

- [x] **Step 6: Add drain and backfill operations**

  Implement deterministic `.json` spool scanning with file claims, idempotent import, and deletion only after commit. Implement `backfill` from legacy `session_fragments` using complete `metadata_json.prompt`, preserving `source_fragment_id`; optionally scan configured Claude transcript roots for missing metadata. Add dry-run counts for valid, empty, invalid, missing-transcript, unsafe-path, and conflicting records.

- [x] **Step 7: Run tests and integration smoke**

  Run: `uv run pytest tests/unit/test_prompt_capture.py tests/unit/test_prompt_backfill.py tests/unit/test_fragment_internal_sources.py -q`

  Expected: PASS. The repository integration test remains a manual command because it starts/uses a real daemon.

- [x] **Step 8: Commit**

  ```bash
  git add packages/cc-plugin/hooks/hooks.json packages/cc-plugin/hooks/fragment-capture.sh jfox/fragment/service.py jfox/fragment/__init__.py jfox/fragment/internal_sources.py jfox/daemon/server.py jfox/global_config.py tests/unit/test_prompt_capture.py tests/unit/test_prompt_backfill.py tests/unit/test_fragment_internal_sources.py
  git commit -m "feat: capture Claude prompts durably"
  ```

## Task 3: Add transcript context, strict grounding, and prompt history evidence

**Files:**

- Create: `jfox/prompts/transcript.py`
- Create: `jfox/prompts/grounding.py`
- Create: `tests/unit/test_prompt_transcript.py`
- Create: `tests/unit/test_prompt_grounding.py`

**Interfaces:**

- Consumes prompt rows and `PromptCaptureConfig`/judge limits from Tasks 1-2.
- Produces `read_transcript(path: Path) -> TranscriptDocument`, `select_context(document, target_prompts, config) -> ContextResult`, `fetch_judgment_grounding(query, kb, config) -> GroundingResult`, and `build_prompt_history(store, prompt, kb_name, limit) -> List[Dict[str, Any]]`.

- [x] **Step 1: Write failing transcript and grounding tests**

  Cover full context under limit, targeted context over limit, prompt-only missing/unsafe transcript, repeated identical user messages with occurrence selection, no fork/resume traversal, permanent-only grounding, unresolved-tag exclusion, empty grounding versus actual search failure, and hash/history evidence ordering.

- [x] **Step 2: Run the focused tests and verify they fail**

  Run: `uv run pytest tests/unit/test_prompt_transcript.py tests/unit/test_prompt_grounding.py -q`

  Expected: FAIL because the new prompt-domain modules do not exist.

- [x] **Step 3: Implement safe transcript parsing**

  Move the useful parsing logic from `gem_synth/transcript.py` without keeping a dependency on the old package. Read only user/assistant messages, strip raw metadata, validate transcript roots and symlink containment, use `transcript_user_index` where available, and consume matching occurrences in order. Return explicit `full`, `targeted`, or `prompt_only` context modes; never truncate the target prompt itself.

- [x] **Step 4: Implement strict evidence queries**

  Query only current-KB active permanent notes for resolved grounding and exclude `unresolved-problems` notes. Return configurable body lengths and distinguish “no results” from search/index/embedding failure. Read active unresolved items through a separate evidence path. Build bounded session history and prior normalized-hash history; include IDs, session, timestamp, and disposition without computing embeddings in the hook.

- [x] **Step 5: Run focused tests and verify they pass**

  Run: `uv run pytest tests/unit/test_prompt_transcript.py tests/unit/test_prompt_grounding.py -q`

  Expected: PASS with all three context modes and evidence separation covered.

- [x] **Step 6: Commit**

  ```bash
  git add jfox/prompts/transcript.py jfox/prompts/grounding.py tests/unit/test_prompt_transcript.py tests/unit/test_prompt_grounding.py
  git commit -m "feat: add prompt transcript and grounding evidence"
  ```

## Task 4: Implement the locked-down configurable external runner

**Files:**

- Create: `jfox/prompts/runner.py`
- Modify: `jfox/global_config.py`
- Create: `tests/unit/test_prompt_runner.py`

**Interfaces:**

- Consumes `PromptJudgeConfig` and a JSON task payload.
- Produces `RunnerResult`, `build_pi_argv(config) -> List[str]`, `run_runner(task: Dict[str, Any], config: PromptJudgeConfig, allow_remote: bool) -> RunnerResult`, and strict output parsing/validation helpers used by Task 5.

- [x] **Step 1: Write failing runner tests**

  Assert `shell=False`, prompt/task JSON only on stdin, fixed pi safety flags, thinking off by default, reserved argument rejection, no-session behavior, isolated working directory, process-group cleanup on timeout, stdout/stderr limits, remote consent before process start, and API-key absence from logs.

- [x] **Step 2: Run the focused tests and verify they fail**

  Run: `uv run pytest tests/unit/test_prompt_runner.py -q`

  Expected: FAIL because `PromptJudgeConfig` and the runner module do not exist.

- [x] **Step 3: Add and validate `PromptJudgeConfig`**

  Add the spec fields and safe defaults. Enforce `claim_timeout_seconds > timeout_seconds + 60`, finite positive limits, valid runner mode, and argv-array-only custom commands. Keep `model` and runner choice configurable; the default model is the configured pi DeepSeek model but business logic must not hardcode a provider.

- [x] **Step 4: Implement pi and argv runners**

  Build pi argv with `--print`, configured `--model`, `--thinking off`, `--no-tools`, `--no-session`, `--no-extensions`, `--no-skills`, `--no-context-files`, `--no-approve`, and an internal `--append-system-prompt`. Reject extra args that attempt to override any reserved safety or prompt/system flags. Use `subprocess.Popen(..., shell=False, start_new_session=True)`, background drainers, output limits, timeout, and process-group cleanup. Set `JFOX_INTERNAL_SESSION=prompt-judge` in the child environment.

- [x] **Step 5: Implement strict runner output parsing**

  Parse the external output leniently only to locate JSON, then validate the exact `items` contract: every target prompt exactly once, allowed classifications, valid evidence IDs, required draft fields only for `new`, finite confidence in `[0, 1]`, and hard output length limits. Reject unknown/missing/duplicate IDs rather than guessing by array position.

- [x] **Step 6: Run focused tests and verify they pass**

  Run: `uv run pytest tests/unit/test_prompt_runner.py tests/unit/test_global_config.py -q`

  Expected: PASS.

- [x] **Step 7: Commit**

  ```bash
  git add jfox/prompts/runner.py jfox/global_config.py tests/unit/test_prompt_runner.py tests/unit/test_global_config.py
  git commit -m "feat: add safe configurable prompt judge runner"
  ```

## Task 5: Implement session-batch judge, evidence validation, and candidate draft creation

**Files:**

- Create: `jfox/prompts/judge.py`
- Modify: `jfox/models.py`
- Modify: `jfox/note.py` only if candidate provenance lookup requires a narrow helper
- Modify: `jfox/prompts/store.py`
- Create: `tests/unit/test_prompt_judge.py`
- Create: `tests/unit/test_prompt_candidate.py`

**Interfaces:**

- Consumes Tasks 1, 3, and 4.
- Produces `judge_prompts(kb_name: str, limit: Optional[int] = None, session_id: Optional[str] = None, all_items: bool = False, retry_failed: bool = False, retry_needs_review: bool = False, allow_remote: bool = False) -> JudgeReport`, `create_candidate_from_draft(...) -> str`, and candidate recovery/reconciliation helpers.

- [x] **Step 1: Write failing judge tests**

  Cover default limit 50, `--all`, session grouping, transcript read once per session, batch splitting by 20 prompts/input budget, SQLite claims, successful classifications, per-item failures, full/targeted/prompt-only context fields, empty grounding, grounding failure, evidence validation, and candidate creation with `source_prompts`.

- [x] **Step 2: Run the focused tests and verify they fail**

  Run: `uv run pytest tests/unit/test_prompt_judge.py tests/unit/test_prompt_candidate.py -q`

  Expected: FAIL because judge orchestration and source prompt provenance do not exist.

- [x] **Step 3: Extend `Note` with prompt provenance**

  Add `source_prompts: List[int]` with safe list parsing and serialization in Markdown, `to_dict`, and `to_show_dict`. Preserve existing `source_fragments` semantics and promoted-note provenance. Candidate creation must use verified permanent evidence titles for `grounded_by`, set `status=pending`, `gem_level=flawed`, confidence, knowledge type, and one prompt ID.

- [x] **Step 4: Implement candidate creation idempotency**

  Use a deterministic draft identity derived from `(kb_name, prompt_id, attempt/session batch identity)` in the recovery lookup, while keeping the visible note ID generated by existing JFox conventions. Before creating a candidate, search current KB candidate files for the unique `source_prompts=[prompt_id]` pending draft; one match is reused, multiple matches fail for manual repair, and no match creates exactly one candidate. Do not call dedup or auto-merge.

- [x] **Step 5: Implement session-batch orchestration**

  Select prompt records for the current KB, group by source/session, claim them transactionally, read each transcript once, collect strict permanent/history/unresolved evidence, enforce remote consent, call the runner, validate output, create candidates for `new`, and write judgment rows. Clear claims on every success/failure path. A runner batch failure fails all claimed items; a single invalid item does not block its siblings.

- [x] **Step 6: Implement explicit retry selection**

  Make ordinary judge select only unjudged records. `--retry-failed` selects technical failures; `--retry-needs-review` selects pending needs-review judgments. Keep successful judgments out of ordinary selection and record runner/model/context metadata on each success.

- [x] **Step 7: Run focused tests and verify they pass**

  Run: `uv run pytest tests/unit/test_prompt_judge.py tests/unit/test_prompt_candidate.py tests/unit/test_note_candidate_fields.py -q`

  Expected: PASS.

- [x] **Step 8: Commit**

  ```bash
  git add jfox/prompts/judge.py jfox/models.py jfox/prompts/store.py tests/unit/test_prompt_judge.py tests/unit/test_prompt_candidate.py tests/unit/test_note_candidate_fields.py
  git commit -m "feat: judge prompt batches into candidates"
  ```

## Task 6: Implement unresolved permanent aggregate and explicit prompt actions

**Files:**

- Modify: `jfox/prompts/store.py`
- Create: `jfox/prompts/cli.py`
- Create: `jfox/prompts/lifecycle.py`
- Modify: `jfox/cli.py`
- Modify: `jfox/note.py` only to expose the existing lifecycle dispatch payload to the new prompt subscriber
- Create: `tests/unit/test_prompt_actions.py`
- Create: `tests/unit/test_prompt_cli.py`

**Interfaces:**

- Consumes Task 5 judgments/candidates and existing `promote_note`, `reject_note`, `update_note`, `use_kb` APIs.
- Produces `jfox prompts list/show/status/drain/backfill/judge/promote/unresolved/resolve-unresolved/ignore/retry/config` commands and lifecycle reconciliation.

- [x] **Step 1: Write failing action and CLI tests**

  Test command preconditions, JSON/table output, `--kb`, idempotent promote, unresolved marker updates, duplicate unresolved calls, resolution, ignore with and without `--reject-candidate`, retry restrictions, and explicit `--force --reason` audit fields.

- [x] **Step 2: Run focused tests and verify they fail**

  Run: `uv run pytest tests/unit/test_prompt_actions.py tests/unit/test_prompt_cli.py -q`

  Expected: FAIL because the prompts CLI and lifecycle module do not exist.

- [x] **Step 3: Implement the prompts CLI**

  Add the Typer sub-app and register it in `jfox/cli.py`. Ensure all commands support `--kb` and `--format json`; command output must keep complete prompt text out of table previews unless `prompts show --full` is requested. Make `status` report spool, unjudged, processing, failed, pending, and active unresolved counts without invoking an LLM.

- [x] **Step 4: Implement human action preconditions and audit**

  `prompts promote` accepts only `new/pending` with one live candidate; `prompts unresolved` accepts only `repeated/pending`; `ignore` changes only a successful pending judgment and requires `--reject-candidate` to reject an existing candidate. Add `--force --reason` only where the spec permits a classification override, persist `manual_override/manual_reason`, and never bypass candidate existence or archive checks.

- [x] **Step 5: Implement the unresolved aggregate note**

  Locate/create exactly one current-KB permanent note titled `JFox 待解决问题清单` with the `unresolved-problems` tag. Update it under a per-KB file lock with atomic write and machine markers keyed by prompt ID; escape user preview text and never interpret user text as Markdown links. Update `unresolved_items` and judgment disposition with reconciliation on restart. `resolve-unresolved` marks the marker/index/judgment resolved without deleting the prompt.

- [x] **Step 6: Implement direct candidate lifecycle synchronization**

  Register the new prompt lifecycle callbacks from the package entrypoint without importing the old gem_synth lifecycle. On direct candidate promote/reject, use `source_prompts` and current KB to update matching judgments; do not affect old candidates without the new provenance field. Reconcile failed callbacks through `prompts show/status`.

- [x] **Step 7: Run focused tests and verify they pass**

  Run: `uv run pytest tests/unit/test_prompt_actions.py tests/unit/test_prompt_cli.py tests/unit/test_note_promote.py -q`

  Expected: PASS.

- [x] **Step 8: Commit**

  ```bash
  git add jfox/prompts/store.py jfox/prompts/cli.py jfox/prompts/lifecycle.py jfox/cli.py jfox/note.py tests/unit/test_prompt_actions.py tests/unit/test_prompt_cli.py tests/unit/test_note_promote.py
  git commit -m "feat: add human prompt judgment actions"
  ```

## Task 7: Extract candidate CLI and preserve existing candidate behavior

**Files:**

- Create: `jfox/candidates/__init__.py`
- Create: `jfox/candidates/service.py`
- Create: `jfox/candidates/cli.py`
- Modify: `jfox/cli.py`
- Create: `tests/unit/test_candidates_migrated_cli.py`
- Modify: `tests/unit/test_gem_synth_cli.py` imports and fixtures to target the extracted candidate CLI

**Interfaces:**

- Consumes existing candidate behavior from `jfox/gem_synth/cli.py` and Task 5's candidate service.
- Produces the unchanged user commands `jfox candidates list/show/promote/reject`, with the same output and exit behavior.

- [x] **Step 1: Write migration parity tests**

  Copy the existing candidate list/show/promote/reject coverage to the new module and add a test proving old candidates without `source_prompts` still work. Verify promoted candidate provenance fields are preserved and candidate indexing/backlinks remain unchanged.

- [x] **Step 2: Run the parity tests and verify they fail**

  Run: `uv run pytest tests/unit/test_candidates_migrated_cli.py -q`

  Expected: FAIL because `jfox.candidates` does not exist.

  (`tests/integration/test_candidate_promote_flow.py` is integration-marked — per Global Constraints it is provided for manual execution, not run autonomously inside the TDD loop.)

- [x] **Step 3: Extract without changing command semantics**

  Move candidate presentation and service helpers out of `gem_synth/cli.py`, register the new app under the same `candidates` name, and keep the old command flags. Reuse the existing `promote_note`/`reject_note` operations. Do not change the jfox-promote skill’s three-mode workflow.

- [x] **Step 4: Run parity tests and verify they pass**

  Run: `uv run pytest tests/unit/test_candidates_migrated_cli.py tests/unit/test_gem_synth_cli.py -q`

  Expected: PASS. Integration coverage (`test_candidate_promote_flow.py`) is executed manually per Global Constraints.

- [x] **Step 5: Commit**

  ```bash
  git add jfox/candidates/__init__.py jfox/candidates/service.py jfox/candidates/cli.py jfox/cli.py tests/unit/test_candidates_migrated_cli.py tests/unit/test_gem_synth_cli.py
  git commit -m "refactor: separate candidate commands from gem synth"
  ```

## Task 8: Remove daemon auto-synthesis and obsolete fragment collection paths

**Files:**

- Modify: `jfox/daemon/server.py`
- Modify: `jfox/fragment/service.py`, `jfox/fragment/__init__.py`, `jfox/fragment/internal_sources.py`
- Modify: `jfox/cli.py`
- Modify: `jfox/global_config.py`
- Modify: `jfox/__init__.py`
- Modify: `jfox/add_dedup.py` (repoint imports to the extracted `jfox/dedup.py`) and `tests/unit/test_add_dedup.py`
- Modify: `packages/cc-plugin/hooks/hooks.json`, `packages/cc-plugin/hooks/fragment-capture.sh`
- Create: `jfox/dedup.py` (extracted from `jfox/gem_synth/dedup.py` BEFORE deletion — `jfox/add_dedup.py` (#383) imports `dedup_check`/`upsert_dedup`/`_resolve_kb_name` from it, so the module must survive retirement as a standalone note-dedup utility; inline `default_synthesis_db_path` from `gem_synth/paths.py`, drop the anchor-release helper that depended on `SynthesisLog`)
- Delete: the entire `jfox/gem_synth/` directory — `anchors.py`, `cli.py`, `dedup.py`, `grounding.py`, `__init__.py`, `lifecycle.py`, `llm.py`, `loop.py`, `paths.py`, `store.py`, `synthesizer.py`, `transcript.py`
- Delete: `jfox/fragment/detector.py` (Step 4 removes detector-based collection)
- Modify/Delete: obsolete gem-synth tests only after replacement tests cover retained behavior

**Interfaces:**

- Consumes the new prompts/candidates paths from Tasks 1-7.
- Produces a build with no import or runtime path from daemon/CLI/package initialization to old automatic gem-synth synthesis.

- [x] **Step 1: Write regression tests for retirement**

  Assert daemon lifespan does not create a gem-synth task, old PostToolUse/Stop events do not write new fragments, `jfox fragments list/show` still reads historical rows, old synthesis databases remain untouched, and candidate commands remain registered.

- [x] **Step 2: Run retirement tests and verify they fail**

  Run: `uv run pytest tests/unit/test_prompt_retirement.py tests/unit/test_daemon_process.py tests/unit/test_fragment_service.py -q`

  Expected: FAIL while old daemon task and old fragment classifier are still active.

- [x] **Step 3: Extract dedup, then remove old runtime imports and tasks**

  First extract `jfox/dedup.py` from `gem_synth/dedup.py` and repoint `jfox/add_dedup.py` imports (the #383 add-gate depends on it; `tests/unit/test_add_dedup.py` stays green). The extract must also take over ALL FOUR dedup-table lifecycle hooks the old `gem_synth/lifecycle.py` owned — `post_delete`/`post_archive`/`post_reject` → `delete_dedup` (rejected candidates must not leave stale rows either) and `post_promote` → `update_dedup_type("permanent")` — wired from `jfox/__init__.py`; otherwise deleted/archived/rejected notes leave stale embeddings and `jfox add` would false-positive on re-adding removed content. Preserve the lazy-import-in-callback pattern: heavy imports (dedup → numpy) stay inside the callback bodies, the package `__init__` only holds callback references, so `import jfox` never pays the numpy startup cost (see the moc_cli import-weight guard test). Then delete daemon `_maybe_start_gem_synth`/`_maybe_stop_gem_synth` wiring and the package-level old lifecycle registration. Remove old anchor/synthesis execution paths and obsolete `gem_synthesis` runtime configuration while preserving backward-compatible config loading and historical DB files.

- [x] **Step 4: Stop obsolete collection without deleting history**

  Remove detector-based new collection for correction/decision/tool_call/session_summary. Keep `session_fragments` schema and read-only CLI for historical access. Make the old endpoint compatibility behavior explicit and update help text/documentation from active collection to historical fragments.

- [x] **Step 5: Remove obsolete tests and update references**

  Remove tests whose only contract was deleted automatic synthesis; retain transcript/grounding/candidate behavior tests that now target the new package. Search tracked code/docs for `gem_synth.loop`, `find_anchors`, and old lifecycle imports, allowing only historical design documents and migration notes.

- [x] **Step 6: Run retirement tests and focused regression suite**

  Run: `uv run pytest tests/unit/test_prompt_retirement.py tests/unit/test_daemon_process.py tests/unit/test_fragment_service.py tests/unit/test_candidates_migrated_cli.py -q`

  Expected: PASS.

- [x] **Step 7: Commit**

  ```bash
  git add jfox/dedup.py jfox/add_dedup.py tests/unit/test_add_dedup.py jfox/daemon/server.py jfox/fragment/service.py jfox/fragment/__init__.py jfox/fragment/internal_sources.py jfox/cli.py jfox/global_config.py jfox/__init__.py packages/cc-plugin/hooks/hooks.json packages/cc-plugin/hooks/fragment-capture.sh tests/unit/test_prompt_retirement.py
  git rm -r jfox/gem_synth/ jfox/fragment/detector.py
  git commit -m "refactor: retire daemon gem synth"
  ```

## Task 9: Add documentation, migration commands, and configuration help

**Files:**

- Modify: `README.md`
- Modify: `packages/cc-plugin/skills/promote/SKILL.md` only where candidate command ownership/help changes
- Modify: `packages/cc-plugin/skills/using-jfox/SKILL.md` if command routing needs updating
- Modify: `jfox/prompts/cli.py`, `jfox/global_config.py`
- Modify: `docs/cli-descriptions.yaml` (add the `jfox prompts` command group, drop `jfox gem-synth`, refresh `candidates`/`fragments` wording) and regenerate `docs/cli-reference.md` via `uv run python scripts/generate_docs.py` — the CI drift gate (#476) fails otherwise
- Create: `tests/unit/test_prompt_config_cli.py`

**Interfaces:**

- Consumes all new commands/config from Tasks 1-8.
- Produces user-facing instructions for backfill, drain, judge, remote consent, candidate processing, unresolved resolution, and old-data preservation.
- Skill copy changes (promote/using-jfox) must be mirrored to ALL four locations per CLAUDE.md: `packages/cc-plugin/skills/`, `packages/kimi-plugin/skills/`, `skills-recommend/kimi-cli/`, `skills-recommend/pi/` (#440 single-copy drift lesson).

- [x] **Step 1: Write failing configuration/help tests**

  Verify config show redacts sensitive fields, config set validates runner safety fields, help lists all prompt commands and remote consent behavior, and migration commands expose dry-run/reporting options.

- [x] **Step 2: Run focused tests and verify they fail**

  Run: `uv run pytest tests/unit/test_prompt_config_cli.py -q`

  Expected: FAIL until config and help commands are implemented.

- [x] **Step 3: Implement config command behavior**

  Add `jfox prompts config show/set`, preserving unknown global config fields, validating safe runner options, and never accepting API keys as persisted values. Ensure default capture and judge settings match the spec and explain local versus remote runner behavior.

- [x] **Step 4: Update user documentation**

  Document the new manual flow, the exact cutover/backfill sequence, the fact that only Claude Code capture is in this issue, pi capture belongs to #462, and the unchanged three-mode candidate review path. Document that full transcript content may leave the machine only after explicit consent.

- [x] **Step 5: Run tests and lint**

  Run: `uv run pytest tests/unit/test_prompt_config_cli.py -q`

  Expected: PASS.

  Run: `npx --yes markdownlint-cli2 README.md packages/cc-plugin/skills/promote/SKILL.md packages/cc-plugin/skills/using-jfox/SKILL.md`

  Expected: 0 markdownlint issues.

- [x] **Step 6: Commit**

  ```bash
  git add README.md packages/cc-plugin/skills/promote/SKILL.md packages/cc-plugin/skills/using-jfox/SKILL.md jfox/prompts/cli.py jfox/global_config.py tests/unit/test_prompt_config_cli.py
  git commit -m "docs: document prompt judgment workflow"
  ```

## Task 10: Final verification, migration rehearsal, and issue delivery evidence

**Files:**

- Modify: no source files; this task is verification-only
- Modify: `docs/superpowers/specs/2026-08-30-gem-synth-prompt-judgment-design.md` only if implementation behavior intentionally changes the approved design

**Interfaces:**

- Consumes the complete implementation from Tasks 1-9.
- Produces reproducible verification evidence and a clean issue branch ready for review; no automatic merge or push.

- [x] **Step 1: Run the focused fast suite**

  Run:

  ```bash
  uv run pytest tests/unit/test_prompt_store.py tests/unit/test_prompt_capture.py tests/unit/test_prompt_backfill.py tests/unit/test_prompt_transcript.py tests/unit/test_prompt_grounding.py tests/unit/test_prompt_runner.py tests/unit/test_prompt_judge.py tests/unit/test_prompt_candidate.py tests/unit/test_prompt_actions.py tests/unit/test_prompt_cli.py tests/unit/test_prompt_config_cli.py tests/unit/test_prompt_retirement.py tests/unit/test_candidates_migrated_cli.py -q
  ```

  Expected: PASS with zero failures.

- [x] **Step 2: Run static checks and CLI smoke checks**

  Run:

  ```bash
  uv run black --check jfox/ tests/ packages/cc-plugin/hooks/fragment-capture.sh
  uv run ruff check jfox/ tests/
  uv run jfox --help
  uv run jfox prompts --help
  uv run jfox candidates --help
  ```

  Expected: format/lint exit 0 and all three help commands list the expected subcommands. If Black is not configured to inspect shell files, omit the shell path and run a shell syntax check with `bash -n packages/cc-plugin/hooks/fragment-capture.sh`.

- [x] **Step 3: Run the manual integration commands requested by project policy**

  Provide, but do not autonomously execute, these commands:

  ```bash
  uv run pytest tests/integration/test_fragment_capture_flow.py -q -m integration
  uv run pytest tests/integration/test_candidate_promote_flow.py -q -m integration
  uv run pytest tests/integration/test_gem_synth_flow.py -q -m integration
  uv run pytest tests/ -m "not embedding and not slow"
  ```

  The retired `test_gem_synth_flow.py` command should be removed or replaced by a prompt-judge integration test before this step; do not claim it passes until the replacement exists.

- [x] **Step 4: Rehearse migration in a temporary database/KB**

  Create a temporary `fragments.db` containing long UserPromptSubmit metadata and old correction/decision/tool rows, run `jfox prompts backfill --dry-run`, run backfill twice, drain a duplicate spool twice, and assert counts, full prompt text, preserved historical rows, and no candidate generation during migration.

- [x] **Step 5: Verify retirement and repository cleanliness**

  Run:

  ```bash
  rg -n "_maybe_start_gem_synth|_maybe_stop_gem_synth|find_anchors|synthesize_anchor|gem_synth\.lifecycle" jfox packages tests
  git status --short
  git diff --check HEAD~10..HEAD
  ```

  Expected: no active-code matches for retired runtime symbols (historical docs may be documented exceptions), no whitespace errors, and no untracked test artifacts or accidental user data.

- [x] **Step 6: Commit any narrowly scoped verification fix**

  If verification exposes a defect, add a focused regression test and fix in a separate commit using a conventional message. Otherwise do not create an empty commit.

## Plan Self-Review Checklist

- Spec coverage: Tasks 1-2 cover lossless capture/spool/API/backfill; Task 3 covers transcript and evidence; Task 4 covers configurable pi/argv runner and privacy; Task 5 covers session batch judge, claims, classification, candidate provenance, and no dedup; Task 6 covers manual actions and unresolved lifecycle; Task 7 preserves candidate commands; Task 8 performs the one-shot retirement; Task 9 documents migration/config; Task 10 verifies the complete branch.
- Placeholder scan: every implementation step contains concrete files, behavior, tests, and expected results. Any failure discovered during implementation must become a focused test/fix task, not an unbounded edge-case note.
- Type consistency: `PromptStore`, `PromptJudgeConfig`, `JudgeReport`, `RunnerResult`, `TranscriptDocument`, `ContextResult`, and `GroundingResult` are the shared interfaces used by later tasks. Implementers must keep these names and field semantics stable.
- Scope: all tasks are parts of the single approved #399 cutover. Pi-side capture remains #462 and no worktree task may add it.
