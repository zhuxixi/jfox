# JSON Schema Unify (#502) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** All jfox CLI commands emit `success: true` at top level in `--json` mode, all error paths emit `{"success": false, "error": ...}` JSON, plus add top-level id/title, field renames, bare-array wrapping, and a schema doc.

**Architecture:** Explicit `{"success": True, **result}` wrapping at each JSON output site (never mutating shared result dicts that also feed yaml/csv/table branches). Contract test file with a hardcoded command list enforces the invariant. No envelope, no channel unification.

**Tech Stack:** Python 3.10+, Typer, pytest with real subprocess execution.

## Global Constraints

- Spec: `docs/superpowers/specs/2026-09-14-json-schema-unify-design.md` (read first).
- Wrap at the JSON print site: `print(output_json({"success": True, **result}))` — do NOT add `"success"` to the shared `result` dict when yaml/csv/table branches also consume it (status/list/kb do).
- Never auto-inject success inside `output_json` (spec D2).
- Every new try/except must have `except typer.Exit: raise` BEFORE `except Exception` (KB trap 202608292119524400).
- #483 frozen shapes stay byte-identical: `add` success `{success, note{...}}`, dedup `{success:false, skipped:"duplicate", duplicate{...}}`, `vector_dimension_warning` merge — `tests/test_add_dedup_cli.py` must pass unmodified.
- Do not change yaml/csv/table output shapes.
- Do not fix `--format` silent-default behavior (wontfix-by-design).
- Each task: `git add <specific files>` only (never `git add -A`), conventional commit.
- Fast tests only in-session: `uv run pytest tests/test_json_schema_contract.py -v -x` and per-task test files. Full suite is for CI.
- Working directory: the worktree root (this repo checkout on branch `issue-502-json-schema-unify`). Never touch main.

## File Structure

- Create: `tests/test_json_schema_contract.py` — A1/A2 contract tests (command list + `assert_json_shape`)
- Modify: `jfox/cli.py` — main CLI commands (C1a/C1b/C2a/C3)
- Modify: `jfox/template_cli.py`, `jfox/fragment/cli.py` — C1c/C2b
- Modify: `jfox/prompts/cli.py` — C1d/C2c/C5a
- Modify: `jfox/bookshelf/cli.py`, `jfox/auto_summary/cli.py`, `jfox/backup/cli.py` — C1e/C2d/C4/C5b
- Modify: `jfox/candidates/cli.py` — C1f
- Create: `docs/json-schemas.md` — C6
- Modify: `CHANGELOG.md` — breaking-change annotations (if the project keeps one; else README release notes section — check first)

---

### Task 1: Contract test scaffolding (A1/A2 basis)

**Files:**
- Create: `tests/test_json_schema_contract.py`

**Interfaces:**
- Consumes: `tests/utils/jfox_cli.py` `ZKCLI` (via existing `cli` fixture from conftest), `tests/conftest.py` fixtures `cli`, `temp_kb`
- Produces: `assert_json_shape(stdout: str, success_expected: bool) -> dict`, `EXPECTED_SUCCESS_COMMANDS` list, `_run_json(cli, *args) -> subprocess.CompletedProcess` — later tasks only append entries to `EXPECTED_SUCCESS_COMMANDS`; no other changes to this file except Task 6/7 additions noted there.

- [ ] **Step 1: Write the contract test file**

```python
"""#502 JSON schema contract tests.

Rule under test (docs/json-schemas.md): every --json output has top-level
boolean `success`; error outputs additionally have non-empty `error` and
exit code 1. Uses real subprocesses with stderr merged (TestJsonPurity
pattern from tests/test_add_dedup_cli.py).
"""

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent


def _run_json(cli, *args: str) -> subprocess.CompletedProcess:
    """Run `jfox <args> --json --kb <kb>` as a real subprocess, merge stderr."""
    cmd = [sys.executable, "-m", "jfox", *args, "--json", "--kb", cli.kb_name]
    return subprocess.run(
        cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        cwd=str(REPO_ROOT),
    )


def assert_json_shape(stdout: str, success_expected: bool) -> dict:
    """Parse stdout as strict JSON and assert the contract shape."""
    data = json.loads(stdout)  # strict: any pollution raises here
    assert isinstance(data, dict), f"top level must be object, got {type(data)}"
    assert "success" in data, f"missing top-level success in: {stdout[:200]}"
    assert isinstance(data["success"], bool), (
        f"success must be bool, got {type(data['success'])}: {data['success']!r}"
    )
    assert data["success"] is success_expected
    if not success_expected:
        assert data.get("error"), "error output must carry non-empty error"
    return data


def test_helper_rejects_non_json():
    """Guard the guard: helper must raise on polluted output."""
    with pytest.raises(json.JSONDecodeError):
        assert_json_shape("INFO something\n{}", True)


def test_helper_rejects_missing_success():
    with pytest.raises(AssertionError):
        assert_json_shape('{"total": 0}', True)


class TestAlreadyCompliantSmoke:
    """Commands that already emit success — proves the harness works."""

    def test_add_success_shape(self, cli):
        r = _run_json(cli, "add", "契约冒烟正文", "--title", "Contract-Smoke-1")
        assert r.returncode == 0
        data = assert_json_shape(r.stdout, True)
        assert data["note"]["id"]  # #483 shape intact
```

- [ ] **Step 2: Run it — both tasks must pass (they test already-compliant commands)**

Run: `uv run pytest tests/test_json_schema_contract.py -v`
Expected: 3 PASS (harness proves itself on `add`).

- [ ] **Step 3: Commit**

```bash
git add tests/test_json_schema_contract.py
git commit -m "test: add json schema contract harness for #502"
```

---

### Task 2: Main CLI query commands emit success (C1a → A1)

**Files:**
- Modify: `jfox/cli.py` — search (~L805), status (~L1049), list (~L1147), show (~L1270), refs (3 result dicts ~L1307/L1333/L1394 region), query (~L2022), graph (3 branches ~L2089/L2128/L2148), daily (~L2226), inbox (~L2296), suggest-links (~L2331), bulk-import (~L3171), check (~L3564)
- Modify: `tests/test_json_schema_contract.py` — add `EXPECTED_SUCCESS_COMMANDS` and parameterized tests

**Interfaces:**
- Consumes: Task 1 helpers
- Produces: query-class commands contract-green; `EXPECTED_SUCCESS_COMMANDS` list that Tasks 3-8 extend

- [ ] **Step 1: Add the parameterized contract list (only commands this task makes green)**

Append to `tests/test_json_schema_contract.py`:

```python
class TestContractList:
    """Every entry: (id, cmd-args-after-'jfox', needs_existing_note).

    Commands are added here by the task that fixes them; the list is the
    contract. Run with no setup beyond an initialized temp KB unless
    needs_existing_note (then a note is created first via cli fixture).
    """

    EXPECTED_SUCCESS_COMMANDS = [
        # --- Task 2: main CLI query class ---
        ("search", ["search", "任意词"], False),
        ("status", ["status"], False),
        ("list", ["list"], False),
        ("show", ["show", "{note_id}"], True),
        ("refs-default", ["refs"], False),
        ("query", ["query", "任意词"], False),
        ("graph-stats", ["graph", "--stats"], False),
        ("graph-orphans", ["graph", "--orphans"], False),
        ("daily", ["daily"], False),
        ("inbox", ["inbox"], False),
        ("suggest-links", ["suggest-links", "--content", "一段内容"], False),
        ("bulk-import", ["bulk-import", str(Path(__file__).parent / "fixtures" / "empty_repo")], False),
        ("check", ["check"], False),
    ]

    @pytest.mark.parametrize(
        "cmd_id,args,needs_note",
        EXPECTED_SUCCESS_COMMANDS,
        ids=[c[0] for c in EXPECTED_SUCCESS_COMMANDS],
    )
    def test_success_has_top_level_success(self, cli, cmd_id, args, needs_note):
        note_id = None
        if needs_note:
            created = _run_json(cli, "add", "契约前置正文", "--title", f"Contract-Setup-{cmd_id}")
            note_id = assert_json_shape(created.stdout, True)["note"]["id"]
        final_args = [a.format(note_id=note_id) for a in args]
        r = _run_json(cli, *final_args)
        assert r.returncode == 0, f"stdout: {r.stdout[:300]}"
        assert_json_shape(r.stdout, True)
```

And create the empty-repo fixture referenced above:

```bash
mkdir -p tests/fixtures/empty_repo && git -C tests/fixtures/empty_repo init -q 2>/dev/null; touch tests/fixtures/empty_repo/.gitkeep
```

Note: if a `tests/fixtures/empty_repo` already exists with commits, use a fresh `mkdtemp`-based path in the test instead — implementer's call, keep it deterministic.

- [ ] **Step 2: Run — expect exactly the Task-2 entries to FAIL (missing success), harness tests still PASS**

Run: `uv run pytest tests/test_json_schema_contract.py -v`
Expected: 3 old PASS; the 13 new params FAIL on "missing top-level success" (bulk-import may fail differently: `{imported,failed,total}` — same assertion).

- [ ] **Step 3: Implement — wrap at each JSON print site in `jfox/cli.py`**

Uniform pattern (12 sites in this task). Locate each with the anchors below, then wrap the dict at the print site. Pattern:

```python
# before
print(output_json(result))
# after
print(output_json({"success": True, **result}))

# before (OutputFormatter variant — search/status/list)
print(OutputFormatter.to_json(result))
# after
print(OutputFormatter.to_json({"success": True, **result}))
```

Sites (anchor → wrapping):
1. `search` — `if output_format == "json": print(OutputFormatter.to_json(result))` after the `"results": results` dict (~L812)
2. `status` — same OutputFormatter site after `"backend"` dict (~L1067). ⚠️ this result also feeds yaml branch — wrap at print site only
3. `list` — OutputFormatter site after `"notes": data` (~L1152). ⚠️ same wrap-at-print rule
4. `show` — `print(output_json(n.to_show_dict(raw_markdown=raw)))` (~L1270) → `print(output_json({"success": True, **n.to_show_dict(raw_markdown=raw)}))`
5. `refs` default — `result = {"notes": notes_with_links}` print site (~L1450)
6. `refs --search` — `result = {"query": search, "matches": ...}` print site (~L1335)
7. `refs --note` — `result = {"note": {...}, "forward_links": ...}` print site (~L1396 region)
8. `query` — `"results"`/`"semantic_results"` result print (~L2024)
9. `graph --stats` — `result = {"total_nodes": ...}` print (~L2102)
10. `graph --orphans` — `result = {"orphans": orphans_list}` print (~L2130)
11. `graph --note` — `"related"` result print (~L2152) — needs a note id; contract test covers via `refs-default` style: add `("graph-note", ["graph", "--note", "{note_id}"], True)` to the list in Step 1
12. `daily` (~L2236), `inbox` (~L2306), `suggest-links` (~L2340), `bulk-import` (~L3171: `print(output_json(result))` → `{"success": True, **result}`), `check` (~L3564: `print(output_json({"total": len(issues), "issues": issues}))` → `print(output_json({"success": True, "total": len(issues), "issues": issues}))`)

(That is 16 print sites total — wrap every one; the list above groups near-identical ones.)

- [ ] **Step 4: Run — all Task-2 contract entries green + harness green**

Run: `uv run pytest tests/test_json_schema_contract.py -v`
Expected: all PASS (14 params + 3 harness tests).

Also run the JSON purity regression to prove no channel damage:
`uv run pytest tests/test_add_dedup_cli.py -v`
Expected: all PASS unmodified.

- [ ] **Step 5: Run broader fast tests touching these commands**

Run: `uv run pytest tests/test_core_workflow.py -m "not slow and not embedding" -v`
Expected: PASS (assertions use `.get()`/specific keys; added key is additive).

- [ ] **Step 6: Commit**

```bash
git add jfox/cli.py tests/test_json_schema_contract.py tests/fixtures/empty_repo
git commit -m "feat(cli): emit top-level success on query-class json output (#502 C1a)"
```

---

### Task 3: index/kb action branches + model download purity (C1b/C2a → A1/A2)

**Files:**
- Modify: `jfox/cli.py` — `index` action branches `status`/`bm25-status`/`verify`, `kb` list/current/info JSON prints, `kb` error branches (missing name / KB not found / no default KB / path escape), `model download`
- Modify: `tests/test_json_schema_contract.py` — extend list + error-shape tests

**Interfaces:**
- Consumes: Task 1/2 helpers
- Produces: `kb`-subcommand error JSON contract: `{"success": false, "error": str}` + exit 1

- [ ] **Step 1: Extend contract list**

Add to `EXPECTED_SUCCESS_COMMANDS`:

```python
        # --- Task 3: index/kb ---
        ("index-status", ["index", "--action", "status"], False),
        ("index-bm25-status", ["index", "--action", "bm25-status"], False),
        ("index-verify", ["index", "--action", "verify"], False),
        ("kb-list", ["kb", "list"], False),
        ("kb-current", ["kb", "current"], False),
```

Add error-shape test class:

```python
class TestErrorContract:
    def test_kb_switch_nonexistent_outputs_json_error(self, cli):
        r = _run_json(cli, "kb", "switch", "definitely-no-such-kb-502")
        assert r.returncode == 1
        assert_json_shape(r.stdout, False)

    def test_kb_remove_missing_name_outputs_json_error(self, cli):
        # kb remove with no name arg: currently console-only (L2848-2850)
        r = _run_json(cli, "kb", "remove")
        assert r.returncode == 1
        assert_json_shape(r.stdout, False)
```

- [ ] **Step 2: Run — new success entries FAIL, error entries FAIL (stdout not JSON)**

Run: `uv run pytest tests/test_json_schema_contract.py -v -k "index or kb"`
Expected: 5 success entries fail on missing success; 2 error entries fail on `json.JSONDecodeError` (console-only output).

- [ ] **Step 3: Implement success wraps**

- `index bm25-status` (~L2459): `result = {"bm25_index": stats}` print → wrap
- `index status` (find `"total_indexed"` / `"pending_changes"` dict): wrap at print
- `index verify` (~L2564): `result = verification` then print → replace print with:

```python
            if output_format == "json":
                # verify report executes successfully even when unhealthy;
                # execution errors surface via verification["error"]
                print(output_json({"success": not verification.get("error"), **verification}))
```

- `kb list` / `kb current` / `kb info` — the three `OutputFormatter.to_json(result)` sites (~L2727/L2908/L2960): wrap at print (`kb info` optional if hard to reach without extra KB — it needs a named KB; covered by `kb-current` if signature equal. Implementer: wrap all three code sites regardless; contract test covers list+current).

- [ ] **Step 4: Implement kb + status error JSON**

Find every `console.print`-only error branch in the `kb` command (`raise typer.Exit(1)` nearby without a JSON print): missing name (L2848-2850 `kb remove`/`kb delete`), KB not found (switch/use/remove), no default KB, path escape. Uniform pattern:

```python
            if output_format == "json":
                print(output_json({"success": False, "error": str(e)}))
            else:
                console.print(f"[red]✗[/red] {e}")
            raise typer.Exit(1)
```

Keep the exact error message strings unchanged — only add the JSON branch. For branches whose message is a plain string (not exception `e`), inline that string into the error field.

Also fix `status` generic except (L1109-1112) — note the command layer receives both `output_format` and `json_output`:

```python
    except typer.Exit:
        raise
    except Exception as e:
        if output_format == "json" or json_output:
            print(output_json({"success": False, "error": str(e)}))
        else:
            console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)
```

- [ ] **Step 5: Implement model download purity (C2a)**

In `model download` (~L3465-3485):
1. Move `console.print(f"[yellow]准备下载模型: ...")` into the non-json branch (it pollutes stdout in json mode).
2. Change `console.print(output_json(result))` → `print(output_json(result))` (Rich console may wrap/escape JSON).
3. Wrap the whole body in try/except with the Exit-first pattern:

```python
    try:
        result = _download_impl(model=model, force=force)
    except typer.Exit:
        raise
    except Exception as e:  # unexpected crash must still yield JSON
        result = {"model": model or "auto", "success": False, "cache_dir": None,
                  "instructions": str(e)}
        if output_format == "json":
            print(output_json({"success": False, "error": str(e)}))
            raise typer.Exit(1)
```

(Implementer: adjust to keep table branch behavior identical; the key contract is json-mode stdout = single JSON object.)

- [ ] **Step 6: Run + commit**

Run: `uv run pytest tests/test_json_schema_contract.py -v`
Expected: all PASS (harness + Task2 + Task3 entries + errors).

```bash
git add jfox/cli.py tests/test_json_schema_contract.py
git commit -m "feat(cli): success on index/kb json, kb+model error json purity (#502 C1b/C2a)"
```

---

### Task 4: add top-level id/title (C3 → A3)

**Files:**
- Modify: `jfox/cli.py` — `_add_note_impl` result dict (~L632)
- Modify: `tests/test_json_schema_contract.py` — extend smoke test

**Interfaces:**
- Consumes: Task 1 harness
- Produces: `add --json` top-level `id`/`title` == `note.id`/`note.title`

- [ ] **Step 1: Extend the smoke test**

```python
    def test_add_top_level_shortcuts(self, cli):
        r = _run_json(cli, "add", "快捷字段正文", "--title", "Contract-Shortcut-1")
        data = assert_json_shape(r.stdout, True)
        assert data["id"] == data["note"]["id"]
        assert data["title"] == data["note"]["title"]
```

- [ ] **Step 2: Run — fails on missing `id`**

Run: `uv run pytest tests/test_json_schema_contract.py::TestAlreadyCompliantSmoke::test_add_top_level_shortcuts -v`
Expected: FAIL `KeyError: 'id'`.

- [ ] **Step 3: Implement**

In `_add_note_impl` (~L630):

```python
        result = {
            "success": True,
            "id": new_note.id,        # top-level shortcut (#502 C3)
            "title": new_note.title,  # top-level shortcut (#502 C3)
            "note": {
                "id": new_note.id,
                "title": new_note.title,
                "type": new_note.type.value,
                "filepath": str(new_note.filepath),
                "links": resolved_links,
            },
        }
```

- [ ] **Step 4: Run purity + workflow**

Run: `uv run pytest tests/test_json_schema_contract.py tests/test_add_dedup_cli.py -v`
Expected: all PASS (dedup shapes untouched).

- [ ] **Step 5: Commit**

```bash
git add jfox/cli.py tests/test_json_schema_contract.py
git commit -m "feat(add): top-level id/title shortcuts in json output (#502 C3)"
```

---

### Task 5: template + fragments: success & error JSON (C1c/C2b → A1/A2)

**Files:**
- Modify: `jfox/template_cli.py` — list/show json sites + error branches
- Modify: `jfox/fragment/cli.py` — list/show json sites + error branches
- Modify: `tests/test_json_schema_contract.py`

**Interfaces:**
- Consumes: Task 1 harness
- Produces: contract entries for template/fragments

- [ ] **Step 1: Extend contract list + error tests**

```python
        # --- Task 5: template/fragments ---
        ("template-list", ["template", "list", "--format", "json"], False),
        ("template-show", ["template", "show", "quick"], False),
        ("fragments-list", ["fragments", "list", "--format", "json"], False),
```

Error tests:

```python
    def test_template_show_not_found_json_error(self, cli):
        r = _run_json(cli, "template", "show", "no-such-template-502")
        assert r.returncode == 1
        assert_json_shape(r.stdout, False)

    def test_fragments_show_missing_json_error(self, cli):
        r = _run_json(cli, "fragments", "show", "999999999")
        assert r.returncode == 1
        assert_json_shape(r.stdout, False)
```

- [ ] **Step 2: Run — 4 new FAIL entries**

Run: `uv run pytest tests/test_json_schema_contract.py -v -k "template or fragments"`
Expected: 3 success entries FAIL (missing success); 2 error tests FAIL (non-JSON output).

- [ ] **Step 3: Implement template_cli.py**

1. `list` json site (~L74): `print(json.dumps(result, ...))` → `print(json.dumps({"success": True, **result}, ensure_ascii=False, indent=2))`
2. `show` json site (~L142): same wrap.
3. `show` not-found branch (~L124-127): JSON output before Exit:

```python
        if not template:
            if json_output:
                print(json.dumps(
                    {"success": False, "error": f"Template '{name}' not found"},
                    ensure_ascii=False, indent=2))
            else:
                available = manager.get_available_templates()
                console.print(f"[red]Template '{name}' not found[/red]")
                if available:
                    console.print(f"[dim]Available: {', '.join(available)}[/dim]")
            raise typer.Exit(1)
```

4. `list` generic except (~L105): add `if output_format == "json": print(json.dumps({"success": False, "error": str(e)}, ...))` before the console print, keep Exit(1).

- [ ] **Step 4: Implement fragment/cli.py**

1. `list` json site (~L43): `_json.dumps({"fragments": rows, "total": len(rows)}, ...)` → `_json.dumps({"success": True, "fragments": rows, "total": len(rows)}, ...)`
2. `list` read-failure (~L37): add JSON branch (mirror template pattern; gate on `output_format == "json"`).
3. `show` output (~L79): `_json.dumps(row, ...)` → `_json.dumps({"success": True, **row}, ...)` (show is JSON-only).
4. `show` error branches (~L72-77): JSON-only command → always JSON error:

```python
    except Exception as e:
        _json_console.print(_json.dumps(
            {"success": False, "error": f"读取碎片失败：{e}"},
            ensure_ascii=False, indent=2))
        raise typer.Exit(code=1)
```

And not-found (~L77) likewise with `"error": f"找不到碎片 ID={fragment_id}"`.

- [ ] **Step 5: Run + commit**

Run: `uv run pytest tests/test_json_schema_contract.py -v -k "template or fragments"`
Expected: 5 PASS.

```bash
git add jfox/template_cli.py jfox/fragment/cli.py tests/test_json_schema_contract.py
git commit -m "feat(template,fragments): success flag and json error branches (#502 C1c/C2b)"
```

---

### Task 6: prompts: success, error JSON, bare-array wrap (C1d/C2c/C5a → A1/A2/A5)

**Files:**
- Modify: `jfox/prompts/cli.py` — list/show/status/drain/backfill/judge/config json sites; action-command error branches (~L326-336/366-376/405-415 region)
- Modify: `tests/test_json_schema_contract.py`

**Interfaces:**
- Consumes: Task 1 harness
- Produces: `prompts list` wrapped shape `{success, items}`

- [ ] **Step 1: Contract additions**

```python
        # --- Task 6: prompts ---
        ("prompts-list", ["prompts", "list"], False),
        ("prompts-status", ["prompts", "status"], False),
```

```python
    def test_prompts_list_is_object_with_items(self, cli):
        r = _run_json(cli, "prompts", "list")
        data = assert_json_shape(r.stdout, True)
        assert isinstance(data["items"], list)
```

- [ ] **Step 2: Run — FAIL**

Run: `uv run pytest tests/test_json_schema_contract.py -v -k prompts`
Expected: 3 FAIL (list: top-level array raises isinstance assertion; status: missing success).

- [ ] **Step 3: Implement**

1. `list` (~L76): `print(json.dumps(rows, ...))` → `print(json.dumps({"success": True, "items": rows}, ensure_ascii=False, indent=2))`
2. `status` (~L169): wrap its `data` dict with success.
3. `show` (~L123): wrap `out` dict; not-found already JSON-shaped — verify it also has success:false (it does per inventory) and leave.
4. `drain` (~L200), `backfill` (~L225), `judge` (~L279): wrap result/data dicts.
5. `config` (~L111 site with capture/judge): wrap.
6. Action commands (promote/unresolved/resolve-unresolved/ignore/retry) error branches (~L326-415): the pattern at these sites is already `json.dumps({...})` in json mode for failures — audit each: ensure failure JSON includes `"success": False` and `"error"`; where the current failure JSON lacks `error`, add it (message from the service result if available, else generic). Success side of action commands prints console text only — leave as-is (out of #502 scope: they have no `--json` success output today; wrapping a new success JSON would be additive but is NOT required by the spec — do not gold-plate).

- [ ] **Step 4: Run + commit**

Run: `uv run pytest tests/test_json_schema_contract.py -v -k prompts`
Expected: 3 PASS.

```bash
git add jfox/prompts/cli.py tests/test_json_schema_contract.py
git commit -m "feat(prompts): success flag, json errors, list bare-array wrap (#502 C1d/C2c/C5a)"
```

---

### Task 7: bookshelf + auto-summary + backup (C1e/C2d/C4/C5b → A1/A2/A4/A5)

**Files:**
- Modify: `jfox/bookshelf/cli.py` — list (~L166), show json site, remove (~L289/L294)
- Modify: `jfox/auto_summary/cli.py` — status (~L109 + progress dict ~L100), scan, run (~L353-374)
- Modify: `jfox/backup/cli.py` — status, list (~L197), verify (~L220)
- Modify: `tests/test_json_schema_contract.py`

**Interfaces:**
- Consumes: Task 1 harness
- Produces: `auto-summary run` shape `{success: bool, succeeded: int, ...}`; `backup list` `{success, items}`; `backup verify` `{success, snapshot, ok}`

- [ ] **Step 1: Contract additions**

```python
        # --- Task 7: bookshelf/auto-summary/backup ---
        ("bookshelf-list", ["bookshelf", "list"], False),
        ("auto-summary-status", ["auto-summary", "status"], False),
        ("auto-summary-scan", ["auto-summary", "scan"], False),
        ("backup-status", ["backup", "status"], False),
        ("backup-list", ["backup", "list"], False),
```

```python
    def test_backup_list_is_object_with_items(self, cli):
        r = _run_json(cli, "backup", "list")
        data = assert_json_shape(r.stdout, True)
        assert isinstance(data["items"], list)

    def test_auto_summary_scan_shape(self, cli):
        r = _run_json(cli, "auto-summary", "scan")
        data = assert_json_shape(r.stdout, True)
        assert isinstance(data.get("pending"), list)
```

(`auto-summary run` fires `claude -p` — NOT tested via subprocess; unit-level assertion below covers the rename.)

- [ ] **Step 2: Unit test for the run rename (no daemon/claude invocation)**

Add to the contract file (pure shape test via monkeypatch):

```python
class TestAutoSummaryRunShape:
    def test_run_json_has_bool_success_and_int_succeeded(self, cli, monkeypatch):
        """run's json branch shape: success=bool, succeeded=int (C4 rename)."""
        from jfox.auto_summary import cli as as_cli

        class FakeReport:
            scanned = processed = skipped = failed = 0
            success = 3  # int count — the field being renamed
            items = []

        monkeypatch.setattr(as_cli, "run_once", lambda dry_run: FakeReport())
        import io, contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            as_cli.run(dry_run=True, output_format="json")
        data = json.loads(buf.getvalue())
        assert data["success"] is True          # boolean
        assert data["succeeded"] == 3           # renamed count
        assert "error" not in data
```

- [ ] **Step 3: Run — new entries FAIL (run-shape test fails on success==3 bool assert)**

Run: `uv run pytest tests/test_json_schema_contract.py -v -k "bookshelf or auto-summary or backup"`
Expected: FAIL entries as described.

- [ ] **Step 4: Implement bookshelf**

1. `list` (~L166): `_emit_json({"books": rows, "total": len(rows)})` → `_emit_json({"success": True, "books": rows, "total": len(rows)})`
2. `show` json site (find `_emit_json(book_meta...)` / `to_dict()` print): wrap with success.
3. `show --page` shape `{slug, page, content}`: wrap with success.
4. `remove` (~L289/294): add `"success": True` to both `{slug, removed}` dicts.

- [ ] **Step 5: Implement auto_summary**

1. `run` json (~L355): `"success": report.success` → `"success": True, "succeeded": report.success`
2. `status` progress dict (~L100): `"success": success` → `"succeeded": success`; add `"success": True` to the top-level `_fmt(json_data={...})` dict (~L112).
3. `scan` json site: wrap with success.

- [ ] **Step 6: Implement backup**

1. `list` (~L197): `_fmt(json_data=snaps, fmt="json")` → `_fmt(json_data={"success": True, "items": snaps}, fmt="json")`
2. `verify` (~L220): `{"snapshot": str(p), "ok": ok}` → `{"success": ok, "snapshot": str(p), "ok": ok}` (keep ok for compat; success carries the contract; exit code already correct at ~L223)
3. `status` json site: wrap with success.

- [ ] **Step 7: Run + commit**

Run: `uv run pytest tests/test_json_schema_contract.py -v -k "bookshelf or auto-summary or backup"`
Expected: all PASS. Then full contract file:
`uv run pytest tests/test_json_schema_contract.py -v`
Expected: all PASS.

```bash
git add jfox/bookshelf/cli.py jfox/auto_summary/cli.py jfox/backup/cli.py tests/test_json_schema_contract.py
git commit -m "feat(bookshelf,auto-summary,backup): success flag, run rename, list wrap (#502 C1e/C4/C5b)"
```

---

### Task 8: candidates show/list (C1f → A1)

**Files:**
- Modify: `jfox/candidates/cli.py` — show/list json sites
- Modify: `tests/test_json_schema_contract.py`

**Interfaces:**
- Consumes: Task 1 harness
- Produces: candidates contract entries

- [ ] **Step 1: Contract additions**

```python
        # --- Task 8: candidates ---
        ("candidates-list", ["candidates", "list"], False),
```

(show needs a candidate note — skip in contract list; wrap its json site by inspection.)

- [ ] **Step 2: Run — candidates-list FAIL**

Run: `uv run pytest tests/test_json_schema_contract.py -v -k candidates`
Expected: FAIL missing success.

- [ ] **Step 3: Implement**

1. `list` json site: wrap `{"candidates": ..., "total": ...}` with success.
2. `show` json site (`typer.echo(json.dumps(note.to_dict()...))`): wrap `{"success": True, **note_dict}`.
3. Do NOT touch promote/reject (already have success; their failure-without-error quirk is out of #502 scope — noted in plan deliberately).

- [ ] **Step 4: Run + commit**

Run: `uv run pytest tests/test_json_schema_contract.py -v -k candidates`
Expected: PASS.

```bash
git add jfox/candidates/cli.py tests/test_json_schema_contract.py
git commit -m "feat(candidates): success flag on show/list json (#502 C1f)"
```

---

### Task 9: docs/json-schemas.md (C6 → U1 support)

**Files:**
- Create: `docs/json-schemas.md`

**Interfaces:**
- Consumes: final shapes from Tasks 2-8
- Produces: the user-facing schema doc (U1 verifies against real output)

- [ ] **Step 1: Write the doc**

Structure (Chinese, consistent with repo docs):

```markdown
# jfox --json 输出 schema（v1.14.0 起）

## 分流规则

所有 `--json` 输出顶层必有布尔 `success`：
- `success: true` —— 命令执行成功，实体字段位置见下表
- `success: false` —— 执行失败，必有非空 `error` 字符串，进程退出码 1

调用方只需 `data["success"]` 即可分流，无需先看退出码。

## 顶层字段约定

| 字段 | 类型 | 出现条件 |
|------|------|----------|
| success | bool | 恒有 |
| error | string | 仅失败时 |
| id / title | string | add 成功时（冗余快捷字段，与 note.id/note.title 同值）|
| 其余 | 按命令 | 见下表 |

## 命令 schema 表

（每行：命令 | 成功顶层字段 | 实体字段位置 | 失败附加字段 | 示例）

| 命令 | 成功顶层字段 | 实体位置 |
|------|--------------|----------|
| add | success, id, title, note{...}, [warnings] | note 嵌套 |
| search | success, query, mode, total, results[] | results 列表 |
| show | success, id, title, type, ..., content_body | 顶层平铺 |
| list | success, total, notes[] | notes 列表 |
| ...(全部 27 顶层命令 + 8 子应用命令，从 schema-inventory.md 逐条转写，加上 success) |

## v1.14.0 breaking changes

- backup list / prompts list：裸数组 → `{success, items}`（原 `[...]` 调用方改 `.items`）
- auto-summary run：`success`(int 计数) → `succeeded`(int)，`success` 变布尔；status 的 progress.success 同理
```

Fill every command row from `~/.claude/github-issue-driven/zhuxixi/jfox/issue-502/research/schema-inventory.md` (the inventory tables) plus this plan's final shapes. Doc must pass `npx --yes markdownlint-cli2`.

- [ ] **Step 2: Lint**

Run: `npx --yes markdownlint-cli2 docs/json-schemas.md`
Expected: clean (fix any findings).

- [ ] **Step 3: Commit**

```bash
git add docs/json-schemas.md
git commit -m "docs: add json output schema reference (#502 C6)"
```

---

### Task 10: Full regression + acceptance cross-check (A1-A5)

**Files:**
- Modify: none (verification task)

**Interfaces:**
- Consumes: everything
- Produces: acceptance evidence recorded in the PR description

- [ ] **Step 1: Full contract suite**

Run: `uv run pytest tests/test_json_schema_contract.py -v`
Expected: 100% PASS. Count params — EXPECTED_SUCCESS_COMMANDS must contain every command touched by Tasks 2-8 (cross-check against the spec C1 scope list).

- [ ] **Step 2: Touched-command fast tests**

Run: `uv run pytest tests/test_add_dedup_cli.py tests/test_core_workflow.py tests/test_kb_current.py tests/test_integration.py -m "not slow and not embedding" -v`
Expected: PASS — if any assertion broke on `succeeded`/`items` renames, fix the TEST (shapes are the new contract) and note it in the commit.

- [ ] **Step 3: markdownlint whole repo**

Run: `npx --yes markdownlint-cli2`
Expected: clean.

- [ ] **Step 4: U1 preparation — manual verification checklist**

Output (do not execute) the U1 checklist for the user: pick add/search/show/list/kb list/bookshelf list, run each with `--json` against a scratch KB, compare with docs/json-schemas.md rows. Record results in PR description as U1 evidence (or pending).

- [ ] **Step 5: Final commit (if test fixes) + summary**

```bash
git status --short  # verify nothing stray
git log --oneline main..HEAD  # show task commits
```

---

## Acceptance traceability

| Spec ID | Tasks | Evidence |
|---------|-------|----------|
| A1 | 1,2,3,5,6,7,8,10 | contract suite green |
| A2 | 3,5,10 | TestErrorContract + per-branch tests green; untestable branches (status generic except, model download crash path) noted as review-verified in PR |
| A3 | 4,10 | test_add_top_level_shortcuts green |
| A4 | 7,10 | TestAutoSummaryRunShape green |
| A5 | 6,7,10 | list-wrap tests green |
| U1 | 9,10 | docs/json-schemas.md + manual checklist output |
