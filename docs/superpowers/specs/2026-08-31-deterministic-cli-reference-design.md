# Design Spec: Deterministic English CLI Reference

- **Issue:** [#472](https://github.com/zhuxixi/jfox/issues/472)
- **Parent issue:** [#456](https://github.com/zhuxixi/jfox/issues/456)
- **Repository:** `zhuxixi/jfox`
- **Status:** Approved for implementation
- **Phase:** 2A — deterministic CLI reference generation

## 1. Problem

The root README is now a curated English landing page, but JFox still has no exhaustive English command reference. The current CLI surface is defined by a Typer application with nested command groups, arguments, options, aliases, defaults, and runtime help text that is primarily Chinese.

Using Typer's built-in Markdown generator directly can enumerate the command surface, but it would copy Chinese runtime descriptions into a public English reference. Maintaining a complete English command document by hand would recreate the documentation drift that Phase 2A is intended to prevent.

This phase therefore needs two separate sources with a strict boundary:

- the Typer application is authoritative for command structure and syntax;
- a small English metadata layer is authoritative only for human-readable command descriptions.

## 2. Desired outcome

Add a deterministic local generation workflow that produces `docs/cli-reference.md` in English and satisfies all of the following:

1. Every command path exposed by the real Typer application appears in the reference.
2. Every argument and option is extracted from the real command definitions rather than manually copied into metadata.
3. Command descriptions are English without changing runtime CLI help text.
4. The same source tree and metadata produce byte-identical output.
5. The generator can run without a knowledge base, embedding model, daemon, network service, or confirmation prompt.
6. Generation and its tests cannot write the user's real `~/.zk_config.json` or alter the user's default knowledge base.
7. The root README links to the exhaustive reference without regaining a hand-maintained exhaustive command table.

## 3. Scope

### In scope

- `scripts/generate_docs.py` as the stable local entry point.
- `docs/cli-descriptions.yaml` as the human-maintained English command-description catalog.
- `docs/cli-reference.md` as a generated, clearly marked Markdown file.
- Extraction and normalization of the real Typer/Click command tree.
- Deterministic Markdown rendering of command paths, usage, arguments, options, aliases, types, required flags, defaults, and choices where available.
- Metadata completeness validation for command descriptions.
- Unit, integration, and automated end-to-end tests for extraction, normalization, metadata validation, deterministic rendering, real command coverage, and safe output generation.
- A minimal root README link to the generated reference.
- Documentation for maintainers showing the exact regeneration command.

### Out of scope

- Translating or changing runtime Typer help text in `jfox/cli.py` or subcommand modules.
- Changing CLI behavior, command names, arguments, options, aliases, or defaults.
- CI drift gates; these belong to the later Phase 3 issue.
- Automatic documentation PRs.
- AI-assisted documentation generation or translation.
- Plugin inventory checks.
- NoteType or GemLevel coverage checks.
- A full documentation website.
- Rewriting the README's product narrative or restoring exhaustive command tables.

## 4. Language decision

Phase 2A uses the documentation-metadata strategy:

- Runtime help remains unchanged and continues to serve existing Chinese-speaking CLI users.
- `docs/cli-descriptions.yaml` contains concise English descriptions keyed by complete command path.
- The generator obtains command paths and all syntax facts from the Typer application.
- The generated reference uses English headings, labels, descriptions, and explanatory notes.
- It does not copy Chinese runtime `help` or docstring text into the generated public reference.

The metadata catalog contains prose only. It must not define or override:

- whether a command exists;
- parent/child command relationships;
- argument or option names;
- option flags or aliases;
- parameter types;
- required status;
- default values;
- choices;
- command ordering.

Those facts are always derived from the live Typer/Click command tree.

## 5. User-facing outputs

### 5.1 Generator command

The primary documented command is:

```bash
uv run python scripts/generate_docs.py
```

The default output is:

```text
docs/cli-reference.md
```

For tests and local inspection, the generator accepts an explicit output path and, if useful, an explicit descriptions path without changing the default behavior:

```bash
uv run python scripts/generate_docs.py \
  --output /tmp/jfox-cli-reference.md \
  --descriptions docs/cli-descriptions.yaml
```

The generator must resolve the repository root from its own location, not from the caller's current working directory, so the command remains reliable when invoked from the repository root. Relative user-supplied paths are interpreted relative to the repository root.

### 5.2 Description catalog

`docs/cli-descriptions.yaml` has this shape:

```yaml
commands:
  "jfox":
    description: "Manage a local-first Zettelkasten knowledge base."
  "jfox init":
    description: "Initialize and register a knowledge base."
  "jfox add":
    description: "Create a note and update its local indexes and links."
  "jfox search":
    description: "Search notes by keyword, semantic meaning, or both."
  "jfox bookshelf":
    description: "Manage local book assets, extracted bundles, and metadata."
  "jfox bookshelf add":
    description: "Add a book folder to the local bookshelf."
```

The implementation must include entries for every command path extracted from the current application, including the current nested command groups and their children. The catalog may use multiline YAML strings for longer explanations, but every description must remain concise enough for a command reference.

The catalog must not contain parameter definitions. Parameter-level syntax is rendered from Typer/Click. Parameter descriptions are intentionally not copied from Chinese runtime help in this phase; the generated table communicates the structural contract through English column labels and the live parameter facts.

### 5.3 Generated reference

`docs/cli-reference.md` begins with a generated-file marker that includes the exact regeneration command:

```markdown
<!--
This file is generated by scripts/generate_docs.py.
Do not edit manually.

Regenerate with:
uv run python scripts/generate_docs.py
-->
```

The generated document contains:

1. A title and short explanation of the source-of-truth boundary.
2. A root usage section for `jfox`.
3. One section for each command path, including nested commands.
4. A usage block for each command.
5. A parameter table with English columns for parameter name, syntax, type, required status, default, and choices when available.
6. The command's English description from the metadata catalog.
7. A note directing users to the installed CLI's `--help` for runtime help and behavior details.

A representative section is:

````markdown
## `jfox search`

Search notes by keyword, semantic meaning, or both.

**Usage**:

```console
$ jfox search [OPTIONS] QUERY
```

| Parameter | Syntax | Type | Required | Default |
|---|---|---|---|---|
| `query` | `QUERY` | TEXT | yes | — |
| `top` | `--top, -n` | INTEGER | no | `5` |
| `search_mode` | `--mode, -m` | TEXT | no | `hybrid` |
```
````

The exact parameter rows are generated from the current application and may contain additional structural columns when Typer/Click exposes choices or multiplicity.

## 6. Architecture and data flow

The generation flow is:

```text
jfox.cli:app
    ↓
Typer → Click command tree
    ↓
command-path and parameter normalization
    ↓
English description catalog validation
    ↓
deterministic Markdown rendering
    ↓
docs/cli-reference.md
```

The implementation is divided into independently testable boundaries:

### 6.1 Command-tree extraction

Input: the Typer application object.

Output: a normalized collection of command records. Each record contains a complete command path, command kind, English-description lookup key, usage-relevant metadata, and normalized parameters. Extraction recursively traverses Click groups and must include the root command and all nested commands.

Extraction does not read or write knowledge-base data. It does not invoke command callbacks.

### 6.2 Parameter normalization

Input: a Click `Argument` or `Option` object.

Output: a serializable normalized parameter record containing:

- parameter name;
- argument or option kind;
- option flags and aliases;
- value type;
- required status;
- default value;
- choices, if available;
- multiple-value status, if available;
- flag/boolean status.

Formatting quirks of Click objects must be resolved here rather than inside the Markdown renderer. This keeps the renderer independent from Typer/Click internals.

### 6.3 Description catalog loading and validation

Input: a YAML catalog and the extracted command paths.

Validation rules:

- every extracted command path has exactly one non-empty English description;
- every catalog key maps to an extracted command path;
- duplicate keys are rejected by the YAML loader or explicit validation;
- unknown keys are rejected;
- empty or non-string descriptions are rejected;
- parameter names and options are not accepted as catalog schema fields.

Output: an immutable or otherwise read-only description mapping used by rendering.

### 6.4 Markdown rendering

Input: normalized command records and validated descriptions.

Output: a complete UTF-8 Markdown string.

Rendering must be pure with respect to its inputs. It must not inspect the filesystem, environment, global configuration, current time, machine details, or command callbacks. It fixes all formatting conventions in one renderer:

- stable command ordering by normalized command path;
- stable parameter ordering from the normalized command record;
- stable blank lines and headings;
- stable representation of absent values as `—`;
- stable representation of defaults and choices;
- Unix newline output;
- no timestamps, absolute paths, ANSI escape sequences, or Chinese runtime help text.

### 6.5 Filesystem output

Input: rendered Markdown and an output path.

Output: the generated reference file.

Filesystem writing is kept outside extraction, validation, and rendering. The writer creates parent directories only when necessary, writes UTF-8 text with deterministic newlines, and does not invoke JFox commands or mutate any knowledge-base configuration.

## 7. Determinism and safety

### 7.1 Determinism

For a fixed source tree, Python/Typer/Click environment, description catalog, and generator version:

```text
render(extract(app), descriptions)
    == render(extract(app), descriptions)
```

The generated file must be byte-identical across two consecutive runs. The output must not include:

- current date or time;
- current working directory;
- absolute file paths;
- platform-specific path separators;
- terminal color codes;
- process IDs;
- unordered set/dictionary output;
- runtime help text whose formatting depends on terminal width.

### 7.2 Configuration safety

The generator must never run JFox commands. Its real-app extraction path only imports and introspects the Typer application. Tests run with `ZK_CONFIG_PATH` and `HOME`/`USERPROFILE` redirected to a temporary directory as a defense-in-depth measure.

The test suite must verify that the real user's `~/.zk_config.json` hash and default entry remain unchanged before and after the generator subprocess test. Tests must not use the user's default KB as a fixture and must not create artifacts in the repository root outside declared test output paths.

## 8. README integration

Phase 2A makes a minimal update to the curated root README:

- Replace the statement that an exhaustive generated reference is merely planned with a link to [`docs/cli-reference.md`](cli-reference.md).
- Keep the existing curated command overview and user workflows.
- Do not copy generated command sections into the README.
- Do not add a second exhaustive command table.

The README remains a human-curated product document. The generated file is the exhaustive CLI fact document.

## 9. Acceptance matrix

All acceptance items in this phase are suitable for automation; no external service or subjective user observation is required.

| ID | Feature point | Acceptance method | Verification | Pass criteria |
|---|---|---|---|---|
| A1 | Normalize a command tree | Automated (`unit`) | `uv run pytest tests/unit/test_generate_docs.py -k command_tree` | Synthetic Typer/Click trees produce complete, correct command paths including nested groups. |
| A2 | Normalize parameters | Automated (`unit`) | `uv run pytest tests/unit/test_generate_docs.py -k parameter` | Arguments, flags, aliases, types, defaults, required status, choices, and boolean/multiple markers normalize correctly. |
| A3 | Validate English descriptions | Automated (`unit`) | `uv run pytest tests/unit/test_generate_docs.py -k description` | Missing, unknown, empty, duplicate, and malformed catalog entries fail with actionable errors; complete catalog passes. |
| A4 | Render stable English Markdown | Automated (`unit`) | `uv run pytest tests/unit/test_generate_docs.py -k render` | Rendering is byte-stable, contains the generated marker and English labels, and contains no runtime Chinese help, timestamp, absolute path, or ANSI code. |
| A5 | Cover the real JFox CLI | Automated (`integration`) | `uv run pytest tests/integration/test_cli_reference_generation.py -k coverage` | The real app extracts every current top-level and nested command, including `model`, `auto-summary`, `backup`, `fragments`, `candidates`, `gem-synth`, `bookshelf`, and `moc`. |
| A6 | Generate the reference through the public entry point | Automated (`automated E2E`) | `uv run pytest tests/integration/test_cli_reference_generation.py -k subprocess` | The generator exits 0, writes the requested output, and includes representative nested command sections without requiring a KB, daemon, model, network, or prompt. |
| A7 | Prove repeatability | Automated (`automated E2E`) | `uv run pytest tests/integration/test_cli_reference_generation.py -k deterministic` | Two generator runs produce byte-identical files. |
| A8 | Prove configuration safety | Automated (`automated E2E`) | `uv run pytest tests/integration/test_cli_reference_generation.py -k config_safety` | The real `~/.zk_config.json` hash and default KB are unchanged; no undeclared repository-root artifacts are created. |
| A9 | Verify generated and curated Markdown | Automated (`static`) | `npx --yes markdownlint-cli2 README.md docs/cli-reference.md` plus relative-link check | Both Markdown files lint successfully; README's generated-reference link resolves. |
| A10 | Preserve the curated/generated boundary | Automated (`static`) | `uv run pytest tests/integration/test_cli_reference_generation.py -k readme_boundary` | README contains a minimal reference link and no exhaustive generated command sections; `docs/cli-reference.md` contains the generated marker. |

## 10. Testability decomposition

The following test boundaries are mandatory, not optional implementation advice:

| Boundary | Production unit | Test strategy | Side effects allowed |
|---|---|---|---|
| Command extraction | `extract_commands(click_root)` | Synthetic nested command tree and real-app integration coverage | None; no callback execution |
| Parameter normalization | `normalize_parameter(click_parameter)` | One test per argument, option, alias, boolean flag, default, choice, and multiple-value case | None |
| Catalog parsing | `load_descriptions(path)` | Valid YAML, malformed YAML, duplicate/empty/non-string values | Reads only the supplied catalog |
| Catalog validation | `validate_descriptions(command_paths, descriptions)` | Missing and unknown keys plus complete catalog | None |
| Markdown rendering | `render_reference(commands, descriptions)` | Snapshot-like structural assertions and two-render equality | None |
| Output writing | `write_reference(path, text)` | Temporary directory write and parent creation | Writes only supplied temporary/output path |
| Public generation orchestration | `generate_reference(...)` or equivalent | Subprocess test with isolated environment and explicit output | May import `jfox.cli`; must not invoke commands or write global config |

The renderer must not be coupled to Click objects, and the writer must not be coupled to JFox configuration. This separation ensures that the most important invariants can be proved with low-cost unit tests before the real-app subprocess test.

## 11. Error handling

The generator fails closed with a non-zero exit code when:

- the description catalog cannot be read or parsed;
- a command has no English description;
- the catalog contains an unknown command path;
- a description is empty or not a string;
- command extraction produces an unsupported parameter shape;
- the output cannot be written.

Errors must name the relevant command path or file path and explain the remediation. A missing description error must tell the maintainer to add the command path to `docs/cli-descriptions.yaml`; it must not silently fall back to Chinese runtime help or a generic untranslated string.

The generator must not catch and hide exceptions from extraction or validation. The CLI wrapper may format expected user-facing errors, but the underlying functions must remain testable and preserve the failure cause.

## 12. Compatibility and maintenance

- Use Python features compatible with the repository's `requires-python = ">=3.10"`.
- Reuse the existing PyYAML dependency; do not add a new runtime dependency solely for this generator.
- Keep the generator compatible with the Typer version resolved by the repository lockfile.
- Do not import or execute the embedding backend, daemon, or knowledge-base operations during extraction.
- Mark `docs/cli-reference.md` as generated so future contributors do not edit it manually.
- Document the regeneration command in the generated marker and in the issue/PR description.
- The later CI phase should run the generator and fail on a diff; this phase only makes that check possible.

## 13. Implementation deliverables

Expected implementation files:

- Create: `scripts/generate_docs.py`.
- Create: `docs/cli-descriptions.yaml`.
- Create: `docs/cli-reference.md`.
- Create: `tests/unit/test_generate_docs.py`.
- Create: `tests/integration/test_cli_reference_generation.py`.
- Modify: `README.md` for the minimal reference link only.
- Create: the implementation plan under `docs/superpowers/plans/`.

The exact helper names may vary only if the implementation preserves the testability boundaries and acceptance IDs above.
