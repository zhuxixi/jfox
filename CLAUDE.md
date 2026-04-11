# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

JFox is a local-first personal knowledge management CLI tool based on the Zettelkasten method. It supports bidirectional links (`[[note title]]`), semantic search (sentence-transformers + ChromaDB), knowledge graph analysis (NetworkX), and multi-knowledge-base management. Pure CPU, no GPU required.

- **Language**: Python >= 3.10
- **CLI entry point**: `jfox` command → `jfox.cli:app` (Typer)
- **Project docs and comments are primarily in Chinese (中文)**

## Development Commands

```bash
# Install (using uv, recommended)
uv sync --extra dev

# Install (legacy pip fallback)
pip install -e ".[dev]"

# Run tests
uv run pytest tests/ -v                                # All tests
uv run pytest tests/test_core_workflow.py -v           # Single file
uv run pytest tests/ -m "not slow"                     # Exclude slow tests
uv run pytest tests/ -m "not embedding and not slow"   # Fast tests (no model loading)
uv run pytest tests/ -m "integration"                  # Integration tests only
uv run pytest tests/ --keep-data                       # Keep test data for debugging
uv run pytest tests/ --cov=jfox --cov-report=html      # With coverage

# Format and lint
uv run black jfox/ tests/
uv run ruff check jfox/ tests/

# Build
uv build

# Verify CLI
uv run jfox --help
uv run jfox --version
```

Windows full test: `.\run_full_test.ps1` or `.\run_full_test.ps1 -KeepData`

## Architecture

### Core Data Flow

Notes are Markdown files with YAML frontmatter stored under `~/.zettelkasten/<kb-name>/notes/{type}/`. The system has three layers:

1. **Storage** (`note.py`, `models.py`) — CRUD on Markdown files with YAML frontmatter. Note IDs are timestamps (`YYYYMMDDHHMMSS`).
2. **Search Index** (`search_engine.py`) — Hybrid search combining BM25 (`bm25_index.py`) + semantic embeddings (`vector_store.py` + `embedding_backend.py`) via Reciprocal Rank Fusion.
3. **Graph** (`graph.py`) — NetworkX-based graph built from `links`/`backlinks` in frontmatter.

### Key Module Map

| Module | Role |
|--------|------|
| `cli.py` | All CLI commands (~1800 lines). Commands follow pattern: `@app.command()` → `_xxx_impl()` helper for reuse |
| `config.py` | `ZKConfig` + `use_kb()` context manager for multi-KB switching |
| `global_config.py` | `GlobalConfigManager` managing `~/.zk_config.json` |
| `kb_manager.py` | Knowledge base lifecycle (create, rename, remove) |
| `formatters.py` | Output formats: JSON, CSV, YAML, Table, Paths |
| `indexer.py` | File monitoring (watchdog) + incremental indexing |
| `note.py` | Markdown file CRUD with YAML frontmatter |
| `models.py` | `Note` data model with frontmatter serialization |
| `search_engine.py` | `HybridSearchEngine` with `SearchMode` enum, RRF fusion |
| `bm25_index.py` | BM25 keyword search index |
| `embedding_backend.py` | Sentence-transformers embedding backend |
| `vector_store.py` | ChromaDB vector store for semantic search |
| `graph.py` | NetworkX knowledge graph from links/backlinks |
| `template.py` / `template_cli.py` | Jinja2 template system for structured note creation |
| `performance.py` | Batch processing and model caching |

### Note Types

- `fleeting` — Quick capture, filename: `YYYYMMDD-HHMMSS.md`
- `literature` — Reading notes, filename: `YYYYMMDDHHMMSS-{slug}.md`
- `permanent` — Processed knowledge, filename: `YYYYMMDDHHMMSS-{slug}.md`

### Multi-Knowledge Base

- Global config: `~/.zk_config.json`
- Default KB: `~/.zettelkasten/default/`, named KB: `~/.zettelkasten/<name>/`
- Switch at runtime with `--kb` flag or `use_kb()` context manager

## Testing Rules

- **全量/集成测试（~50min）不要自主运行**，让用户手动执行。包括：`uv run pytest tests/ -v`、`uv run pytest tests/ -m "not embedding and not slow"`、`uv run pytest tests/test_core_workflow.py` 等。改完代码后提供命令让用户跑。
- **快速单元测试（几秒内）可以自主运行**。如单个模块的纯逻辑测试，不涉及 embedding 或 ChromaDB 的。

## Conventions

- **Version bump**: 发版时必须同时修改 `pyproject.toml` 和 `jfox/__init__.py` 两处版本号（曾有 #88 遗漏 `__init__.py` 的教训）
- **Line length**: 100 chars (black + ruff configured in `pyproject.toml`)
- **Comments/docs**: Chinese (中文)
- **Adding a CLI command**: Add `@app.command()` in `cli.py`, implement `_xxx_impl()` helper, add `--kb` and `--format json` support
- **Adding a search mode**: Add to `SearchMode` enum in `search_engine.py`, implement in `HybridSearchEngine.search()`, update CLI `--mode` help text
- **Modifying data models**: Update `Note` class in `models.py`, update `to_markdown()`/`from_markdown()`, consider backward compat

## Test Infrastructure

- **Fixtures** (`conftest.py`): `temp_kb` (temp KB path), `cli` (ZKCLI instance), `cli_fast` (ZKCLI with mocked embeddings), `generator` (NoteGenerator), `mock_embedding_backend`
- **Test utils** (`tests/utils/`): `temp_kb.py`, `jfox_cli.py` (CLI wrapper), `note_generator.py`
- **Model caching**: Session-level model cache in conftest.py to avoid 30-60s reload per test
- **Test markers**: `slow`, `performance`, `integration`, `embedding`, `workflow`, `bulk`
- **Run single-process** to avoid ChromaDB/model loading conflicts
- **Test directory reorganization in progress**:
  - `tests/unit/` — Pure logic unit tests (formatters, config, kb_manager, template)
  - `tests/integration/` — Cross-module integration tests (backlinks)
  - `tests/performance/` — Performance benchmarks
  - Root-level `test_*_unit.py` files also exist (partial migration)
- **pytest.ini**: `timeout=120`, `--strict-markers`, `-ra` (show all test summary)

## CI (GitHub Actions)

Four jobs in `.github/workflows/integration-test.yml`:
- **Fast** (PR/push): `not embedding and not slow`, Python 3.11, Ubuntu + Windows
- **Core** (main branch): Core workflow tests with real embeddings, Python 3.10 + 3.12
- **Full** (manual): All tests, all OS, all Python versions
- **Coverage** (after fast): Runs coverage on fast tests, uploads HTML/XML artifacts

## Windows Notes

- `robocopy` flags get misinterpreted by bash — use `cmd.exe /c "robocopy source dest /E"`
- Set `PYTHONUTF8=1` and `chcp 65001` for encoding
- HuggingFace mirror for China: `export HF_ENDPOINT=https://hf-mirror.com`

## Gotchas

- `pytest.ini` `addopts` includes `-v`, so `pytest tests/` already runs verbose — adding `-v` manually is redundant
- Test directory migration is partial: root-level `test_*_unit.py` files duplicate `tests/unit/` tests
