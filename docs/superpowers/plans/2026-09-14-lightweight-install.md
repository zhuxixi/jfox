# #519 轻量化安装（[embed] extra 拆分 + 软依赖降级）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 纯 CPU 机器默认安装 jfox-cli 零 `nvidia-*` 下载；语义检索拆为 `[embed]` extra，缺失时核心功能（CRUD/BM25/图谱）可用且有友好引导（issue #519，spec: `docs/superpowers/specs/2026-09-10-lightweight-install-embed-extra-design.md`）。

**Architecture:** 打包层把 `sentence-transformers` 移入 `[embed]` extra；运行层新增「本地组件探测 + daemon 服务可用性」两个判定函数与专用异常 `EmbedDependencyMissingError`，VectorStore 只报告事实（typed re-raise + 记录 warning），降级决策在 save 层（`save_note`/`update_note`）、引擎层（`_semantic_search`/`_hybrid_search_with_k`）与 CLI 前置守卫完成；不变量「编码成功前不得删除既有向量行」。

**Tech Stack:** Python 3.10+ / Typer / uv（`UV_TORCH_BACKEND=cpu`）/ pytest（`no_embed` marker + 独立 `.venv-noembed` 测试环境）/ GitHub Actions。

## Global Constraints

- 所有工作在 worktree `<repo>/.pi/worktrees/issue-519-lightweight-install` 内进行，**禁止碰 main**；`git add` 按文件 stage，禁止 `git add -A`。
- 公共 API 名称逐字固定（spec §3.1）：`is_local_embed_available()`、`is_embedding_service_available()`、`reset_embed_availability_cache()`、`EmbedDependencyMissingError`、`format_embed_hint(context)`，全部定义在 `jfox/embedding_backend.py`。
- 不变量（spec §3.2/§3.4）：**编码成功前不得删除既有向量行**。
- JSON 协议（spec §3.5）：降级警告 `{"code": "embedding_unavailable", "message": "<hint>", "fallback": "keyword" | "bm25_only"}`；拒绝 `{"success": false, "code": "embed_dependency_missing", "error": "<hint>"}`；add/edit 增 `semantic_index_warning` 字符串字段；rebuild 增 `semantic_skipped` 布尔字段；query 增 `effective_mode` 字段。
- pyproject：核心 dependencies 移除 `sentence-transformers>=3.0`；新增 `embed = ["sentence-transformers>=3.0"]`；`dev` extra 不动。`pytest.ini` 注册 `no_embed` marker（`--strict-markers` 开启，未注册即失败）。
- CI：Fast/Lint 保持 `uv sync --extra dev`（天然无 embed 环境）；Core/Full 改 `uv sync --extra dev --extra embed` 且 pytest 命令带 `uv run --extra dev --extra embed`。
- 测试环境双轨：dev 环境 `uv run --extra dev --extra embed pytest ...`（**不要裸 `uv run`**，可能按无 extra 同步环境）；no-embed 环境 `.venv-noembed/bin/python -m pytest ...`（安装 `-e ".[dev]"`，无 sentence-transformers/torch）。`no_embed` 标记的测试必须带 `skipif(is_local_embed_available())`。
- 注释中文、commit message 英文 conventional commits；每个 task 一个 commit。
- 不改版本号（2.0.0 由 release 流程处理）；不改任何命令的 help 文本（避免 docs/cli-reference.md 漂移，Task 11 有 drift 校验）。

---

### Task 1: 打包基建——依赖拆分 + CI 矩阵 + no_embed 环境

**Files:**

- Modify: `pyproject.toml`（dependencies / optional-dependencies）
- Modify: `pytest.ini:11-21`（markers 块）
- Modify: `.github/workflows/integration-test.yml:209,214`（Core）与 `:267,272`（Full）
- Modify: `.gitignore`（追加 `.venv-noembed/`，若缺失）
- Create: `tests/unit/test_pyproject_embed_extra.py`
- Regenerate: `uv.lock`

**Interfaces:**

- Consumes: 无（首个任务）
- Produces: 可安装的轻量核心包；`embed` extra；`.venv-noembed` 测试环境（后续所有 no-embed 测试的运行环境）；pytest marker `no_embed`

- [ ] **Step 1: 写失败的结构断言测试（A3）**

创建 `tests/unit/test_pyproject_embed_extra.py`：

```python
"""A3 (#519): 打包结构静态断言——核心依赖不含 sentence-transformers。"""

import sys
from pathlib import Path

import pytest

try:
    import tomllib
except ModuleNotFoundError:  # Python 3.10 无 stdlib tomllib；用例已由下方 skipif 拦截
    tomllib = None  # type: ignore[assignment]

pytestmark = pytest.mark.skipif(
    sys.version_info < (3, 11),
    reason="tomllib requires Python 3.11+ (#519 A3 runs on 3.11+)",
)

PYPROJECT = Path(__file__).resolve().parent.parent.parent / "pyproject.toml"


def _project() -> dict:
    with open(PYPROJECT, "rb") as f:
        return tomllib.load(f)["project"]


def _deps_of(section: str) -> list:
    return _project()["optional-dependencies"].get(section, [])


def test_core_deps_exclude_sentence_transformers():
    core = _project()["dependencies"]
    offenders = [
        d for d in core if d.lower().replace(" ", "").startswith("sentence-transformers")
    ]
    assert offenders == [], f"核心依赖不应含 sentence-transformers: {offenders}"


def test_embed_extra_contains_sentence_transformers():
    embed = _deps_of("embed")
    assert any(
        d.lower().startswith("sentence-transformers") for d in embed
    ), "embed extra 应含 sentence-transformers"


def test_dev_extra_has_no_sentence_transformers():
    dev = _deps_of("dev")
    assert not any(
        d.lower().startswith("sentence-transformers") for d in dev
    ), "dev extra 不应含 sentence-transformers"
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run --extra dev pytest tests/unit/test_pyproject_embed_extra.py -v`
Expected: FAIL（`test_core_deps_exclude_sentence_transformers` 与 `test_embed_extra_contains_sentence_transformers` 失败——依赖还在核心里）

- [ ] **Step 3: 修改 pyproject.toml**

`[project] dependencies` 中删除这一行：

```toml
    "sentence-transformers>=3.0",
```

`[project.optional-dependencies]` 在 `dev = [` 之前新增：

```toml
embed = [
    "sentence-transformers>=3.0",
]
```

- [ ] **Step 4: pytest.ini 注册 marker**

`markers =` 块内（`embedding:` 行之后）追加一行：

```ini
    no_embed: marks tests that must run without sentence-transformers installed (#519)
```

- [ ] **Step 5: 修改 CI（Core/Full 补 embed extra）**

`.github/workflows/integration-test.yml`：

- Core job 的 Install 步骤（约 209 行）：`run: uv sync --extra dev` → `run: uv sync --extra dev --extra embed`
- Core job 的 Run core tests（约 214 行）：`uv run pytest tests/test_core_workflow.py tests/test_integration.py -v --timeout=400 --tb=short` → 前缀改 `uv run --extra dev --extra embed pytest ...`
- Full job 的 Install 步骤（约 267 行）：同上改 `--extra dev --extra embed`
- Full job 的 Run full test suite（约 272 行）：`uv run pytest tests/ -v ...` → `uv run --extra dev --extra embed pytest tests/ -v ...`
- **Fast job 与 lint job 不动**（`uv sync --extra dev` 天然无 embed，正是 no_embed 测试的运行环境）

- [ ] **Step 6: .gitignore 追加（若缺失）**

Run: `grep -n "^\.venv-noembed/" .gitignore || echo ".venv-noembed/" >> .gitignore`

- [ ] **Step 7: 重算 lock 并刷新 dev 环境**

```bash
uv lock
uv sync --extra dev --extra embed
```

Expected: lock 更新（torch 族移入 embed 组）；dev 环境仍含 sentence-transformers。

- [ ] **Step 8: 运行结构测试确认通过**

Run: `uv run --extra dev pytest tests/unit/test_pyproject_embed_extra.py -v`
Expected: PASS（3 个用例）

- [ ] **Step 9: 建立 no-embed 测试环境并验证**

```bash
uv venv .venv-noembed
UV_PROJECT_ENVIRONMENT=.venv-noembed uv sync --extra dev
.venv-noembed/bin/python -c "import importlib.util; assert importlib.util.find_spec('sentence_transformers') is None; print('noembed OK')"
.venv-noembed/bin/python -m pytest tests/unit/test_pyproject_embed_extra.py -v
```

Expected: `noembed OK`；3 个用例 PASS。

- [ ] **Step 10: 快速回归（确认拆分未破坏既有 fast 测试，在 no-embed 环境跑——这正是它的意义）**

Run: `.venv-noembed/bin/python -m pytest tests/unit -m "not embedding and not slow" -q`
Expected: PASS（若有因缺包失败的用例，逐个确认是否隐性依赖模型库：属 no_embed 场景的加 `@pytest.mark.no_embed` + `skipif`，属必须真实模型的加 `@pytest.mark.embedding`，改动随本 task 提交并在 commit body 说明）

- [ ] **Step 11: Commit**

```bash
git add pyproject.toml pytest.ini .github/workflows/integration-test.yml .gitignore uv.lock tests/unit/test_pyproject_embed_extra.py
git commit -m "chore(deps): move sentence-transformers to [embed] extra + CI matrix (#519)"
```

---

### Task 2: 可用性探测与安装提示（embedding_backend 新接口，A1/A2）

**Files:**

- Modify: `jfox/embedding_backend.py`（模块顶部、`_GPU_DEFAULT_MODEL` 之前插入新代码段）
- Create: `tests/unit/test_embed_availability.py`

**Interfaces:**

- Consumes: `jfox.daemon.process.is_daemon_running` / `_get_daemon_url`、`jfox.daemon.client.DaemonClient`（既有）
- Produces（后续所有 task 依赖，签名逐字固定）:
  - `is_local_embed_available() -> bool`（find_spec + 模块级缓存）
  - `is_embedding_service_available() -> bool`（本地或 daemon；`JFOX_DAEMON_PROCESS` 下只看本地）
  - `reset_embed_availability_cache() -> None`
  - `class EmbedDependencyMissingError(RuntimeError)`
  - `format_embed_hint(context: str = "") -> str`

- [ ] **Step 1: 写失败测试**

创建 `tests/unit/test_embed_availability.py`：

```python
"""A1/A2 (#519): 语义组件可用性探测、缓存与安装提示。"""

import importlib.util
import sys
from unittest.mock import MagicMock, patch

import pytest

import jfox.embedding_backend as eb
from jfox.embedding_backend import (
    EmbedDependencyMissingError,
    format_embed_hint,
    is_embedding_service_available,
    is_local_embed_available,
    reset_embed_availability_cache,
)


@pytest.fixture(autouse=True)
def _reset_probe_cache():
    reset_embed_availability_cache()
    yield
    reset_embed_availability_cache()


class TestLocalProbe:
    def test_true_when_spec_found(self, monkeypatch):
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
        assert is_local_embed_available() is True

    def test_false_when_spec_missing(self, monkeypatch):
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
        assert is_local_embed_available() is False

    def test_cached_after_first_probe(self, monkeypatch):
        calls = []

        def counting(name):
            calls.append(name)
            return None

        monkeypatch.setattr(importlib.util, "find_spec", counting)
        is_local_embed_available()
        is_local_embed_available()
        assert len(calls) == 1  # 第二次走缓存

        reset_embed_availability_cache()
        is_local_embed_available()
        assert len(calls) == 2  # reset 后重查


class TestServiceAvailability:
    def test_local_available_short_circuits(self, monkeypatch):
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
        with patch("jfox.daemon.process.is_daemon_running") as m:
            assert is_embedding_service_available() is True
            m.assert_not_called()  # 本地可用时不查 daemon

    def test_daemon_running_and_client_available(self, monkeypatch):
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
        monkeypatch.setattr("jfox.daemon.process.is_daemon_running", lambda: True)
        monkeypatch.setattr("jfox.daemon.process._get_daemon_url", lambda: "http://127.0.0.1:18700")
        with patch("jfox.daemon.client.DaemonClient") as client_cls:
            client_cls.return_value.available = True
            assert is_embedding_service_available() is True

    def test_daemon_not_running(self, monkeypatch):
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
        monkeypatch.setattr("jfox.daemon.process.is_daemon_running", lambda: False)
        assert is_embedding_service_available() is False

    def test_daemon_process_env_ignores_daemon(self, monkeypatch):
        # daemon 进程内部不得代理自己：JFOX_DAEMON_PROCESS 下只看本地
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
        monkeypatch.setattr("jfox.daemon.process.is_daemon_running", lambda: True)
        monkeypatch.setenv("JFOX_DAEMON_PROCESS", "1")
        assert is_embedding_service_available() is False

    def test_daemon_check_exception_is_false(self, monkeypatch):
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

        def boom():
            raise RuntimeError("pid file corrupted")

        monkeypatch.setattr("jfox.daemon.process.is_daemon_running", boom)
        assert is_embedding_service_available() is False


class TestHintAndError:
    def test_hint_contains_four_elements(self):
        hint = format_embed_hint("语义检索")
        assert "UV_TORCH_BACKEND=cpu" in hint
        assert 'jfox-cli[embed]' in hint
        assert "https://download.pytorch.org/whl/cpu" in hint
        assert "index rebuild" in hint
        assert "语义检索" in hint  # context 前缀拼入

    def test_hint_default_context(self):
        hint = format_embed_hint()
        assert hint.startswith("[提示]")

    def test_error_carries_hint(self):
        err = EmbedDependencyMissingError(format_embed_hint("写入语义索引"))
        assert "UV_TORCH_BACKEND" in str(err)
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run --extra dev --extra embed pytest tests/unit/test_embed_availability.py -v`
Expected: FAIL（ImportError：函数不存在）

- [ ] **Step 3: 实现（embedding_backend.py 顶部，`_GPU_DEFAULT_MODEL` 之前）**

在 `import` 块追加 `import importlib.util`（与既有 stdlib import 并列），然后插入：

```python
# ---------------------------------------------------------------------------
# 语义组件可用性探测（#519 轻量化安装：sentence-transformers 拆入 [embed] extra）
# ---------------------------------------------------------------------------

_local_embed_available: Optional[bool] = None


def is_local_embed_available() -> bool:
    """本地 sentence-transformers 是否已安装。

    importlib.util.find_spec 探测（不执行 import，毫秒级），
    结果模块级缓存——包的安装状态在进程生命周期内不变。
    """
    global _local_embed_available
    if _local_embed_available is None:
        try:
            _local_embed_available = (
                importlib.util.find_spec("sentence_transformers") is not None
            )
        except Exception:
            _local_embed_available = False
    return _local_embed_available


def reset_embed_availability_cache() -> None:
    """清空本地探测缓存（测试后门）。"""
    global _local_embed_available
    _local_embed_available = None


def is_embedding_service_available() -> bool:
    """是否存在可用的 embedding 服务：本地组件或外部 daemon 任一可用。

    本地探测走缓存；daemon 状态每次实时检查（可起可停）。
    daemon 进程内部（JFOX_DAEMON_PROCESS）只看本地组件，不代理自己。
    """
    if is_local_embed_available():
        return True
    if os.environ.get("JFOX_DAEMON_PROCESS"):
        return False
    try:
        from .daemon.process import _get_daemon_url, is_daemon_running

        if not is_daemon_running():
            return False
        from .daemon.client import DaemonClient

        return DaemonClient(_get_daemon_url()).available
    except Exception:
        return False


class EmbedDependencyMissingError(RuntimeError):
    """本地语义组件缺失且无可用 daemon（#519）。message 含安装提示。"""


def format_embed_hint(context: str = "") -> str:
    """拼装统一安装提示文案（纯函数）。context 为场景前缀，如 '语义检索'。"""
    prefix = context if context else "该操作"
    return (
        f"[提示] {prefix}需要语义检索组件（jfox 核心为精简安装，未包含）。\n"
        '  GPU 机器:  uv tool install "jfox-cli[embed]"\n'
        '  CPU 机器:  UV_TORCH_BACKEND=cpu uv tool install "jfox-cli[embed]"\n'
        '  pip 用户:  pip install "jfox-cli[embed]"\n'
        "             （CPU 机器先执行: pip install torch --index-url "
        "https://download.pytorch.org/whl/cpu）\n"
        "补装后运行 `jfox index rebuild` 可补建语义索引。"
    )
```

- [ ] **Step 4: 运行确认通过（两个环境各跑一次）**

```bash
uv run --extra dev --extra embed pytest tests/unit/test_embed_availability.py -v
.venv-noembed/bin/python -m pytest tests/unit/test_embed_availability.py -v
```

Expected: 两环境均 PASS（测试全部 mock，与环境无关）。

- [ ] **Step 5: Commit**

```bash
git add jfox/embedding_backend.py tests/unit/test_embed_availability.py
git commit -m "feat(embed): availability probes + missing-dependency error + install hint (#519)"
```

---

### Task 3: `EmbeddingBackend.load()` 的 ImportError 转专用异常

**Files:**

- Modify: `jfox/embedding_backend.py:105-140`（`load()` 方法内）
- Test: `tests/unit/test_embed_availability.py`（追加 class）

**Interfaces:**

- Consumes: Task 2 的 `EmbedDependencyMissingError` / `format_embed_hint`
- Produces: `load()` 在本地组件缺失时抛 `EmbedDependencyMissingError`（daemon 路径与 `encode(daemon_only=True)` 语义不变）——Task 4/5/6 依赖此行为

- [ ] **Step 1: 追加失败测试**

在 `tests/unit/test_embed_availability.py` 末尾追加：

```python
class TestLoadRaisesTypedError:
    def test_load_without_package_raises_typed(self, monkeypatch):
        # sys.modules 置 None 使 `from sentence_transformers import ...` 抛 ImportError
        monkeypatch.setitem(sys.modules, "sentence_transformers", None)
        monkeypatch.setattr("jfox.daemon.process.is_daemon_running", lambda: False)

        backend = eb.EmbeddingBackend(model_name="BAAI/bge-small-zh-v1.5", device="cpu")
        with pytest.raises(EmbedDependencyMissingError) as exc_info:
            backend.load()
        assert "UV_TORCH_BACKEND" in str(exc_info.value)
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run --extra dev --extra embed pytest tests/unit/test_embed_availability.py::TestLoadRaisesTypedError -v`
Expected: FAIL（当前抛普通异常或直接成功加载，不是 `EmbedDependencyMissingError`）

- [ ] **Step 3: 实现（load() 内的 import 包一层）**

`load()` 中把：

```python
        try:
            from sentence_transformers import SentenceTransformer
```

改为：

```python
        try:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # #519 轻量化安装：本地语义组件缺失
                raise EmbedDependencyMissingError(
                    format_embed_hint("加载本地嵌入模型")
                ) from exc
```

（外层既有 `try/except Exception` 结构与其余逻辑全部不动。）

- [ ] **Step 4: 运行确认通过 + 既有 load 测试回归**

```bash
uv run --extra dev --extra embed pytest tests/unit/test_embed_availability.py tests/unit/test_embedding_local_load.py -v
.venv-noembed/bin/python -m pytest tests/unit/test_embed_availability.py -v
```

Expected: PASS（`test_embedding_local_load.py` 自带 stub，应不受影响）。

- [ ] **Step 5: Commit**

```bash
git add jfox/embedding_backend.py tests/unit/test_embed_availability.py
git commit -m "feat(embed): load() raises EmbedDependencyMissingError on missing package (#519)"
```

---

### Task 4: VectorStore 守卫——typed re-raise + 行保留

**Files:**

- Modify: `jfox/vector_store.py`（顶部 import、`__init__`、`add_note`、`search`、`add_or_update_note`）
- Create: `tests/unit/test_vector_store_embed_guard.py`

**Interfaces:**

- Consumes: Task 2 的 `EmbedDependencyMissingError`、`is_embedding_service_available`；Task 3 的 load() 抛错路径
- Produces:
  - `VectorStore.last_embed_warning: Optional[str]` 实例属性（CLI add/edit 展示用，Task 6）
  - `add_note` / `search` 在组件缺失时 re-raise `EmbedDependencyMissingError`（其余异常行为不变）
  - `add_or_update_note` 在服务不可用时**不删除既有行**、直接走 `add_note`（typed 异常照抛）——Task 6/8 依赖

- [ ] **Step 1: 写失败测试**

创建 `tests/unit/test_vector_store_embed_guard.py`：

```python
"""#519: VectorStore 守卫——typed re-raise、warning 记录、替换写入不删既有行。"""

import pytest

import jfox.vector_store as vs_mod
from jfox.embedding_backend import EmbedDependencyMissingError, format_embed_hint
from jfox.models import Note, NoteType
from jfox.note import create_note
from jfox.vector_store import VectorStore


def _typed_error():
    return EmbedDependencyMissingError(format_embed_hint("写入语义索引"))


@pytest.fixture
def store(tmp_path):
    s = VectorStore(persist_directory=tmp_path / "chroma")
    s.init()
    return s


def _raising_backend(monkeypatch):
    """backend.encode_single 抛 typed error（模拟无组件且无 daemon）。"""
    import jfox.embedding_backend as eb

    class StubBackend:
        def encode_single(self, text):
            raise _typed_error()

    monkeypatch.setattr(eb, "get_backend", lambda: StubBackend())


def _seed_row(store, note_id):
    store.collection.add(
        ids=[note_id],
        embeddings=[[0.1] * 8],
        documents=["既有向量行"],
        metadatas=[{"title": "t", "type": "fleeting", "filepath": "x", "tags": ""}],
    )


class TestAddNote:
    def test_raises_typed_and_records_warning(self, store, monkeypatch):
        _raising_backend(monkeypatch)
        note = create_note("内容", title="标题")
        with pytest.raises(EmbedDependencyMissingError):
            store.add_note(note)
        assert store.last_embed_warning is not None
        assert "UV_TORCH_BACKEND" in store.last_embed_warning


class TestSearch:
    def test_raises_typed_and_records_warning(self, store, monkeypatch):
        _raising_backend(monkeypatch)
        with pytest.raises(EmbedDependencyMissingError):
            store.search("查询")
        assert store.last_embed_warning is not None


class TestAddOrUpdatePreservesRow:
    def test_no_delete_when_service_unavailable(self, store, monkeypatch):
        note = create_note("内容", title="标题")
        _seed_row(store, note.id)
        _raising_backend(monkeypatch)
        # 服务不可用（本地 False 且无 daemon）→ 不删行
        monkeypatch.setattr(vs_mod, "is_embedding_service_available", lambda: False)
        with pytest.raises(EmbedDependencyMissingError):
            store.add_or_update_note(note)
        assert store.collection.get(ids=[note.id])["ids"] == [note.id]  # 行保留

    def test_replaces_when_service_available(self, store, monkeypatch):
        note = create_note("内容", title="标题")
        _seed_row(store, note.id)
        monkeypatch.setattr(vs_mod, "is_embedding_service_available", lambda: True)

        import numpy as np

        class WorkingBackend:
            def encode_single(self, text):
                return np.zeros(8, dtype=float)  # ndarray：add_note 会调 .tolist()

        import jfox.embedding_backend as eb

        monkeypatch.setattr(eb, "get_backend", lambda: WorkingBackend())
        assert store.add_or_update_note(note) is True  # 删除 + 重写成功
        assert store.collection.get(ids=[note.id])["ids"] == [note.id]
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run --extra dev --extra embed pytest tests/unit/test_vector_store_embed_guard.py -v`
Expected: FAIL（无 `last_embed_warning` 属性 / typed 异常被吞成 False/[]）

- [ ] **Step 3: 实现**

`jfox/vector_store.py` 顶部（`from .models import Note` 之后）追加：

```python
from .embedding_backend import EmbedDependencyMissingError, is_embedding_service_available
```

`__init__` 中 `self.last_dimension_warning` 行后追加：

```python
        # #519 轻量化安装：语义组件缺失时由 add_note/search 设置，CLI 展示
        self.last_embed_warning: Optional[str] = None
```

`add_note` 的 `except Exception as e:` **之前**插入：

```python
        except EmbedDependencyMissingError as e:
            # #519：组件缺失是可降级事实，记录后原样上抛，由调用层决策
            self.last_embed_warning = str(e)
            raise
```

`search` 的 `except Exception as e:` **之前**插入同样的三行（提示语不变，`str(e)` 已含场景）。

`add_or_update_note` 整体替换为：

```python
    def add_or_update_note(self, note: Note) -> bool:
        """添加或更新笔记（如果已存在则更新）"""
        # #519 不变量：编码成功前不得删除既有行。服务不可用时直接走 add_note
        # （它会抛 EmbedDependencyMissingError 且不产生任何删除副作用）。
        if not is_embedding_service_available():
            return self.add_note(note)
        # 先尝试删除旧的（如果存在）
        try:
            collection = self.collection
            assert collection is not None
            collection.delete(ids=[note.id])
        except Exception:
            pass  # 可能不存在，忽略错误

        # 添加新的
        return self.add_note(note)
```

- [ ] **Step 4: 运行确认通过 + vector_store 既有测试回归**

```bash
uv run --extra dev --extra embed pytest tests/unit/test_vector_store_embed_guard.py -v
rg -l "vector_store" tests/unit --glob '*.py' | head -5
uv run --extra dev --extra embed pytest tests/unit/test_vector_store*.py tests/unit/test_dim_warning*.py -v 2>/dev/null || true
```

Expected: 新文件 PASS；如有 vector_store 相关既有测试文件，一并跑绿。

- [ ] **Step 5: Commit**

```bash
git add jfox/vector_store.py tests/unit/test_vector_store_embed_guard.py
git commit -m "feat(store): typed re-raise on missing embed + preserve rows on replace (#519)"
```

---

### Task 5: SearchEngine 双路径告警通道

**Files:**

- Modify: `jfox/search_engine.py`（顶部 import、`__init__`、`search`、`_semantic_search`、`_hybrid_search_with_k`）
- Create: `tests/unit/test_search_engine_embed_warning.py`

**Interfaces:**

- Consumes: Task 4 的 typed re-raise
- Produces: `HybridSearchEngine.last_embed_warning: Optional[str]`（每次 `search()` 开头清空）——CLI search/query/suggest-links 展示用（Task 7）

- [ ] **Step 1: 写失败测试**

创建 `tests/unit/test_search_engine_embed_warning.py`：

```python
"""#519: 搜索引擎双路径（semantic / hybrid）的 embed 缺失告警。"""

from types import SimpleNamespace

from jfox.embedding_backend import EmbedDependencyMissingError, format_embed_hint
from jfox.models import NoteType
from jfox.search_engine import HybridSearchEngine, SearchMode


class FakeVectorStore:
    def __init__(self, exc=None):
        self._exc = exc

    def search(self, *args, **kwargs):
        if self._exc:
            raise self._exc
        return []


class FakeBM25:
    needs_rebuild = False

    def __init__(self, results=None):
        self._results = results or []

    def search(self, *args, **kwargs):
        return self._results

    def check_stale_and_reload(self):
        pass


def _fake_note_loader(monkeypatch, note_id="n1"):
    import jfox.note as note_module

    fake = SimpleNamespace(
        id=note_id,
        title="标题",
        content="内容",
        type=NoteType.FLEETING,
        tags=[],
        archived=False,
        filepath=None,
    )
    monkeypatch.setattr(note_module, "load_note_by_id", lambda nid, cfg=None: fake)


def _engine(store, bm25):
    return HybridSearchEngine(vector_store=store, bm25_index=bm25)


def test_semantic_mode_returns_empty_with_warning(monkeypatch):
    _fake_note_loader(monkeypatch)
    typed = EmbedDependencyMissingError(format_embed_hint("语义检索"))
    engine = _engine(FakeVectorStore(exc=typed), FakeBM25())
    results = engine.search("查询", mode=SearchMode.SEMANTIC, include_archived=True)
    assert results == []
    assert engine.last_embed_warning is not None
    assert "UV_TORCH_BACKEND" in engine.last_embed_warning


def test_hybrid_mode_falls_back_to_bm25_with_warning(monkeypatch):
    _fake_note_loader(monkeypatch)
    typed = EmbedDependencyMissingError(format_embed_hint("语义检索"))
    engine = _engine(FakeVectorStore(exc=typed), FakeBM25(results=[
        {"note_id": "n1", "score": 1.0}
    ]))
    results = engine.search("查询", mode=SearchMode.HYBRID, include_archived=True)
    assert engine.last_embed_warning is not None
    assert len(results) >= 1  # BM25 兜底结果可见
    assert results[0]["id"] == "n1"


def test_search_clears_stale_warning(monkeypatch):
    _fake_note_loader(monkeypatch)
    engine = _engine(FakeVectorStore(), FakeBM25(results=[
        {"note_id": "n1", "score": 1.0}
    ]))
    engine.last_embed_warning = "旧告警"
    engine.search("查询", mode=SearchMode.KEYWORD, include_archived=True)
    assert engine.last_embed_warning is None
```

- [ ] **Step 2: 运行确认失败**

Run: `uv run --extra dev --extra embed pytest tests/unit/test_search_engine_embed_warning.py -v`
Expected: FAIL（无 `last_embed_warning` 属性）

- [ ] **Step 3: 实现**

`jfox/search_engine.py` 顶部追加：

```python
from .embedding_backend import EmbedDependencyMissingError, format_embed_hint
```

`__init__` 末尾（`self.rrf_k = rrf_k` 后）追加：

```python
        # #519 轻量化安装：semantic/hybrid 路径遇组件缺失时写入，CLI 展示
        self.last_embed_warning: Optional[str] = None
```

`search()` 方法体第一行（`if mode == ...` 之前）：

```python
        self.last_embed_warning = None
```

`_semantic_search` 的 `except Exception as e:` **之前**插入：

```python
        except EmbedDependencyMissingError:
            self.last_embed_warning = format_embed_hint("语义检索")
            return []
```

`_hybrid_search_with_k` 中语义调用块改为（在既有 `except Exception` 前加 typed 分支）：

```python
        try:
            semantic_results = self.vector_store.search(
                query, top_k=search_k, note_type=note_type, tags=tags
            )
        except EmbedDependencyMissingError:
            # #519：组件缺失 → BM25-only 融合（RRF 自然退化），写告警供 CLI 展示
            self.last_embed_warning = format_embed_hint("语义检索")
            semantic_results = []
        except Exception as e:
            logger.warning(f"Semantic search failed in hybrid mode: {e}")
```

（`semantic_results = []` 预置行保留，BM25 调用块不动。）

- [ ] **Step 4: 运行确认通过 + 引擎既有测试回归**

```bash
uv run --extra dev --extra embed pytest tests/unit/test_search_engine_embed_warning.py -v
uv run --extra dev --extra embed pytest tests/test_hybrid_search.py -m "not embedding and not slow" -q --timeout=120
```

Expected: PASS。

- [ ] **Step 5: Commit**

```bash
git add jfox/search_engine.py tests/unit/test_search_engine_embed_warning.py
git commit -m "feat(search): engine-level embed-missing warning on semantic+hybrid paths (#519)"
```

---

### Task 6: save 层降级 + add/edit CLI 展示 + A4 集成测试

**Files:**

- Modify: `jfox/note.py`（顶部 import、`save_note:151-190`、`update_note:585-645`）
- Modify: `jfox/cli.py`（`_add_note_impl` 的 dim-warning 展示区 `~650-700`；`_edit_impl` 结果输出区 `~1881-1935`）
- Create: `tests/integration/test_no_embed_degradation.py`

**Interfaces:**

- Consumes: Task 4 的 typed re-raise / `last_embed_warning` / 行保留
- Produces: `save_note`/`update_note` 在组件缺失时返回 `True`（文件 + BM25 落盘，向量跳过）；CLI `add`/`edit` 的 JSON `semantic_index_warning` 字段与 table 黄字提示——A4 验收；集成测试文件后续 task 追加用例

- [ ] **Step 1: 写失败集成测试（A4）**

创建 `tests/integration/test_no_embed_degradation.py`：

```python
"""#519 no-embed 集成测试（A4/A5/A6/A7/A10）。

必须在无 sentence-transformers 环境执行（CI Fast job 天然满足；
本地用 .venv-noembed/bin/python -m pytest 运行）。
"""

import pytest

from jfox.embedding_backend import is_local_embed_available

pytestmark = [
    pytest.mark.no_embed,
    pytest.mark.integration,
    pytest.mark.skipif(
        is_local_embed_available(), reason="需在无 sentence-transformers 环境执行 (#519)"
    ),
]


def _seed_vector_row(kb_name: str, note_id: str):
    """直接经 ChromaDB 预置 dummy 向量行（不经 embedding，模拟既有索引）。"""
    from jfox.config import use_kb
    from jfox.vector_store import get_vector_store

    with use_kb(kb_name):
        store = get_vector_store()
        store.init()
        store.collection.add(
            ids=[note_id],
            embeddings=[[0.1] * 8],
            documents=["既有向量行"],
            metadatas=[{"title": "t", "type": "fleeting", "filepath": "x", "tags": ""}],
        )


def _get_vector_ids(kb_name: str, note_id: str):
    from jfox.config import use_kb
    from jfox.vector_store import get_vector_store

    with use_kb(kb_name):
        store = get_vector_store()
        store.init()
        return store.collection.get(ids=[note_id])["ids"]


class TestAddDegradation:  # A4
    def test_add_creates_note_bm25_skips_vector(self, cli):
        result = cli.add("轻量安装降级测试内容", title="轻量安装")
        assert result.returncode == 0
        data = result.json()
        assert data["success"] is True
        # 提示出现且含安装指引
        assert "semantic_index_warning" in data
        assert "UV_TORCH_BACKEND" in data["semantic_index_warning"]
        # BM25 可检索到
        search = cli._run("search", "轻量安装", "--mode", "keyword")
        assert search.returncode == 0
        assert search.json()["total"] >= 1
        # 语义写入未发生（collection 为空）
        from jfox.config import use_kb
        from jfox.vector_store import get_vector_store

        with use_kb(cli.kb_name):
            store = get_vector_store()
            store.init()
            assert store.collection.count() == 0


class TestEditPreservesVectorRow:  # A4 行保留
    def test_edit_keeps_existing_row(self, cli):
        created = cli.add("编辑前内容", title="编辑测试")
        note_id = created.json()["note"]["id"]
        _seed_vector_row(cli.kb_name, note_id)

        edited = cli._run("edit", note_id, "--content", "编辑后内容轻量")
        assert edited.returncode == 0
        assert "semantic_index_warning" in edited.json()

        assert _get_vector_ids(cli.kb_name, note_id) == [note_id]  # 行未被删除
```

- [ ] **Step 2: 运行确认失败（no-embed 环境）**

Run: `.venv-noembed/bin/python -m pytest tests/integration/test_no_embed_degradation.py -v`
Expected: FAIL（add 返回非 0 或无 `semantic_index_warning`——向量 add 抛错被 save 层吞成 False）

同时确认 dev 环境下跳过：`uv run --extra dev --extra embed pytest tests/integration/test_no_embed_degradation.py -v` → SKIPPED。

- [ ] **Step 3: 实现 note.py**

顶部 import 区追加：

```python
from .embedding_backend import EmbedDependencyMissingError
```

`save_note` 中把：

```python
        if add_to_index:
            from .vector_store import get_vector_store

            vector_store = get_vector_store()
            vector_store.add_note(note)
```

改为：

```python
        if add_to_index:
            from .vector_store import get_vector_store

            vector_store = get_vector_store()
            try:
                vector_store.add_note(note)
            except EmbedDependencyMissingError:
                # #519 轻量化安装：组件缺失 → 跳过向量索引；文件已写、BM25 继续
                logger.info("语义组件不可用，跳过向量索引（#519）")
```

`update_note` 中把：

```python
        if add_to_index:
            # 先删除旧索引，再添加新索引
            try:
                from .vector_store import get_vector_store

                vector_store = get_vector_store()
                vector_store.delete_note(note_obj.id)
                vector_store.add_note(note_obj)
            except Exception as e:
                logger.warning(f"Failed to update vector store index: {e}")
```

改为：

```python
        if add_to_index:
            # #519 替换写入走守卫原语：服务不可用时不删除既有行；
            # 组件缺失（typed）单独降级，其余异常保持既有 warning 语义
            try:
                from .vector_store import get_vector_store

                vector_store = get_vector_store()
                vector_store.add_or_update_note(note_obj)
            except EmbedDependencyMissingError:
                logger.info("语义组件不可用，跳过向量索引更新（#519）")
            except Exception as e:
                logger.warning(f"Failed to update vector store index: {e}")
```

- [ ] **Step 4: 实现 cli.py 的 add/edit 展示**

`_add_note_impl` JSON 分支（`dim_warning` 读取块之后、`print(output_json(result))` 之前）追加：

```python
            # #519 语义组件缺失提示（对齐 vector_dimension_warning 的读取模式）
            embed_warning = get_vector_store().last_embed_warning
            if embed_warning:
                result["semantic_index_warning"] = embed_warning
```

table 分支（末尾 dim_warning 展示块之后）追加：

```python
            embed_warning = get_vector_store().last_embed_warning
            if embed_warning:
                console.print(f"  [yellow]⚠ {embed_warning}[/yellow]")
                console.print("  [yellow]笔记已保存，但未进入语义索引。[/yellow]")
```

`_edit_impl` 成功分支：JSON `result` 构造后、`print(output_json(result))` 前追加：

```python
        from .vector_store import get_vector_store

        embed_warning = get_vector_store().last_embed_warning
        if embed_warning:
            result["semantic_index_warning"] = embed_warning
```

table 输出末尾（unresolved 提示之后）追加：

```python
        from .vector_store import get_vector_store

        embed_warning = get_vector_store().last_embed_warning
        if embed_warning:
            console.print(f"  [yellow]⚠ {embed_warning}[/yellow]")
            console.print("  [yellow]笔记已更新，但语义索引未刷新。[/yellow]")
```

- [ ] **Step 5: 运行确认通过（no-embed 环境）**

Run: `.venv-noembed/bin/python -m pytest tests/integration/test_no_embed_degradation.py -v`
Expected: PASS（2 个用例）。

- [ ] **Step 6: dev 环境回归（add/edit 正常路径不受影响）**

Run: `uv run --extra dev --extra embed pytest tests/unit -m "not embedding and not slow" -q --timeout=120`
Expected: PASS。

- [ ] **Step 7: Commit**

```bash
git add jfox/note.py jfox/cli.py tests/integration/test_no_embed_degradation.py
git commit -m "feat(core): save-layer degradation on missing embed + add/edit hint (#519)"
```

---

### Task 7: CLI search/query/suggest-links——semantic 拒绝 + warnings 展示（A5）

**Files:**

- Modify: `jfox/cli.py`（`_search_impl:783-886`、`search` 命令 `~887-915`、`_query_impl:1952-2015`、`_suggest_links_impl:2320-2358`）
- Test: `tests/integration/test_no_embed_degradation.py`（追加 class）

**Interfaces:**

- Consumes: Task 2 的探测函数与 `format_embed_hint`；Task 5 的 `get_search_engine().last_embed_warning`
- Produces: 拒绝协议 `{"success": false, "code": "embed_dependency_missing", "error": hint}`；降级 warnings `{"code": "embedding_unavailable", "message": ..., "fallback": "keyword"}`；query `effective_mode` 字段

- [ ] **Step 1: 追加失败测试（A5）**

`tests/integration/test_no_embed_degradation.py` 末尾追加：

```python
class TestSearchModes:  # A5
    def test_hybrid_degrades_to_bm25_with_warning(self, cli):
        cli.add("混合检索降级测试量子内容", title="混合降级")
        result = cli._run("search", "量子", "--mode", "hybrid")
        assert result.returncode == 0
        data = result.json()
        assert data["total"] >= 1
        assert data["warnings"][0]["code"] == "embedding_unavailable"
        assert data["warnings"][0]["fallback"] == "keyword"

    def test_semantic_mode_refused(self, cli):
        result = cli._run("search", "量子", "--mode", "semantic")
        assert result.returncode == 1
        data = result.json()
        assert data["code"] == "embed_dependency_missing"
        assert "UV_TORCH_BACKEND" in data["error"]

    def test_keyword_mode_unaffected(self, cli):
        cli.add("关键词模式不受影响内容", title="关键词模式")
        result = cli._run("search", "不受影响", "--mode", "keyword")
        assert result.returncode == 0
        assert result.json()["total"] >= 1
        assert "warnings" not in result.json()

    def test_query_degrades_with_effective_mode(self, cli):
        cli.add("联合查询降级测试内容", title="联合查询")
        result = cli._run("query", "联合查询")
        assert result.returncode == 0
        data = result.json()
        assert data["effective_mode"] == "keyword"
        assert data["warnings"][0]["code"] == "embedding_unavailable"
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv-noembed/bin/python -m pytest tests/integration/test_no_embed_degradation.py -v`
Expected: 新增 4 个用例 FAIL（无 warnings / semantic 未拒绝 / 无 effective_mode）。

- [ ] **Step 3: 实现共享 helper（cli.py，`output_json` 函数之后）**

```python
def _print_embed_refusal(output_format: str, context: str):
    """#519 显式语义入口拒绝：JSON 结构化错误（stdout）/ 人类模式 stderr。"""
    from .embedding_backend import format_embed_hint

    hint = format_embed_hint(context)
    if output_format == "json":
        print(output_json({"success": False, "code": "embed_dependency_missing", "error": hint}))
    else:
        import sys

        print(f"✗ {hint}", file=sys.stderr)


def _embed_warning_payload(engine) -> dict:
    """#519 降级 warnings 数组元素（fallback=keyword：搜索类降级）。"""
    return {
        "code": "embedding_unavailable",
        "message": engine.last_embed_warning,
        "fallback": "keyword",
    }
```

- [ ] **Step 4: 实现 `_search_impl`**

方法开头（`from .formatters import OutputFormatter` 之后）插入 semantic 守卫：

```python
    # #519 显式语义入口：服务不可用 → 拒绝，不静默换 BM25
    if search_mode == "semantic":
        from .embedding_backend import is_embedding_service_available

        if not is_embedding_service_available():
            _print_embed_refusal(output_format, "语义检索")
            raise typer.Exit(1)
```

在方法**开头**（构造 `result` 之前）取引擎单例，供搜索后读取：

```python
    from .search_engine import get_search_engine

    engine = get_search_engine()
```

JSON 分支：`result` 构造后、`print(output_json(result))` 前插入：

```python
    if engine.last_embed_warning:
        result["warnings"] = [_embed_warning_payload(engine)]
```

（放在 `if output_format == "json":` 内部 print 之前。）

table 分支（结果打印后、dim_warning 安全网之前）追加：

```python
    if engine.last_embed_warning:
        console.print(f"[yellow]⚠ {engine.last_embed_warning}[/yellow]")
```

末尾 dim_warning 安全网中「else: print stderr」分支之后追加：

```python
    if engine.last_embed_warning and output_format not in ("json", "table"):
        import sys

        print(f"⚠ {engine.last_embed_warning}", file=sys.stderr)
```

- [ ] **Step 5: `search` 命令加 `typer.Exit` 透传**

`search` 命令的 `except Exception as e:` **之前**插入：

```python
    except typer.Exit:
        raise
```

（否则拒绝路径的 `typer.Exit(1)` 被 `except Exception` 捕获，重复打印错误 JSON。）

- [ ] **Step 6: 实现 `_query_impl`**

`vector_results = note.search_notes(query_str, top_k=top)` 之前取引擎：

```python
    from .search_engine import get_search_engine

    engine = get_search_engine()
    vector_results = note.search_notes(query_str, top_k=top)
```

`result` 构造改为：

```python
    degraded = engine.last_embed_warning is not None
    result = {
        "query": query_str,
        "semantic_results": len(vector_results),  # 兼容保留（降级时实为 BM25 计数）
        "effective_mode": "keyword" if degraded else "hybrid",
        "results": enriched_results,
    }
    if degraded:
        result["warnings"] = [_embed_warning_payload(engine)]
```

非 JSON 输出路径（`console.print(f"[bold]Query:[bold] ...")` 之前）追加：

```python
    if degraded:
        console.print(f"[yellow]⚠ {engine.last_embed_warning}[/yellow]")
```

`query` 命令同样补 `except typer.Exit: raise`（若其 `except Exception` 之前缺失）。

- [ ] **Step 7: 实现 `_suggest_links_impl`**

`suggestions = note.suggest_links(...)` 之后追加：

```python
    from .search_engine import get_search_engine

    engine = get_search_engine()
    degraded = engine.last_embed_warning is not None
```

JSON 分支 result 构造后：

```python
    if degraded:
        result["warnings"] = [_embed_warning_payload(engine)]
```

table 分支（suggestions 打印前）：

```python
        if degraded:
            console.print("[yellow]⚠ 语义组件不可用，当前仅使用关键词匹配[/yellow]")
```

- [ ] **Step 8: 运行确认通过**

Run: `.venv-noembed/bin/python -m pytest tests/integration/test_no_embed_degradation.py -v`
Expected: PASS（6 个用例）。

- [ ] **Step 9: dev 环境回归（semantic 正常路径不受影响）**

Run: `uv run --extra dev --extra embed pytest tests/test_suggest_links.py -m "not embedding and not slow" -q --timeout=120`
Expected: PASS（suggest-links 正常路径 warning 不出现）。

- [ ] **Step 10: Commit**

```bash
git add jfox/cli.py tests/integration/test_no_embed_degradation.py
git commit -m "feat(cli): semantic refusal gate + degrade warnings for search/query/suggest-links (#519)"
```

---

### Task 8: `index rebuild` 降级——不清空向量库（A6）

**Files:**

- Modify: `jfox/cli.py`（`_index_impl` 的 `elif action == "rebuild":` 分支，约 2510-2560）
- Test: `tests/integration/test_no_embed_degradation.py`（追加 class）

**Interfaces:**

- Consumes: Task 2 探测 + hint；spec 不变量（不调用会 reset collection 的 `Indexer.index_all()`）
- Produces: rebuild 结果 `semantic_skipped: bool` + `warnings`（`fallback: "bm25_only"`）

- [ ] **Step 1: 追加失败测试（A6）**

```python
class TestIndexRebuild:  # A6
    def test_rebuild_bm25_only_preserves_vectors(self, cli):
        n1 = cli.add("重建保留测试甲", title="重建甲").json()["note"]["id"]
        n2 = cli.add("重建保留测试乙", title="重建乙").json()["note"]["id"]
        _seed_vector_row(cli.kb_name, n1)
        _seed_vector_row(cli.kb_name, n2)

        result = cli._run("index", "rebuild")
        assert result.returncode == 0
        data = result.json()
        assert data["semantic_skipped"] is True
        assert data["warnings"][0]["code"] == "embedding_unavailable"
        assert data["warnings"][0]["fallback"] == "bm25_only"
        assert data["bm25_rebuilt"] is True
        # 既有向量行保留
        assert _get_vector_ids(cli.kb_name, n1) == [n1]
        assert _get_vector_ids(cli.kb_name, n2) == [n2]
        # BM25 全量可检索
        search = cli._run("search", "重建甲", "--mode", "keyword")
        assert search.json()["total"] >= 1

    def test_rebuild_backlinks_still_works(self, cli):
        result = cli._run("index", "rebuild", "--backlinks")
        assert result.returncode == 0
        assert "backlinks_rebuilt" in result.json()
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv-noembed/bin/python -m pytest tests/integration/test_no_embed_degradation.py -v -k TestIndexRebuild`
Expected: FAIL（现状：rebuild 逐条 add_or_update 失败，无 `semantic_skipped` 字段；`--backlinks` 路径可能因语义失败中断）。

- [ ] **Step 3: 实现 `_index_impl` rebuild 分支**

把：

```python
        elif action == "rebuild":
            console.print("[yellow]Rebuilding index...[/yellow]")
            count = indexer.index_all()
```

改为：

```python
        elif action == "rebuild":
            from .embedding_backend import (
                format_embed_hint,
                is_embedding_service_available,
            )

            semantic_available = is_embedding_service_available()
            count = 0
            if semantic_available:
                console.print("[yellow]Rebuilding index...[/yellow]")
                count = indexer.index_all()
            else:
                # #519：无编码能力时不调用 index_all（它会 reset collection 清空向量库），
                # 只重建 BM25，既有向量行原样保留
                logger.info("语义组件不可用，跳过语义索引重建（#519）")
                console.print("[yellow]语义组件不可用，跳过语义索引重建（#519）[/yellow]")
```

`result` 构造改为：

```python
            result = {
                "success": True,
                "indexed": count,
                "semantic_skipped": not semantic_available,
                "bm25_rebuilt": bm25_success,
                "bm25_indexed": len(notes),
            }
            if not semantic_available:
                result["warnings"] = [
                    {
                        "code": "embedding_unavailable",
                        "message": format_embed_hint("重建语义索引"),
                        "fallback": "bm25_only",
                    }
                ]
```

table 输出分支（`console.print(f"[green]✓[/green] Indexed {count} notes")` 之后）追加：

```python
                if not semantic_available:
                    console.print(
                        f"[yellow]⚠ {format_embed_hint('重建语义索引')}[/yellow]"
                    )
```

（`--backlinks` 逻辑与 BM25 重建代码全部不动。）

- [ ] **Step 4: 运行确认通过**

Run: `.venv-noembed/bin/python -m pytest tests/integration/test_no_embed_degradation.py -v`
Expected: PASS（8 个用例）。

- [ ] **Step 5: Commit**

```bash
git add jfox/cli.py tests/integration/test_no_embed_degradation.py
git commit -m "feat(index): rebuild degrades to BM25-only without resetting vector store (#519)"
```

---

### Task 9: daemon 守卫 + status 块 + ingest-log/bulk-import 守卫（A7/A10）

**Files:**

- Modify: `jfox/cli.py`（`daemon:3242-`、`_status_impl:1027-1080`、`_ingest_log_impl:3025-`、`bulk_import:3128-`）
- Test: `tests/integration/test_no_embed_degradation.py`（追加两个 class）

**Interfaces:**

- Consumes: Task 2 探测函数；Task 7 的 `_print_embed_refusal`
- Produces: `status` 输出的 `embedding` 块（`local_package`/`daemon_running`/`service_available`）

- [ ] **Step 1: 追加失败测试（A7/A10）**

```python
class TestRefusalEntrypoints:  # A7
    def test_daemon_start_refused(self, cli):
        result = cli._run("daemon", "start", "--no-auto-summary", json_output=False)
        assert result.returncode == 1
        assert "UV_TORCH_BACKEND" in result.stderr

    def test_daemon_restart_refused(self, cli):
        result = cli._run("daemon", "restart", "--no-auto-summary", json_output=False)
        assert result.returncode == 1
        assert "UV_TORCH_BACKEND" in result.stderr

    def test_bulk_import_refused(self, cli, tmp_path):
        # bulk-import 的 --json/--no-json 默认 True → 拒绝时 stdout 输出结构化错误
        result = cli._run("bulk-import", str(tmp_path / "notexist.json"))
        assert result.returncode == 1
        data = result.json()
        assert data["code"] == "embed_dependency_missing"
        assert "UV_TORCH_BACKEND" in data["error"]

    def test_suggest_links_keyword_degradation(self, cli):
        cli.add("量子纠缠与拓扑序的关联笔记", title="量子纠缠")
        result = cli.suggest_links("量子纠缠专题笔记内容")
        assert result.returncode == 0
        data = result.json()
        assert data["warnings"][0]["code"] == "embedding_unavailable"
        keyword_hits = [s for s in data["suggestions"] if s["match_type"] == "keyword"]
        assert len(keyword_hits) >= 1  # 关键词降级仍给建议


class TestStatusEmbeddingBlock:  # A10
    def test_status_shows_availability(self, cli):
        result = cli._run("status")
        assert result.returncode == 0
        emb = result.json()["embedding"]
        assert emb["local_package"] is False
        assert emb["service_available"] is False
        assert emb["daemon_running"] is False
```

- [ ] **Step 2: 运行确认失败**

Run: `.venv-noembed/bin/python -m pytest tests/integration/test_no_embed_degradation.py -v`
Expected: 新增 5 个用例 FAIL。

- [ ] **Step 3: 实现 daemon 守卫**

`daemon` 函数的函数内 import 区（`from .daemon.process import ...` 附近）追加：

```python
    from .embedding_backend import format_embed_hint, is_local_embed_available
```

`if action == "start":` 分支第一行（auto-summary 检查之前）插入：

```python
            # #519 daemon 必须本地加载模型：组件缺失直接拒绝
            if not is_local_embed_available():
                import sys

                print(format_embed_hint("启动 embedding daemon"), file=sys.stderr)
                raise typer.Exit(1)
```

`elif action == "restart":` 分支第一行（`if enable_auto_summary:` 之前）插入同样四行（提示语改「重启 embedding daemon」）。

检查 `daemon` 函数尾部的 `except`：若存在 `except Exception` 而无 `except typer.Exit: raise`，在前面补上（模式同 Task 7 Step 5）。

- [ ] **Step 4: 实现 status 块**

`_status_impl` 中 `result = {...}` 构造之后、输出格式分支之前追加：

```python
    # #519 语义组件可用性（不触发模型加载）
    from .daemon.process import is_daemon_running
    from .embedding_backend import (
        is_embedding_service_available,
        is_local_embed_available,
    )

    result["embedding"] = {
        "local_package": is_local_embed_available(),
        "daemon_running": is_daemon_running(),
        "service_available": is_embedding_service_available(),
    }
```

table 分支（`table.add_row("Dimension", ...)` 之后）追加：

```python
        table.add_row(
            "Embed Component",
            "[green]installed[/green]" if result["embedding"]["local_package"] else "[yellow]not installed[/yellow]",
        )
        table.add_row(
            "Embed Service",
            "[green]available[/green]" if result["embedding"]["service_available"] else "[yellow]unavailable[/yellow]",
        )
```

- [ ] **Step 5: 实现 ingest-log / bulk-import 守卫**

`_ingest_log_impl` 函数体第一行（docstring 后）插入：

```python
    # #519 批量导入走本地模型路径：组件缺失直接拒绝
    from .embedding_backend import is_local_embed_available

    if not is_local_embed_available():
        _print_embed_refusal(output_format, "批量导入（ingest-log）")
        raise typer.Exit(1)
```

`bulk_import` 命令函数体（`try:` 之后、读取文件之前）插入：

```python
        from .embedding_backend import is_local_embed_available

        if not is_local_embed_available():
            hint = format_embed_hint("批量导入（bulk-import）")
            if json_output:
                print(output_json({"success": False, "code": "embed_dependency_missing", "error": hint}))
            else:
                import sys

                print(f"✗ {hint}", file=sys.stderr)
            raise typer.Exit(1)
```

（`bulk_import` 顶部需补 `from .embedding_backend import format_embed_hint`；`ingest_log`/`bulk_import` 命令的 `except Exception` 前补 `except typer.Exit: raise`，同 Task 7 模式。）

- [ ] **Step 6: 运行确认通过**

Run: `.venv-noembed/bin/python -m pytest tests/integration/test_no_embed_degradation.py -v`
Expected: PASS（13 个用例，覆盖 A4/A5/A6/A7/A10）。

- [ ] **Step 7: dev 环境回归**

```bash
uv run --extra dev --extra embed pytest tests/unit -m "not embedding and not slow" -q --timeout=120
```

Expected: PASS。

- [ ] **Step 8: Commit**

```bash
git add jfox/cli.py tests/integration/test_no_embed_degradation.py
git commit -m "feat(cli): daemon/status/bulk gates on missing embed component (#519)"
```

---

### Task 10: E2E 验证脚本 + README/AGENTS 文档（A8）

**Files:**

- Create: `scripts/verify_lightweight_install.sh`（chmod +x）
- Modify: `README.md`（安装章节、开发环境章节）
- Modify: `AGENTS.md`（「安装开发环境」命令）

**Interfaces:**

- Consumes: Task 1 的 wheel 打包结构
- Produces: A8 可执行验证；对外安装文档三段式

- [ ] **Step 1: 写 E2E 脚本**

创建 `scripts/verify_lightweight_install.sh`：

```bash
#!/usr/bin/env bash
# A8 (#519): 核心包轻量安装验证——零 nvidia-*、无 torch、CRUD/BM25 smoke。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT

echo "==> [1/5] uv build"
cd "$ROOT"
uv build --out-dir "$WORK/dist" >/dev/null

echo "==> [2/5] 独立 venv 安装 wheel"
uv venv "$WORK/venv" >/dev/null
uv pip install --python "$WORK/venv/bin/python" "$WORK"/dist/jfox_cli-*.whl >/dev/null

echo "==> [3/5] 断言零 nvidia-* / 无 torch / 无 sentence-transformers"
BAD="$(uv pip list --python "$WORK/venv/bin/python" 2>/dev/null \
  | grep -iE '^(nvidia-|torch |sentence-transformers)' || true)"
if [ -n "$BAD" ]; then
  echo "FAIL: 轻量安装包含重依赖："
  echo "$BAD"
  exit 1
fi

echo "==> [4/5] jfox --version"
"$WORK/venv/bin/jfox" --version

echo "==> [5/5] 隔离 HOME smoke：init / add / keyword search"
SMOKE_HOME="$WORK/home"
mkdir -p "$SMOKE_HOME"
HOME="$SMOKE_HOME" "$WORK/venv/bin/jfox" init --name smoke >/dev/null
HOME="$SMOKE_HOME" "$WORK/venv/bin/jfox" add "轻量安装冒烟测试内容" --title smoke >/dev/null
HOME="$SMOKE_HOME" "$WORK/venv/bin/jfox" search "冒烟" --mode keyword | grep -q '"total"'

echo "PASS: 轻量安装验证通过（零 nvidia-* / 无 torch / smoke OK）"
```

Run: `chmod +x scripts/verify_lightweight_install.sh`

- [ ] **Step 2: 运行脚本确认通过**

Run: `./scripts/verify_lightweight_install.sh`
Expected: 5 步全过，输出 `PASS: ...`。

- [ ] **Step 3: 改 README 安装章节**

安装章节替换为（保留既有 git 源说明，按三段式重组；具体措辞可顺 README 风格微调，四条安装命令一条不可少）：

````markdown
## 安装

### 默认安装（轻量，纯 CPU 友好）

```bash
uv tool install "jfox-cli"
# 或从源码: uv tool install "git+https://github.com/zhuxixi/jfox.git"
```

包含笔记 CRUD、BM25 关键词检索、知识图谱；**不含**语义向量检索（不下载 torch/CUDA，纯 CPU 机器零 nvidia 依赖）。

### 语义检索组件（可选）

```bash
# GPU 机器
uv tool install "jfox-cli[embed]"

# 纯 CPU 机器（UV_TORCH_BACKEND=cpu 让 uv 解析 CPU 版 torch，不拉 CUDA）
UV_TORCH_BACKEND=cpu uv tool install "jfox-cli[embed]"

# pip 用户（CPU 机器先执行: pip install torch --index-url https://download.pytorch.org/whl/cpu）
pip install "jfox-cli[embed]"
```

### 从 1.x 升级

2.0 起默认安装不再包含语义检索组件。原地升级（pip/uv 不卸载已装包）通常无感知；
重建环境后首次使用语义功能时，jfox 会打印同样的补装提示。补装后运行
`jfox index rebuild` 可补建语义索引。
````

（开发环境章节：`uv sync --extra dev` 改为 `uv sync --extra dev --extra embed`。）

- [ ] **Step 4: 改 AGENTS.md 安装命令**

「安装开发环境」两行命令改：

```bash
# 安装（使用 uv，推荐；embed 为语义组件，开发环境需要）
uv sync --extra dev --extra embed
```

- [ ] **Step 5: markdownlint 校验**

Run: `npx --yes markdownlint-cli2 "README.md" "AGENTS.md"`
Expected: 无输出（通过；CI 用 `npx --yes markdownlint-cli2@0.23.2 "**/*.md" "#node_modules" "#.venv"`，本地对改动文件校验即可）。

- [ ] **Step 6: Commit**

```bash
git add scripts/verify_lightweight_install.sh README.md AGENTS.md
git commit -m "docs+build: lightweight-install E2E script + 3-part install docs (#519)"
```

---

### Task 11: 全量验证与收尾

**Files:**

- Modify: 按验证结果修正（预期无或极少）

**Interfaces:**

- Consumes: 全部前置 task
- Produces: PR 就绪状态（本地 CR 前的最后校验）

- [ ] **Step 1: dev 环境全量快测**

```bash
uv run --extra dev --extra embed pytest tests/ -m "not embedding and not slow" --timeout=180 -q
```

Expected: PASS（含本计划新增全部 unit 测试；no_embed 集成用例在 dev 环境 SKIPPED 属预期）。

- [ ] **Step 2: no-embed 环境全量**

```bash
.venv-noembed/bin/python -m pytest tests/integration/test_no_embed_degradation.py tests/unit/test_embed_availability.py tests/unit/test_pyproject_embed_extra.py -v
```

Expected: PASS / SKIPPED（embedding 环境跳过的只有 skipif 项）。

- [ ] **Step 3: lint 三件套**

```bash
uv run --extra dev ruff check jfox/ tests/ scripts/ 2>/dev/null || uv run --extra dev ruff check jfox/ tests/
uv run --extra dev black --check jfox/ tests/
npx --yes markdownlint-cli2 "**/*.md" "#node_modules" "#.venv" "#.venv-noembed"
```

Expected: 全过（black 不过则 `uv run --extra dev black jfox/ tests/` 后重新提交修正）。

- [ ] **Step 4: 生成文档 drift 校验（CI lint job 同款）**

```bash
uv run --extra dev python scripts/generate_docs.py
git diff --exit-code -- docs/cli-reference.md docs/plugin-inventory.md
git ls-files --others --exclude-standard -- docs/cli-reference.md docs/plugin-inventory.md
```

Expected: 无 diff、无 untracked（本计划未改 help 文本，不应漂移；若漂移，将生成结果一并提交并检查原因）。

- [ ] **Step 5: E2E 脚本终跑**

Run: `./scripts/verify_lightweight_install.sh`
Expected: PASS。

- [ ] **Step 6: 验收矩阵对账自查**

对照 spec §8 逐项核对：A1–A8、A10 已有对应测试/脚本且本次全绿；A9 待 push 后看 CI Fast/Core；U1/U2 属发布后用户实测（PR 描述中标注 pending）。确认无遗漏后进入本地 CR。

- [ ] **Step 7: 修正提交（如有）**

按文件 stage 本次验证暴露的修正（逐个 `git add <file>`，遵守禁用 `git add -A`/`-u` 纪律）：

```bash
git add <具体文件>
git commit -m "chore: fix verification findings (#519)" || echo "nothing to fix"
```

---

## 验收对账（spec §8 ↔ task）

| 验收 | Task |
|------|------|
| A1/A2 | Task 2（+Task 3） |
| A3 | Task 1 |
| A4 | Task 6 |
| A5 | Task 7 |
| A6 | Task 8 |
| A7/A10 | Task 9 |
| A8 | Task 10 |
| A9 | Task 1（yml）+ push 后 CI 实跑 |
| U1/U2 | 发布后用户实测（不在本 plan 内，PR 描述标注 pending） |
