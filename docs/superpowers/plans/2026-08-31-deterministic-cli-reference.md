# Deterministic English CLI Reference Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Generate an exhaustive English CLI reference from JFox's live Typer command tree without changing runtime CLI help or touching the user's global knowledge-base configuration.

**Architecture:** `scripts/generate_docs.py` will expose pure extraction, parameter-normalization, description-validation, and Markdown-rendering functions, with filesystem writing and real-app orchestration kept at the edge. The Typer/Click command tree remains authoritative for command structure and syntax; `docs/cli-descriptions.yaml` contains English prose only; `docs/cli-reference.md` is generated output.

**Tech Stack:** Python 3.10+, Typer/Click, PyYAML, dataclasses, argparse, pytest, Markdown, `markdownlint-cli2`.

## Global Constraints

- Work only in `/home/elling/git-repo/github/jfox/.pi/worktrees/issue-472-cli-reference` on branch `issue-472-cli-reference`.
- Preserve the approved design in `docs/superpowers/specs/2026-08-31-deterministic-cli-reference-design.md`.
- Keep runtime Typer help text unchanged; do not modify `jfox/cli.py` or any CLI callback/module for localization.
- Use Python syntax compatible with `requires-python = ">=3.10"`.
- Reuse the existing PyYAML dependency; add no new dependency.
- Typer/Click is authoritative for command paths, arguments, options, aliases, types, required status, defaults, choices, multiplicity, and ordering after normalization.
- English description metadata contains prose only and must not define parameter or option facts.
- The generated reference must be byte-identical for the same source tree, metadata, dependency versions, and generator version.
- The generator must not invoke JFox commands, callbacks, embedding, daemon, network, prompts, or real knowledge-base operations.
- All subprocess and real-app tests must set `ZK_CONFIG_PATH`, `HOME`, and `USERPROFILE` to temporary paths; no test may write the user's real `~/.zk_config.json`.
- Generated output must contain no timestamps, absolute paths, process IDs, ANSI codes, terminal-width-dependent help text, or Chinese runtime help.
- Do not restore an exhaustive command table to `README.md`; add only a minimal link to `docs/cli-reference.md`.
- Do not modify `.github/workflows/*`, `AGENTS.md`, `CLAUDE.md`, plugin files, or unrelated application code.
- Every implementation task must map to one or more acceptance IDs from the spec: A1–A10.

---

## File Map

- Create: `scripts/generate_docs.py` — public generator entry point plus pure extraction, normalization, validation, rendering, and isolated real-app orchestration.
- Create: `docs/cli-descriptions.yaml` — manually maintained English command descriptions keyed by complete command path; no parameter schema.
- Create: `docs/cli-reference.md` — generated English reference, clearly marked as generated.
- Create: `tests/unit/test_generate_docs.py` — pure unit coverage for extraction, normalization, catalog parsing/validation, and rendering.
- Create: `tests/integration/test_cli_reference_generation.py` — real-app coverage, subprocess generation, determinism, configuration safety, and README boundary checks.
- Modify: `README.md` — replace the “planned generated reference” sentence with a link to `docs/cli-reference.md` while retaining the curated overview.
- Preserve: `docs/superpowers/specs/2026-08-31-deterministic-cli-reference-design.md` — already committed as the first worktree commit.

## Interfaces

Use these public interfaces unless a technically necessary equivalent keeps the same boundaries and acceptance coverage:

```python
@dataclass(frozen=True)
class NormalizedParameter:
    name: str
    kind: str
    syntax: str
    type_name: str
    required: bool
    default: str
    choices: tuple[str, ...]
    multiple: bool
    is_flag: bool

@dataclass(frozen=True)
class NormalizedCommand:
    path: str
    is_group: bool
    usage: str
    description_key: str
    parameters: tuple[NormalizedParameter, ...]


def extract_commands(root_command: click.Command, root_name: str = "jfox") -> tuple[NormalizedCommand, ...]: ...
def normalize_parameter(parameter: click.Parameter) -> NormalizedParameter: ...
def load_descriptions(path: Path) -> dict[str, str]: ...
def validate_descriptions(command_paths: Collection[str], descriptions: Mapping[str, str]) -> None: ...
def render_reference(commands: Sequence[NormalizedCommand], descriptions: Mapping[str, str]) -> str: ...
def write_reference(path: Path, content: str) -> None: ...
def generate_reference(output: Path, descriptions: Path) -> None: ...
```

The exact module-qualified Click type annotations may be adjusted to match the resolved Click API, but the renderer must consume normalized records rather than Click objects.

## Command-tree rules

- Convert the live Typer application with `typer.main.get_command(app)`.
- Use `jfox` as the root documentation name even if Click exposes no root name.
- Include a root record for `jfox` and one record for every nested command path.
- Recursively visit `click.Group.commands`.
- Sort command records by path segments so output is stable and root appears before descendants.
- Do not execute command callbacks while extracting.
- For a group, usage is `jfox <path> [OPTIONS] COMMAND [ARGS]...` with the appropriate omission of `[OPTIONS]` only when no options exist.
- For a leaf command, usage is `jfox <path> [OPTIONS] <ARGUMENTS>` using normalized argument metavars.
- Preserve all option aliases exposed by Click in stable order; preserve secondary boolean flags such as `--foo/--no-foo`.
- Preserve parameter definition order within a command after normalization.

## Parameter-display rules

- `click.Argument` uses its explicit metavar or an uppercase parameter name as syntax.
- `click.Option` syntax contains all primary and secondary flags, with boolean primary/secondary pairs rendered as `--flag / --no-flag`.
- Type names use the Click type's stable uppercase name when available; fall back to the class name only when no name is exposed.
- Required is rendered as `yes` or `no`.
- Missing defaults are rendered as `—`; booleans use lowercase `true`/`false`; strings and choices are rendered without machine-specific repr noise.
- Choices are rendered in stable declaration order; absent choices render as `—` in the table.
- `multiple`, `is_flag`, and other structural facts may be rendered as additional columns when exposed by the normalized record.
- Do not include parameter help text from the current Chinese runtime help in the English reference.

## Catalog rules

`docs/cli-descriptions.yaml` uses this schema:

```yaml
commands:
  "jfox":
    description: "Manage a local-first Zettelkasten knowledge base."
  "jfox init":
    description: "Initialize and register a knowledge base."
```

- Load only the top-level `commands` mapping.
- Reject malformed YAML, missing `commands`, non-mapping command entries, missing `description`, empty descriptions, non-string descriptions, unknown command paths, duplicate YAML keys, and extra parameter/option fields.
- A duplicate command key must fail instead of being silently overwritten by PyYAML.
- The complete catalog must cover the root and every command path extracted from the current application, including all current groups: `template`, `model`, `auto-summary`, `backup`, `fragments`, `candidates`, `gem-synth`, `bookshelf`, and `moc`.
- The catalog may contain concise command-group descriptions and leaf-command descriptions; it must not contain `options`, `arguments`, `aliases`, `type`, `default`, or equivalent structural definitions.

## Generated-file rules

`docs/cli-reference.md` must begin with:

```markdown
<!--
This file is generated by scripts/generate_docs.py.
Do not edit manually.

Regenerate with:
uv run python scripts/generate_docs.py
-->
```

Then include:

- title `# JFox CLI Reference`;
- a short English source-of-truth explanation;
- the root `jfox` usage and parameters;
- one `##` section per normalized command path;
- the English metadata description;
- a stable usage block;
- an English parameter table with syntax, type, required, default, and choices/structural fields;
- a note that runtime help remains available through `jfox --help` and `jfox <command> --help`.

The file must not include the original Chinese runtime docstrings or help text.

## Implementation Tasks

### Task 1: Implement and unit-test pure extraction, normalization, catalog validation, and rendering

**Acceptance IDs:** A1, A2, A3, A4.

**Files:**

- Create: `scripts/generate_docs.py`.
- Create: `tests/unit/test_generate_docs.py`.

**Interfaces:**

- Consumes: Synthetic Click command trees and temporary YAML catalogs.
- Produces: `NormalizedCommand`, `NormalizedParameter`, extraction, normalization, catalog-loading/validation, and rendering interfaces listed above.

- [ ] **Step 1: Write failing unit tests for nested command extraction (A1).**

Create a synthetic Click group with a leaf command and a nested group/leaf command. Assert that:

- the root record is present;
- complete paths use the `jfox` root prefix;
- nested paths are present;
- group/leaf classification is correct;
- command ordering is stable and sorted by path;
- callbacks are not invoked during extraction.

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-472-cli-reference
uv run pytest tests/unit/test_generate_docs.py -k command_tree -q
```

Expected: tests fail because `scripts/generate_docs.py` and the extraction interface do not exist.

- [ ] **Step 2: Implement minimal command extraction for A1.**

Implement immutable normalized records and recursive Click-group traversal. Do not import `jfox.cli` in the unit-test path and do not execute callbacks. Sort command records by path while retaining the root before descendants.

- [ ] **Step 3: Run extraction tests.**

Run the same `-k command_tree` command. Expected: all extraction tests pass.

- [ ] **Step 4: Write failing unit tests for parameter normalization (A2).**

Cover at least:

- positional argument with metavar;
- option with long and short aliases;
- boolean option with primary and secondary flags;
- required option;
- default integer, boolean, string, and absent default;
- `click.Choice` values;
- `multiple=True`;
- stable type names and syntax.

Run:

```bash
uv run pytest tests/unit/test_generate_docs.py -k parameter -q
```

Expected: the new tests fail for the missing normalizer.

- [ ] **Step 5: Implement minimal parameter normalization for A2.**

Normalize Click parameters into serializable records. Keep Click-specific formatting and version quirks inside `normalize_parameter`; do not make the renderer inspect Click objects. Render boolean secondary flags and absent values according to the parameter-display rules above.

- [ ] **Step 6: Run parameter tests.**

Run:

```bash
uv run pytest tests/unit/test_generate_docs.py -k parameter -q
```

Expected: all parameter tests pass.

- [ ] **Step 7: Write failing unit tests for YAML loading and completeness validation (A3).**

Cover:

- valid catalog loads;
- malformed YAML fails;
- duplicate YAML command keys fail;
- missing `commands` fails;
- missing command description fails validation;
- unknown command entry fails validation;
- empty/non-string description fails;
- extra parameter/option fields fail.

Run:

```bash
uv run pytest tests/unit/test_generate_docs.py -k description -q
```

Expected: tests fail until catalog parsing and validation exist.

- [ ] **Step 8: Implement catalog loading and validation for A3.**

Use a PyYAML safe loader that detects duplicate keys. Validate the exact prose-only schema and raise actionable errors naming the file or command path. Never fall back to runtime Chinese help or a generic untranslated description.

- [ ] **Step 9: Run catalog tests.**

Run the same `-k description` command. Expected: all catalog tests pass.

- [ ] **Step 10: Write failing unit tests for deterministic Markdown rendering (A4).**

Build normalized records directly and assert:

- the generated marker and regeneration command exist;
- English headings and table labels exist;
- command descriptions are inserted from metadata;
- absent values render as `—`;
- no timestamps, absolute paths, ANSI escapes, or Chinese fixture text are emitted;
- rendering identical records twice returns byte-identical strings;
- command sections and usage are stable.

Run:

```bash
uv run pytest tests/unit/test_generate_docs.py -k render -q
```

Expected: tests fail until rendering exists.

- [ ] **Step 11: Implement deterministic Markdown rendering for A4.**

Render only normalized records and validated descriptions. Use fixed headings, fixed English labels, stable ordering, UTF-8 text, and Unix newline strings. Do not call Click help formatting or inspect the environment, filesystem, current time, or terminal width.

- [ ] **Step 12: Run pure unit tests and the unit lint check.**

Run:

```bash
uv run pytest tests/unit/test_generate_docs.py -q
npx --yes markdownlint-cli2 tests/unit/test_generate_docs.py scripts/generate_docs.py
```

The Markdown lint command should be applied only to Markdown files if the CLI rejects non-Markdown paths; the expected Markdown result is 0 issues for any Markdown test/spec files.

Expected: all unit tests pass. Python files are checked with the repository's Ruff/Black commands in the final validation task.

### Task 2: Add English catalog, real-app orchestration, generated reference, and integration tests

**Acceptance IDs:** A5, A6, A7, A8.

**Files:**

- Modify: `scripts/generate_docs.py`.
- Create: `docs/cli-descriptions.yaml`.
- Create: `docs/cli-reference.md`.
- Create: `tests/integration/test_cli_reference_generation.py`.

**Interfaces:**

- Consumes: Task 1's pure normalization and rendering functions.
- Produces: `generate_reference(output, descriptions)` and the public `uv run python scripts/generate_docs.py` command.

- [ ] **Step 1: Extract the real command-path inventory before writing metadata (A5).**

Run under an isolated environment:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-472-cli-reference
test_home="$(mktemp -d)"
trap 'rm -rf "$test_home"' EXIT
HOME="$test_home" USERPROFILE="$test_home" ZK_CONFIG_PATH="$test_home/config.json" \
  uv run python - <<'PY'
from typer.main import get_command
from jfox.cli import app
from scripts.generate_docs import extract_commands

root = get_command(app)
for command in extract_commands(root):
    print(command.path)
PY
```

Expected: the output includes the root and every current command path, including the nested groups and children listed in the catalog rules. Use this output as the checklist for the catalog, not a manually guessed inventory.

- [ ] **Step 2: Write the complete English description catalog.**

Add one concise `description` entry for every path printed in Step 1. Keep descriptions factual and user-facing. Do not add parameter or option definitions. Include explicit descriptions for command groups so every generated section is readable.

- [ ] **Step 3: Write failing real-app coverage tests for A5.**

Create integration tests that import the real Typer app under an isolated environment and assert that normalized paths include all current top-level and nested commands, including:

```text
jfox model download
jfox auto-summary forget
jfox auto-summary prune
jfox backup restore
jfox fragments list
jfox candidates promote
jfox candidates reject
jfox gem-synth status
jfox gem-synth dedup-backfill
jfox bookshelf add
jfox bookshelf remove
jfox moc create
jfox moc update
jfox moc diagnose
```

Run:

```bash
ZK_CONFIG_PATH="$(mktemp)" uv run pytest tests/integration/test_cli_reference_generation.py -k coverage -q
```

Expected: the tests initially fail if the catalog/orchestration is incomplete.

- [ ] **Step 4: Implement safe real-app orchestration for A5/A6.**

Implement `generate_reference` and the CLI `main()` using `argparse`. Resolve the repository root from `scripts/generate_docs.py`, resolve relative paths from that root, import the Typer app only at orchestration time, and pass the app through the pure extraction/validation/rendering pipeline.

Before importing `jfox.cli`, ensure the generator process has an isolated temporary config/KB environment if those variables are not already supplied, so importing the app cannot write the user's real global configuration. Do not invoke a command callback. Preserve explicit caller-provided `ZK_CONFIG_PATH`, `HOME`, `USERPROFILE`, or `ZK_KB_ROOT` values when present.

The CLI must support:

```text
uv run python scripts/generate_docs.py
uv run python scripts/generate_docs.py --output PATH --descriptions PATH
```

On validation or write errors, exit non-zero with the command path/file path and remediation.

- [ ] **Step 5: Run real-app coverage tests (A5).**

Run:

```bash
ZK_CONFIG_PATH="$(mktemp)" uv run pytest tests/integration/test_cli_reference_generation.py -k coverage -q
```

Expected: the real JFox command inventory is covered and no callback or model is invoked.

- [ ] **Step 6: Write failing subprocess-generation and determinism tests (A6/A7).**

Use `subprocess.run` with a temporary output directory and temporary `HOME`, `USERPROFILE`, and `ZK_CONFIG_PATH`. Assert:

- the public generator exits 0;
- the output file exists;
- representative English headings/descriptions and nested commands exist;
- two consecutive outputs are byte-identical;
- the generated marker is present;
- no repository-root artifact is created.

Run:

```bash
ZK_CONFIG_PATH="$(mktemp)" uv run pytest tests/integration/test_cli_reference_generation.py -k 'subprocess or deterministic' -q
```

Expected: tests fail until the catalog, generator, and output file are complete.

- [ ] **Step 7: Implement and run the public generator (A6/A7).**

Run:

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-472-cli-reference
rm -f /tmp/jfox-cli-reference-a.md /tmp/jfox-cli-reference-b.md
HOME="$(mktemp -d)" USERPROFILE="$(mktemp -d)" ZK_CONFIG_PATH="$(mktemp)" \
  uv run python scripts/generate_docs.py --output /tmp/jfox-cli-reference-a.md
HOME="$(mktemp -d)" USERPROFILE="$(mktemp -d)" ZK_CONFIG_PATH="$(mktemp)" \
  uv run python scripts/generate_docs.py --output /tmp/jfox-cli-reference-b.md
cmp /tmp/jfox-cli-reference-a.md /tmp/jfox-cli-reference-b.md
```

Expected: both runs exit 0 and `cmp` reports identical files. The generated file includes all real command paths and English descriptions.

- [ ] **Step 8: Add configuration-safety regression test (A8).**

Record the real `~/.zk_config.json` SHA-256 before and after a generator subprocess run. Use a fresh temporary environment for the child process. Assert the hash, default entry, and knowledge-base registry are unchanged. Assert no generated test output appears in the repository root.

Run:

```bash
uv run pytest tests/integration/test_cli_reference_generation.py -k config_safety -q
```

Expected: pass with the real config unchanged.

- [ ] **Step 9: Run all generator-focused tests.**

Run:

```bash
uv run pytest tests/unit/test_generate_docs.py tests/integration/test_cli_reference_generation.py -q
```

Expected: all generator tests pass with no access to the real user config.

### Task 3: Integrate the generated reference with README and perform static validation

**Acceptance IDs:** A9, A10.

**Files:**

- Modify: `README.md`.
- Read: `docs/cli-reference.md`, `docs/cli-descriptions.yaml`.

**Interfaces:**

- Consumes: The generated reference and public generator from Task 2.
- Produces: A curated README link and a verified generated/curated boundary.

- [ ] **Step 1: Write the minimal README link change (A10).**

In the existing `Common Commands` section, replace the sentence that says an exhaustive generated CLI reference is planned with:

```markdown
For the complete command and option reference, see the [CLI Reference](cli-reference.md). You can also run `jfox --help` or `jfox <command> --help` for the installed CLI's runtime help.
```

Keep the curated command table unchanged. Do not copy any generated command sections into `README.md`.

- [ ] **Step 2: Verify the README boundary (A10).**

Run:

```bash
uv run pytest tests/integration/test_cli_reference_generation.py -k readme_boundary -q
```

Expected: the README link resolves, the README remains curated/non-exhaustive, and the generated file contains the generated marker.

- [ ] **Step 3: Run Markdown and link checks (A9).**

Run:

```bash
npx --yes markdownlint-cli2 README.md docs/cli-reference.md
python - <<'PY'
from pathlib import Path
import re

for filename in ("README.md", "docs/cli-reference.md"):
    path = Path(filename)
    text = path.read_text(encoding="utf-8")
    for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
        if target.startswith(("http://", "https://", "#", "mailto:")):
            continue
        target_path = (path.parent / target.split("#", 1)[0]).resolve()
        if not target_path.exists():
            raise SystemExit(f"Broken link in {filename}: {target}")
print("README and CLI reference relative links are valid.")
PY
```

Expected: Markdown lint reports 0 issues and every relative link resolves.

- [ ] **Step 4: Run Python quality checks.**

Run:

```bash
uv run ruff check scripts/generate_docs.py tests/unit/test_generate_docs.py tests/integration/test_cli_reference_generation.py
uv run black --check scripts/generate_docs.py tests/unit/test_generate_docs.py tests/integration/test_cli_reference_generation.py
```

Expected: Ruff and Black both pass.

- [ ] **Step 5: Verify runtime help isolation and stale-content rules.**

Run:

```bash
uv run jfox --help >/tmp/jfox-472-root-help.txt
uv run jfox search --help >/tmp/jfox-472-search-help.txt
git diff -- jfox/cli.py
grep -nE 'This file is generated|Regenerate with|jfox auto-summary forget|jfox backup restore|jfox bookshelf add|jfox moc diagnose' docs/cli-reference.md
if grep -nP '[\x{4e00}-\x{9fff}]' docs/cli-reference.md; then
  echo 'Chinese characters found in generated CLI reference'
  exit 1
fi
```

Expected: runtime help commands succeed, `git diff -- jfox/cli.py` is empty, representative generated sections exist, and the generated reference contains no Chinese characters.

- [ ] **Step 6: Run the complete focused acceptance set.**

Run:

```bash
uv run pytest tests/unit/test_generate_docs.py tests/integration/test_cli_reference_generation.py -q
npx --yes markdownlint-cli2 README.md docs/cli-reference.md

git diff --check
git status --short
git diff --name-only
```

Expected:

- all generator tests pass under isolated configuration;
- both user-facing Markdown files lint successfully;
- no whitespace errors;
- only the planned files are changed or created;
- no runtime CLI, CI, plugin, or unrelated application files are modified.

- [ ] **Step 7: Record acceptance evidence.**

The implementation report and issue comment must map evidence to:

```text
A1 command-tree unit coverage
A2 parameter-normalization unit coverage
A3 English-catalog validation unit coverage
A4 deterministic-renderer unit coverage
A5 real JFox command coverage
A6 public subprocess generation
A7 byte-identical repeated generation
A8 real global-config safety
A9 Markdown/link static validation
A10 curated README/generated-reference boundary
```

Do not claim all acceptance criteria are complete until the isolated subprocess test and the real-config hash assertion have both passed.

## Review Handoff

Use one writer for the shared worktree. After implementation, provide the reviewer with the full branch diff and this plan/spec. The reviewer must inspect:

1. Typer/Click command and parameter facts are not duplicated in metadata.
2. Runtime help and application code remain unchanged.
3. The English catalog covers every live command and rejects stale/unknown keys.
4. Pure renderer and writer boundaries remain separate.
5. Generated output is deterministic and free of Chinese runtime help, timestamps, paths, ANSI codes, and machine details.
6. The generator and tests cannot touch the real global config.
7. README remains curated and only links to the generated reference.
8. Acceptance IDs A1–A10 have concrete evidence.

The next phase may add CI drift gating, but it must consume this local generator and must not be implemented in this plan.
