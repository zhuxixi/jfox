# Nightly-test 失败修复（#523）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 9-08 nightly 的 6 个测试失败（3 组：过时集成测试 / flaky 生成器 / 过时维度断言），全部为测试侧改动，不动生产代码。

**Architecture:** 组 C 改单测断言指向 #442 的 `last_dimension_warning` 属性；组 B 把 `NoteGenerator.generate()` 从有放回抽样改为洗牌无放回轮转，消除重复标题（#483 防重闸门后重复即失败）；组 A 重写集成测试适配 #399/#462 新链路（spool + `/api/prompt` + retired 契约），session id 随机化防真实库残留污染。

**Tech Stack:** pytest（unit + integration 标记）、FastAPI daemon HTTP 契约、bash hook 脚本、`random.shuffle` 轮转。

**Spec:** `docs/superpowers/specs/2026-09-09-nightly-test-failures-design.md`

## Global Constraints

- 只改测试代码与测试工具（`tests/`），不改 `jfox/` 生产代码与 hook 脚本（spec §5）
- 集成测试 session id 一律随机前缀 `it-<uuid8>`，禁止固定 `it-sess-N`（spec §2.1）
- 集成测试不查库，只断言 API 响应与 spool 文件行为（spec §5）
- 不断言 hook 执行中途的 spool 文件时序，只断言终态（spec §2.1 时序断言取舍）
- 本 plan 所有命令在 worktree 根目录执行：`.pi/worktrees/issue-523-nightly-test-failures`
- 验收 ID 对应 spec §3：Task 1→A3、Task 2→A2/A4、Task 3→A1、Task 4→A5

---

### Task 1: 组 C——维度提示断言更新（A3）

**Files:**

- Modify: `tests/unit/test_vector_store_clear.py:174-190`（`TestVectorStoreDimensionMismatch::test_add_note_dimension_mismatch_friendly_message`）

**Interfaces:**

- Consumes: `VectorStore.last_dimension_warning` 属性（#442 引入，`jfox/vector_store.py:46`）、`VectorStore._dimension_warning_text()` 静态方法（`jfox/vector_store.py:48`）
- Produces: 无（叶子测试改动）

- [x] **Step 1: 确认当前测试失败**

Run: `uv run pytest tests/unit/test_vector_store_clear.py::TestVectorStoreDimensionMismatch -q`
Expected: `test_add_note_dimension_mismatch_friendly_message` FAIL（`assert 'jfox index rebuild' in 'Embedding dim mismatch for note ...'`），`test_add_note_non_dimension_exception_unchanged` PASS

- [x] **Step 2: 更新断言到 last_dimension_warning**

把该用例的断言尾部（保留 mock_error 捕获，用于同时确认日志格式）替换为：

```python
        assert result is False
        # 维度不匹配：日志保留原始错误（调试用），rebuild 提示经
        # last_dimension_warning 属性上浮给 CLI（#442 行为）
        error_msg = mock_error.call_args[0][0]
        assert "dim mismatch" in error_msg
        assert "rebuild" not in error_msg
        assert store.last_dimension_warning is not None
        assert "jfox index rebuild" in store.last_dimension_warning
        assert "384" in store.last_dimension_warning
        assert "1024" in store.last_dimension_warning
```

- [x] **Step 3: 运行验证通过**

Run: `uv run pytest tests/unit/test_vector_store_clear.py -q`
Expected: 全部 PASS

- [x] **Step 4: Commit**

```bash
git add tests/unit/test_vector_store_clear.py
git commit -m "test(vector-store): assert rebuild hint via last_dimension_warning (#442 behavior, #523)"
```

---

### Task 2: 组 B——NoteGenerator 无放回抽样（A2/A4）

**Files:**

- Create: `tests/unit/test_note_generator.py`
- Modify: `tests/utils/note_generator.py:186-198`（`generate()` 的模板选择循环）

**Interfaces:**

- Consumes: `NoteGenerator.__init__(seed)`、`NOTE_TEMPLATES`（15 个模板）、现有后缀规则 `if count > len(templates): title = f"{title} ({i+1})"`
- Produces: `generate(count, note_type, category)` 行为契约——同一轮（前 `len(templates)` 个）标题不重复；count > 15 时全量后缀保证跨轮唯一。签名不变。

- [x] **Step 1: 写失败测试**

新建 `tests/unit/test_note_generator.py`：

```python
"""NoteGenerator 抽样行为：无放回轮转保证标题唯一（#523 组 B）。

#483 防重双通道闸门后，add 命令拒绝重复标题；旧实现 random.choice
有放回抽样在 count 接近模板数时高概率撞标题（seed=0 时 15 选 15 撞 5 个），
导致 test_multiple_notes_with_links_batch flaky。
"""

from tests.utils.note_generator import NOTE_TEMPLATES, NoteGenerator

TEMPLATE_COUNT = sum(len(v) for v in NOTE_TEMPLATES.values())  # 15


class TestGenerateNoDuplicateTitles:
    def test_one_round_titles_unique(self):
        """一轮内（count == 模板数）标题不重复——seed=0 在旧实现下撞 5 个"""
        gen = NoteGenerator(seed=0)
        notes = gen.generate(TEMPLATE_COUNT)
        titles = [n.title for n in notes]
        assert len(titles) == TEMPLATE_COUNT
        assert len(set(titles)) == TEMPLATE_COUNT

    def test_count_below_pool_unique(self):
        """count 小于模板数：无后缀且不重复"""
        gen = NoteGenerator(seed=7)
        notes = gen.generate(TEMPLATE_COUNT - 1)
        titles = [n.title for n in notes]
        assert len(set(titles)) == len(titles)
        assert not any("(" in t for t in titles)

    def test_count_above_pool_suffixed_unique(self):
        """count 超过模板数：后缀规则生效，跨轮全局唯一"""
        gen = NoteGenerator(seed=3)
        notes = gen.generate(TEMPLATE_COUNT + 5)
        titles = [n.title for n in notes]
        assert len(set(titles)) == len(titles)
        assert all("(" in t for t in titles)

    def test_no_seed_still_unique(self):
        """无 seed（全局随机态）：唯一性不依赖可复现性"""
        gen = NoteGenerator()
        notes = gen.generate(TEMPLATE_COUNT)
        titles = [n.title for n in notes]
        assert len(set(titles)) == TEMPLATE_COUNT
```

- [x] **Step 2: 运行确认失败**

Run: `uv run pytest tests/unit/test_note_generator.py -q`
Expected: `test_one_round_titles_unique` FAIL（seed=0 有重复）；`test_count_above_pool_suffixed_unique` 可能 PASS（后缀规则本来就唯一）

- [x] **Step 3: 改 generate() 为无放回轮转**

`tests/utils/note_generator.py` 的 `generate()` 循环开头，替换模板选择：

```python
        # 无放回轮转（#523 组 B）：每轮洗牌取尽再补，一轮内标题不重复；
        # 旧 random.choice 有放回抽样在 count 接近模板数时高概率撞标题，
        # #483 防重闸门后 add 直接拒绝重复标题 → flaky。
        pool: List[dict] = []
        for i in range(count):
            if not pool:
                pool = templates.copy()
                random.shuffle(pool)
            template = pool.pop()
```

（删除原 `template = random.choice(templates)` 行；其余 detail 填充与后缀逻辑不动。）

- [x] **Step 4: 运行验证通过**

Run: `uv run pytest tests/unit/test_note_generator.py -q`
Expected: 全部 PASS

- [x] **Step 5: A4 回归——flaky 用例连跑 3 次**

Run: `uv run pytest "tests/test_core_workflow.py::TestCompleteWorkflow::test_multiple_notes_with_links_batch" -q --count 3`（无 pytest-repeat 插件则手动连跑 3 次同一命令）
Expected: 3 次全 PASS（若该 fixture 实载 embedding 导致单次 >2min，降为 1 次并在执行记录注明，根因已由 Step 4 单测覆盖）

- [x] **Step 6: Commit**

```bash
git add tests/unit/test_note_generator.py tests/utils/note_generator.py
git commit -m "test(generator): draw templates without replacement to kill duplicate-title flakiness (#523)"
```

---

### Task 3: 组 A——集成测试重写适配新链路（A1）

**Files:**

- Rewrite: `tests/integration/test_fragment_capture_flow.py`（整文件重写）

**Interfaces:**

- Consumes: daemon HTTP 契约——`POST /api/prompt` → `{status: stored, prompt_id, prompt}` / `{status: duplicate, prompt_id, prompt}` / `{status: skipped, reason}` / `{status: error, error}`（`jfox/daemon/server.py:354`，`jfox/prompts/service.py:ingest_prompt`）；`POST /api/fragment` → UserPromptSubmit 转发 `/api/prompt`，PostToolUse/Stop → `{status: retired, reason}`（`server.py:336`）
- Consumes: hook 环境契约——`JFOX_PROMPT_SPOOL_DIR`（spool 目录覆盖）、`JFOX_DAEMON_URL`（daemon 地址覆盖）、`JFOX_INTERNAL_SESSION ∈ {auto-summary, gem-synth, prompt-judge}`（内部来源直接 exit 0，`packages/cc-plugin/hooks/fragment-capture.sh`）
- Produces: 无（叶子测试改动）

- [x] **Step 1: 整文件重写**

```python
"""端到端：hook 脚本 → spool / daemon API → user_prompts（#399 新链路）。

标记 integration：依赖真实运行的 daemon（jfox daemon start）。
用户手动跑：uv run pytest tests/integration/test_fragment_capture_flow.py -v -m integration

历史：#399/#493 退役旧分类采集（PostToolUse/Stop → retired），
#462/#521 hook 改版为 spool + POST /api/prompt 静默模式。本文件
按新契约重写（原用例见 git 历史），session id 一律随机，避免真实
daemon 持久库的固定 session 残留污染（#523 根因之一）。
"""

import json
import os
import subprocess
import urllib.error
import urllib.request
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

DAEMON = "http://127.0.0.1:18700"
REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / "packages" / "cc-plugin" / "hooks" / "fragment-capture.sh"


def _daemon_up() -> bool:
    try:
        with urllib.request.urlopen(f"{DAEMON}/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _sess() -> str:
    """随机 session id：杜绝固定 id 在真实库累积/污染。"""
    return f"it-{uuid.uuid4().hex[:8]}"


def _post_api(event: dict) -> dict:
    req = urllib.request.Request(
        f"{DAEMON}/api/prompt",
        data=json.dumps(event).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def _run_hook(payload: str, spool_dir: Path, extra_env: dict | None = None) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "JFOX_PROMPT_SPOOL_DIR": str(spool_dir),
        **(extra_env or {}),
    }
    return subprocess.run(
        ["bash", str(HOOK)], input=payload, capture_output=True, text=True, timeout=10, env=env
    )


@pytest.fixture(scope="module", autouse=True)
def require_daemon():
    if not _daemon_up():
        pytest.skip("JFox daemon 未运行；先 `jfox daemon start`（需用户手动启动，会加载模型）")


def test_prompt_api_stores_full_prompt():
    """POST /api/prompt（UserPromptSubmit）→ stored + prompt 原文完整回显"""
    sess, text = _sess(), "不对，应该用 patch 而不是 put（集成测试随机注入）"
    body = _post_api(
        {"hook_event_name": "UserPromptSubmit", "session_id": sess, "prompt": text}
    )
    assert body["status"] == "stored"
    assert body["prompt"] == text


def test_prompt_api_idempotent():
    """同 capture_id 重复 POST → duplicate（幂等键 source_key=capture:<id>）"""
    cid = uuid.uuid4()
    event = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": _sess(),
        "prompt": "幂等探针（集成测试随机注入）",
        "jfox_capture_id": cid,
    }
    first = _post_api(event)
    second = _post_api(event)
    assert first["status"] in ("stored", "duplicate")
    assert second["status"] == "duplicate"
    assert second["prompt_id"] == first["prompt_id"]


def test_hook_post_success_clears_spool(tmp_path):
    """daemon 可用：hook 完成后 spool 为空（stored 确认后删除）、静默 exit 0"""
    payload = json.dumps(
        {"hook_event_name": "UserPromptSubmit", "session_id": _sess(), "prompt": "hook 链路探针"}
    )
    proc = _run_hook(payload, tmp_path)
    assert proc.returncode == 0
    assert proc.stdout == ""  # hook 静默契约：不打印摘要（#462 改版）
    assert list(tmp_path.glob("*.json")) == []  # POST 成功 → spool 已删


def test_hook_post_failure_keeps_spool(tmp_path):
    """daemon 不可达：spool 保留（durable 降级不丢数据）、仍静默 exit 0。
    本用例不依赖真实 daemon（JFOX_DAEMON_URL 指向黑洞端口）。"""
    payload = json.dumps(
        {"hook_event_name": "UserPromptSubmit", "session_id": _sess(), "prompt": "降级探针"}
    )
    proc = _run_hook(payload, tmp_path, extra_env={"JFOX_DAEMON_URL": "http://127.0.0.1:1"})
    assert proc.returncode == 0
    assert proc.stdout == ""
    spool_files = list(tmp_path.glob("*.json"))
    assert len(spool_files) == 1  # POST 失败 → spool 留存待 drain
    kept = json.loads(spool_files[0].read_text(encoding="utf-8"))
    assert kept["jfox_capture_id"]  # capture id 已注入
    assert kept["prompt"] == "降级探针"


@pytest.mark.parametrize("source", ["auto-summary", "gem-synth", "prompt-judge"])
def test_hook_internal_session_skipped(source, tmp_path):
    """JFOX_INTERNAL_SESSION 命中内部来源 → hook 直接 exit 0，不产生 spool 文件"""
    payload = json.dumps(
        {"hook_event_name": "UserPromptSubmit", "session_id": _sess(), "prompt": "内部来源探针"}
    )
    proc = _run_hook(payload, tmp_path, extra_env={"JFOX_INTERNAL_SESSION": source})
    assert proc.returncode == 0
    assert list(tmp_path.glob("*.json")) == []


def test_legacy_fragment_endpoint_retired():
    """旧 /api/fragment 端点：PostToolUse/Stop → retired（#399 退役契约）"""
    for event_name in ("PostToolUse", "Stop"):
        req = urllib.request.Request(
            f"{DAEMON}/api/fragment",
            data=json.dumps(
                {"hook_event_name": event_name, "session_id": _sess()}
            ).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            body = json.loads(r.read())
        assert body["status"] == "retired"
        assert event_name in body["reason"]
```

- [x] **Step 2: 运行验证通过（前提：daemon 运行且 ≥ 含 #493 的版本）**

Run: `uv run pytest tests/integration/test_fragment_capture_flow.py -v -m integration`
Expected: 全部 PASS（7 个用例：stores_full_prompt / idempotent / clears_spool / keeps_spool / skipped×3 / retired）

- [x] **Step 3: 确认无残留固定 session**

Run: `rg -n "it-sess" tests/integration/test_fragment_capture_flow.py`
Expected: 无匹配（固定 session id 已全部移除）

- [x] **Step 4: Commit**

```bash
git add tests/integration/test_fragment_capture_flow.py
git commit -m "test(integration): rewrite fragment capture flow for prompt-capture pipeline (#523)"
```

---

### Task 4: 全量回归与静态检查（A5）

**Files:**

- 无新改动（验证性 task）

**Interfaces:**

- Consumes: Task 1-3 的全部产物
- Produces: 验收记录（A5 通过证据）

- [x] **Step 1: 全量快速回归**

Run: `uv run pytest tests/ -m "not embedding and not slow" -q`
Expected: 无新增失败（组 A 为 integration 标记，本命令跳过，由 Task 3 Step 2 覆盖）

- [x] **Step 2: lint 与格式**

Run: `npx --yes markdownlint-cli2 "docs/superpowers/specs/2026-09-09-nightly-test-failures-design.md" && uv run black --check tests/ && uv run ruff check tests/`
Expected: 全部 exit 0

- [x] **Step 3: 验收对账**

对照 spec §3 验收矩阵逐项核对：A1（Task 3 Step 2）、A2（Task 2 Step 4）、A3（Task 1 Step 3）、A4（Task 2 Step 5）、A5（Task 4 Step 1），记录实际命令与结果。

---

## Self-Review 结论

- **Spec 覆盖**：spec §2.1 六用例 → Task 3 全部落位；§2.2 → Task 2；§2.3 → Task 1；§3 A1-A5 → Task 1-4；§5 非目标（不改生产代码）→ Global Constraints。无缺口。
- **占位符扫描**：所有代码步骤含完整代码；无 TBD/TODO/“适当处理”。
- **类型/签名一致性**：`_post_api`/`_run_hook`/`_sess` 在 Task 3 内自洽；Task 2 `generate()` 签名不变、`pool` 用 `List[dict]`（文件已 import List）。
