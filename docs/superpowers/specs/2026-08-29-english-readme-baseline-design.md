# Design Spec: English Dual-Audience README Baseline

- **Issue:** [#457](https://github.com/zhuxixi/jfox/issues/457)
- **Parent issue:** [#456](https://github.com/zhuxixi/jfox/issues/456)
- **Repository:** `zhuxixi/jfox`
- **Status:** Draft for user review
- **Scope:** Root `README.md` only

## 1. Problem

The current README is useful but has accumulated documentation drift and presents the project primarily through implementation details. It also mixes a user-facing English landing page with incomplete manually maintained command and plugin inventories.

The most visible examples are:

- It says that JFox has three note types, while the current model has six.
- It does not describe several current product workflows, including fragments, gem synthesis, candidate review, and bookshelf assets.
- Its command tables do not cover all current command groups.
- Its architecture map lists a subset of implementation modules and is therefore likely to become stale.
- Its plugin section contains hard-coded skill counts that no longer match the repository.
- Its “all offline” wording can be read as applying to optional auto-summary, which sends session content to Anthropic through `claude -p`.

This phase establishes an accurate human-curated README baseline. It does not attempt to solve automated documentation generation or drift detection.

## 2. Desired outcome

`README.md` becomes an English, local-first, dual-audience project entry point that:

1. explains JFox in terms of user goals before implementation details;
2. lets a first-time user install JFox and complete a minimal note workflow;
3. explains the major current workflows without claiming that the README is an exhaustive command reference;
4. gives technical readers concise architecture, integration, and contribution entry points;
5. documents the current note model and knowledge-gem lifecycle accurately;
6. establishes a clear boundary between curated narrative and future generated facts.

## 3. Audience and reading order

The README has two audiences, served in sequence rather than mixed line by line.

### Primary audience: first-time and knowledge-management users

They should be able to answer these questions quickly:

- What is JFox?
- Why would I use it instead of keeping disconnected Markdown files?
- Is my data local and under my control?
- How do I install it?
- What is the shortest useful workflow?

### Secondary audience: CLI users, developers, and contributors

They should be able to locate:

- common command examples;
- the note and gem data model;
- a conceptual architecture overview;
- agent integration entry points;
- development and verification commands;
- detailed installation and troubleshooting documents.

The README should not attempt to serve exhaustive CLI API documentation. Users needing a complete command surface should be directed to `jfox --help` and `jfox <command> --help` until the later generated CLI reference phase exists.

## 4. Language and terminology policy

### 4.1 Language scope

All user-facing prose in the root README must be English. This includes headings, feature descriptions, workflow explanations, command descriptions written outside code blocks, notes, warnings, and contribution instructions.

This phase does not translate:

- `AGENTS.md`;
- `CLAUDE.md`;
- historical specifications and implementation plans;
- runtime Typer help text in `jfox/cli.py` or its subcommand modules;
- unrelated package or skill documents.

The implementation must not change runtime CLI help text as part of this README task.

### 4.2 Preferred terms

Use these terms consistently:

| Concept | Preferred English wording | Notes |
|---|---|---|
| 本地优先 | **local-first** | Do not claim that every optional path is offline. |
| 知识库 | **knowledge base** | Define `KB` only if an abbreviation is needed later. |
| 闪念笔记 | **fleeting note** | Keep the enum value `fleeting` in code formatting. |
| 文献笔记 | **literature note** | Keep the enum value `literature` in code formatting. |
| 永久笔记 | **permanent note** | Keep the enum value `permanent` in code formatting. |
| 会话笔记 | **session note** | Explain that it records an AI-agent session. |
| 候选笔记 | **candidate note** | Explain that it requires human review before promotion. |
| 结构笔记 | **structure note (MOC)** | Explain MOC as a Map of Content on first use. |
| 知识宝石 | **knowledge gem** | Use “gem synthesis” for the process. |
| 碎片采集 | **session fragment capture** | Avoid presenting raw fragments as trusted knowledge. |
| 过审/晋升 | **candidate review and promotion** | Promotion means candidate → permanent. |
| 嵌入模型 | **embedding model** | Explain embeddings once for non-specialists. |
| 守护进程 | **embedding daemon** | A background service that keeps the model available. |
| 书架 | **bookshelf** | Describe it as local book assets and metadata. |

### 4.3 Product positioning

Use the following positioning as the default direction:

> **JFox is a local-first Zettelkasten knowledge management CLI.**

The README may describe AI-assisted refinement as an important advanced workflow, but JFox should not be repositioned as an AI-only product. The stable core remains a local Markdown knowledge base with links, indexes, search, and graph navigation.

## 5. Information architecture

The following section order is the implementation target. Headings may be adjusted slightly for readability, but the user journey and curated/generated boundary must remain intact.

### 5.1 Header and value proposition

Keep a compact header containing:

- project name;
- license, Python, and platform badges where each badge is accurate and useful;
- a one-line English value proposition;
- a short paragraph explaining Markdown files, wiki links, local indexes, search, and graph navigation.

Do not add decorative badges whose values are not backed by a repository or CI source.

### 5.2 `What is JFox?`

Explain the product in user terms:

- JFox uses the Zettelkasten method;
- notes remain plain Markdown files on disk;
- links use `[[wiki links]]`;
- indexes support keyword and semantic retrieval;
- graph and MOC features help users navigate connected knowledge;
- the design is local-first rather than a hosted knowledge service.

Keep this section short enough that a new reader can understand it without knowing Python, ChromaDB, BM25, or NetworkX.

### 5.3 `What you can do`

Use benefit-oriented bullets rather than a source-file inventory. Cover the following capabilities:

1. Capture and refine notes.
2. Connect notes with bidirectional links and backlinks.
3. Search by keywords and meaning through hybrid search.
4. Explore relationships through graph analysis and MOCs.
5. Refine session material through fragments, gem synthesis, candidate review, and promotion.
6. Manage books as local assets through the bookshelf.
7. Separate work, personal, and research knowledge bases.
8. Run optional background services, backups, and session auto-summary.

Each bullet should state the user benefit first and use implementation terms only when they clarify how the benefit works.

### 5.4 `Features`

Retain a concise feature summary for scanability. It should not duplicate every detail from `What you can do` or become a full module catalog.

At minimum, it must accurately represent:

- Markdown-first note storage;
- six note types;
- bidirectional links and backlinks;
- hybrid search;
- graph analysis and MOC structure notes;
- session fragments and candidate knowledge gems;
- bookshelf asset management;
- multiple knowledge bases;
- optional daemon, backup, and auto-summary capabilities.

The exact presentation may combine this section with `What you can do` if the result is less repetitive. The final README should have one clear feature overview, not two near-duplicate lists.

### 5.5 `Quick Start`

Make the shortest complete path prominent:

```text
install → initialize → create a note → create a link → search
```

The examples should use commands verified against the current CLI. Keep the examples minimal and avoid options that are not needed to demonstrate the workflow.

The section should include:

- recommended installation using the repository's current preferred method;
- initialization;
- creation of a permanent note;
- a second note containing a `[[wiki link]]`;
- hybrid search;
- one optional graph/query example if it remains concise.

Link to `docs/installation.md` for extended installation, upgrade, uninstall, PATH, and model-download details. Do not duplicate the full installation guide.

### 5.6 `Core Workflows`

This is the main explanatory section. It should use user goals and explain why each workflow exists.

#### Capture and connect notes

Explain fleeting, literature, and permanent notes at a practical level. Show how a `[[Note Title]]` link is resolved and how backlinks are maintained. Avoid repeating the complete frontmatter specification here.

#### Search and navigate knowledge

Explain the difference between keyword search and semantic search in one sentence each, then describe hybrid search, graph traversal, backlinks, and MOC navigation. Avoid promising a specific latency or ranking behavior unless it is a stable documented contract.

#### Refine knowledge with the gem pipeline

Introduce the pipeline explicitly:

```text
session fragments
    → gem synthesis
    → candidate notes
    → human review
    → permanent notes
```

State clearly that candidate notes are reviewable proposals, not automatically trusted permanent knowledge. Explain that the current L3 synthesis output is a `flawed` candidate gem when that detail is useful.

#### Organize and preserve knowledge

Briefly introduce archive/unarchive, multiple knowledge bases, backup/restore, the embedding daemon, and optional auto-summary. Link to a more detailed document only when one exists; do not invent a future documentation path in this phase.

#### Manage books as local assets

Explain that the bookshelf manages PDFs, extracted bundles, and JFox metadata as file assets, and that these assets are not automatically part of the note index. This distinction prevents users from assuming that adding a book automatically makes its contents searchable through note search.

### 5.7 `Note Model`

Document the six current `NoteType` values:

| Value | Meaning |
|---|---|
| `fleeting` | A quick capture or temporary idea. |
| `literature` | Notes derived from reading or source material. |
| `permanent` | Refined knowledge intended to remain useful. |
| `session` | A record of an AI-agent session. |
| `candidate` | A synthesized proposal awaiting human review. |
| `structure` | A Map of Content (MOC) used to organize related notes. |

Document the current `GemLevel` lifecycle:

```text
chipped → flawed → normal → flawless → perfect
```

Explain the important boundary:

- `chipped` represents raw fragments and is not a note file state;
- `flawed` is the current L3 candidate output;
- later levels represent increasingly mature knowledge;
- promotion to `permanent` is a review decision, not an automatic trust guarantee.

The exact maturity semantics must be checked against `jfox/models.py` during implementation.

### 5.8 `Common Commands`

Keep this section intentionally curated and non-exhaustive. Group a small number of representative commands by user task:

- initialize and create notes;
- list, show, edit, archive, and delete notes;
- search, query, refs, graph, and MOC navigation;
- candidate review and bookshelf operations;
- index, knowledge-base, daemon, backup, and auto-summary operations.

Use examples and short descriptions instead of a complete hand-maintained option matrix. Include a clear note:

> For the complete current command and option list, run `jfox --help` or `jfox <command> --help`. An exhaustive generated CLI reference is planned separately.

Do not link to `docs/cli-reference.md` during this phase because that file does not exist yet.

### 5.9 `Architecture`

Replace the current implementation-heavy module map with a conceptual architecture. The architecture should explain stable boundaries, not count files or list every package.

The conceptual model should include:

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

A Mermaid diagram is acceptable if it remains conceptual and does not encode a fragile exhaustive module list. If a diagram cannot remain clear without implementation-file details, prefer a short prose architecture section over a misleading diagram.

Do not retain claims such as `cli.py` line counts in the README.

### 5.10 `Agent Integrations`

Describe the supported integration surfaces:

- Claude Code plugin;
- Kimi Code plugin;
- pi Agent Skills.

Describe capabilities and link to the relevant package or skills README. Do not include hard-coded skill counts. Do not claim that every platform has identical features unless the repository confirms it.

### 5.11 `Installation and Development`

Keep a concise installation and contribution entry point:

- `uv` installation/development setup;
- pip compatibility if still supported;
- Python requirement;
- basic verification commands;
- fast test command for contributors;
- links to installation and troubleshooting documents.

The phase should not rewrite `docs/installation.md` unless implementation discovers a direct README link contradiction that must be corrected to keep the landing page usable. Such a change must be called out separately in the PR.

### 5.12 `Privacy`

Use precise local-first wording:

- notes and indexes are stored locally by default;
- core note, search, and graph operations run locally;
- embedding models may need to be downloaded on first use;
- optional auto-summary invokes `claude -p` and sends session text to Anthropic;
- users choose whether to enable auto-summary.

Do not use an unqualified “all offline” claim.

### 5.13 `License` and `Acknowledgments`

Keep the existing license and technology acknowledgments, translated or edited into consistent English prose where needed. Preserve valid project and dependency links.

## 6. Curated versus generated boundary

Phase 1 establishes the following boundary for later automation:

| README content | Phase 1 treatment | Future treatment |
|---|---|---|
| Positioning and product narrative | Human-curated | Human review; AI may suggest edits |
| User workflows and recommendations | Human-curated | Human review |
| Conceptual architecture | Human-curated | Optional targeted checks, not blind generation |
| NoteType and GemLevel explanation | Human-curated and verified against code | Deterministic coverage check |
| Common command examples | Human-curated and smoke-checked | Existence/option checks |
| Exhaustive CLI commands/options | Kept out of README | Generate `docs/cli-reference.md` from Typer |
| Plugin inventory/counts | No hard-coded counts | Validate against directories/manifests |
| Package metadata and dependencies | Mention only stable user-relevant facts | Validate against `pyproject.toml` |

The README must not contain markers that imply it is fully generated. Only future generated files should be marked as generated.

## 7. Files and implementation boundaries

### Expected file changes

- Primary: `README.md`.
- Optional: a README link target only if a direct contradiction is discovered in an existing user-facing document; any such change requires explicit explanation in the implementation PR.

### Explicitly unchanged

- `jfox/cli.py` and all runtime help text;
- `jfox/models.py` and application behavior;
- `.github/workflows/*`;
- `scripts/*`;
- `docs/cli-reference.md` (not created in this phase);
- `AGENTS.md` and `CLAUDE.md`;
- package skill files and plugin manifests unless the README cannot accurately link to their current documented entry point.

## 8. Verification plan

The implementation PR must provide fresh evidence for each item below.

### Markdown quality

```bash
npx --yes markdownlint-cli2 README.md
```

### Internal links

Check every relative link in `README.md` against the repository working tree. At minimum, verify the existing targets:

- `LICENSE`;
- `pyproject.toml`;
- `docs/installation.md`;
- `docs/troubleshooting.md`;
- `packages/kimi-plugin/README.md`;
- any other target introduced by the rewrite.

### CLI example sanity

Run help for the commands used in the README examples and confirm that no runtime CLI help text was changed:

```bash
uv run jfox --help
uv run jfox init --help
uv run jfox add --help
uv run jfox search --help
```

If the README uses additional command examples, run their corresponding help commands as well.

### Model facts

Compare the documented NoteType and GemLevel values with `jfox/models.py`. The README must contain all six NoteType values and all five GemLevel values, with no claim that there are only three note types.

### Drift-prone wording

Search the final README for and review these classes of claims:

- hard-coded skill counts;
- `cli.py` line counts;
- exhaustive command claims;
- unqualified “all offline” or equivalent wording;
- stale model names, dimensions, or installation methods.

### Diff hygiene

```bash
git diff --check
git status --short
```

The PR should be limited to the README baseline unless an explicitly justified link correction is required.

## 9. Risks and mitigations

| Risk | Mitigation |
|---|---|
| README becomes too long again | Prioritize user journey; keep exhaustive CLI details out. |
| English rewrite loses project-specific meaning | Preserve code identifiers and define terms on first use. |
| Product narrative overstates AI automation | Present candidates as reviewable proposals and keep local-first core primary. |
| Privacy wording is misleading | Separate local core behavior from optional `claude -p` transmission. |
| Architecture diagram drifts again | Make it conceptual and avoid line counts or exhaustive file lists. |
| Phase 1 accidentally expands into automation | Keep generators, CI, and bot PRs as later issues under #456. |
| Runtime users expect English CLI help | State explicitly that CLI help remains unchanged and defer localization. |

## 10. Acceptance criteria

- [ ] `README.md` is fully English in user-facing prose.
- [ ] The README presents JFox as a local-first Zettelkasten CLI.
- [ ] A first-time user can understand and follow the minimal install → init → add → link → search workflow.
- [ ] The README covers the current major capabilities: notes, links, hybrid search, graph/MOC, gem refinement, bookshelf, multiple KBs, daemon, backup, and auto-summary.
- [ ] All six NoteType values are documented accurately.
- [ ] All five GemLevel values and their lifecycle are documented accurately.
- [ ] Candidate notes are described as requiring human review before promotion.
- [ ] Bookshelf assets are clearly distinguished from indexed notes.
- [ ] The command section is curated and explicitly non-exhaustive.
- [ ] The README does not contain stale hard-coded plugin counts or implementation line counts.
- [ ] The README does not claim that every operation is offline.
- [ ] The conceptual architecture does not attempt to enumerate all implementation modules.
- [ ] The README does not require runtime CLI help changes.
- [ ] Internal links resolve.
- [ ] `npx --yes markdownlint-cli2 README.md` passes.
- [ ] The implementation PR includes the curated/generated boundary for future Phase 2 work.

## 11. Follow-up

After this spec is accepted and Phase 1 is implemented, create or update the next child issue under #456 for deterministic CLI reference generation. That issue should use the stable README boundary established here and should not reintroduce exhaustive command tables into the README.
