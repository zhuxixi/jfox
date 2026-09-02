# Design Spec: Plugin Inventory and Enum Coverage Checks

- **Issue:** [#480](https://github.com/zhuxixi/jfox/issues/480)
- **Parent issue:** [#456](https://github.com/zhuxixi/jfox/issues/456)
- **Repository:** `zhuxixi/jfox`
- **Status:** Approved for implementation
- **Phase:** 2B — plugin inventory and NoteType/GemLevel coverage checks

## 1. Problem

Two documented-fact sources still have no mechanical verification:

- **Plugin inventory.** The skills under `packages/cc-plugin/skills/` and `packages/kimi-plugin/skills/` are user-relevant facts. The current Claude Code manifest does not enumerate skills, and the Kimi manifest's `skills` value is the directory pointer `"./skills/"`, not a per-skill list. The actual discovery contract is therefore the plugin manifest plus the directories that the manifest resolves to. A new, renamed, or removed skill directory currently has no documentation consequence, and the README deliberately carries no per-skill list (Phase 1 removed hard-coded counts).
- **Enum coverage.** `jfox/models.py` defines `NoteType` and `GemLevel`. The README Note Model section matches the current values by hand; adding, removing, or renaming a model value without updating the README passes silently.
- **Generated-file deletion.** The Phase 3 gate uses `git diff --exit-code`, which detects changes to tracked files but not a generated file that is recreated as untracked after being deleted from the checkout. Adding a second generated document makes that blind spot concrete.

## 2. Desired outcome

1. A generated `docs/plugin-inventory.md` containing English structural facts only: plugin, skill name, and source directory. It must not copy Agent-facing `SKILL.md` descriptions or trigger words.
2. Minimal manifest validation: the known plugin manifests must be readable, and their skill-root declarations must resolve to existing directories. The checker must honor a manifest's resolved skill root rather than hard-code it silently.
3. An enum-coverage checker that compares the README Note Model values with the string values declared in `jfox/models.py`, reports missing/stale/duplicate values, and never rewrites the curated README.
4. Both checks must run through the existing `uv run python scripts/generate_docs.py` entry point. The existing Phase 3 gate invocation remains the same, while its comparison block also detects untracked generated files.
5. `packages/**` must be present in both workflow path-filter blocks, and README Agent Integrations must link to the generated inventory.
6. All new logic must have isolated unit boundaries and a subprocess test path that can use temporary inputs and outputs without modifying the real README, package directories, or generated files.

## 3. Scope

### In scope

- Keep `scripts/generate_docs.py` as the single public CLI entry point and extend its orchestration.
- Add focused helper modules:
  - `scripts/plugin_inventory.py` for manifest resolution, skill-directory discovery, and inventory rendering.
  - `scripts/enum_coverage.py` for README parsing, model-value extraction, and enum comparison.
- Generate `docs/plugin-inventory.md` with a generated-file marker and deterministic ordering.
- Validate the two current plugin manifests:
  - `packages/cc-plugin/.claude-plugin/plugin.json`;
  - `packages/kimi-plugin/kimi.plugin.json`.
- Check the README `## Note Model` section against `NoteType` and `GemLevel` in `jfox/models.py`.
- Extend the existing `lint` gate with a targeted untracked-generated-file check.
- Add `packages/**` to both `push` and `pull_request` path filters in `.github/workflows/integration-test.yml`.
- Add one curated README link to the generated inventory.
- Add unit and integration tests, and update the existing CLI-reference subprocess helper so it sends every generated output to a temporary path.

### Out of scope

- `skills-recommend/pi/` inventory. It is a separate consumption model and is not a package plugin in this phase.
- Per-skill English descriptions or a new `docs/plugin-descriptions.yaml`. The inventory is intentionally structural only.
- Parsing or validating `SKILL.md` frontmatter. A directory counts only when its discovered root contains `SKILL.md`; frontmatter prose is not an inventory source.
- Changes to plugin runtime behavior, manifest schemas beyond the skill-root contract, or skill content.
- Phase 4 (docs-sync bot) and Phase 5 (AI review).
- The AGENTS.md/CLAUDE.md documentation-policy sync PR. It must follow this work and include the final CI path list.
- Adding `uv.lock` to workflow paths (the advisory from #477 remains a separate follow-up).
- The four low-severity advisories from PR #474.

## 4. Design

### 4.1 Plugin source of truth and manifest resolution

The inventory has two layers of source of truth: the manifest identifies the skill root, and the resolved directory tree identifies the skills. The current package contracts are:

| Package | Manifest | Current skill-root rule |
|---|---|---|
| `cc-plugin` | `packages/cc-plugin/.claude-plugin/plugin.json` | If `skills` is absent, use the default `packages/cc-plugin/skills/` auto-discovery root. |
| `kimi-plugin` | `packages/kimi-plugin/kimi.plugin.json` | Resolve the string `skills` value `"./skills/"` relative to the manifest's package directory. |

The validator must apply these exact rules:

1. Each manifest file must exist, contain a JSON object, and be parseable.
2. If `skills` is absent, the package's default `skills/` directory is used. This is valid for the current Claude Code manifest.
3. If `skills` is present, it must be a non-empty relative string path. Resolve it relative to the package directory, normalize it, and reject a path that escapes the package root.
4. The resolved skill root must be an existing directory. An unsupported value type, a missing root, or a path-escape attempt is a hard, actionable error naming the manifest.
5. Unknown manifest fields are ignored. This phase does not impose a full plugin-manifest schema.

A skill entry exists if and only if an immediate child of a resolved skill root is a directory containing a file named `SKILL.md`. Other children are ignored because they are not discoverable skills under the current plugin contract. The checker does not read the file's frontmatter.

### 4.2 Structural inventory artifact

`docs/plugin-inventory.md` is English because all prose is generator-owned static text; it contains no copied Agent-facing descriptions. Its layout is fixed:

```markdown
<!--
This file is generated by scripts/generate_docs.py.
Do not edit manually.

Regenerate with:
uv run python scripts/generate_docs.py
-->

# JFox Plugin Skill Inventory

This inventory is generated from plugin manifests and discoverable skill directories.

## `cc-plugin`

Source root: `packages/cc-plugin/skills/`

| Skill | Source |
|---|---|
| `bookshelf` | `packages/cc-plugin/skills/bookshelf/` |

## `kimi-plugin`

Source root: `packages/kimi-plugin/skills/`

| Skill | Source |
|---|---|
| `jfox-search` | `packages/kimi-plugin/skills/jfox-search/` |
```

The example rows are illustrative; the committed document must contain every discovered skill. Package sections use the fixed package order above, skill rows use lexical order by directory name, source paths always use repository-relative POSIX separators, and the writer uses UTF-8 Unix newlines. The output contains no timestamps, absolute paths, frontmatter descriptions, or machine-specific data.

The generated marker must reuse the existing `GENERATED_MARKER` value from `scripts/generate_docs.py`. The inventory renderer is pure with respect to its normalized entries and must not inspect the environment, current time, or global JFox configuration.

### 4.3 Enum extraction and README parsing

`jfox/models.py` remains the only enum source of truth. To avoid importing the `jfox` package and triggering package-level lifecycle wiring during a documentation check, model values are extracted from the Python AST of the supplied `models.py` file:

- Find the classes named exactly `NoteType` and `GemLevel`.
- Read their uppercase member assignments whose values are string literals, preserving source order.
- Use the literal values (for example, `"permanent"`), not Python member names (for example, `PERMANENT`).
- A missing class, a non-string member value, or an unreadable/invalid source file is an actionable checker error.

`parse_readme_enums(text)` reads only the `## Note Model` section, ending at the next level-2 heading. It must enforce the following syntax contract:

1. Find the first Markdown table in that section whose first header cell is `Value`. Each data row must have a backtick-wrapped first cell; those cells are the documented `NoteType` values. A missing section, missing table, malformed row, or missing backticks is an error naming the README section.
2. Find the fenced text block in that section containing the arrow chain. Split its single chain line on `→`, trim optional backticks and whitespace, and require non-empty identifier-like values. A missing or malformed chain is an error naming `GemLevel`.
3. Ignore explanatory prose and inline code outside the table and chain block. This prevents values in the explanatory bullets from being counted twice.
4. Preserve the order returned by the parser and reject duplicate documented values before comparison.

The parser returns:

```python
@dataclass(frozen=True)
class DocumentedEnums:
    note_types: tuple[str, ...]
    gem_levels: tuple[str, ...]
```

`validate_enum_coverage(model_values, documented_values)` compares the two records as follows:

- `NoteType`: exact set equality after duplicate detection. Documentation order is curated and does not affect coverage.
- `GemLevel`: exact sequence equality because the arrow chain expresses a lifecycle.
- Missing values and stale values are reported separately, with the enum name, value, README section, and a direct remediation (`add ...` or `remove ...`).

The checker reads the README and never edits it.

### 4.4 Testable interfaces and orchestration

The following interfaces are the design contract. Private helpers may be added, but they must preserve these boundaries:

```python
@dataclass(frozen=True)
class SkillEntry:
    package: str
    name: str
    relative_source: str


def extract_skill_inventory(packages_root: Path) -> tuple[SkillEntry, ...]:
    """Resolve manifests and discover immediate skill directories."""


def render_inventory(entries: Sequence[SkillEntry]) -> str:
    """Render deterministic English structural inventory Markdown."""


def parse_readme_enums(text: str) -> DocumentedEnums:
    """Parse NoteType and GemLevel values from the bounded README section."""


def extract_model_enums(models_path: Path) -> DocumentedEnums:
    """Extract string enum values from the supplied models.py AST."""


def validate_enum_coverage(
    model_values: DocumentedEnums,
    documented_values: DocumentedEnums,
) -> None:
    """Raise an actionable error when model and README values diverge."""


def generate_all(
    cli_output: Path,
    descriptions: Path,
    inventory_output: Path,
    readme_path: Path,
    models_path: Path,
    packages_root: Path,
) -> None:
    """Validate all sources, then write both generated documents."""
```

`generate_all` must perform manifest resolution, inventory discovery/rendering, README parsing, model extraction, enum validation, and CLI description validation before writing either output file. This prevents a bad enum or manifest from leaving one generated file updated and the other stale. It then writes the existing CLI reference and the inventory with the same deterministic UTF-8 writer behavior.

The public CLI keeps the existing options and adds explicit paths needed for isolated tests:

```text
--output             default: docs/cli-reference.md
--descriptions       default: docs/cli-descriptions.yaml
--inventory-output   default: docs/plugin-inventory.md
--readme             default: README.md
--models             default: jfox/models.py
--packages-root      default: packages
```

Relative paths are resolved against the repository root derived from the script location, as the current CLI does. The existing `generate_reference(output, descriptions)` behavior remains available for current tests and callers; the CLI entry point delegates to `generate_all`.

### 4.5 Gate integration and untracked-file detection

The existing `lint` job remains the integration point. No new workflow is created, and `quality-gate` needs/semantics remain unchanged. The gate step keeps the same generator command and extends the comparison block to cover the two known generated outputs:

```yaml
    - name: Check generated docs are up to date
      run: |
        uv run python scripts/generate_docs.py
        untracked_generated="$(git ls-files --others --exclude-standard -- \
          docs/cli-reference.md docs/plugin-inventory.md)"
        if ! git diff --exit-code; then
          tracked_drift=1
        else
          tracked_drift=0
        fi
        if [ "$tracked_drift" -ne 0 ] || [ -n "$untracked_generated" ]; then
          echo "::error::Generated documentation is stale or untracked. Regenerate locally with:"
          echo "::error::  uv run python scripts/generate_docs.py"
          echo "--- Tracked changes ---"
          git diff --name-only
          if [ -n "$untracked_generated" ]; then
            echo "--- Untracked generated files ---"
            printf '%s\n' "$untracked_generated"
          fi
          exit 1
        fi
```

`git diff --exit-code` continues to detect tracked drift. `git ls-files --others` closes the specific deletion/recreation hole for `docs/cli-reference.md` and `docs/plugin-inventory.md`; when a future generated output is added, its path must be added to this explicit list in the same change. The failure output names the exact local repair command and both tracked and untracked evidence.

Add this path entry to both the `push.paths` and `pull_request.paths` lists:

```yaml
      - 'packages/**'
```

The existing `jfox/**`, `scripts/**`, `**/*.md`, and workflow entries remain unchanged. `packages/**` is required for non-Markdown manifest changes; skill Markdown files are already covered by `**/*.md`.

### 4.6 README integration

Add one curated line under `## Agent Integrations`, after the three integration bullets:

```markdown
For the current per-skill directory inventory, see the [generated plugin skill inventory](docs/plugin-inventory.md).
```

Do not copy generated rows into README and do not add descriptions or hard-coded skill counts.

## 5. Acceptance matrix

Every automated item below names a concrete command and pass condition. The GitHub path-engine smoke check remains a manual item because local pytest cannot execute GitHub's event filter engine.

| ID | Feature point | Acceptance method | Verification | Pass criteria |
|---|---|---|---|---|
| A1 | Manifest skill-root resolution | Automated (`unit`) | `uv run pytest tests/unit/test_plugin_inventory.py::test_resolve_manifest_skill_roots -q` | CC absent `skills` uses its default root; Kimi `"./skills/"` resolves inside its package; invalid/missing/escaping roots fail with the manifest path. |
| A2 | Real plugin inventory coverage | Automated (`integration`) | `uv run pytest tests/integration/test_plugin_inventory.py::test_real_inventory_matches_skill_directories -q` | The rendered inventory's `(package, skill, source)` set equals an independently globbed set of discoverable `SKILL.md` directories. The test reports the current 9 CC and 11 Kimi entries diagnostically but does not hard-code those counts. |
| A3 | New and removed skills change inventory | Automated (`unit` + local E2E) | `uv run pytest tests/unit/test_plugin_inventory.py::test_inventory_includes_new_skill_directory tests/unit/test_plugin_inventory.py::test_inventory_excludes_removed_skill_directory tests/integration/test_plugin_inventory.py::test_stale_inventory_diff_is_nonzero -q` | A new or removed discoverable directory changes rendered output, and a temporary Git checkout's `git diff --exit-code` detects the stale tracked inventory. |
| A4 | Deleted generated file cannot bypass gate | Automated (`integration`) | `uv run pytest tests/integration/test_plugin_inventory.py::test_deleted_inventory_is_detected_as_untracked -q` | Deleting a committed inventory, regenerating it as untracked, and running the specified `git ls-files --others` check produces a non-empty result and a failing gate decision. |
| A5 | README enum parser | Automated (`unit`) | `uv run pytest tests/unit/test_enum_coverage.py::test_parse_current_readme_enums tests/unit/test_enum_coverage.py::test_parse_readme_rejects_malformed_sections -q` | The current Note Model table and GemLevel chain parse correctly; missing headings, malformed rows, and missing chains fail with section-specific errors. |
| A6 | Missing model enum value fails | Automated (`unit`) | `uv run pytest tests/unit/test_enum_coverage.py::test_missing_note_type_is_actionable tests/unit/test_enum_coverage.py::test_missing_gem_level_is_actionable -q` | A model value absent from README raises a non-zero-path error naming the enum, value, README section, and `add` remediation. |
| A7 | Stale/duplicate README value fails | Automated (`unit`) | `uv run pytest tests/unit/test_enum_coverage.py::test_stale_note_type_is_actionable tests/unit/test_enum_coverage.py::test_stale_gem_level_is_actionable tests/unit/test_enum_coverage.py::test_duplicate_documented_value_is_rejected -q` | An extra, stale, duplicate, or incorrectly ordered documented value fails with an actionable `remove`/ordering message. |
| A8 | Current enum coverage passes | Automated (`integration`) | `uv run pytest tests/integration/test_plugin_inventory.py::test_current_enum_coverage -q` | Current `jfox/models.py` values and the README Note Model section pass without modifying README. |
| A9 | Deterministic full generation | Automated (`automated E2E`) | `uv run pytest tests/integration/test_plugin_inventory.py::test_full_generation_is_deterministic -q` | Two isolated subprocess runs produce byte-identical CLI and plugin-inventory outputs and do not write the real README, package tree, or global config. |
| A10 | Existing CLI reference remains compatible | Automated (`integration`) | `uv run pytest tests/integration/test_cli_reference_generation.py -q` | Existing CLI reference tests remain green; their temporary-output helper explicitly redirects both generated outputs. |
| A11 | Package path declarations are present | Automated (`static`) | `uv run pytest tests/integration/test_plugin_inventory.py::test_workflow_paths_include_packages -q` | Both `push` and `pull_request` path blocks contain exactly `packages/**`; `quality-gate` still needs `lint` and `test-fast`. |
| A12 | README link and Markdown quality | Automated (`static` + `build`) | `uv run pytest tests/integration/test_plugin_inventory.py::test_readme_links_inventory -q` and `npx --yes markdownlint-cli2@0.23.2 README.md docs/plugin-inventory.md` | README links the generated inventory without duplicating its rows; both files have zero Markdown lint findings. |
| U1 | Package-only path trigger | User-tested (`GitHub Actions`) | On a temporary branch, make a formatting-only change to a non-Markdown manifest JSON, push it, and inspect the Actions run list. | The existing integration workflow starts even though no `jfox/**` or `**/*.md` file changed. Revert the temporary formatting change after observation. |
| U2 | Manual dispatch regression | User-tested (`manual`) | Trigger `workflow_dispatch` with `test_type=fast` on the implementation branch. | The existing `lint` and `test-fast` jobs behave as before, including the new generation and untracked-file checks. |

## 6. Testability decomposition

The implementation must preserve these independent boundaries. Filesystem and subprocess effects stay at the edges; parsing, normalization, rendering, and comparison remain independently testable.

| Boundary | Production unit | Test strategy | Side effects |
|---|---|---|---|
| Manifest JSON loading | `load_plugin_manifests(packages_root)` | Temporary valid, malformed, missing, and non-object JSON files | Reads only supplied paths |
| Manifest root resolution | `resolve_manifest_skill_roots(manifest_data, package_root)` | Pure tests for absent/default, relative pointer, unsupported type, and path escape | None |
| Skill discovery | `discover_skill_paths(skill_root)` plus `extract_skill_inventory(packages_root)` | Temporary roots with normal directories, missing `SKILL.md`, empty roots, and new/removed directories | Reads only supplied package tree |
| Inventory normalization | `SkillEntry` records | Assert package, name, and POSIX relative source values from synthetic roots | None |
| Inventory rendering | `render_inventory(entries)` | Structural assertions, sorted-order assertions, two-render equality, generated marker checks | None |
| Model enum extraction | `extract_enum_values_from_ast(tree)` plus `extract_model_enums(path)` | AST fixtures with current classes, missing classes, non-string values, and reordered members | Path wrapper reads only supplied file |
| README enum parsing | `parse_readme_enums(text)` | Current text plus missing heading/table/chain, malformed rows, duplicates, and explanatory-code cases | None; pure text |
| Enum comparison | `validate_enum_coverage(model_values, documented_values)` | Aligned, missing, stale, duplicate, and GemLevel order cases | None |
| Full orchestration | `generate_all(...)` and CLI `main()` | Isolated subprocess with explicit `--inventory-output`, `--readme`, `--models`, and `--packages-root` paths | Writes only declared output paths; no package import for enum extraction |
| Gate comparison | The exact shell block in §4.5 | Temporary Git repository with tracked-stale and deleted/recreated generated files | Runs Git commands only in the temporary repository |

The existing `tests/integration/test_cli_reference_generation.py` helper must pass an explicit temporary `--inventory-output` after the generator gains its new default output. No test may rely on, modify, or clean up a generated file in the real repository as a side effect.

## 7. Failure modes

| Failure | Behavior | Remediation shown |
|---|---|---|
| Manifest missing, invalid JSON, unsupported `skills` shape, or path escape | Generator exits non-zero before writing either output | Error names the manifest and explains the valid root contract |
| Resolved skill root missing | Generator exits non-zero | Error names the package and expected root path |
| Child directory lacks `SKILL.md` | Directory is ignored by definition; it is not a discoverable skill | Add `SKILL.md` if the directory is intended to be a skill |
| Inventory is stale or recreated as untracked | Gate exits non-zero | `::error::` annotation gives the regeneration command and lists tracked/untracked files |
| README Note Model section cannot be parsed | Generator exits non-zero before writing outputs | Error names `README.md` and the missing/malformed section component |
| Model enum value missing from README | Enum check exits non-zero | Error names enum/value and says to add it to the Note Model section |
| README contains stale or duplicate value | Enum check exits non-zero | Error names enum/value and says to remove or correct it |
| `models.py` class/member is unsupported | Generator exits non-zero | Error names `jfox/models.py`, class, and expected string-literal shape |
| CLI description catalog is invalid | Existing description-specific remediation remains | Error points to `docs/cli-descriptions.yaml`, not README or plugin files |
| Output path cannot be written | Generator exits non-zero | Error names the output path and permission/parent-directory problem |

New inventory and enum errors must not be caught by the current generic `ValueError` handler that always tells users to update `docs/cli-descriptions.yaml`. The CLI wrapper must preserve source-specific remediation for each check.

## 8. Compatibility and maintenance

- Support Python `>=3.10`; use the existing standard library and PyYAML/JSON dependencies only. No new runtime dependency is allowed.
- Keep the CLI command `uv run python scripts/generate_docs.py` unchanged for maintainers and CI.
- Extract enum values from AST rather than importing `jfox`, so documentation checks do not trigger package lifecycle registration, embedding, daemon, or knowledge-base operations.
- Keep all generated prose English. Structural names and paths may reflect repository identifiers, including the `jfox-` Kimi skill prefix.
- Use repository-relative POSIX paths and deterministic package/skill ordering on every platform.
- Keep generated inventory outside the curated README body; README contains only the link and maintenance prose.
- The gate's explicit generated-file list must be updated whenever a new generated output is added.
- `packages/**` path coverage is maintained in both event blocks. The CLAUDE.md path-list sync remains a follow-up obligation.

## 9. Implementation deliverables

- Modify: `scripts/generate_docs.py` (CLI options, orchestration, context-specific error handling, and shared generated-file writing).
- Create: `scripts/plugin_inventory.py` (manifest resolution, discovery, normalized entries, rendering).
- Create: `scripts/enum_coverage.py` (AST extraction, README parsing, comparison errors).
- Create: `docs/plugin-inventory.md` (generated artifact).
- Modify: `.github/workflows/integration-test.yml` (add `packages/**` to both trigger blocks and extend the gate comparison with the targeted untracked-file check).
- Modify: `README.md` (one Agent Integrations link line).
- Create: `tests/unit/test_plugin_inventory.py`.
- Create: `tests/unit/test_enum_coverage.py`.
- Create: `tests/integration/test_plugin_inventory.py`.
- Modify: `tests/integration/test_cli_reference_generation.py` so all generator outputs use isolated temporary paths.
- Create: the implementation plan under `docs/superpowers/plans/`.
