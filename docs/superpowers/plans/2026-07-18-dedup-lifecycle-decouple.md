# dedup 生命周期解耦 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 gem-synth dedup 的生命周期同步从核心存储层 `note.py` 上移到特性层订阅，消除 `note.py` 对 `gem_synth.dedup` 的反向依赖（零运行时行为变更）。

**Architecture:** `note.py` 新增轻量生命周期注册表，在 delete/archive/promote/reject 末尾广播 `post_*` 事件（携带 `note_id` + `note_type`）；新文件 `jfox/gem_synth/lifecycle.py` 订阅这些事件，复刻原 dedup 同步逻辑（类型守卫下移到订阅器）；`cli.py` 模块级调用 `register()` 确保所有 CLI 路径订阅就位。

> **演进声明（2026-07-19）**：本 plan 为 2026-07-18 实施前的**设计快照**。实施期间经 zima CR 多轮 fix，代码已演进：numpy 改回调内 lazy import 避免 eager 启动开销（`d821088`）、test fixture 加 teardown `_LIFECYCLE_HOOKS.clear()` 防泄漏 + 测试 patch 目标 `lifecycle.*`→`dedup.*`（`c7403de`/`cc5591d`）。**plan 内各 Task 的代码块为初始设计版本，与最终合入代码存在上述 CR 驱动的差异，属预期演进而非文档缺陷**。最终实现以 PR #322 的 `jfox/gem_synth/lifecycle.py` 等实际代码为准；请勿把 plan 代码块作为代码一致性的审查基准。

**Tech Stack:** Python ≥ 3.10，pytest，无新依赖。

**Spec:** `docs/superpowers/specs/2026-07-18-dedup-lifecycle-decouple-design.md`

## Global Constraints

- **分支**：在 `refactor/dedup-lifecycle-decouple` 分支上做，**绝不直接动 main**。每次 commit 前 `git branch --show-current` 守卫（防并发 session 串台）。
- **行宽 100**：black + ruff 双检（CI 跑两步）。提交前 `uv run ruff check` **和** `uv run black --check`（没装 black 用 `uv run --with black==26.3.1 black --check`）。
- **注释/文档中文**，与周边代码一致。
- **测试自主跑范围**：本 plan 的单测都是 fast/unit（mock embedding，不加载模型），可自主跑。**不要**自主跑全量/集成测试——完成后给命令让用户跑。
- **stage 按文件**：`git add <具体文件>`，**禁用 `git add -A`**（防 sweep untracked 临时文件）。

---

## File Structure

| 文件 | 责任 | 动作 |
|---|---|---|
| `jfox/note.py` | 笔记 CRUD + 生命周期事件注册表（广播方） | 新增注册表 API + 4 处 lazy import 改 `_dispatch` |
| `jfox/gem_synth/lifecycle.py`（新）| 订阅 note 生命周期事件，复刻 dedup 同步 | 新建 |
| `jfox/cli.py` | 顶层入口，模块级触发 `register()` | 加 2 行 |
| `tests/unit/test_note_lifecycle_hooks.py`（新）| 注册表纯单测 | 新建 |
| `tests/unit/test_gem_synth_lifecycle.py`（新）| 订阅器单测 | 新建 |
| `tests/unit/test_note_dedup_sync.py` | 现有 dedup 同步测试，入口不变，fixture 加 register | 修改 |

---

## Task 1: note.py 生命周期注册表 + 纯单测

**Files:**
- Modify: `jfox/note.py`（在 `logger = logging.getLogger(__name__)` 即 line 15 之后插入注册表）
- Test: `tests/unit/test_note_lifecycle_hooks.py`（新）

**Interfaces:**
- Produces: `register_lifecycle_hook(event: str, callback) -> None`、`unregister_lifecycle_hook(event: str, callback) -> None`、`_dispatch(event: str, **payload) -> None`、模块级 `_LIFECYCLE_HOOKS: Dict[str, List[Any]]`。回调签名：`callback(note_id: str, note_type, **payload)`。

- [ ] **Step 1: 写失败测试** `tests/unit/test_note_lifecycle_hooks.py`

```python
"""note.py 生命周期注册表纯单测（不依赖 gem_synth）。"""

import pytest

from jfox.note import (
    _LIFECYCLE_HOOKS,
    _dispatch,
    register_lifecycle_hook,
    unregister_lifecycle_hook,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


@pytest.fixture(autouse=True)
def _clean_hooks():
    """每测前后清空注册表，避免互相污染。"""
    _LIFECYCLE_HOOKS.clear()
    yield
    _LIFECYCLE_HOOKS.clear()


def test_dispatch_calls_registered_callback():
    calls = []
    register_lifecycle_hook("post_delete", lambda **kw: calls.append(kw))
    _dispatch("post_delete", note_id="123", note_type="candidate")
    assert calls == [{"note_id": "123", "note_type": "candidate"}]


def test_dispatch_no_callbacks_is_noop():
    # 未注册任何回调时不抛
    _dispatch("post_delete", note_id="123", note_type="candidate")


def test_dispatch_isolates_callback_exceptions():
    """一个回调抛异常不影响其他回调，且不向外抛（dispatch 内 warning 兜底）。"""
    seen = []

    def bad(**kw):
        raise RuntimeError("boom")

    register_lifecycle_hook("post_delete", bad)
    register_lifecycle_hook("post_delete", lambda **kw: seen.append(kw["note_id"]))
    _dispatch("post_delete", note_id="123", note_type="candidate")
    assert seen == ["123"]


def test_register_is_idempotent():
    """同一 callback 重复注册只挂一次。"""
    calls = []

    def cb(**kw):
        calls.append(1)

    register_lifecycle_hook("post_delete", cb)
    register_lifecycle_hook("post_delete", cb)
    _dispatch("post_delete", note_id="1", note_type="candidate")
    assert len(calls) == 1


def test_unregister_removes_callback():
    seen = []

    def cb(**kw):
        seen.append(1)

    register_lifecycle_hook("post_delete", cb)
    unregister_lifecycle_hook("post_delete", cb)
    _dispatch("post_delete", note_id="1", note_type="candidate")
    assert seen == []


def test_dispatch_isolates_events():
    """post_delete 的回调不被 post_archive 触发。"""
    deleted = []
    archived = []
    register_lifecycle_hook("post_delete", lambda **kw: deleted.append(kw["note_id"]))
    register_lifecycle_hook("post_archive", lambda **kw: archived.append(kw["note_id"]))
    _dispatch("post_delete", note_id="9", note_type="candidate")
    assert deleted == ["9"]
    assert archived == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_note_lifecycle_hooks.py -v`
Expected: FAIL（`ImportError: cannot import name '_LIFECYCLE_HOOKS' ...`）

- [ ] **Step 3: 在 `jfox/note.py` 实现注册表**

在 `logger = logging.getLogger(__name__)`（line 15）之后、`def generate_id()`（line 18）之前插入：

```python
# ---------------------------------------------------------------------------
# 笔记生命周期事件注册表
#
# 核心存储层只"广播"生命周期事件（delete/archive/promote/reject），不主动调用
# 任何特性层。特性层（如 gem_synth 的 dedup 维护）通过 register_lifecycle_hook
# 订阅，依赖方向保持 特性 → 存储 单向（分层约束见 CLAUDE.md『Core Data Flow』）。
# ---------------------------------------------------------------------------
_LIFECYCLE_HOOKS: Dict[str, List[Any]] = {}


def register_lifecycle_hook(event: str, callback: Any) -> None:
    """注册笔记生命周期回调（幂等：同一 callback 重复注册不叠加）。

    Args:
        event: 事件名，约定 post_delete / post_archive / post_promote / post_reject
        callback: 回调，签名 callback(note_id=<str>, note_type=<NoteType>, **payload)
    """
    cbs = _LIFECYCLE_HOOKS.setdefault(event, [])
    if callback not in cbs:
        cbs.append(callback)


def unregister_lifecycle_hook(event: str, callback: Any) -> None:
    """取消注册（主要用于测试清理）。"""
    cbs = _LIFECYCLE_HOOKS.get(event, [])
    if callback in cbs:
        cbs.remove(callback)


def _dispatch(event: str, **payload: Any) -> None:
    """触发某事件的全部回调。单个回调抛异常仅 warning，不影响其他回调，
    也不向调用方抛（与原 'dedup 同步失败不阻塞主流程' 语义一致）。"""
    for cb in list(_LIFECYCLE_HOOKS.get(event, [])):
        try:
            cb(**payload)
        except Exception as e:  # noqa: BLE001 — 订阅器故障不得阻塞存储主流程
            logger.warning("lifecycle hook %s 失败 %r: %s", event, cb, e)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_note_lifecycle_hooks.py -v`
Expected: PASS（6 个测试全绿）

- [ ] **Step 5: lint + commit**

```bash
uv run ruff check jfox/note.py tests/unit/test_note_lifecycle_hooks.py
uv run --with black==26.3.1 black --check jfox/note.py tests/unit/test_note_lifecycle_hooks.py
git branch --show-current  # 必须是 refactor/dedup-lifecycle-decouple
git add jfox/note.py tests/unit/test_note_lifecycle_hooks.py
git commit -m "$(cat <<'EOF'
feat(note): 笔记生命周期事件注册表（广播方，零特性层依赖）

note.py 新增 register_lifecycle_hook/_dispatch，核心存储层只广播
post_delete/archive/promote/reject 事件，不 import 任何特性层。为 #310
dedup 生命周期上移铺路。

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: gem_synth 订阅器 + 单测

**Files:**
- Create: `jfox/gem_synth/lifecycle.py`
- Test: `tests/unit/test_gem_synth_lifecycle.py`（新）

**Interfaces:**
- Consumes: Task 1 的 `register_lifecycle_hook`；`jfox/gem_synth/dedup.py` 的 `_resolve_kb_name`、`delete_dedup`、`update_dedup_type`、`release_blocked_anchors`（签名不变）；`jfox.models.NoteType`。
- Produces: `register() -> None`（幂等）；模块内 `_on_deleted/_on_archived/_on_promoted/_on_rejected` 回调。

- [ ] **Step 1: 写失败测试** `tests/unit/test_gem_synth_lifecycle.py`

```python
"""gem_synth lifecycle 订阅器单测：4 事件回调 + 类型守卫 + kb 解析。"""

from unittest.mock import patch

import pytest

from jfox.models import NoteType

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_on_deleted_candidate_deletes_and_releases():
    from jfox.gem_synth.lifecycle import _on_deleted

    with (
        patch("jfox.gem_synth.dedup.delete_dedup") as dd,
        patch("jfox.gem_synth.dedup.release_blocked_anchors") as rba,
        patch("jfox.gem_synth.dedup._resolve_kb_name", return_value="kb1"),
    ):
        _on_deleted(note_id="n1", note_type=NoteType.CANDIDATE)
        dd.assert_called_once_with("kb1", "n1")
        rba.assert_called_once_with("n1")


def test_on_deleted_permanent_also_syncs():
    """删 permanent 同样清 dedup + 释放锚点（原 note.py 守卫含 PERMANENT）。"""
    from jfox.gem_synth.lifecycle import _on_deleted

    with (
        patch("jfox.gem_synth.dedup.delete_dedup") as dd,
        patch("jfox.gem_synth.dedup.release_blocked_anchors") as rba,
        patch("jfox.gem_synth.dedup._resolve_kb_name", return_value="kb1"),
    ):
        _on_deleted(note_id="n1", note_type=NoteType.PERMANENT)
        dd.assert_called_once_with("kb1", "n1")
        rba.assert_called_once_with("n1")


def test_on_deleted_fleeting_skips_early():
    """fleeting/literature/session 无 dedup 行：早返回，不解析 kb 也不碰 store。"""
    from jfox.gem_synth.lifecycle import _on_deleted

    with (
        patch("jfox.gem_synth.dedup.delete_dedup") as dd,
        patch("jfox.gem_synth.dedup.release_blocked_anchors") as rba,
        patch("jfox.gem_synth.dedup._resolve_kb_name") as rkn,
    ):
        _on_deleted(note_id="n1", note_type=NoteType.FLEETING)
        dd.assert_not_called()
        rba.assert_not_called()
        rkn.assert_not_called()


def test_on_archived_reuses_deleted_logic():
    from jfox.gem_synth import lifecycle

    with (
        patch("jfox.gem_synth.dedup.delete_dedup") as dd,
        patch("jfox.gem_synth.dedup.release_blocked_anchors") as rba,
        patch("jfox.gem_synth.dedup._resolve_kb_name", return_value="kb1"),
    ):
        lifecycle._on_archived(note_id="n1", note_type=NoteType.CANDIDATE)
        dd.assert_called_once_with("kb1", "n1")
        rba.assert_called_once_with("n1")


def test_on_promoted_updates_type_to_permanent():
    from jfox.gem_synth.lifecycle import _on_promoted

    with (
        patch("jfox.gem_synth.dedup.update_dedup_type") as udt,
        patch("jfox.gem_synth.dedup._resolve_kb_name", return_value="kb1"),
    ):
        _on_promoted(note_id="n1", note_type=NoteType.PERMANENT)
        udt.assert_called_once_with("kb1", "n1", "permanent")


def test_on_rejected_deletes_and_releases():
    from jfox.gem_synth.lifecycle import _on_rejected

    with (
        patch("jfox.gem_synth.dedup.delete_dedup") as dd,
        patch("jfox.gem_synth.dedup.release_blocked_anchors") as rba,
        patch("jfox.gem_synth.dedup._resolve_kb_name", return_value="kb1"),
    ):
        _on_rejected(note_id="n1", note_type=NoteType.CANDIDATE)
        dd.assert_called_once_with("kb1", "n1")
        rba.assert_called_once_with("n1")


def test_register_hooks_four_events():
    """register() 把 4 回调注册到 note.py，事件名齐全。"""
    from jfox.gem_synth import lifecycle

    with patch("jfox.note.register_lifecycle_hook") as reg:
        lifecycle.register()
        events = {c.args[0] for c in reg.call_args_list}
        assert events == {"post_delete", "post_archive", "post_promote", "post_reject"}


def test_register_calls_four_hooks_each_invocation():
    """register() 每次调用注册 4 个事件回调（mock 不去重 → 2 次调用 = 8 次 register_lifecycle_hook）；真正幂等性由 register_lifecycle_hook 去重保证，见 test_note_lifecycle_hooks.py。"""
    from jfox.gem_synth import lifecycle

    with patch("jfox.note.register_lifecycle_hook") as reg:
        lifecycle.register()
        lifecycle.register()
        assert len(reg.call_args_list) == 8
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_gem_synth_lifecycle.py -v`
Expected: FAIL（`ModuleNotFoundError: jfox.gem_synth.lifecycle`）

- [ ] **Step 3: 实现** `jfox/gem_synth/lifecycle.py`

```python
"""gem_synth 订阅 note.py 生命周期事件，同步 dedup 表。

把 dedup 生命周期同步从核心存储层（note.py）上移到特性层：note.py 只广播
post_delete/archive/promote/reject 事件，本模块订阅并复刻原 dedup 同步逻辑，
保持 note.py 零 gem_synth 依赖（分层约束见 KB 笔记 20260712223046-705752）。

类型守卫（仅 candidate/permanent 有 dedup 行）下移到本模块：note.py 无条件广播，
本模块按 note_type 早返回，避免给 fleeting/literature/session 实例化 DedupStore
（防未启用 gem-synth 用户产生 synthesis_log.db 污染）。
"""

from __future__ import annotations

import logging
from typing import Any

from ..models import NoteType
from .dedup import (
    _resolve_kb_name,
    delete_dedup,
    release_blocked_anchors,
    update_dedup_type,
)

logger = logging.getLogger(__name__)

# 仅 candidate/permanent 有 dedup 行；其它类型早返回避免实例化 store
_DEDUP_TYPES = (NoteType.CANDIDATE, NoteType.PERMANENT)


def _on_deleted(note_id: str, note_type: NoteType, **_: Any) -> None:
    """硬删 candidate/permanent：删 dedup 行 + 释放被该笔记阻断的锚点。

    残留 dedup 行会让未来 candidate 永久命中已删笔记；被阻断锚点不释放则知识
    永久丢失。失败由 note._dispatch 兜底 warning，不阻塞主流程。
    """
    if note_type not in _DEDUP_TYPES:
        return
    kb = _resolve_kb_name(None)
    delete_dedup(kb, note_id)
    release_blocked_anchors(note_id)


def _on_archived(note_id: str, note_type: NoteType, **_: Any) -> None:
    """归档与硬删的 dedup 同步动作一致（candidate/permanent 同样清行 + 释放锚点）。"""
    _on_deleted(note_id, note_type)


def _on_promoted(note_id: str, note_type: NoteType, **_: Any) -> None:
    """candidate → permanent：dedup 表 note_type 改 permanent（仍占位防重复合成）。"""
    if note_type not in _DEDUP_TYPES:
        return
    update_dedup_type(_resolve_kb_name(None), note_id, "permanent")


def _on_rejected(note_id: str, note_type: NoteType, **_: Any) -> None:
    """reject candidate：删 dedup 行 + 释放锚点（让该事实可被未来重新合成）。"""
    if note_type not in _DEDUP_TYPES:
        return
    kb = _resolve_kb_name(None)
    delete_dedup(kb, note_id)
    release_blocked_anchors(note_id)


_HOOKS = {
    "post_delete": _on_deleted,
    "post_archive": _on_archived,
    "post_promote": _on_promoted,
    "post_reject": _on_rejected,
}


def register() -> None:
    """把 dedup 生命周期回调注册到 note.py。

    幂等——register_lifecycle_hook 对同一 callback 去重，重复调用安全。
    由 jfox.cli 模块级调用一次，保证所有 CLI 命令路径订阅就位。
    """
    from ..note import register_lifecycle_hook  # lazy：避免顶层 import 循环

    for event, cb in _HOOKS.items():
        register_lifecycle_hook(event, cb)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_gem_synth_lifecycle.py -v`
Expected: PASS（8 个测试全绿）

- [ ] **Step 5: lint + commit**

```bash
uv run ruff check jfox/gem_synth/lifecycle.py tests/unit/test_gem_synth_lifecycle.py
uv run --with black==26.3.1 black --check jfox/gem_synth/lifecycle.py tests/unit/test_gem_synth_lifecycle.py
git branch --show-current
git add jfox/gem_synth/lifecycle.py tests/unit/test_gem_synth_lifecycle.py
git commit -m "$(cat <<'EOF'
feat(gem-synth): dedup 生命周期订阅器（复刻 note.py 同步逻辑）

新 lifecycle.py 订阅 note 的 post_delete/archive/promote/reject 事件，
类型守卫下移到订阅器。dedup 同步逻辑从核心层上移到特性层。

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: cli.py 模块级触发 register()

**Files:**
- Modify: `jfox/cli.py`（在 `from .template_cli import template_app` 即 line 42 之后插入）

**Interfaces:**
- Consumes: Task 2 的 `jfox.gem_synth.lifecycle.register()`
- Produces: import `jfox.cli` 后 `_LIFECYCLE_HOOKS` 已填充 4 事件

**为什么放 cli.py**：所有 `jfox xxx` 命令（含核心 `jfox delete/archive`、`jfox candidates promote/reject`）都经 `cli.py` 模块加载；顶层调一次 `register()` 即保证任何命令执行前订阅就位。`cli.py → gem_synth` 是顶层依赖，合规（验收只禁 `note.py`/`global_config.py` 反向依赖）。daemon 路径只合成（直接调 `upsert_dedup`，不触发 note 生命周期事件），无需注册。

- [ ] **Step 1: 确认 candidates 命令经 cli.py 加载**

Run: `grep -n "gem_synth" jfox/cli.py`
Expected: 看到 `jfox candidates` 命令的 import/注册（确认 promote/reject 执行时 cli.py 已加载）。若 candidates 是独立 typer app 经 `app.add_typer` 挂载，同样在 cli.py 模块级——register 仍先生效。记录观察到的集成方式。

- [ ] **Step 2: 在 `jfox/cli.py` line 42 后插入 register 调用**

在 `from .template_cli import template_app`（line 42）之后插入：

```python
# 注册 gem_synth dedup 生命周期订阅：note.py 广播 post_delete/archive/promote/reject
# 事件，gem_synth 订阅同步 dedup 表。放 cli.py 顶层——所有 jfox 命令都 import 本
# 模块，保证命令执行前订阅就位（核心 delete/archive 也覆盖）。分层约束：note.py
# 不依赖 gem_synth，反向通知由本顶层入口接线。
from .gem_synth.lifecycle import register as _register_gem_synth_lifecycle

_register_gem_synth_lifecycle()
```

- [ ] **Step 3: 验证 register 生效**

Run: `uv run python -c "import jfox.cli; from jfox.note import _LIFECYCLE_HOOKS; print(sorted(_LIFECYCLE_HOOKS))"`
Expected: 输出含 `['post_archive', 'post_delete', 'post_promote', 'post_reject']`（4 事件齐全）

- [ ] **Step 4: 确认现有 fast 测试不因 import 副作用回归**

Run: `uv run pytest tests/unit/test_note_lifecycle_hooks.py tests/unit/test_gem_synth_lifecycle.py -v`
Expected: 仍 PASS（14 个测试）

- [ ] **Step 5: lint + commit**

```bash
uv run ruff check jfox/cli.py
uv run --with black==26.3.1 black --check jfox/cli.py
git branch --show-current
git add jfox/cli.py
git commit -m "$(cat <<'EOF'
feat(cli): 模块级注册 gem_synth 生命周期订阅

import jfox.cli 即触发 register()，保证所有 CLI 命令（含核心 delete/archive）
执行前 dedup 生命周期订阅就位。

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: note.py 4 处切换为 _dispatch + 重构 test_note_dedup_sync

**Files:**
- Modify: `jfox/note.py`（delete_note 283-295、archive_note 329-341、promote_note 446-451、reject_note 471-481 的 dedup 块）
- Modify: `tests/unit/test_note_dedup_sync.py`（`_mock_backend` fixture 加 register）

**Interfaces:**
- Consumes: Task 1 的 `_dispatch`；Task 2 的订阅器经 Task 3 注册后自动接管同步。

**关键**：这是行为切换点——切换前（Task 1-3）订阅器已就位但 note.py 仍在用旧 lazy import；本 task 一次性把 4 处切到 `_dispatch` 并删 `gem_synth` import。切完后 note.py 零 `gem_synth` 依赖。

- [ ] **Step 1: 重构 `test_note_dedup_sync.py` 的 fixture（入口/断言不变，补 register）**

在 `_mock_backend` fixture 的 `monkeypatch.setattr(...)` 之后、`original = ...` 之前插入一行注册（确保测试期间订阅器已挂；幂等安全）：

```python
    # 注册 gem_synth 生命周期订阅（生产代码由 cli.py 模块级触发；测试不走 cli.py，
    # 这里显式 register，使 note.delete_note/archive_note/promote_note/reject_note
    # 的 _dispatch 能路由到 dedup 同步回调）。
    from jfox.gem_synth.lifecycle import register as _register_gem_synth_lifecycle

    _register_gem_synth_lifecycle()
```

> 入口与断言（`store.delete.assert_called_once_with(temp_kb.name, n.id)` 等）**保持不变**——方案 B 下 `_dispatch → _on_deleted → delete_dedup → _get_store().delete(kb, note_id)` 路径最终仍命中被 patch 的 `_get_store`，参数一致。fleeting-skip 测试（`ms.assert_not_called()`）同样成立——订阅器对 fleeting 早返回不碰 store。

- [ ] **Step 2: 切换 `delete_note`（变量名 `note`，line 279-295）**

把这段：

```python
        # 从 dedup 表删除 + 释放被阻断锚点（硬删后残留行 → dedup_check 匹配已删笔记 →
        # 未来 candidate 永久跳过；被该笔记阻断的锚点也需释放，否则知识永久丢失）。
        # 仅 candidate/permanent 有 dedup 行；fleeting/literature/session 跳过，避免实例化
        # DedupStore/SynthesisLog 给未启用 gem-synth 的用户创建 synthesis_log.db 污染。
        if note.type in (NoteType.CANDIDATE, NoteType.PERMANENT):
            try:
                from .gem_synth.dedup import (
                    _resolve_kb_name,
                    delete_dedup,
                    release_blocked_anchors,
                )

                kb = _resolve_kb_name(None)
                delete_dedup(kb, note_id)
                release_blocked_anchors(note_id)
            except Exception as e:
                logger.warning("delete_note dedup 清理失败 note=%s: %s", note_id, e)
```

替换为：

```python
        # 广播 post_delete：gem_synth 订阅做 dedup 清理（类型守卫在订阅器）。
        _dispatch("post_delete", note_id=note_id, note_type=note.type)
```

- [ ] **Step 3: 切换 `archive_note`（变量名 `n`，line 325-341）**

把这段：

```python
    # 先持久化，成功后再做 dedup 清理（防 update_note 失败 → 保护已删 → 下轮重复合成）。
    # 仅 candidate/permanent 有 dedup 行；其它类型跳过，避免实例化 DedupStore/SynthesisLog
    # 给未启用 gem-synth 的用户创建 synthesis_log.db 污染。
    ok = update_note(n)
    if ok and n.type in (NoteType.CANDIDATE, NoteType.PERMANENT):
        try:
            from .gem_synth.dedup import (
                _resolve_kb_name,
                delete_dedup,
                release_blocked_anchors,
            )

            kb = _resolve_kb_name(None)
            delete_dedup(kb, note_id)
            release_blocked_anchors(note_id)
        except Exception as e:
            logger.warning("archive dedup 同步失败 note=%s: %s", note_id, e)
    return ok
```

替换为：

```python
    # 先持久化，成功后再广播 post_archive（防 update_note 失败 → 保护已删 → 下轮重复合成）。
    # 类型守卫在 gem_synth 订阅器。
    ok = update_note(n)
    if ok:
        _dispatch("post_archive", note_id=note_id, note_type=n.type)
    return ok
```

- [ ] **Step 4: 切换 `promote_note`（变量名 `n`，line 445-451）**

把这段：

```python
    # dedup 同步：candidate→permanent，表内 note_type 改 permanent（仍占位防重复合成）
    try:
        from .gem_synth.dedup import _resolve_kb_name, update_dedup_type

        update_dedup_type(_resolve_kb_name(None), note_id, "permanent")
    except Exception as e:
        logger.warning("promote dedup 同步失败 note=%s: %s", note_id, e)
    return True
```

替换为：

```python
    # 广播 post_promote：gem_synth 订阅把 dedup 表 note_type 改 permanent。
    _dispatch("post_promote", note_id=note_id, note_type=n.type)
    return True
```

- [ ] **Step 5: 切换 `reject_note`（变量名 `n`，line 469-482）**

把这段：

```python
    # 先持久化，成功后再做 dedup 清理（防 update_note 失败 → 保护已删 → 下轮重复合成）
    ok = update_note(n)
    if ok:
        # dedup 同步：reject 的 candidate 从表删除，让该事实可被未来重新合成；
        # 同时释放被该 candidate 阻断的锚点（曾因 dedup 命中它而被标记 duplicate）
        try:
            from .gem_synth.dedup import _resolve_kb_name, delete_dedup, release_blocked_anchors

            kb = _resolve_kb_name(None)
            delete_dedup(kb, note_id)
            release_blocked_anchors(note_id)
        except Exception as e:
            logger.warning("reject dedup 同步失败 note=%s: %s", note_id, e)
    return ok
```

替换为：

```python
    # 先持久化，成功后再广播 post_reject（防 update_note 失败 → 保护已删 → 下轮重复合成）。
    # gem_synth 订阅做 dedup 清理 + 释放被阻断锚点（类型守卫在订阅器）。
    ok = update_note(n)
    if ok:
        _dispatch("post_reject", note_id=note_id, note_type=n.type)
    return ok
```

- [ ] **Step 6: 跑 dedup 同步测试 + 注册表/订阅器测试，确认不回归**

Run: `uv run pytest tests/unit/test_note_dedup_sync.py tests/unit/test_note_lifecycle_hooks.py tests/unit/test_gem_synth_lifecycle.py -v`
Expected: PASS（9 + 6 + 8 = 23 个测试全绿；test_note_dedup_sync 的 9 个行为断言不变）

- [ ] **Step 7: grep 守卫——确认核心层零 gem_synth 反向依赖**

Run: `grep -n "gem_synth" jfox/note.py jfox/global_config.py; echo "exit=$?"`
Expected: **无输出**（exit=1，grep 无匹配）。`note.py`/`global_config.py` 不再出现 `gem_synth`。

- [ ] **Step 8: lint + commit**

```bash
uv run ruff check jfox/note.py tests/unit/test_note_dedup_sync.py
uv run --with black==26.3.1 black --check jfox/note.py tests/unit/test_note_dedup_sync.py
git branch --show-current
git add jfox/note.py tests/unit/test_note_dedup_sync.py
git commit -m "$(cat <<'EOF'
refactor(note): dedup 同步改生命周期事件广播，移除 gem_synth 反向依赖

delete/archive/promote/reject 4 处 lazy import gem_synth.dedup 替换为
_dispatch 广播，dedup 同步逻辑由 gem_synth/lifecycle.py 订阅接管。note.py
零 gem_synth 依赖，分层约束恢复。行为不变（test_note_dedup_sync 入口与
断言保留）。Closes #310（KB-rename 验收项 deferred，见 issue）。

Co-Authored-By: Claude <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: 全量验证 + issue 留痕

**Files:** 无代码改动（验证 + issue 评论）

- [ ] **Step 1: 跑全部相关单测一次**

Run: `uv run pytest tests/unit/test_note_dedup_sync.py tests/unit/test_note_lifecycle_hooks.py tests/unit/test_gem_synth_lifecycle.py tests/unit/test_gem_synth_dedup.py tests/unit/test_archive.py tests/unit/test_update.py -v`
Expected: PASS。留意 `test_archive.py`/`test_update.py` 是否有隐式依赖旧 dedup 入口（PR #308 改过这俩）。

- [ ] **Step 2: 全仓 grep 确认无残留反向依赖**

Run: `grep -rn "from .gem_synth\|from ..gem_synth\|import gem_synth" jfox/note.py jfox/global_config.py jfox/models.py jfox/config.py`
Expected: **无输出**。核心存储层（note/global_config/models/config）零 gem_synth 引用。

- [ ] **Step 3: 提供全量/集成测试命令给用户（不自主跑）**

给用户：
```
uv run pytest tests/ -m "not embedding and not slow" -v
```
（CI fast 等价集；让用户确认无跨模块回归。）

- [ ] **Step 4: issue #310 评论——KB-rename deferred 说明 + 收尾**

```bash
gh issue comment 310 --body "重构完成（待 PR）。

- note.py/global_config.py 已零 gem_synth 反向依赖（grep 守卫通过）。
- dedup 生命周期同步行为不变（test_note_dedup_sync 9 断言保留 + 新增 14 单测覆盖注册表/订阅器）。
- **KB-rename 验收项 deferred**：依据 KB 笔记 20260712223046-705752 决策（用户不重命名 KB，dedup-backfill 兜底），本 PR 不迁移 dedup_embeddings.kb，记为已知限制。
- 方案 B（生命周期事件 + 订阅），register 由 cli.py 模块级触发。"
```

---

## Self-Review（写完即检）

**Spec coverage**：
- §3.1 注册表 → Task 1 ✅
- §3.2 订阅器 → Task 2 ✅
- §3.3 守卫下移 → Task 2（`_DEDUP_TYPES` 早返回）✅
- §3.4 注册时机 → Task 3 ✅
- §4 文件变动 → Task 1-4 全覆盖 ✅
- §5 测试 → Task 1/2/4 ✅
- §7 验收映射：note.py/global_config.py 零依赖（Task 4 Step 7 + Task 5 Step 2）、行为不变（Task 4 Step 6）、KB-rename deferred（Task 5 Step 4）、测试不回归（Task 4 Step 6）✅

**Placeholder scan**：无 TBD/TODO；每步含完整代码或精确命令。✅

**Type consistency**：`register_lifecycle_hook(event, callback)` 全 plan 一致；事件名 `post_delete/post_archive/post_promote/post_reject` 全程一致；回调签名 `(note_id, note_type, **_)` 一致；`_dispatch(event, **payload)` 一致。变量名 `note`（delete_note）vs `n`（archive/promote/reject）与源码现状对应。✅
