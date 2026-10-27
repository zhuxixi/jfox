# status backend 取数源改为 daemon 真实值 — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `jfox status` 的 `backend{type,model,dimension}` 在 daemon 运行中时显示 daemon 的真实值，并新增 `backend.source` 标明来源；无法确知维度时输出 `null` 而不是伪造 512。

**Architecture:** 在 `jfox/cli.py` 加一个纯函数 `_status_backend_payload(local, daemon_info)` 承载全部三态判断，`_status_impl` 只负责取数 + 渲染，json/yaml/table 三态共用同一 payload。`get_daemon_status()` 的 `dimension` 兜底从 512 改为 `None`，两处 `daemon status` 显示点改显式判空。

**Tech Stack:** Python 3.10+ / Typer / Rich / pytest（unit 为主，CliRunner in-process）

**Spec:** `docs/superpowers/specs/2026-10-27-status-backend-daemon-truth-design.md`（issue #363）

## Global Constraints

- 行宽 100，`black` + `ruff` 通过；注释中文，commit message 英文 conventional commits。
- 验收 ID 必须可双向追溯（spec §5 ↔ 本 plan 每个 task）。
- **禁止**把分支判断塞回 `_status_impl`——所有三态判断只在 `_status_backend_payload` 内，否则 A1 覆盖不到。
- `_status_impl` 对 `get_daemon_status` **必须在函数内** `from .daemon.process import ...`（照抄 `cli.py:3682-3688`），否则 A2/A3 的 patch 目标失效。
- 维度显示一律用显式 `is None` 判空，**禁止 `or "unknown"`**（degraded daemon 上报 `dimension: 0`，`or` 会把 `0` 吞成 `unknown`）。
- 不跑全量测试（~50min，按 AGENTS.md 交用户）；单元子集必须全绿。
- `git add` 按文件 stage，不用 `git add -A`。

---

### Task 1: 纯函数 `_status_backend_payload` + `_display_dimension`（A1、A8）

**Files:**
- Modify: `jfox/cli.py`（在 `_index_status_payload` 附近新增两个模块级函数，约 168 行前）
- Test: `tests/unit/test_status_backend_payload.py`（新建）

**Interfaces:**
- Produces:
  - `_status_backend_payload(local: dict, daemon_info: Optional[dict]) -> dict`
    - `local` 键：`type: str`（`backend.resolved_device`）、`model: Optional[str]`（`backend.model_name`）、`loaded: bool`（`backend.model is not None`）、`dimension: int`
    - `daemon_info` 键：`model`、`dimension`、`device`（缺键用 `.get` 兜底）
    - 返回键固定 `{type, model, dimension, source}`，`source ∈ {"daemon","local","unloaded"}`
  - `_display_dimension(value: Optional[int]) -> str`

- [ ] **Step 1: Write the failing test**

```python
"""#363 status backend 块组装纯函数单测（A1 + A8）。"""

from jfox.cli import _display_dimension, _status_backend_payload

LOCAL_LOADED = {"type": "cuda", "model": "BAAI/bge-m3", "loaded": True, "dimension": 1024}
LOCAL_PINNED_UNLOADED = {"type": "cpu", "model": "BAAI/bge-m3", "loaded": False, "dimension": 1024}
LOCAL_AUTO = {"type": "unknown", "model": None, "loaded": False, "dimension": 512}

DAEMON = {
    "pid": 19793,
    "host": "127.0.0.1",
    "port": 18700,
    "model": "BAAI/bge-m3",
    "dimension": 1024,
    "device": "cuda",
    "started_at": None,
}


class TestDaemonSource:
    """A1：daemon 在跑时完全覆盖本地值。"""

    def test_daemon_wins_over_local(self):
        assert _status_backend_payload(LOCAL_AUTO, DAEMON) == {
            "type": "cuda",
            "model": "BAAI/bge-m3",
            "dimension": 1024,
            "source": "daemon",
        }

    def test_missing_keys_fall_back_without_raising(self):
        assert _status_backend_payload(LOCAL_AUTO, {}) == {
            "type": "unknown",
            "model": "unknown",
            "dimension": None,
            "source": "daemon",
        }

    def test_degraded_daemon_passes_through_zero(self):
        """A8：degraded daemon 上报 dimension=0，必须原样透传。"""
        degraded = {"model": "unavailable", "dimension": 0, "device": "none"}
        assert _status_backend_payload(LOCAL_AUTO, degraded) == {
            "type": "none",
            "model": "unavailable",
            "dimension": 0,
            "source": "daemon",
        }


class TestLocalSource:
    """A1：同进程已 load 时用真实维度。"""

    def test_loaded_backend_uses_real_dimension(self):
        assert _status_backend_payload(LOCAL_LOADED, None) == {
            "type": "cuda",
            "model": "BAAI/bge-m3",
            "dimension": 1024,
            "source": "local",
        }


class TestUnloadedSource:
    """A1：未加载时不伪造维度。"""

    def test_auto_model_has_null_dimension(self):
        assert _status_backend_payload(LOCAL_AUTO, None) == {
            "type": "unknown",
            "model": "auto (未加载)",
            "dimension": None,
            "source": "unloaded",
        }

    def test_pinned_model_keeps_name_but_no_dimension(self):
        payload = _status_backend_payload(LOCAL_PINNED_UNLOADED, None)
        assert payload["model"] == "BAAI/bge-m3"
        assert payload["dimension"] is None
        assert payload["source"] == "unloaded"

    def test_key_set_is_stable(self):
        for local, daemon in ((LOCAL_AUTO, DAEMON), (LOCAL_LOADED, None), (LOCAL_AUTO, None)):
            assert set(_status_backend_payload(local, daemon)) == {
                "type",
                "model",
                "dimension",
                "source",
            }


class TestDisplayDimension:
    """A9 的显示侧：None→unknown，0 保留。"""

    def test_none_renders_unknown(self):
        assert _display_dimension(None) == "unknown"

    def test_zero_is_kept(self):
        assert _display_dimension(0) == "0"

    def test_int_renders_plain(self):
        assert _display_dimension(1024) == "1024"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_status_backend_payload.py -q`
Expected: FAIL — `ImportError: cannot import name '_status_backend_payload' from 'jfox.cli'`

- [ ] **Step 3: Write minimal implementation**

在 `jfox/cli.py` 的 `_index_status_payload` 定义之前插入：

```python
def _status_backend_payload(local: dict, daemon_info: Optional[dict]) -> dict:
    """#363 组装 status 的 backend 块（纯函数，json/yaml/table 三态共用）。

    daemon 在跑时它就是 embedding 的真实服务方，用其自报值覆盖本地快照；
    否则退回进程内 backend 快照，并用 source 标明可信度。
    """
    if daemon_info is not None:
        return {
            "type": daemon_info.get("device") or "unknown",
            "model": daemon_info.get("model") or "unknown",
            "dimension": daemon_info.get("dimension"),
            "source": "daemon",
        }

    device = local.get("type") or "unknown"
    if local.get("loaded"):
        return {
            "type": device,
            "model": local.get("model"),
            "dimension": local.get("dimension"),
            "source": "local",
        }
    return {
        "type": device,
        "model": local.get("model") or "auto (未加载)",
        "dimension": None,
        "source": "unloaded",
    }


def _display_dimension(value: Optional[int]) -> str:
    """维度显示：None→unknown；0 与正整数照常显示（degraded daemon 上报 0）。"""
    return "unknown" if value is None else str(value)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_status_backend_payload.py -q`
Expected: PASS（12 passed）

- [ ] **Step 5: Commit**

```bash
git add jfox/cli.py tests/unit/test_status_backend_payload.py
git commit -m "feat(status): add _status_backend_payload pure function for daemon-first backend block (#363)"
```

---

### Task 2: `get_daemon_status()` 维度兜底改 None + 两处显示点判空（A7、A9）

**Files:**
- Modify: `jfox/daemon/process.py:444`（`"dimension": health.get("dimension", 512)`）
- Modify: `jfox/cli.py:3703`（`_print_daemon_status`）、`jfox/cli.py:3821`（`daemon status` 分支）
- Test: `tests/unit/test_daemon_process.py`（新增 `TestGetDaemonStatus`）、`tests/unit/test_daemon_cli.py`（新增 `TestDaemonStatusDimensionDisplay`）

**Interfaces:**
- Produces: `get_daemon_status()["dimension"]` 类型为 `Optional[int]`（缺键时 `None`，不再伪造 512）。下游只有两处 table 显示点，均在本 task 内改完。

- [ ] **Step 1: Write the failing tests**

追加到 `tests/unit/test_daemon_process.py` 末尾：

```python
class TestGetDaemonStatus:
    """A7：get_daemon_status() 本体行为（此前零覆盖）。"""

    @staticmethod
    def _patch(monkeypatch, health, pid_data=None):
        from jfox.daemon import process

        monkeypatch.setattr(process, "_read_pid_file", lambda: pid_data)
        monkeypatch.setattr(process, "_http_health_check", lambda *a, **k: health)
        removed = []
        monkeypatch.setattr(process, "_remove_pid_file", lambda: removed.append(1))
        return process, removed

    def test_assembles_dict_from_health(self, monkeypatch):
        health = {"pid": 347901, "model": "BAAI/bge-m3", "dimension": 1024, "device": "cuda"}
        pid_data = {"host": "127.0.0.1", "port": 18700, "started_at": "t0"}
        process, removed = self._patch(monkeypatch, health, pid_data)

        info = process.get_daemon_status()

        assert info == {
            "pid": 347901,
            "host": "127.0.0.1",
            "port": 18700,
            "model": "BAAI/bge-m3",
            "dimension": 1024,
            "device": "cuda",
            "started_at": "t0",
        }
        assert removed == []

    def test_health_failure_returns_none_and_cleans_pid_file(self, monkeypatch):
        process, removed = self._patch(monkeypatch, None)

        assert process.get_daemon_status() is None
        assert removed == [1]

    def test_missing_dimension_key_is_none_not_512(self, monkeypatch):
        process, _ = self._patch(monkeypatch, {"pid": 1, "model": "m", "device": "cpu"})

        assert process.get_daemon_status()["dimension"] is None
```

追加到 `tests/unit/test_daemon_cli.py` 末尾：

```python
class TestDaemonStatusDimensionDisplay:
    """A9：维度 None→unknown，0→0（degraded 不被 or 吞掉）。"""

    @staticmethod
    def _invoke(runner, dimension):
        info = {
            "pid": 1,
            "port": 18700,
            "model": "BAAI/bge-m3",
            "dimension": dimension,
            "device": "cpu",
        }
        with patch("jfox.daemon.process.get_daemon_status", return_value=info):
            return runner.invoke(app, ["daemon", "status"])

    def test_none_dimension_renders_unknown(self, runner):
        result = self._invoke(runner, None)

        assert result.exit_code == 0, result.output
        assert "unknown" in result.output
        assert "None" not in result.output

    def test_zero_dimension_renders_zero(self, runner):
        result = self._invoke(runner, 0)

        assert result.exit_code == 0, result.output
        assert "unknown" not in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_daemon_process.py::TestGetDaemonStatus tests/unit/test_daemon_cli.py::TestDaemonStatusDimensionDisplay -q`
Expected: `test_missing_dimension_key_is_none_not_512` FAIL（得到 512）；`test_none_dimension_renders_unknown` FAIL（输出含 `None`）

- [ ] **Step 3: Implement**

`jfox/daemon/process.py`：

```python
        "dimension": health.get("dimension"),
```

`jfox/cli.py:3703`（`_print_daemon_status`）：

```python
            dimension = info.get("dimension")
            table.add_row("维度", "unknown" if dimension is None else str(dimension))
```

`jfox/cli.py:3821`（`daemon status` 分支）：

```python
                dimension = info.get("dimension")
                table.add_row("维度", "unknown" if dimension is None else str(dimension))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_daemon_process.py tests/unit/test_daemon_cli.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/daemon/process.py jfox/cli.py tests/unit/test_daemon_process.py tests/unit/test_daemon_cli.py
git commit -m "fix(daemon): stop fabricating dimension 512 when /health omits it (#363)"
```

---

### Task 3: `_status_impl` 接线三格式共用 payload（A2、A3、A4）

**Files:**
- Modify: `jfox/cli.py:1233-1248`（取数）、`jfox/cli.py:1283-1285`（table 三行）
- Test: `tests/unit/test_status_daemon_source.py`（新建）

**Interfaces:**
- Consumes: `_status_backend_payload`、`_display_dimension`（Task 1）、`get_daemon_status() -> Optional[dict]`（Task 2）
- Produces: `jfox status` 的 `backend` 块 = payload；table 新增 `Backend Source` 行

- [ ] **Step 1: Write the failing tests**

```python
"""#363 status 的 backend 接线：daemon 值优先、三格式同源（A2/A3/A4）。"""

import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from jfox.cli import app

runner = CliRunner()

DAEMON = {
    "pid": 19793,
    "host": "127.0.0.1",
    "port": 18700,
    "model": "BAAI/bge-m3",
    "dimension": 1024,
    "device": "cuda",
    "started_at": None,
}


@pytest.fixture
def no_daemon():
    with patch("jfox.daemon.process.get_daemon_status", return_value=None), patch(
        "jfox.daemon.process.is_daemon_running", return_value=False
    ):
        yield


@pytest.fixture
def running_daemon():
    with patch("jfox.daemon.process.get_daemon_status", return_value=DAEMON), patch(
        "jfox.daemon.process.is_daemon_running", return_value=True
    ):
        yield


def _invoke(cli, *args):
    result = runner.invoke(app, ["status", "--kb", cli.kb_name, *args])
    assert result.exit_code == 0, result.output
    return result


class TestDaemonRunning:
    """A2/A4：daemon 在跑时三格式都用 daemon 值。"""

    def test_json_backend_block(self, cli, running_daemon):
        data = json.loads(_invoke(cli, "--json").output)

        assert data["backend"] == {
            "type": "cuda",
            "model": "BAAI/bge-m3",
            "dimension": 1024,
            "source": "daemon",
        }

    def test_daemon_model_not_shadowed_by_local_fallback(self, cli, running_daemon):
        data = json.loads(_invoke(cli, "--json").output)

        assert data["backend"]["model"] != "auto (未加载)"

    def test_yaml_backend_block(self, cli, running_daemon):
        out = _invoke(cli, "--format", "yaml").output

        assert "source: daemon" in out
        assert "dimension: 1024" in out

    def test_table_shows_source_row(self, cli, running_daemon):
        out = _invoke(cli).output

        assert "Backend Source" in out
        assert "daemon" in out


class TestNoDaemon:
    """A3：无 daemon 时不伪造维度。"""

    def test_json_backend_block(self, cli, no_daemon):
        data = json.loads(_invoke(cli, "--json").output)

        assert data["backend"]["source"] == "unloaded"
        assert data["backend"]["dimension"] is None
        assert data["backend"]["model"] == "auto (未加载)"

    def test_table_dimension_renders_unknown(self, cli, no_daemon):
        out = _invoke(cli).output

        assert "Backend Source" in out
        assert "unloaded" in out
        assert "512" not in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_status_daemon_source.py -q`
Expected: FAIL — `KeyError: 'source'` / 断言失败（当前 `backend` 无 `source`，dimension 为 512）

- [ ] **Step 3: Implement**

`jfox/cli.py` 的 `_status_impl`，把 1233-1248 改为：

```python
    # #363 daemon 是 embedding 的真实服务方：在跑就用它的自报值，不再读本地兜底
    from .daemon.process import get_daemon_status, is_daemon_running
    from .embedding_backend import get_backend

    backend = get_backend()
    local = {
        "type": backend.resolved_device,
        "model": backend.model_name,
        "loaded": backend.model is not None,
        "dimension": backend.dimension,
    }

    result = {
        "knowledge_base": {
            "path": str(config.base_dir),
            "exists": config.base_dir.exists(),
        },
        "stats": stats,
        "backend": _status_backend_payload(local, get_daemon_status()),
    }
```

并把后面 1250-1255 的重复 import 段改为只保留 embedding 相关：

```python
    # #519 语义组件可用性（不触发模型加载）
    from .embedding_backend import (
        is_embedding_service_available,
        is_local_embed_available,
    )
```

table 三行（1283-1285）改为：

```python
        table.add_row("Backend", result["backend"]["type"])
        table.add_row("Model", result["backend"]["model"])
        table.add_row("Dimension", _display_dimension(result["backend"]["dimension"]))
        table.add_row("Backend Source", result["backend"]["source"])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_status_daemon_source.py tests/test_cli_format.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/cli.py tests/unit/test_status_daemon_source.py
git commit -m "fix(status): read backend state from daemon health instead of lazy local defaults (#363)"
```

---

### Task 4: schema 文档同步 + 静态防漂移测试（A5）

**Files:**
- Modify: `docs/json-schemas.md:45`（status 行）、`docs/json-schemas.md:166-175`（破坏性变更表）
- Test: `tests/unit/test_json_schema_contract_doc.py`（追加两条）

**Interfaces:**
- Consumes: `backend{type,model,dimension,source}` 字段集（Task 1/3）

- [ ] **Step 1: Write the failing tests**

追加到 `tests/unit/test_json_schema_contract_doc.py`：

```python
def test_status_backend_documents_source_field():
    """#363：status 的 backend 块新增 source 字段，文档必须跟上。"""
    text = DOC.read_text(encoding="utf-8")
    assert "backend{type,model,dimension,source}" in text


def test_status_dimension_nullability_in_breaking_changes():
    """#363：dimension 从 int 变 int|null，属破坏性变更，必须在表里登记。"""
    text = DOC.read_text(encoding="utf-8")
    assert "`backend.dimension` 可为 `null`" in text
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_json_schema_contract_doc.py -q`
Expected: 两条新用例 FAIL

- [ ] **Step 3: Update the doc**

`docs/json-schemas.md:45` 整行替换为：

```markdown
| `status` | `success, knowledge_base{path,exists}, stats, backend{type,model,dimension,source}, embedding{local_package,daemon_running,service_available}`（#519 可用性块；#363 `backend.source` 取 `daemon`/`local`/`unloaded`，`unloaded` 时 `dimension` 为 `null`） | 嵌套三段 | `{success, error}` |
```

破坏性变更表末尾追加一行：

```markdown
| `status` | `backend.dimension` 恒为 int（未加载时伪造默认 512） | `backend.dimension` 可为 `null`（当 `backend.source="unloaded"`）；新增 `backend.source` 字段 |
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_json_schema_contract_doc.py -q`
Expected: PASS

另外跑 markdownlint 确认文档合规：`npx --yes markdownlint-cli2 docs/json-schemas.md`

- [ ] **Step 5: Commit**

```bash
git add docs/json-schemas.md tests/unit/test_json_schema_contract_doc.py
git commit -m "docs(schema): document status backend.source and nullable dimension (#363)"
```

---

### Task 5: 回归子集 + 格式检查（A6）

**Files:** 无代码改动（只验证）

- [ ] **Step 1: 跑相关测试子集**

Run:
```bash
uv run pytest tests/unit/test_status_backend_payload.py tests/unit/test_status_daemon_source.py \
  tests/unit/test_daemon_process.py tests/unit/test_daemon_cli.py \
  tests/unit/test_json_schema_contract_doc.py tests/test_cli_format.py \
  tests/test_json_schema_contract.py -q
```
Expected: 全绿

- [ ] **Step 2: 格式检查**

Run:
```bash
uv run black --check jfox/cli.py jfox/daemon/process.py tests/unit/test_status_backend_payload.py tests/unit/test_status_daemon_source.py tests/unit/test_daemon_process.py tests/unit/test_daemon_cli.py tests/unit/test_json_schema_contract_doc.py
uv run ruff check jfox/cli.py jfox/daemon/process.py tests/unit/
npx --yes markdownlint-cli2 docs/superpowers/specs/2026-10-27-status-backend-daemon-truth-design.md docs/superpowers/plans/2026-10-27-status-backend-daemon-truth.md docs/json-schemas.md
```
Expected: 全绿（black 需要格式化则先 `uv run black <files>` 再重跑）

- [ ] **Step 3: 真机冒烟（实现者自测，替代部分 U1）**

Run（worktree 内）:
```bash
uv run jfox status --json | python3 -c "import json,sys; print(json.load(sys.stdin)['backend'])"
uv run jfox daemon status
```
Expected: 若本机 daemon 在跑，两命令的 model / dimension / device 一致且 `source == "daemon"`；若未跑，`source == "unloaded"` 且 `dimension` 为 `None`。**这是实现者自测，U1/U2 仍需用户在合入后的构建上确认。**

- [ ] **Step 4: Commit（如有格式化改动）**

```bash
git add -u
git commit -m "style: black formatting for #363 changes"
```

---

## 验收对账

| 验收 ID | 对应 Task | 结果 |
|---|---|---|
| A1 纯函数三态 | Task 1 | 待填 |
| A2 三格式一致 | Task 3 | 待填 |
| A3 无 daemon 不伪造 | Task 3 | 待填 |
| A4 daemon 值不被遮蔽 | Task 3 | 待填 |
| A5 schema 防漂移 | Task 4 | 待填 |
| A6 无回归 | Task 5 | 待填 |
| A7 get_daemon_status 本体 | Task 2 | 待填 |
| A8 degraded 透传 | Task 1 | 待填 |
| A9 维度显示 | Task 2 | 待填 |
| U1 真 daemon 一致 | 用户实测 | pending |
| U2 停 daemon 退化可读 | 用户实测 | pending |
| U3 KB 笔记回写 | 用户授权后 | pending |
