# Index Status Persist 实现计划（#539）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Work from:** `/home/elling/git-repo/github/jfox/.pi/worktrees/issue-539-index-status-persist`（所有路径基于此 worktree，禁碰 main checkout）

**Goal:** `index status` 只显示真实持久化状态——删除三个 watcher 内存死字段（含 errors 段），补上 `bm25_indexed`（现成 BM25 计数）与 `last_rebuild`（新 `.zk/index_state.json` 状态文件，rebuild 成功路径原子写入）。

**Architecture:** 三层——持久层（新模块 `jfox/index_state.py` 的 load/save 纯函数对）、组装层（cli.py 的 `_index_status_payload` 纯函数）、命令层（status 分支重写 + rebuild/rebuild-bm25 成功路径写状态）。schema 文档同 PR 同步 + 静态防漂移测试。

**Tech Stack:** Python 3.10+ stdlib（json/tempfile/os.replace）、Typer CLI、pytest（unit/static/integration，in-process `runner.invoke` 为主）。

**Spec:** `docs/superpowers/specs/2026-10-09-index-status-persist-design.md`（验收矩阵 A1-A6/U1-U2 见其 §6）

## Global Constraints

- 只允许改动：`jfox/index_state.py`（新建）、`jfox/cli.py`、`docs/json-schemas.md`、`tests/unit/test_index_state.py`（新建）、`tests/unit/test_index_status_payload.py`（新建）、`tests/integration/test_index_status_persist.py`（新建）、`tests/unit/test_json_schema_contract_doc.py`（新建）、`tests/unit/test_index_kb_param.py`（仅 :79 一处断言更新）。不碰 `jfox/indexer.py`、`jfox/daemon/`、`index verify`、其余任何现有测试。
- 新字段名固定：`bm25_indexed`、`last_rebuild`；删除字段：`total_indexed`、`last_indexed`、`pending_changes`（status 语境）+ "Recent Errors" 段。禁用 `total_indexed` 装新语义（与 verify 的真实字段冲突）。
- 状态文件：`cfg.zk_dir / "index_state.json"`（与 chroma_dir 同源推导）；内容 `{"last_rebuild": ISO8601, "semantic": bool, "notes": int}`；写入必须 temp+rename 原子；读容错（无文件/损坏/非 dict → None，不抛）。
- 写入点仅 rebuild / rebuild-bm25 成功路径（rebuild 以 `bm25_success` 为准，rebuild-bm25 以其 `success` 为准）；失败不写。
- `_index_status_payload` 为纯函数（无 IO、无全局读取）；payload 函数与文件 IO 不得互相耦合。
- 测试命令统一 `uv run --extra dev --extra embed pytest …`（裸 `uv run` 会反向重同步环境）；语义探针相关测试必须 `patch("jfox.embedding_backend.is_embedding_service_available", return_value=False)` 钉住（防本机 daemon 环境分歧，KB 已知坑）。
- Python 行宽 100（black/ruff）；改动 md 过 `npx --yes markdownlint-cli2`；`git add` 按文件 stage，禁止 `git add -A`；commit message 英文 conventional 格式。

---

### Task 1: `jfox/index_state.py` 持久层 + 单测 [A1]

**Files:**

- Create: `jfox/index_state.py`
- Test: `tests/unit/test_index_state.py`（新建）

**Interfaces:**

- Consumes: `ZKConfig.zk_dir`（鸭子类型，仅用该属性）
- Produces: `load_index_state(cfg=None) -> dict | None`；`save_index_state(state: dict, cfg=None) -> bool`；`build_rebuild_state(semantic: bool, notes: int, now: datetime | None = None) -> dict`（后续 task 依赖这三个签名）

- [ ] **Step 1: 写失败测试**（新建 `tests/unit/test_index_state.py`，完整内容）

```python
"""#539 index_state 状态文件读写单测（.zk/index_state.json）。"""

import json
from datetime import datetime
from pathlib import Path

from jfox.index_state import build_rebuild_state, load_index_state, save_index_state


class _CfgStub:
    """仅提供 zk_dir 属性的最小配置桩（鸭子类型）。"""

    def __init__(self, root: Path):
        self.zk_dir = root / ".zk"


def test_load_missing_returns_none(tmp_path):
    assert load_index_state(_CfgStub(tmp_path)) is None


def test_load_corrupt_json_returns_none(tmp_path):
    cfg = _CfgStub(tmp_path)
    cfg.zk_dir.mkdir(parents=True)
    (cfg.zk_dir / "index_state.json").write_text("{broken", encoding="utf-8")
    assert load_index_state(cfg) is None


def test_load_non_dict_returns_none(tmp_path):
    cfg = _CfgStub(tmp_path)
    cfg.zk_dir.mkdir(parents=True)
    (cfg.zk_dir / "index_state.json").write_text("[1, 2]", encoding="utf-8")
    assert load_index_state(cfg) is None


def test_save_then_load_roundtrip(tmp_path):
    cfg = _CfgStub(tmp_path)
    state = build_rebuild_state(
        semantic=False, notes=3, now=datetime(2026, 10, 9, 21, 0, 0)
    )
    assert save_index_state(state, cfg) is True
    assert load_index_state(cfg) == state


def test_save_atomic_leaves_no_temp_files(tmp_path):
    cfg = _CfgStub(tmp_path)
    save_index_state(build_rebuild_state(semantic=True, notes=1), cfg)
    assert [p for p in cfg.zk_dir.iterdir() if p.suffix == ".tmp"] == []
    assert json.loads((cfg.zk_dir / "index_state.json").read_text(encoding="utf-8"))[
        "semantic"
    ] is True


def test_build_rebuild_state_shape():
    s = build_rebuild_state(
        semantic=True, notes=9, now=datetime(2026, 10, 9, 8, 0, 0)
    )
    assert s == {"last_rebuild": "2026-10-09T08:00:00", "semantic": True, "notes": 9}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run --extra dev --extra embed pytest tests/unit/test_index_state.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'jfox.index_state'`

- [ ] **Step 3: 实现**（新建 `jfox/index_state.py`，完整内容）

```python
"""索引状态持久层（#539）：.zk/index_state.json 的读与原子写。

`index status` 的 last_rebuild 事实来源；`index rebuild` / `rebuild-bm25`
成功路径写入。纯文件 IO，无索引/模型依赖。
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .config import ZKConfig, config

STATE_FILENAME = "index_state.json"


def _state_path(cfg: Optional[ZKConfig] = None) -> Path:
    use_cfg = cfg or config
    return use_cfg.zk_dir / STATE_FILENAME


def load_index_state(cfg: Optional[ZKConfig] = None) -> Optional[dict]:
    """读取索引状态；无文件、损坏 JSON 或非 dict 一律返回 None（容错不抛）。"""
    path = _state_path(cfg)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save_index_state(state: dict, cfg: Optional[ZKConfig] = None) -> bool:
    """原子写入索引状态（temp + os.replace）；返回是否成功。"""
    path = _state_path(cfg)
    tmp: Optional[str] = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        return False
    finally:
        if tmp is not None and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def build_rebuild_state(
    semantic: bool, notes: int, now: Optional[datetime] = None
) -> dict:
    """构造一次成功 rebuild 的状态记录（纯函数，now 可注入便于测试）。"""
    ts = now or datetime.now()
    return {"last_rebuild": ts.isoformat(), "semantic": semantic, "notes": notes}
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run --extra dev --extra embed pytest tests/unit/test_index_state.py -q`
Expected: PASS（6 个全绿）

- [ ] **Step 5: Commit**

```bash
git add jfox/index_state.py tests/unit/test_index_state.py
git commit -m "feat(index): add index_state persistence module for .zk/index_state.json (#539)"
```

---

### Task 2: payload 纯函数 + status 分支重写 [A2, A3]

**Files:**

- Modify: `jfox/cli.py`（新增模块级 `_index_status_payload`；重写 status 分支）
- Test: `tests/unit/test_index_status_payload.py`（新建）；`tests/integration/test_index_status_persist.py`（新建，本 task 先写 status 部分）

**Interfaces:**

- Consumes: Task 1 的 `load_index_state`；既有 `bm25_index.get_stats()`（键 `indexed/version/index_path/index_exists`）、`vector_store.get_stats()`（键含 `total_notes`）
- Produces: `_index_status_payload(vs_stats: dict, bm25_stats: dict, state: dict | None) -> dict`，返回 `{"vector_store": vs_stats, "bm25_indexed": int, "last_rebuild": str | None}`

- [ ] **Step 1: 写失败测试**（新建 `tests/unit/test_index_status_payload.py`，完整内容）

```python
"""#539 _index_status_payload 组装纯函数单测。"""

from jfox.cli import _index_status_payload


def test_payload_fields_and_none_state():
    vs = {"total_notes": 5, "persist_directory": "/tmp/x"}
    bm25 = {"indexed": 4, "version": 2, "index_path": "p", "index_exists": True}
    payload = _index_status_payload(vs, bm25, None)
    assert set(payload) == {"vector_store", "bm25_indexed", "last_rebuild"}
    assert payload["vector_store"] is vs
    assert payload["bm25_indexed"] == 4
    assert payload["last_rebuild"] is None


def test_payload_with_state():
    state = {"last_rebuild": "2026-10-09T21:00:00", "semantic": False, "notes": 7}
    payload = _index_status_payload({}, {"indexed": 7}, state)
    assert payload["bm25_indexed"] == 7
    assert payload["last_rebuild"] == "2026-10-09T21:00:00"


def test_payload_missing_indexed_key_defaults_zero():
    payload = _index_status_payload({}, {}, None)
    assert payload["bm25_indexed"] == 0
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run --extra dev --extra embed pytest tests/unit/test_index_status_payload.py -q`
Expected: FAIL — `ImportError: cannot import name '_index_status_payload'`

- [ ] **Step 3: 实现 payload 函数**（`jfox/cli.py`，放在 `_print_embed_refusal` 函数之后）

```python
def _index_status_payload(
    vs_stats: dict, bm25_stats: dict, state: Optional[dict]
) -> dict:
    """#539 组装 index status 输出（纯函数，JSON/table 两态共用取数源）。"""
    return {
        "vector_store": vs_stats,
        "bm25_indexed": bm25_stats.get("indexed", 0),
        "last_rebuild": (state or {}).get("last_rebuild"),
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run --extra dev --extra embed pytest tests/unit/test_index_status_payload.py -q`
Expected: PASS（3 个全绿）

- [ ] **Step 5: 重写 status 分支**（`jfox/cli.py` `_index_impl` 内，`if action == "status":` 到 errors 段结束）

删除原块：

```python
        if action == "status":
            stats = indexer.get_stats()
            vs_stats = vector_store.get_stats()

            result = {
                "total_indexed": stats.total_indexed,
                "last_indexed": (stats.last_indexed.isoformat() if stats.last_indexed else None),
                "pending_changes": stats.pending_changes,
                "vector_store": vs_stats,
            }

            if output_format == "json":
                print(output_json({"success": True, **result}))
            else:
                table = Table(title="Index Status")
                table.add_column("Property", style="cyan")
                table.add_column("Value", style="green")
                table.add_row("Total Indexed", str(stats.total_indexed))
                table.add_row("Last Indexed", str(stats.last_indexed or "Never"))
                table.add_row("Pending Changes", str(stats.pending_changes))
                table.add_row("Vector Store Notes", str(vs_stats.get("total_notes", 0)))
                console.print(table)

                if stats.errors:
                    console.print("\n[yellow]Recent Errors:[/yellow]")
                    for err in stats.errors[-5:]:
                        console.print(f"  - {err}")
```

替换为：

```python
        if action == "status":
            # #539：只显示真实持久化状态（watcher 内存计数器在 CLI 一次性进程中
            # 结构性读不到非零值，已删除）
            from .bm25_index import get_bm25_index
            from .index_state import load_index_state

            vs_stats = vector_store.get_stats()
            bm25_stats = get_bm25_index().get_stats()
            state = load_index_state(config)
            payload = _index_status_payload(vs_stats, bm25_stats, state)

            if output_format == "json":
                print(output_json({"success": True, **payload}))
            else:
                table = Table(title="Index Status")
                table.add_column("Property", style="cyan")
                table.add_column("Value", style="green")
                table.add_row(
                    "Vector Store Notes", str(payload["vector_store"].get("total_notes", 0))
                )
                table.add_row("BM25 Indexed", str(payload["bm25_indexed"]))
                table.add_row("Last Rebuild", str(payload["last_rebuild"] or "Never"))
                console.print(table)
```

- [ ] **Step 6: 写 status 集成测试**（新建 `tests/integration/test_index_status_persist.py`，本 task 写入以下部分；rebuild 部分留 Task 3 追加）

```python
"""#539 index status 持久化集成测试（in-process runner，模式同 test_index_kb_param）。"""

import json

from typer.testing import CliRunner

from jfox.cli import app

runner = CliRunner()


class TestIndexStatusFields:
    """A3：status 输出字段集合与 table 模式。"""

    @staticmethod
    def _reset_global_config_cache():
        from jfox import global_config as gc
        from jfox import kb_manager as km

        km._kb_manager = None
        if gc._global_config_manager is not None:
            gc._global_config_manager._config = None
        gc._global_config_manager = None

    def test_status_json_fields_no_dead_fields(self, cli):
        self._reset_global_config_cache()
        result = runner.invoke(app, ["index", "status", "--kb", cli.kb_name, "--json"])
        assert result.exit_code == 0, result.output
        data = json.loads(result.output)
        assert data["success"] is True
        assert set(data) == {"success", "vector_store", "bm25_indexed", "last_rebuild"}
        assert "total_indexed" not in data
        assert "pending_changes" not in data
        assert "last_indexed" not in data
        # 全新临时库无 rebuild 记录
        assert data["last_rebuild"] is None

    def test_status_table_mode_renders(self, cli):
        self._reset_global_config_cache()
        result = runner.invoke(app, ["index", "status", "--kb", cli.kb_name])
        assert result.exit_code == 0, result.output
        assert "Last Rebuild" in result.output
        assert "Total Indexed" not in result.output
```

- [ ] **Step 7: 跑集成测试确认通过**

Run: `uv run --extra dev --extra embed pytest tests/integration/test_index_status_persist.py -q`
Expected: PASS（2 个全绿；rebuild 追加用例在 Task 3）

- [ ] **Step 8: Commit**

```bash
git add jfox/cli.py tests/unit/test_index_status_payload.py tests/integration/test_index_status_persist.py
git commit -m "feat(index): status shows persistent state only - drop watcher counters, add bm25_indexed/last_rebuild (#539)"
```

---

### Task 3: rebuild 写入点 + 落盘集成测试 [A4]

**Files:**

- Modify: `jfox/cli.py`（rebuild 与 rebuild-bm25 两处成功路径）
- Test: `tests/integration/test_index_status_persist.py`（追加 TestIndexRebuildState 类）

**Interfaces:**

- Consumes: Task 1 的 `build_rebuild_state` / `save_index_state`
- Produces: rebuild 成功后 `.zk/index_state.json` 存在且 `last_rebuild`/`semantic`/`notes` 正确；rebuild-bm25 同

- [ ] **Step 1: 写失败测试**（`tests/integration/test_index_status_persist.py` 追加）

```python
class TestIndexRebuildState:
    """A4：rebuild / rebuild-bm25 成功路径落盘状态。"""

    @staticmethod
    def _reset_global_config_cache():
        from jfox import global_config as gc
        from jfox import kb_manager as km

        km._kb_manager = None
        if gc._global_config_manager is not None:
            gc._global_config_manager._config = None
        gc._global_config_manager = None

    def test_rebuild_bm25_writes_state(self, cli):
        self._reset_global_config_cache()
        r = runner.invoke(app, ["index", "rebuild-bm25", "--kb", cli.kb_name, "--json"])
        assert r.exit_code == 0, r.output

        from jfox.config import config, use_kb

        with use_kb(cli.kb_name):
            from jfox.index_state import load_index_state

            state = load_index_state(config)
        assert state is not None
        assert state["semantic"] is False
        assert isinstance(state["notes"], int)
        assert isinstance(state["last_rebuild"], str)

        # status 立即可见
        r2 = runner.invoke(app, ["index", "status", "--kb", cli.kb_name, "--json"])
        data = json.loads(r2.output)
        assert data["last_rebuild"] == state["last_rebuild"]

    def test_rebuild_semantic_skipped_still_writes_state(self, cli):
        self._reset_global_config_cache()
        from unittest.mock import patch

        # 钉住语义探针为不可用：走 #519 降级路径（不触模型，且不受本机 daemon 影响）
        with patch(
            "jfox.embedding_backend.is_embedding_service_available",
            return_value=False,
        ):
            r = runner.invoke(app, ["index", "rebuild", "--kb", cli.kb_name, "--json"])
        assert r.exit_code == 0, r.output
        assert json.loads(r.output)["semantic_skipped"] is True

        from jfox.config import config, use_kb

        with use_kb(cli.kb_name):
            from jfox.index_state import load_index_state

            state = load_index_state(config)
        assert state is not None
        assert state["semantic"] is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run --extra dev --extra embed pytest tests/integration/test_index_status_persist.py::TestIndexRebuildState -q`
Expected: FAIL — `assert state is not None`（当前无写入点，状态文件不存在）

- [ ] **Step 3: 实现两处写入点**（`jfox/cli.py`）

(a) `rebuild` 分支：在 `bm25_success = bm25_index.rebuild_from_notes(notes)` 之后、`result = {` 之前插入：

```python
            # #539：成功路径落盘索引状态（失败不写）
            if bm25_success:
                from .index_state import build_rebuild_state, save_index_state

                save_index_state(
                    build_rebuild_state(semantic=semantic_available, notes=len(notes)),
                    config,
                )
```

(b) `rebuild-bm25` 分支：在 `success = bm25_index.rebuild_from_notes(notes)` 之后、`result = {` 之前插入：

```python
        # #539：成功路径落盘索引状态（失败不写）
        if success:
            from .index_state import build_rebuild_state, save_index_state

            save_index_state(
                build_rebuild_state(semantic=False, notes=len(notes)), config
            )
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run --extra dev --extra embed pytest tests/integration/test_index_status_persist.py -q`
Expected: PASS（4 个全绿）

- [ ] **Step 5: Commit**

```bash
git add jfox/cli.py tests/integration/test_index_status_persist.py
git commit -m "feat(index): persist rebuild state to .zk/index_state.json on success (#539)"
```

---

### Task 4: schema 文档同步 + 静态防漂移 + 旧断言更新 [A5, A6]

**Files:**

- Modify: `docs/json-schemas.md`（:57 行 status 字段清单）
- Create: `tests/unit/test_json_schema_contract_doc.py`
- Modify: `tests/unit/test_index_kb_param.py`（仅 :79 一处）

**Interfaces:**

- Consumes: 无
- Produces: 文档 status 行 = `success, vector_store, bm25_indexed, last_rebuild`

- [ ] **Step 1: 写失败测试**（新建 `tests/unit/test_json_schema_contract_doc.py`，完整内容）

```python
"""#539 schema 文档与 index status 实现的静态防漂移测试。"""

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DOC = REPO_ROOT / "docs" / "json-schemas.md"


def test_index_status_fields_documented():
    text = DOC.read_text(encoding="utf-8")
    assert "`status`：`success, vector_store, bm25_indexed, last_rebuild`" in text


def test_index_status_dead_fields_removed_from_doc():
    text = DOC.read_text(encoding="utf-8")
    assert (
        "success, total_indexed, last_indexed, pending_changes, vector_store" not in text
    )
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run --extra dev --extra embed pytest tests/unit/test_json_schema_contract_doc.py -q`
Expected: FAIL — 第一条（文档仍是旧字段清单）

- [ ] **Step 3: 改文档**（`docs/json-schemas.md` :57 行内，仅替换 status 段）

```text
# before
`status`：`success, total_indexed, last_indexed, pending_changes, vector_store`
# after
`status`：`success, vector_store, bm25_indexed, last_rebuild`
```

- [ ] **Step 4: 更新旧断言**（`tests/unit/test_index_kb_param.py:79`）

```python
# before
        assert "total_indexed" in data
# after
        assert "bm25_indexed" in data
        assert "last_rebuild" in data
```

- [ ] **Step 5: 验证通过 + lint**

Run: `uv run --extra dev --extra embed pytest tests/unit/test_json_schema_contract_doc.py tests/unit/test_index_kb_param.py -q && npx --yes markdownlint-cli2 "docs/json-schemas.md"`
Expected: PASS + lint 0 issues

- [ ] **Step 6: Commit**

```bash
git add docs/json-schemas.md tests/unit/test_json_schema_contract_doc.py tests/unit/test_index_kb_param.py
git commit -m "docs(index): sync status json schema with persistent fields (#539)"
```

---

### Task 5: 全量验证与记录 [A6, U1 准备]

**Files:** 无新改动（纯验证；发现问题回前面 task 修）

**Interfaces:**

- Consumes: Task 1-4 全部产物
- Produces: A6 执行记录（PR 描述与 issue 评论素材）

- [ ] **Step 1: A6 全量相关测试**

Run: `uv run --extra dev --extra embed pytest tests/unit/test_index_state.py tests/unit/test_index_status_payload.py tests/unit/test_json_schema_contract_doc.py tests/unit/test_index_kb_param.py tests/integration/test_index_status_persist.py tests/test_json_schema_contract.py tests/test_advanced_features.py -q`
Expected: 全部 PASS（契约套件含 index-status 条目；test_advanced_features 的 verify 断言不受影响）

- [ ] **Step 2: black / ruff**

Run: `uv run --extra dev --extra embed black --check jfox/index_state.py jfox/cli.py tests/unit/test_index_state.py tests/unit/test_index_status_payload.py tests/unit/test_json_schema_contract_doc.py tests/integration/test_index_status_persist.py && uv run --extra dev --extra embed ruff check jfox/ tests/`
Expected: 全部通过（如 black 报格式问题按其机械修正后重跑）

- [ ] **Step 3: U1 准备说明（不在本 task 执行）**：合并后用户在默认库跑 `jfox index status`（可选先 `jfox index rebuild` 让状态文件落地）核对真实条数与时间；U2 为 daemon 运行中重复执行字段稳定。

- [ ] **Step 4: 汇总记录**（不 commit）：A1-A6 命令与结果、U1/U2 待办说明，写入 PR 描述与 issue 评论素材。

---

## Self-Review 结论

- Spec 覆盖：D1→Task 2 Step 5、D2→Task 2、D3→Task 2 payload 命名、D4→Task 1、D5→Task 3、D6→Task 2、D7→Task 4、D8→Task 4；A1→T1、A2/A3→T2、A4→T3、A5→T4、A6→T4+T5；U1/U2 合并后（T5 Step 3 说明）。
- 占位符扫描：无 TBD/TODO；所有代码步骤含完整代码。
- 类型一致性：`load_index_state`/`save_index_state`/`build_rebuild_state` 签名在 Task 1 定义，Task 2/3 调用一致；`_index_status_payload` 签名与 Task 2 测试一致。
