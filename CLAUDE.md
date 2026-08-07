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
| `cli.py` | All CLI commands (~2900 lines). Commands follow pattern: `@app.command()` → `_xxx_impl()` helper for reuse |
| `config.py` | `ZKConfig` + `use_kb()` context manager for multi-KB switching |
| `global_config.py` | `GlobalConfigManager` managing `~/.zk_config.json` |
| `kb_manager.py` | Knowledge base lifecycle (create, rename, remove) |
| `formatters.py` | Output formats: JSON, CSV, YAML, Table, Paths |
| `git_extractor.py` | Git 仓库数据提取器（ingest 功能） |
| `model_downloader.py` | Embedding 模型下载与缓存管理 |
| `note_index.py` | 笔记索引管理（文件名↔ID 映射） |
| `indexer.py` | File monitoring (watchdog) + incremental indexing |
| `note.py` | Markdown file CRUD with YAML frontmatter |
| `models.py` | `Note` data model with frontmatter serialization |
| `search_engine.py` | `HybridSearchEngine` with `SearchMode` enum, RRF fusion |
| `bm25_index.py` | BM25 keyword search index |
| `embedding_backend.py` | Sentence-transformers embedding backend（支持 daemon 代理） |
| `daemon/` | Embedding 模型 HTTP 守护进程 (`server.py`/`client.py`/`process.py`)，`jfox daemon start/stop/status` |
| `fragment/` | 碎片采集：detector 分类 + store SQLite(WAL) + service 编排 |
| `bookshelf/` | 好书资产管理：store 文件夹 CRUD + meta jfox 自有元数据（wrap scan2book manifest）+ cli sub-app；纯文件管理不进索引 |
| `gem_synth/` | L3 宝石合成：daemon 循环围绕锚点用 transcript + 永久笔记基准合成 candidate 笔记；存盘前 `dedup.py` 正文余弦查重，命中 candidate 时 `synthesizer.py` 增量合并（提取 delta 补进已有草稿，#309；permanent 仍跳过）；`lifecycle.py` 订阅 note 的 delete/archive/promote/reject 事件同步 dedup 表 |
| `auto_summary/` | 自动总结子系统：daemon 内扫描 `~/.claude/projects/` 已结束的 Claude Code session，经 `claude -p` 生成摘要写入 `session` 笔记；CLI `jfox auto-summary run/scan/status/enable/disable`，ledger 去重 + schedule time window |
| `backup/` | KB 滚动备份/恢复：`manager.py` BackupManager（tar.gz+sha256 清单+滚动轮转+可逆 restore）+ daemon `loop.py` 定时备份（镜像 auto-summary，quiesce 标志让 gem_synth/auto_summary 跳过写 tick）+ `jfox backup run/enable/disable/status/list/verify/restore`；默认关，opt-in |
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

- **Version bump**: 发版时必须同时修改 `pyproject.toml`、`jfox/__init__.py` 和 `uv.lock` 三处版本号。先改前两个文件，再跑 `uv lock` 更新 lock 文件（曾有 #88 遗漏 `__init__.py` 的教训）
- **Line length**: 100 chars (black + ruff configured in `pyproject.toml`)
- **Comments/docs**: Chinese (中文)
- **Adding a CLI command**: Add `@app.command()` in `cli.py`, implement `_xxx_impl()` helper, add `--kb` and `--format json` support
- **Adding a search mode**: Add to `SearchMode` enum in `search_engine.py`, implement in `HybridSearchEngine.search()`, update CLI `--mode` help text
- **Adding a daemon-scheduled loop**: 镜像 `auto_summary/`（与 gem_synth/backup 同构）——`loop.py`（`_tick_once` + async `X_loop(stop_event)`）+ `daemon/server.py` lifespan 内 `_maybe_start/stop_X` 接线 + `GlobalConfigManager` opt-in（每 tick `reload()` 即时生效）；任何写类 loop 的 `_tick_once` 开头须 check `BackupCoordinator.is_running()` 跳过写，避免备份期间 ChromaDB 并发写
- **Modifying data models**: Update `Note` class in `models.py`, update `to_markdown()`/`from_markdown()`, consider backward compat
- **Viewing note content**: `jfox show <id_or_title>` 复用 `find_note_id_by_title_or_id` 定位笔记，默认输出完整 Markdown（`--json` / `--format json` 输出结构化字段）
- **笔记生命周期事件**: `note.py` 只广播 `post_delete`/`post_archive`/`post_promote`/`post_reject`（`register_lifecycle_hook` + `_dispatch`），绝不 import 特性层；特性层订阅做副作用（如 `gem_synth/lifecycle.py` 同步 dedup 表）。`register` 在 `jfox/__init__.py` 接线，任何 `import jfox.*` 即订阅就位，库式调用方零成本

## Test Infrastructure

- **Fixtures** (`conftest.py`): `temp_kb` (temp KB path), `cli` (ZKCLI instance), `cli_fast` (ZKCLI with mocked embeddings), `generator` (NoteGenerator), `mock_embedding_backend`
- **Test utils** (`tests/utils/`): `temp_kb.py`, `jfox_cli.py` (CLI wrapper), `note_generator.py`
- **Model caching**: Session-level model cache in conftest.py to avoid 30-60s reload per test
- **Test markers**: `slow`, `performance`, `integration`, `embedding`, `workflow`, `bulk`
- **Run single-process** to avoid ChromaDB/model loading conflicts
- **Test directory reorganization mostly complete**:
  - `tests/unit/` — Pure logic unit tests (25 files)
  - `tests/integration/` — Cross-module integration tests (backlinks, tag filter, model download)
  - `tests/performance/` — Performance benchmarks
  - Root-level `test_config_unit.py` and `test_config_set_unit.py` remain (no longer duplicated, test different things)
- **pytest.ini**: `timeout=120`, `--strict-markers`, `-ra` (show all test summary)

## CI (GitHub Actions)

Four jobs in `.github/workflows/integration-test.yml`:
- **Fast** (PR/push): `not embedding and not slow`, Python 3.11, Ubuntu + Windows
- **Core** (main branch): Core workflow tests with real embeddings, Python 3.10 + 3.12
- **Full** (manual): All tests, all OS, all Python versions
- **Coverage** (after fast): Runs coverage on fast tests, uploads HTML/XML artifacts

**Release** workflow in `.github/workflows/publish.yml`: publishes to PyPI on GitHub release publication.

## Release Tooling

三条独立发版轨道，各有单组件 skill + 一个编排 skill（`.claude/skills/`）：

| 轨道 | skill | helper | 发版方式 |
|------|-------|--------|----------|
| jfox CLI | `/release` | `release_helper.py` | tag `v*` + GitHub Release（触发 PyPI publish） |
| cc-plugin | `/release-cc-plugin` | `release_cc_plugin_helper.py` | 三处版本号原子 bump + PR，合 main 即发布（`/plugin update` 拉新） |
| kimi-plugin | `/release-kimi-plugin` | `release_kimi_plugin_helper.py` | 单一 version bump + PR，合 main 即发布 |
| 编排 | `/release-all` | `release_all_helper.py` | detect 三组件跳过无改动者、批量建 PR、最后发 jfox Release |

- **三组件版本轨道独立**，语义各自不同；`/release-all` 只统一编排、不统一版本号。
- **只有 jfox CLI 打 tag / 发 GitHub Release**；cc/kimi 仅 bump + PR。
- `release_helper.py verify`（#333）：创建 jfox GitHub Release 前核对 `last_tag..HEAD` 功能 commit 的 PR 号是否都进 CHANGELOG 顶段，防 bump 后被外部 PR 抢先合入致漏项（v1.1.0/v1.5.0 踩过）。`/release` Step 9 与 `/release-all` 都调用。

## Windows Notes

- `robocopy` flags get misinterpreted by bash — use `cmd.exe /c "robocopy source dest /E"`
- Set `PYTHONUTF8=1` and `chcp 65001` for encoding
- HuggingFace mirror for China: `export HF_ENDPOINT=https://hf-mirror.com`

## Claude Code Plugin

JFox ships as a Claude Code plugin. Two-tier structure:
- `.claude-plugin/marketplace.json` — top-level marketplace registry (version, description)
- `packages/cc-plugin/.claude-plugin/plugin.json` — plugin source metadata
- `packages/cc-plugin/skills/` — 9 skills: `search`, `ingest`, `manage`, `organize`, `promote`, `session-summary`, `session-to-permanent`, `using-jfox`, `bookshelf`

**Plugin versioning**: bump version in **three** places together — `packages/cc-plugin/.claude-plugin/plugin.json` (`version`) and both version fields in `.claude-plugin/marketplace.json` (`metadata.version` + `plugins[0].version`). 漏改任一处都会导致 marketplace 与 plugin 版本不一致。Current: 0.7.0.
**Skill rename history**: `kb` → `manage` (v0.2.0) — "manage" is the canonical KB lifecycle + CRUD skill.

## Branch Rules

- **main 是保护分支**，不能直接 commit 或 push。所有改动必须通过新分支 + PR 合入。

## Gotchas

- `pytest.ini` `addopts` includes `-v`, so `pytest tests/` already runs verbose — adding `-v` manually is redundant
- Test directory migration mostly complete; root-level `test_config_unit.py` and `test_config_set_unit.py` remain but test different things from `tests/unit/`
- 生命周期订阅模块的重依赖（numpy 等）必须 lazy import 进回调体，不能顶层 import——`jfox/__init__.py` 每次启动都 import 订阅模块，顶层会令 `--version`/`search` 等不相关命令多付 ~70-100ms eager 加载。参考 `gem_synth/lifecycle.py`
- `rich` Console 输出机器解析的 JSON 时须 `soft_wrap=True`：默认按 80 列硬折行，会把长字符串（如 Windows 绝对路径）在 JSON 字符串内部断行，`json.loads` 报 Invalid control character（Ubuntu 路径短不触发，只在 Windows CI 挂，#336）。参考 `bookshelf/cli.py` `_emit_json`
