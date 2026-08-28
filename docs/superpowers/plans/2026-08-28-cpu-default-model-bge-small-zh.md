# CPU 默认模型切换 bge-small-zh-v1.5 + 存量索引平滑迁移 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** jfox CPU 默认 embedding 模型切换为 `BAAI/bge-small-zh-v1.5`（512 维），并让存量 384 维索引用户在 `jfox daemon restart` 后获得检测警告 + 交互式逐库 rebuild 引导，search/add 入口有兜底警告。

**Architecture:** 三层改动：① 常量层（默认模型名与维度 fallback，5 处）+ 下载降级链接入 `EmbeddingBackend.load()`；② 新模块 `jfox/embedding_migration.py`（daemon /health 维度 vs 各 KB ChromaDB peek 维度对比 + 交互引导 rebuild），挂载在 `cli.py` daemon 命令 start/restart 成功路径；③ `vector_store.py` 的 search/add 维度异常从静默 log 升级为实例属性上浮，CLI 层显示警告。

**Tech Stack:** Python 3.10+ / Typer / Rich / ChromaDB / sentence-transformers / pytest (mock, monkeypatch)

## Global Constraints

- 工作目录：worktree `/home/elling/git-repo/github/jfox/.pi/worktrees/issue-442-cpu-default-model-bge-small-zh`（分支 `issue-442-cpu-default-model-bge-small-zh`，基于 origin/main 3f34f08）。**禁止碰主 checkout。**
- GPU 路径不动：`_GPU_DEFAULT_MODEL = "BAAI/bge-m3"`（1024 维）保持不变；`config.embedding_model` 显式指定逻辑不动。
- BM25 索引与 embedding 模型无关，迁移 rebuild 不重建 BM25。
- 测试只用 fast 路径：`uv run pytest tests/unit/test_xxx.py -v`（单文件可自主跑）；全套 fast 回归 `uv run pytest -m "not embedding and not slow"`。**不要自主跑全量/集成测试。**
- 代码注释用英文，commit message 用 conventional commits 英文格式。
- 行为契约：检测失败（daemon 无响应 / 单库异常 / 空库）一律跳过不阻塞，`daemon restart` 本身的成功状态优先。
- `git add` 按文件 stage，禁止 `git add -A`。

---

### Task 1: 模型切换本体（常量 + 维度 fallback + README）

**Files:**

- Modify: `jfox/embedding_backend.py:13-14`（模型常量）、`jfox/embedding_backend.py:160-167`（dimension fallback）
- Modify: `jfox/daemon/process.py:443`
- Modify: `jfox/daemon/client.py:28`、`jfox/daemon/client.py:43`
- Modify: `README.md:56`、`README.md:87`
- Test: `tests/unit/test_default_model_switch.py`（新建）

**Interfaces:**

- Produces: `_CPU_DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"`；`EmbeddingBackend.dimension` 未加载 fallback 从 384 → 512；`DaemonClient.dimension` 初始值与 /health 缺省值 512。后续任务按这些值断言。

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_default_model_switch.py
"""Default CPU embedding model switch to bge-small-zh-v1.5 (#442)."""

from jfox import embedding_backend
from jfox.daemon.client import DaemonClient


class TestDefaultModelSwitch:
    def test_cpu_default_model_is_bge_small_zh(self):
        assert embedding_backend._CPU_DEFAULT_MODEL == "BAAI/bge-small-zh-v1.5"

    def test_gpu_default_model_unchanged(self):
        assert embedding_backend._GPU_DEFAULT_MODEL == "BAAI/bge-m3"

    def test_unloaded_dimension_fallback_is_512(self):
        backend = embedding_backend.EmbeddingBackend()
        # No model loaded, no daemon client: dimension property falls back to new default
        backend.model_name = "BAAI/bge-small-zh-v1.5"
        assert backend._resolved_dim is None
        assert backend.model is None
        assert backend._daemon_client is None
        assert backend.dimension == 512

    def test_daemon_client_dimension_default_is_512(self):
        client = DaemonClient.__new__(DaemonClient)  # skip __init__ network access
        assert client._dimension if hasattr(client, "_dimension") else True
        # Direct check of the class-level default used in __init__
        import inspect
        src = inspect.getsource(DaemonClient.__init__)
        assert "512" in src
```

注意：`test_unloaded_dimension_fallback_is_512` 依赖 dimension property 的现行为（`_resolved_dim is None` 且无 model/daemon 时走到 fallback）。实现 Step 3 后该链路返回 512。

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_default_model_switch.py -v`
Expected: FAIL — `_CPU_DEFAULT_MODEL` 仍是 MiniLM，fallback 仍是 384。

- [ ] **Step 3: Write minimal implementation**

`jfox/embedding_backend.py`：

```python
# line 14: replace
_CPU_DEFAULT_MODEL = "BAAI/bge-small-zh-v1.5"
```

`jfox/embedding_backend.py` dimension property 尾部（原 `return 384  # 默认 MiniLM 维度`）：

```python
        if self.model_name and self.model_name != "auto":
            if "bge-m3" in self.model_name or "bge-large" in self.model_name:
                return 1024
            if "bge-small-zh" in self.model_name:
                return 512
        return 512  # default bge-small-zh-v1.5 dimension
```

`jfox/daemon/client.py:28`（`__init__` 内）：`self._dimension: int = 512`
`jfox/daemon/client.py:43`：`self._dimension = data.get("dimension", 512)`
`jfox/daemon/process.py:443`：`"dimension": health.get("dimension", 512),`

`README.md:56`：架构图中 `all-MiniLM-L6-v2` → `bge-small-zh-v1.5`
`README.md:87`：`` Lazy-loaded SentenceTransformer (`BAAI/bge-small-zh-v1.5`, 512-dim vectors; GPU auto-switches to bge-m3) ``

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_default_model_switch.py -v`
Expected: PASS (4 tests)

- [ ] **Step 5: Commit**

```bash
git add jfox/embedding_backend.py jfox/daemon/client.py jfox/daemon/process.py README.md tests/unit/test_default_model_switch.py
git commit -m "feat(embedding): switch CPU default model to bge-small-zh-v1.5 (512-dim) (#442)"
```

---

### Task 2: load() 接入 ModelDownloader 降级链（#374 核心）

**Files:**

- Modify: `jfox/embedding_backend.py:104-125`（`load()` 的本地路径未命中分支）
- Test: `tests/unit/test_embedding_local_load.py`（追加）

**Interfaces:**

- Consumes: `ModelDownloader(model_name).ensure_cached() -> bool`（`jfox/model_downloader.py:73`，已存在）
- Produces: `load()` 行为契约——本地目录未命中时先走 `ensure_cached()` 三级降级（HF → ModelScope → curl），成功后优先从本地目录加载，仍无本地目录则 `SentenceTransformer(model_name)`（此时 HF 缓存已命中，不再联网）；`ensure_cached()` 返回 False 时维持现状直接尝试 `SentenceTransformer`（最终失败抛原异常）。

- [ ] **Step 1: Write the failing tests**（追加到 `tests/unit/test_embedding_local_load.py`）

```python
class TestLoadFallsBackToModelDownloader:
    """load() must try ModelDownloader.ensure_cached() when local dir misses (#374)."""

    def _make_backend(self, monkeypatch):
        from jfox import embedding_backend as eb

        backend = eb.EmbeddingBackend()
        backend.model_name = "BAAI/bge-small-zh-v1.5"
        backend._resolved_device = "cpu"
        monkeypatch.setattr(eb.EmbeddingBackend, "_check_daemon", lambda self: False)
        return backend, eb

    def test_ensure_cached_called_when_local_missing(self, monkeypatch):
        backend, eb = self._make_backend(monkeypatch)
        monkeypatch.setattr(eb.EmbeddingBackend, "_get_local_model_path", lambda self: None)

        calls = []

        class FakeDownloader:
            def __init__(self, model_name):
                calls.append(model_name)

            def ensure_cached(self):
                return False  # all three fallbacks fail

        monkeypatch.setattr("jfox.model_downloader.ModelDownloader", FakeDownloader)

        class FakeST:
            def __init__(self, name, device=None):
                raise RuntimeError("network unreachable")

        monkeypatch.setattr("sentence_transformers.SentenceTransformer", FakeST)

        with pytest.raises(RuntimeError):
            backend.load()
        assert calls == ["BAAI/bge-small-zh-v1.5"]

    def test_load_uses_local_dir_after_download(self, monkeypatch, tmp_path):
        backend, eb = self._make_backend(monkeypatch)
        local_dir = tmp_path / "downloaded-model"
        local_dir.mkdir()

        # First probe misses, second probe (after download) hits
        probes = []

        def fake_local_path(self):
            probes.append(1)
            return local_dir if len(probes) > 1 else None

        monkeypatch.setattr(eb.EmbeddingBackend, "_get_local_model_path", fake_local_path)

        class FakeDownloader:
            def __init__(self, model_name):
                pass

            def ensure_cached(self):
                return True

        monkeypatch.setattr("jfox.model_downloader.ModelDownloader", FakeDownloader)

        loaded_with = []

        class FakeST:
            def __init__(self, name, device=None):
                loaded_with.append(name)

            def get_sentence_embedding_dimension(self):
                return 512

        monkeypatch.setattr("sentence_transformers.SentenceTransformer", FakeST)

        backend.load()
        assert loaded_with == [str(local_dir)]
        assert backend.dimension == 512
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_embedding_local_load.py -v -k TestLoadFallsBackToModelDownloader`
Expected: FAIL — `calls` 为空（现状直接 `SentenceTransformer`，从不调 ModelDownloader）。

- [ ] **Step 3: Write minimal implementation**

`jfox/embedding_backend.py` `load()`，替换 `# 优先从本地目录加载` 起的三行：

```python
            # Prefer local model dir; on miss, run ModelDownloader fallback chain
            # (HF -> ModelScope -> curl) before hard-loading via network (#374).
            local_path = self._get_local_model_path()
            if local_path is None:
                from .model_downloader import ModelDownloader

                if ModelDownloader(self.model_name).ensure_cached():
                    # Download may land in ~/.zettelkasten/.models/ — re-probe;
                    # if it landed in HF hub cache, fall through to name-based load.
                    local_path = self._get_local_model_path()
            if local_path is not None:
                self.model = SentenceTransformer(str(local_path), device=self._resolved_device)
            else:
                self.model = SentenceTransformer(self.model_name, device=self._resolved_device)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_embedding_local_load.py -v`
Expected: PASS（新 2 条 + 该文件原有测试不回归）

- [ ] **Step 5: Commit**

```bash
git add jfox/embedding_backend.py tests/unit/test_embedding_local_load.py
git commit -m "fix(embedding): route load() through ModelDownloader fallback chain (#374, #442)"
```

---

### Task 3: 新模块 embedding_migration — 维度检测

**Files:**

- Create: `jfox/embedding_migration.py`
- Test: `tests/unit/test_embedding_migration.py`

**Interfaces:**

- Consumes: `DaemonClient(url).available -> bool`、`.dimension -> int`（Task 1 后默认 512）；`GlobalConfigManager().list_knowledge_bases() -> List[KnowledgeBaseEntry]`（`name: str, path: str`）；`is_daemon_running()`、`_get_daemon_url()`（`jfox/daemon/process.py`）
- Produces（Task 4 依赖）:

```python
@dataclass
class DimensionMismatchReport:
    model_dimension: int            # current model dim from daemon /health
    affected_kbs: List[str]         # KB names whose index dim != model dim
    kb_dimensions: Dict[str, int]   # kb_name -> existing index dim

def check_dimension_mismatch() -> Optional[DimensionMismatchReport]
    # daemon down / health missing -> None; all KBs match -> None; else report

def prompt_migration(report: DimensionMismatchReport) -> None   # Task 4 implements
```

- [ ] **Step 1: Write the failing tests**

```python
# tests/unit/test_embedding_migration.py
"""Dimension mismatch detection across all KBs (#442)."""

import pytest

from jfox.embedding_migration import DimensionMismatchReport, check_dimension_mismatch


class _FakeCollection:
    def __init__(self, dim=None, count=0):
        self._dim = dim
        self._count = count

    def count(self):
        return self._count

    def peek(self, limit=1):
        if self._dim is None:
            return {"embeddings": None}
        return {"embeddings": [[0.0] * self._dim]}


class _FakeClient:
    def __init__(self, collections):
        self._collections = collections

    def get_collection(self, name):
        if name not in self._collections:
            raise ValueError(f"Collection {name} does not exist")
        return self._collections[name]


def _patch_env(monkeypatch, tmp_path, health_dim, kb_specs):
    """kb_specs: list of (kb_name, exists, dim_or_None, count). Returns affected expectations."""
    import jfox.embedding_migration as em
    from jfox.global_config import KnowledgeBaseEntry

    entries = []
    chroma_roots = {}
    for kb_name, exists, dim, count in kb_specs:
        kb_path = tmp_path / kb_name
        kb_path.mkdir()
        entries.append(
            KnowledgeBaseEntry(name=kb_name, path=str(kb_path), created="2026-08-28")
        )
        if exists:
            chroma_root = kb_path / ".zk" / "chroma_db"
            chroma_root.mkdir(parents=True)
            chroma_roots[str(chroma_root)] = _FakeCollection(dim=dim, count=count)

    class FakeGlobalConfigManager:
        def list_knowledge_bases(self):
            return entries

    monkeypatch.setattr(em, "_GlobalConfigManager", FakeGlobalConfigManager)

    class FakeDaemonClient:
        available = True
        dimension = health_dim

    monkeypatch.setattr(em, "_DaemonClient", FakeDaemonClient)
    monkeypatch.setattr(em, "_is_daemon_running", lambda: True)
    monkeypatch.setattr(em, "_get_daemon_url", lambda: "http://127.0.0.1:8300")

    class FakeChroma:
        @staticmethod
        def PersistentClient(path=None, settings=None):
            if path not in chroma_roots:
                raise RuntimeError("corrupt dir")
            return _FakeClient({"notes": chroma_roots[path]})

    monkeypatch.setattr(em, "chromadb", FakeChroma)


class TestCheckDimensionMismatch:
    def test_mismatch_detected(self, monkeypatch, tmp_path):
        # default KB has 384-dim index, model reports 512
        _patch_env(
            monkeypatch, tmp_path,
            health_dim=512,
            kb_specs=[("default", True, 384, 100), ("work", True, 512, 5)],
        )
        report = check_dimension_mismatch()
        assert report is not None
        assert report.model_dimension == 512
        assert report.affected_kbs == ["default"]
        assert report.kb_dimensions == {"default": 384}

    def test_all_match_returns_none(self, monkeypatch, tmp_path):
        _patch_env(
            monkeypatch, tmp_path,
            health_dim=512,
            kb_specs=[("default", True, 512, 100)],
        )
        assert check_dimension_mismatch() is None

    def test_empty_kb_skipped(self, monkeypatch, tmp_path):
        _patch_env(
            monkeypatch, tmp_path,
            health_dim=512,
            kb_specs=[("default", True, None, 0), ("fresh", False, None, 0)],
        )
        assert check_dimension_mismatch() is None

    def test_corrupt_kb_skipped_not_fatal(self, monkeypatch, tmp_path):
        # "broken" KB: chroma dir exists but unlisted in chroma_roots -> PersistentClient raises
        _patch_env(
            monkeypatch, tmp_path,
            health_dim=512,
            kb_specs=[("default", True, 384, 10), ("broken", True, None, 0)],
        )
        report = check_dimension_mismatch()
        assert report is not None
        assert report.affected_kbs == ["default"]

    def test_daemon_down_returns_none(self, monkeypatch, tmp_path):
        import jfox.embedding_migration as em

        monkeypatch.setattr(em, "_is_daemon_running", lambda: False)
        assert check_dimension_mismatch() is None

    def test_health_without_dimension_returns_none(self, monkeypatch, tmp_path):
        import jfox.embedding_migration as em

        class NoDimClient:
            available = False

        monkeypatch.setattr(em, "_DaemonClient", NoDimClient)
        monkeypatch.setattr(em, "_is_daemon_running", lambda: True)
        monkeypatch.setattr(em, "_get_daemon_url", lambda: "http://127.0.0.1:8300")
        assert check_dimension_mismatch() is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_embedding_migration.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'jfox.embedding_migration'`

- [ ] **Step 3: Write minimal implementation**

```python
# jfox/embedding_migration.py
"""Embedding model migration detection (#442).

Compares each KB's ChromaDB collection dimension against the dimension
served by the running embedding daemon. Returns a report when at least
one KB was indexed with a different (old) model.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import chromadb
from chromadb.config import Settings

logger = logging.getLogger(__name__)

# Re-exported seams for tests (monkeypatch these instead of real modules)
from .daemon.client import DaemonClient as _DaemonClient
from .daemon.process import _get_daemon_url, is_daemon_running as _is_daemon_running
from .global_config import GlobalConfigManager as _GlobalConfigManager


@dataclass
class DimensionMismatchReport:
    model_dimension: int
    affected_kbs: List[str] = field(default_factory=list)
    kb_dimensions: Dict[str, int] = field(default_factory=dict)


def check_dimension_mismatch() -> Optional[DimensionMismatchReport]:
    """Scan all KBs for dimension mismatch. Never raises."""
    try:
        if not _is_daemon_running():
            return None
        client = _DaemonClient(_get_daemon_url())
        if not client.available:
            return None
        model_dim = client.dimension
    except Exception as e:
        logger.debug(f"migration check skipped, daemon unavailable: {e}")
        return None

    report = DimensionMismatchReport(model_dimension=model_dim)
    try:
        kbs = _GlobalConfigManager().list_knowledge_bases()
    except Exception as e:
        logger.debug(f"migration check skipped, cannot list KBs: {e}")
        return None

    for kb in kbs:
        chroma_path = Path(kb.path).expanduser() / ".zk" / "chroma_db"
        if not chroma_path.exists():
            continue
        try:
            c = chromadb.PersistentClient(
                path=str(chroma_path),
                settings=Settings(anonymized_telemetry=False),
            )
            collection = c.get_collection("notes")
            if collection.count() == 0:
                continue
            peek = collection.peek(limit=1)
            embeddings = peek.get("embeddings")
            if not embeddings:
                continue
            kb_dim = len(embeddings[0])
        except Exception as e:
            # Single-KB failure must not block the rest
            logger.debug(f"migration check skipped KB {kb.name}: {e}")
            continue
        if kb_dim != model_dim:
            report.affected_kbs.append(kb.name)
            report.kb_dimensions[kb.name] = kb_dim

    return report if report.affected_kbs else None
```

注意：`get_collection`（非 get_or_create）避免在检测路径产生创建副作用；目录不存在/损坏抛异常走跳过分支。

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_embedding_migration.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add jfox/embedding_migration.py tests/unit/test_embedding_migration.py
git commit -m "feat(migration): detect embedding dimension mismatch across all KBs (#442)"
```

---

### Task 4: prompt_migration + CLI 挂载（restart/start 成功路径）

**Files:**

- Modify: `jfox/embedding_migration.py`（追加 `prompt_migration`）
- Modify: `jfox/cli.py`（daemon 命令 start 成功路径 ~3246、restart 成功路径 ~3283，各在 `_print_daemon_status()` 之后）
- Test: `tests/unit/test_embedding_migration.py`（追加）

**Interfaces:**

- Consumes: Task 3 的 `check_dimension_mismatch` / `DimensionMismatchReport`；`Indexer(config, vector_store).index_all() -> int`（`jfox/indexer.py:210`）；`use_kb(kb_name)` 上下文管理器（`jfox/config.py`）；`get_vector_store()` 单例
- Produces: CLI 行为——`jfox daemon start|restart` 成功后自动检测；有 mismatch 时 Rich 警告 + `typer.confirm`；确认 y 逐库 `index_all()`（BM25 不动）；非 tty 或拒绝时仅警告。

- [ ] **Step 1: Write the failing tests**（追加到 `tests/unit/test_embedding_migration.py`）

```python
class TestPromptMigration:
    def _report(self):
        return DimensionMismatchReport(
            model_dimension=512,
            affected_kbs=["default"],
            kb_dimensions={"default": 384},
        )

    def test_confirm_yes_triggers_rebuild(self, monkeypatch):
        import jfox.embedding_migration as em

        rebuilt = []

        class FakeIndexer:
            def __init__(self, config, vector_store):
                pass

            def index_all(self, progress_callback=None):
                rebuilt.append(True)
                return 7

        entered = []

        class FakeUseKb:
            def __init__(self, name):
                self.name = name

            def __enter__(self):
                entered.append(self.name)

            def __exit__(self, *args):
                return False

        monkeypatch.setattr(em, "_Indexer", FakeIndexer)
        monkeypatch.setattr(em, "_use_kb", FakeUseKb)
        monkeypatch.setattr(em, "_get_vector_store", lambda: object())
        monkeypatch.setattr("typer.confirm", lambda *a, **kw: True)
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)

        em.prompt_migration(self._report())
        assert rebuilt == [True]
        assert entered == ["default"]

    def test_confirm_no_skips_rebuild(self, monkeypatch):
        import jfox.embedding_migration as em

        called = []
        monkeypatch.setattr(em, "_Indexer", lambda *a: (_ for _ in ()).throw(AssertionError("must not rebuild")))
        monkeypatch.setattr("typer.confirm", lambda *a, **kw: False)
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)

        em.prompt_migration(self._report())  # must not raise

    def test_non_tty_prints_hint_only(self, monkeypatch):
        import jfox.embedding_migration as em

        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        monkeypatch.setattr("typer.confirm", lambda *a, **kw: (_ for _ in ()).throw(AssertionError("must not confirm")))

        em.prompt_migration(self._report())  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_embedding_migration.py -v -k TestPromptMigration`
Expected: FAIL — `prompt_migration` 不存在。

- [ ] **Step 3: Write minimal implementation**

追加到 `jfox/embedding_migration.py`：

```python
import sys

# Test seams (imported lazily here to keep module import light)
from .config import use_kb as _use_kb
from .indexer import Indexer as _Indexer
from .vector_store import get_vector_store as _get_vector_store


def prompt_migration(report: DimensionMismatchReport) -> None:
    """Warn about dimension mismatch and offer interactive per-KB rebuild."""
    from rich.console import Console

    console = Console()
    kb_list = ", ".join(report.affected_kbs)
    console.print(
        f"[yellow]⚠ 检测到 embedding 模型已更换（当前模型 {report.model_dimension} 维）[/yellow]"
    )
    for kb in report.affected_kbs:
        console.print(
            f"  - 知识库 [cyan]{kb}[/cyan]: 索引 {report.kb_dimensions.get(kb, '?')} 维"
        )
    console.print("  影响语义搜索（返回空结果）与新笔记向量索引。")

    if not sys.stdin.isatty():
        console.print(
            "  非交互环境，请手动执行 [cyan]jfox index rebuild --kb <name>[/cyan] 重建索引。"
        )
        return

    import typer

    if not typer.confirm("是否现在重建索引？将逐库重新嵌入全部笔记", default=False):
        console.print("  已跳过。可稍后执行 [cyan]jfox index rebuild[/cyan] 重建。")
        return

    from .config import config

    for kb in report.affected_kbs:
        with _use_kb(kb):
            indexer = _Indexer(config, _get_vector_store())
            count = indexer.index_all()
            console.print(f"[green]✓[/green] {kb}: 已重建 {count} 条笔记索引")
    console.print("[green]索引迁移完成，语义搜索已恢复。[/green]")
```

`jfox/cli.py` 挂载（两处，均在 `_print_daemon_status()` 调用行之后插入）：

```python
                # start 分支（~3246 之后）与 restart 分支（~3283 之后）相同代码：
                from .embedding_migration import check_dimension_mismatch, prompt_migration

                report = check_dimension_mismatch()
                if report:
                    prompt_migration(report)
```

注意：两处挂载位置若离得近可提取局部函数，但保持两处显式调用即可（改动最小）。

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_embedding_migration.py -v`
Expected: PASS（Task 3 的 6 条 + 本任务 3 条）

- [ ] **Step 5: Commit**

```bash
git add jfox/embedding_migration.py jfox/cli.py tests/unit/test_embedding_migration.py
git commit -m "feat(migration): interactive per-KB rebuild prompt on daemon start/restart (#442)"
```

---

### Task 5: search / add 维度不匹配兜底警告

**Files:**

- Modify: `jfox/vector_store.py`（`__init__` 加属性；`add_note` :101-117 维度分支；`search` :184-185 except）
- Modify: `jfox/cli.py`（`_add_impl` 尾部、`_search_impl` 尾部）
- Test: `tests/unit/test_vector_store_dimension_warning.py`（新建）

**Interfaces:**

- Produces: `VectorStore.last_dimension_warning: Optional[str]`（实例属性，检测到维度不匹配时非空，文本含旧/新维度与 `jfox daemon restart` 指引）；CLI `add`/`search` 在操作完成后检查单例该属性并打印警告。

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_vector_store_dimension_warning.py
"""Dimension mismatch warnings must surface to users, not stay in logs (#442)."""

import pytest

from jfox.vector_store import VectorStore


def _dimension_error():
    return ValueError(
        "InvalidDimensionalityException: Collection expecting embedding with "
        "dimension of 384, got 512"
    )


class _FakeCollectionRaises:
    def query(self, **kwargs):
        raise _dimension_error()

    def add(self, **kwargs):
        raise _dimension_error()


class TestDimensionWarning:
    def test_init_has_none_warning(self, tmp_path):
        vs = VectorStore(persist_directory=tmp_path / "chroma")
        assert vs.last_dimension_warning is None

    def test_search_sets_warning(self, tmp_path, monkeypatch):
        vs = VectorStore(persist_directory=tmp_path / "chroma")
        monkeypatch.setattr(vs, "init", lambda: None)
        vs.collection = _FakeCollectionRaises()

        class FakeBackend:
            def encode_single(self, text):
                return [0.0] * 512

        monkeypatch.setattr("jfox.embedding_backend.get_backend", lambda: FakeBackend())

        results = vs.search("任何查询")
        assert results == []
        assert vs.last_dimension_warning is not None
        assert "384" in vs.last_dimension_warning and "512" in vs.last_dimension_warning
        assert "daemon restart" in vs.last_dimension_warning

    def test_add_sets_warning(self, tmp_path, monkeypatch):
        vs = VectorStore(persist_directory=tmp_path / "chroma")
        monkeypatch.setattr(vs, "init", lambda: None)
        vs.collection = _FakeCollectionRaises()

        class FakeNote:
            id = "20260828"
            title = "t"
            content = "c"
            type = "fleeting"
            tags = []
            links = []
            backlinks = []
            to_markdown = lambda self: "md"  # noqa: E731

        ok = vs.add_note(FakeNote())
        assert ok is False
        assert vs.last_dimension_warning is not None
        assert "index rebuild" in vs.last_dimension_warning
```

注意：`add_note` 现签名若需要 embedding（通过 backend.encode），monkeypatch `get_backend` 同上；以实际 `add_note` 实现为准调整 Fake 属性（先读 `vector_store.py:70-100` 确认 add_note 的入参与 encode 调用，再定稿测试）。

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_vector_store_dimension_warning.py -v`
Expected: FAIL — `last_dimension_warning` 属性不存在。

- [ ] **Step 3: Write minimal implementation**

`jfox/vector_store.py` `__init__` 尾部加：

```python
        # Surfaced dimension-mismatch warning for CLI display (#442).
        # Set by add_note()/search() when ChromaDB reports dim mismatch;
        # CLI add/search commands print it after their main work.
        self.last_dimension_warning: Optional[str] = None

    @staticmethod
    def _dimension_warning_text(error_msg: str) -> Optional[str]:
        """Build a user-facing warning when the error is a dim mismatch."""
        import re

        if "dimension" not in error_msg.lower() or "expecting" not in error_msg.lower():
            return None
        m = re.search(r"dimension of (\d+).*got (\d+)", error_msg, re.IGNORECASE)
        if m:
            old, new = m.group(1), m.group(2)
            return (
                f"索引维度({old})与当前 embedding 模型维度({new})不匹配。"
                f"请执行 jfox daemon restart 获取迁移引导，或 jfox index rebuild 重建索引。"
            )
        return (
            "索引维度与当前 embedding 模型维度不匹配。"
            "请执行 jfox daemon restart 获取迁移引导，或 jfox index rebuild 重建索引。"
        )
```

（`_dimension_warning_text` 放 `__init__` 后作为静态方法。）

`add_note` 的维度分支（现有 `if "dimension" in error_msg.lower()...` 整块）替换为：

```python
            warning = self._dimension_warning_text(error_msg)
            if warning:
                # Keep the log for debugging, surface to CLI via instance attr
                logger.error(f"Embedding dim mismatch for note {note.id}: {error_msg}")
                self.last_dimension_warning = warning
            else:
                logger.error(f"Failed to add note {note.id}: {error_msg}")
            return False
```

`search` 的 except 替换为：

```python
        except Exception as e:
            warning = self._dimension_warning_text(str(e))
            if warning:
                logger.error(f"Search failed (dim mismatch): {e}")
                self.last_dimension_warning = warning
            else:
                logger.error(f"Search failed: {e}")
            return []
```

`jfox/cli.py` `_search_impl` 尾部（结果输出后、return 前）：

```python
    from .vector_store import get_vector_store

    dim_warning = get_vector_store().last_dimension_warning
    if dim_warning:
        console.print(f"[yellow]⚠ {dim_warning}[/yellow]")
```

`_add_impl` 尾部（笔记写盘成功输出后）同款检查，另加一句说明：`笔记已保存，但未进入向量索引。`

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_vector_store_dimension_warning.py -v`
Expected: PASS (3 tests)。另外跑 `uv run pytest tests/unit/test_backlinks.py -v` 确认 vector_store 相关旧测试不回归。

- [ ] **Step 5: Commit**

```bash
git add jfox/vector_store.py jfox/cli.py tests/unit/test_vector_store_dimension_warning.py
git commit -m "feat(search): surface dimension-mismatch warnings on search/add instead of silent failure (#442)"
```

---

### Task 6: 收尾验证（fast 回归 + 真实模型下载实测）

**Files:**

- 无新文件；可能修 Task 1-5 引入的问题

**Interfaces:**

- Consumes: 全部前序任务

- [ ] **Step 1: Fast 全量回归**

Run: `uv run pytest -m "not embedding and not slow" -q`
Expected: 全绿。任何失败回对应 Task 修复后重跑。

- [ ] **Step 2: 真实模型下载实测（风险表第 1 项验证）**

Run: `uv run jfox model download BAAI/bge-small-zh-v1.5`
Expected: 下载成功（HF 或 ModelScope 降级）。核对 `~/.zettelkasten/.models/BAAI--bge-small-zh-v1.5/` 含 `config.json` + `model.safetensors` + `tokenizer.json`（与 `ModelDownloader._REQUIRED_FILES` 兼容）。若文件清单不兼容，修 `model_downloader.py` 的候选列表并补测试，再回来重跑本步。

- [ ] **Step 3: 检测链路本地冒烟（可选，若环境有 384 维旧索引）**

构造：临时 KB 建库 → mock/旧向量写入 384 维 collection → `uv run jfox daemon restart`
Expected: 输出包含「检测到 embedding 模型已更换」。无旧索引环境跳过本步（CI 覆盖单测层）。

- [ ] **Step 4: 最终 commit（如有修复）+ 工作区干净检查**

```bash
git status --short   # 应为空
git log --oneline origin/main..HEAD
```

Expected: 5-6 个 commit，全部 conventional 格式。

---

## Self-Review 记录

- Spec 覆盖：4.1（Task 1）、4.2（Task 2）、4.3（Task 3+4）、4.4（Task 5）、4.5 文案（Task 4 prompt_migration）、第 7 节测试计划（各 Task Step 1 + Task 6）、风险表 1（Task 6 Step 2）✅
- 占位符扫描：无 TBD/TODO；Task 5 Step 1 中"以实际 add_note 实现为准调整"是执行时核对指令，附带了兜底说明，非占位符 ✅
- 类型一致性：`DimensionMismatchReport(model_dimension: int, affected_kbs: List[str], kb_dimensions: Dict[str, int])` 在 Task 3/4 一致；`_use_kb/_Indexer/_get_vector_store/_DaemonClient/_GlobalConfigManager/_is_daemon_running/_get_daemon_url` test seam 命名一致 ✅
