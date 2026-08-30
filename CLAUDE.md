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
npx --yes markdownlint-cli2@0.23.2 "**/*.md" "#node_modules" "#.venv"  # Markdown lint（配置 .markdownlint-cli2.jsonc，#418）

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
| `cli.py` | All CLI commands (~4100 lines). Commands follow pattern: `@app.command()` → `_xxx_impl()` helper for reuse |
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
| `bm25_index.py` | BM25 keyword search index；写路径 filelock + 原子写 + `write_version` 乐观并发控制，多进程并发写安全（#391/#396） |
| `embedding_backend.py` | Sentence-transformers embedding backend（支持 daemon 代理）；CPU 默认模型 `BAAI/bge-small-zh-v1.5`（512 维，#442），本地模型目录未命中时先走 ModelDownloader 下载链再兜底加载（#374） |
| `daemon/` | Embedding 模型 HTTP 守护进程 (`server.py`/`client.py`/`process.py`)，`jfox daemon start/stop/status` |
| `embedding_migration.py` | 全 KB 向量维度不匹配检测（#442）：daemon start/restart 时比对各 KB Chroma 集合维度与 daemon 服务维度，发现旧模型建库则交互式逐 KB 提示 rebuild，单 KB 失败不阻断其余 |
| `fragment/` | 碎片采集：detector 分类 + store SQLite(WAL) + service 编排 |
| `bookshelf/` | 好书资产管理：store 文件夹 CRUD + meta jfox 自有元数据（wrap scan2book manifest）+ cli sub-app；纯文件管理不进索引 |
| `gem_synth/` | L3 宝石合成：daemon 循环围绕锚点用 transcript + 永久笔记基准合成 candidate 笔记；存盘前 `dedup.py` 正文余弦查重，命中 candidate 时 `synthesizer.py` 增量合并（提取 delta 补进已有草稿，#309；permanent 仍跳过）；`lifecycle.py` 订阅 note 的 delete/archive/promote/reject 事件同步 dedup 表 |
| `auto_summary/` | 自动总结子系统：daemon 内扫描 `~/.claude/projects/` 已结束的 Claude Code session，经 `claude -p` 生成摘要写入 `session` 笔记；CLI `jfox auto-summary run/scan/status/enable/disable`，ledger 去重 + schedule time window |
| `backup/` | KB 滚动备份/恢复：`manager.py` BackupManager（tar.gz+sha256 清单+滚动轮转+可逆 restore）+ daemon `loop.py` 定时备份（镜像 auto-summary，quiesce 标志让 gem_synth/auto_summary 跳过写 tick）+ `jfox backup run/enable/disable/status/list/verify/restore`；默认关，opt-in |
| `moc/` | MOC 结构层：`cluster.py` 密度诊断（永久笔记向量余弦相似度多阈值聚类——阈值化加权图 Louvain 社区发现（边权=相似度，`seed=42` 确定性，#463 起替代传递连通分量），默认阈值 0.65→0.75、diagnose 网格 0.70–0.80，#410/#463；链接/语义孤儿检测，N×N 稠密矩阵上限 5000）+ `draft.py`/`generate.py` create/update（从诊断簇生成并维护 structure 笔记，落盘带 backlinks 回填与成员磁盘存在性校验，#413）；CLI `jfox moc diagnose/create/update`；重依赖经 `__init__.py` 的 `__getattr__` 按需加载 |
| `vector_store.py` | ChromaDB vector store for semantic search；批量读 `get_all_embeddings()` 走复制前后清单校验一致的只读快照副本而非活库（Chroma 只读集合也会写 SQLite），失败抛 `VectorStoreReadError`（#407） |
| `graph.py` | NetworkX knowledge graph from links/backlinks |
| `redirect.py` | 笔记重定向 + delete 入链保护（#435/#449）：`jfox redirect OLD_ID KEEP_ID` 批量改写引用（frontmatter+正文，保留 alias/anchor，跳过 code fence/HTML 注释，非 dry-run 后验证无残留 OLD 引用）；`jfox delete` 默认拒绝删除被引用笔记，`--allow-dangling` 放行 |
| `template.py` / `template_cli.py` | Jinja2 template system for structured note creation |
| `performance.py` | Batch processing and model caching |

### Note Types

- `fleeting` — Quick capture, filename: `YYYYMMDD-HHMMSS.md`
- `literature` — Reading notes, filename: `YYYYMMDDHHMMSS-{slug}.md`
- `permanent` — Processed knowledge, filename: `YYYYMMDDHHMMSS-{slug}.md`
- `structure` — Map of Content (MOC) 导航笔记，由 `jfox moc create/update` 生成维护（#413）

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
- **README**: 英文 baseline（#461 起重写），改 README 保持英文；其余项目文档/注释仍中文
- **Adding a CLI command**: Add `@app.command()` in `cli.py`, implement `_xxx_impl()` helper, add `--kb` and `--format json` support（`--json` 简写等价于 `--format json`，全 CLI 统一约定，moc create/update 曾漏补，#425）
- **Adding a search mode**: Add to `SearchMode` enum in `search_engine.py`, implement in `HybridSearchEngine.search()`, update CLI `--mode` help text
- **Adding a daemon-scheduled loop**: 镜像 `auto_summary/`（与 gem_synth/backup 同构）——`loop.py`（`_tick_once` + async `X_loop(stop_event)`）+ `daemon/server.py` lifespan 内 `_maybe_start/stop_X` 接线 + `GlobalConfigManager` opt-in（每 tick `reload()` 即时生效）；任何写类 loop 的 `_tick_once` 开头须 check `BackupCoordinator.is_running()` 跳过写，避免备份期间 ChromaDB 并发写
- **Modifying data models**: Update `Note` class in `models.py`, update `to_markdown()`/`from_markdown()`, consider backward compat
- **Viewing note content**: `jfox show <id_or_title>` 复用 `find_note_id_by_title_or_id` 定位笔记，默认输出完整 Markdown（`--json` / `--format json` 输出结构化字段）
- **笔记生命周期事件**: `note.py` 只广播 `post_delete`/`post_archive`/`post_promote`/`post_reject`（`register_lifecycle_hook` + `_dispatch`），绝不 import 特性层；特性层订阅做副作用（如 `gem_synth/lifecycle.py` 同步 dedup 表）。`register` 在 `jfox/__init__.py` 接线，任何 `import jfox.*` 即订阅就位，库式调用方零成本
- **源笔记清理统一 archive**: skill 整理/提炼后清理源笔记用 `jfox archive`（软删除，`jfox unarchive` 可回滚误判），不用 `delete --force` 硬删（#436）

## Test Infrastructure

- **Fixtures** (`conftest.py`): `temp_kb` (temp KB path), `cli` (ZKCLI instance), `cli_fast` (ZKCLI with mocked embeddings), `generator` (NoteGenerator), `mock_embedding_backend`
- **Test utils** (`tests/utils/`): `temp_kb.py`, `jfox_cli.py` (CLI wrapper), `note_generator.py`
- **全局配置隔离**: conftest 设 `ZK_CONFIG_PATH`（配合既有 `ZK_KB_ROOT`）指向临时目录，pytest 及其拉起的 CLI 子进程不读写真实 `~/.zk_config.json`（#469，`global_config.py` 的 `DEFAULT_CONFIG_PATH` 支持该 env 覆盖）
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

**CI 触发受 `paths` 限制**：`integration-test.yml` 的 `paths` 含 `jfox/**`/`tests/**`/`pyproject.toml`/`**/*.md`/`.markdownlint-cli2.jsonc`/自身——#418 起 Markdown 文件改动也触发 CI（lint job 跑 markdownlint）；`packages/` 下非 md 文件（cc/kimi-plugin 发版 bump 的 json 等）改动仍**不触发 CI**。后果：`packages/` 下版本 bump 不跑测试，release-helper 测试须按当前版本动态算「下一版」（勿硬编码），否则只在后续触达 `tests/` 的 PR 才暴露（#382 踩过）。

**Release** workflow in `.github/workflows/publish.yml`: publishes to PyPI on GitHub release publication.

**Local nightly full-test**（#263/#361，非 GitHub Action）：`scripts/nightly_test.sh` 是本机 crontab 定时任务（crontab 行装本机、不进仓库），每周二 09:00 跑 CI `test-fast` 跳过的全量 pytest（performance/bulk/slow/embedding）——成功静默，失败按签名去重复用带 `nightly-test-failure` label 的 issue。前置：今日 #338 备份须成功（读 `~/.jfox-backup/state.json` 的 `last_ok`，否则 `SKIP: 今日备份未确认` 退出）。纯逻辑在 `scripts/nightly_test_helpers.py`（单测 `tests/unit/test_nightly_test_helpers.py`）；`--dry-run` 用人造失败走 issue 流程、不跑真实 pytest。

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
- CHANGELOG 条目格式受 markdownlint 约束（MD022/MD032：标题/列表前后空行）：`release_helper.py` 的 `generate_changelog` 已合规（#431），发版后手补条目（verify 兜底，如 #432/#433）同样须守，否则 CI lint job 挂。

## Windows Notes

- `robocopy` flags get misinterpreted by bash — use `cmd.exe /c "robocopy source dest /E"`
- Set `PYTHONUTF8=1` and `chcp 65001` for encoding
- HuggingFace mirror for China: `export HF_ENDPOINT=https://hf-mirror.com`

## Claude Code Plugin

JFox ships as a Claude Code plugin. Two-tier structure:

- `.claude-plugin/marketplace.json` — top-level marketplace registry (version, description)
- `packages/cc-plugin/.claude-plugin/plugin.json` — plugin source metadata
- `packages/cc-plugin/skills/` — 9 skills: `search`, `ingest`, `manage`, `organize`, `promote`, `session-summary`, `session-to-permanent`, `using-jfox`, `bookshelf`

**Plugin versioning**: bump version in **three** places together — `packages/cc-plugin/.claude-plugin/plugin.json` (`version`) and both version fields in `.claude-plugin/marketplace.json` (`metadata.version` + `plugins[0].version`). 漏改任一处都会导致 marketplace 与 plugin 版本不一致。Current: 0.7.5.
**Skill rename history**: `kb` → `manage` (v0.2.0) — "manage" is the canonical KB lifecycle + CRUD skill.
**Non-Claude-Code platforms**: `skills-recommend/`（`pi/` + `kimi-cli/`）是 pi / Kimi CLI 适配版 SKILL.md 集（如 `pi/jfox-moc`，#419）——CLI 语义或命令面变更时须与 cc-plugin skills 同步更新。
**Skill 多副本同步**: skill 文案/行为改动须同步所有镜像副本——`packages/cc-plugin/skills/`、`packages/kimi-plugin/skills/`、`skills-recommend/kimi-cli/`、`skills-recommend/pi/`，只改一处会各端行为分叉（#440 踩过同步模式）

## Branch Rules

- **main 是保护分支**，不能直接 commit 或 push。所有改动必须通过新分支 + PR 合入。

## Gotchas

- `pytest.ini` `addopts` includes `-v`, so `pytest tests/` already runs verbose — adding `-v` manually is redundant
- Test directory migration mostly complete; root-level `test_config_unit.py` and `test_config_set_unit.py` remain but test different things from `tests/unit/`
- 生命周期订阅模块的重依赖（numpy 等）必须 lazy import 进回调体，不能顶层 import——`jfox/__init__.py` 每次启动都 import 订阅模块，顶层会令 `--version`/`search` 等不相关命令多付 ~70-100ms eager 加载。参考 `gem_synth/lifecycle.py`
- `rich` Console 输出机器解析的 JSON 时须 `soft_wrap=True`：默认按 80 列硬折行，会把长字符串（如 Windows 绝对路径）在 JSON 字符串内部断行，`json.loads` 报 Invalid control character（Ubuntu 路径短不触发，只在 Windows CI 挂，#336）。参考 `bookshelf/cli.py` `_emit_json`
- `delete_note`/`promote_note` 增量同步各 target 的 backlinks（#388 起对称）：写盘前按真实磁盘路径 re-read-and-merge——重读 fresh 再合并写回，文件名发散不产生同 id 双文件、与常驻 daemon 并发写不丢更新（#392/#422）；单 target 写盘失败仅 warning 不中断，悬空/不对称残留用 `jfox index rebuild --backlinks` 全量重算兜底
- `HybridSearchEngine` 构造时仅对自取的 BM25 单例做一次 stale 检查并 reload（磁盘被其他进程写过则刷新快照）；显式传入的 `bm25_index` 实例归调用方所有、不隐式 reload——长驻进程须自行周期重建引擎或调 `check_stale_and_reload`（#391）
- `jfox index verify` 以 frontmatter 真实 `id` 对账向量库，文件名格式无关——legacy `14位时间戳-6位微秒-slug` 文件名不再误报 orphan；frontmatter 缺 id/解析失败的文件计入 `unreadable_files` 不参与对账，同 id 多文件报 `duplicate_ids`（#407/#408）
- CPU 默认 embedding 模型已从 `all-MiniLM-L6-v2`（384 维）切到 `BAAI/bge-small-zh-v1.5`（512 维，#442）：旧 KB 向量库维度不匹配时 search/add 显式告警不静默失败（`vector_store.last_dimension_warning`），按提示 `jfox index rebuild` 重建该 KB；CI 模型缓存 key 也随模型名（#453）
