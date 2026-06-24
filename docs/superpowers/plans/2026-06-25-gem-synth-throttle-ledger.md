# gem_synth 限流 + 合成 ledger 实现计划（Issue #283）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development. Steps use checkbox (`- [ ]`).

**Goal:** 给 gem_synth 循环加时间预算限流（替代无上限）+ synthesis_log 升级为带 status 的 ledger（失败标记跳过不重试）+ `jfox gem-synth status` 看进度捞失败。

**Architecture:** `_tick_once` 改时间预算（每轮串行处理直到 interval_minutes 用完）；synthesis_log 加 status/fail_reason 列 + migration；synthesize_anchor 各失败路径 mark_failed；新增 gem_synth status 命令。

**Tech Stack:** Python 3.10+ / SQLite3 / Typer。纯逻辑/SQLite 单测自主跑。

**关联文档:** spec `docs/superpowers/specs/2026-06-25-gem-synth-throttle-ledger-design.md`，issue #283。

---

## 文件结构

改动：
- `jfox/gem_synth/store.py` — schema 加 status/fail_reason + migration；加 mark_failed/status_counts/list_failed
- `jfox/gem_synth/synthesizer.py` — 各失败路径 mark_failed
- `jfox/gem_synth/loop.py` — `_tick_once` 时间预算循环
- `jfox/gem_synth/anchors.py` — 加 `count_anchors`（status 命令算 pending 用）
- `jfox/gem_synth/cli.py` — 加 `gem_synth_app` + `status` 命令
- `jfox/cli.py` — 挂载 `gem_synth_app`

测试：`tests/unit/test_gem_synth_store.py`、`test_gem_synth_synthesizer.py`、`test_gem_synth_loop.py`、`test_gem_synth_cli.py`（扩展）。

---

## Task 1: SynthesisLog ledger 扩展（store.py）

**Files:**
- Modify: `jfox/gem_synth/store.py`
- Test: `tests/unit/test_gem_synth_store.py`

- [ ] **Step 1: 加测试到 `tests/unit/test_gem_synth_store.py`**

```python
def test_mark_failed_and_status_counts(tmp_path):
    from jfox.gem_synth.store import SynthesisLog
    log = SynthesisLog(db_path=tmp_path / "s.db")
    log.mark_processed(1, "c1")
    log.mark_failed(2, "no transcript_path")
    log.mark_failed(3, "llm failed: 非 JSON")
    counts = log.status_counts()
    assert counts == {"success": 1, "failed": 2}
    log.close()


def test_list_failed(tmp_path):
    from jfox.gem_synth.store import SynthesisLog
    log = SynthesisLog(db_path=tmp_path / "s.db")
    log.mark_failed(2, "no transcript_path")
    log.mark_processed(1, "c1")
    log.mark_failed(3, "llm failed")
    failed = log.list_failed()
    ids = [f["anchor_fragment_id"] for f in failed]
    assert 2 in ids and 3 in ids and 1 not in ids
    assert all(f["fail_reason"] for f in failed)
    log.close()


def test_failed_anchor_is_processed_not_retried(tmp_path):
    """failed 也算已处理 → filter_unprocessed 不返回它"""
    from jfox.gem_synth.store import SynthesisLog
    log = SynthesisLog(db_path=tmp_path / "s.db")
    log.mark_failed(5, "boom")
    assert log.is_processed(5) is True
    assert log.filter_unprocessed([5, 6]) == [6]
    log.close()


def test_migration_adds_columns_to_old_table(tmp_path):
    """旧表（无 status/fail_reason 列）建后 SynthesisLog 能升级"""
    import sqlite3
    p = tmp_path / "old.db"
    # 造一个 1.2.0 之前的旧 schema 表
    conn = sqlite3.connect(str(p))
    conn.execute(
        "CREATE TABLE synthesis_log (anchor_fragment_id INTEGER PRIMARY KEY, "
        "candidate_note_id TEXT NOT NULL, synthesized_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)"
    )
    conn.execute("INSERT INTO synthesis_log (anchor_fragment_id, candidate_note_id) VALUES (1, 'c1')")
    conn.commit()
    conn.close()
    # 用 SynthesisLog 打开 → 应自动 ALTER 加列，旧行 status='success'
    from jfox.gem_synth.store import SynthesisLog
    log = SynthesisLog(db_path=p)
    counts = log.status_counts()
    assert counts == {"success": 1}  # 旧行迁移后默认 success
    log.mark_failed(2, "x")  # 新列可用
    assert log.status_counts() == {"success": 1, "failed": 1}
    log.close()
```

- [ ] **Step 2: 跑确认失败**

Run: `uv run pytest tests/unit/test_gem_synth_store.py -v`
Expected: FAIL（mark_failed / status_counts / list_failed 不存在）

- [ ] **Step 3: 改 `jfox/gem_synth/store.py`**

把 `_SCHEMA` 改为（candidate_note_id 去掉 NOT NULL，加 status/fail_reason）：
```python
_SCHEMA = """
CREATE TABLE IF NOT EXISTS synthesis_log (
    anchor_fragment_id  INTEGER PRIMARY KEY,
    candidate_note_id   TEXT,
    status              TEXT NOT NULL DEFAULT 'success',
    fail_reason         TEXT,
    synthesized_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""
```

在 `__init__` 里，`self._conn.executescript(_SCHEMA)` + `self._conn.commit()` 之后、`self._closed = False` 之前，加 migration 调用：
```python
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._maybe_migrate()
        self._closed: bool = False
```

在 `__init__` 之后、`is_processed` 之前，加 `_maybe_migrate` 方法：
```python
    def _maybe_migrate(self) -> None:
        """旧表升级：补 status / fail_reason 列（1.2.0 前的表没有）。新表已含，跳过。"""
        cols = {row["name"] for row in self._conn.execute("PRAGMA table_info(synthesis_log)")}
        if "status" not in cols:
            self._conn.execute(
                "ALTER TABLE synthesis_log ADD COLUMN status TEXT NOT NULL DEFAULT 'success'"
            )
        if "fail_reason" not in cols:
            self._conn.execute("ALTER TABLE synthesis_log ADD COLUMN fail_reason TEXT")
        self._conn.commit()
```

把 `mark_processed` 改为显式写 status：
```python
    def mark_processed(self, anchor_fragment_id: int, candidate_note_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO synthesis_log "
                "(anchor_fragment_id, candidate_note_id, status) VALUES (?, ?, 'success')",
                (anchor_fragment_id, candidate_note_id),
            )
            self._conn.commit()
```

在 `mark_processed` 之后加 `mark_failed`、`status_counts`、`list_failed`：
```python
    def mark_failed(self, anchor_fragment_id: int, fail_reason: str) -> None:
        """失败锚点记账：status='failed' + 原因，candidate_note_id 留空。
        记账后 is_processed 为 True → 不再重试（过夜跑不 thrash）。
        """
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO synthesis_log "
                "(anchor_fragment_id, candidate_note_id, status, fail_reason) "
                "VALUES (?, '', 'failed', ?)",
                (anchor_fragment_id, fail_reason),
            )
            self._conn.commit()

    def status_counts(self) -> dict:
        """返回 {status: count}，如 {'success': 3, 'failed': 1}。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) AS n FROM synthesis_log GROUP BY status"
            ).fetchall()
        return {r["status"]: int(r["n"]) for r in rows}

    def list_failed(self, limit: int = 100) -> List[dict]:
        """返回失败锚点列表（最新在前），供 status --failed 人工复核。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT anchor_fragment_id, fail_reason, synthesized_at "
                "FROM synthesis_log WHERE status = 'failed' "
                "ORDER BY synthesized_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "anchor_fragment_id": r["anchor_fragment_id"],
                "fail_reason": r["fail_reason"],
                "synthesized_at": r["synthesized_at"],
            }
            for r in rows
        ]
```

更新 `__all__`：`__all__ = ["SynthesisLog"]`（不变，方法在类内）。

- [ ] **Step 4: 跑确认通过 + 回归**

Run: `uv run pytest tests/unit/test_gem_synth_store.py tests/unit/test_gem_synth_anchors.py -v`
Expected: PASS（store 新测试 + anchors 不受影响）

- [ ] **Step 5: 提交**

```bash
git add jfox/gem_synth/store.py tests/unit/test_gem_synth_store.py
git commit -m "feat(gem-synth): SynthesisLog ledger (status/fail_reason + migration)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: synthesize_anchor 失败路径 mark_failed（synthesizer.py）

**Files:**
- Modify: `jfox/gem_synth/synthesizer.py`
- Test: `tests/unit/test_gem_synth_synthesizer.py`

- [ ] **Step 1: 加测试到 `tests/unit/test_gem_synth_synthesizer.py`**

```python
def test_synthesize_marks_failed_when_no_transcript(tmp_path):
    """无 transcript_path → mark_failed('no transcript_path')，不重试"""
    from jfox.gem_synth.synthesizer import synthesize_anchor
    from jfox.gem_synth.store import SynthesisLog
    log = SynthesisLog(db_path=tmp_path / "s.db")
    anchor = {
        "fragment_id": 44, "session_id": "s", "timestamp": "t",
        "content": "x", "transcript_path": None, "metadata": {},
    }
    result = synthesize_anchor(anchor, log=log, cfg=MagicMock(grounding_top_k=5), stop_event=None)
    assert result is None
    assert log.is_processed(44) is True  # failed 也算已处理
    failed = log.list_failed()
    assert any(f["anchor_fragment_id"] == 44 and "transcript" in f["fail_reason"] for f in failed)
    log.close()


def test_synthesize_marks_failed_when_llm_none(tmp_path):
    """LLM 返 None → mark_failed('llm ...')"""
    from jfox.gem_synth.synthesizer import synthesize_anchor
    from jfox.gem_synth.store import SynthesisLog
    log = SynthesisLog(db_path=tmp_path / "s.db")
    anchor = {
        "fragment_id": 45, "session_id": "s", "timestamp": "t",
        "content": "x", "transcript_path": str(tmp_path / "t.jsonl"),
        "metadata": {},
    }
    (tmp_path / "t.jsonl").write_text('{"type":"user","message":{"role":"user","content":"x"},"timestamp":"t","uuid":"u"}', encoding="utf-8")
    with patch("jfox.gem_synth.synthesizer.extract_turn_around", return_value="上下文"), \
         patch("jfox.gem_synth.synthesizer.fetch_grounding", return_value=[]), \
         patch("jfox.gem_synth.synthesizer.synthesize_with_llm", return_value=None):
        result = synthesize_anchor(anchor, log=log, cfg=MagicMock(grounding_top_k=5), stop_event=None)
    assert result is None
    failed = log.list_failed()
    assert any(f["anchor_fragment_id"] == 45 and "llm" in f["fail_reason"].lower() for f in failed)
    log.close()
```

- [ ] **Step 2: 跑确认失败**

Run: `uv run pytest tests/unit/test_gem_synth_synthesizer.py -v`
Expected: FAIL（失败路径没调 mark_failed，is_processed False）

- [ ] **Step 3: 改 `jfox/gem_synth/synthesizer.py` synthesize_anchor**

Read `synthesize_anchor`（约 line 108-153）。在每个 `return None` 失败路径**之前**插入 `log.mark_failed(anchor["fragment_id"], "<reason>")`。具体 4 处（按当前代码顺序）：

(a) 无 transcript_path 路径（`if not transcript_path:` 分支），在 `return None` 前加：
```python
        log.mark_failed(anchor["fragment_id"], "no transcript_path")
        return None
```

(b) transcript 上下文为空路径（`if not turn.strip():` 分支），在 `return None` 前加：
```python
        log.mark_failed(anchor["fragment_id"], "empty transcript context")
        return None
```

(c) LLM 返 None 路径（`if llm_result is None:` 分支），在 `return None` 前加：
```python
        log.mark_failed(anchor["fragment_id"], "llm synthesis failed")
        return None
```

(d) _save_candidate_note 失败路径（`if note_id is None:` 分支），在 `return None` 前加：
```python
        log.mark_failed(anchor["fragment_id"], "save candidate note failed")
        return None
```

同时把函数 docstring 里「None → 跳过（不记账，下轮重试）」改为「None → mark_failed 记账（不重试）」。

- [ ] **Step 4: 跑确认通过 + 回归**

Run: `uv run pytest tests/unit/test_gem_synth_synthesizer.py tests/unit/test_gem_synth_loop.py -v`
Expected: PASS（**注意**：loop 测试若 mock synthesize_anchor 返回 None，现在 None=failed。检查 loop 测试是否需调整计数断言。若 test_gem_synth_loop 有断言 success 计数，确认仍对。）

- [ ] **Step 5: 提交**

```bash
git add jfox/gem_synth/synthesizer.py tests/unit/test_gem_synth_synthesizer.py
git commit -m "feat(gem-synth): synthesize_anchor marks failed anchors (no retry)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: _tick_once 时间预算循环（loop.py）

**Files:**
- Modify: `jfox/gem_synth/loop.py`
- Test: `tests/unit/test_gem_synth_loop.py`

- [ ] **Step 1: 加测试到 `tests/unit/test_gem_synth_loop.py`**

```python
def test_tick_time_budget_stops_after_interval():
    """时间预算：interval_minutes 用完就停，即使还有 pending"""
    cfg = MagicMock()
    cfg.enabled = True
    cfg.anchor_types = ["correction"]
    cfg.grounding_top_k = 5
    cfg.target_kb = None
    cfg.interval_minutes = 0  # 预算 0 → 处理 0 个立即停
    fake_anchor = {"fragment_id": 1, "session_id": "s", "timestamp": "t", "content": "c", "transcript_path": "/x", "metadata": {}}
    with patch("jfox.gem_synth.loop.get_global_config_manager") as gm, \
         patch("jfox.gem_synth.loop.find_anchors", return_value=[fake_anchor]) as fa, \
         patch("jfox.gem_synth.loop.synthesize_anchor", return_value={"candidate_note_id": "c1"}) as sa:
        gm.return_value.get_gem_synthesis_config.return_value = cfg
        msg = _tick_once(threading.Event())
    # 预算 0 → 不处理任何锚点（时间检查在合成前）
    sa.assert_not_called()
    assert isinstance(msg, str)


def test_tick_processes_one_at_a_time_within_budget():
    """预算内逐个处理（limit=1），直到无锚点"""
    cfg = MagicMock()
    cfg.enabled = True
    cfg.anchor_types = ["correction"]
    cfg.grounding_top_k = 5
    cfg.target_kb = None
    cfg.interval_minutes = 30  # 充足预算
    call_count = {"n": 0}
    def fake_find(*a, **k):
        call_count["n"] += 1
        # 第 1、2 次返回锚点，第 3 次返回空（无积压）
        return [{"fragment_id": call_count["n"], "session_id": "s", "timestamp": "t", "content": "c", "transcript_path": "/x", "metadata": {}}] if call_count["n"] <= 2 else []
    with patch("jfox.gem_synth.loop.get_global_config_manager") as gm, \
         patch("jfox.gem_synth.loop.find_anchors", side_effect=fake_find), \
         patch("jfox.gem_synth.loop.synthesize_anchor", return_value={"candidate_note_id": "c"}):
        gm.return_value.get_gem_synthesis_config.return_value = cfg
        msg = _tick_once(threading.Event())
    assert "success=2" in msg
```

- [ ] **Step 2: 跑确认失败**

Run: `uv run pytest tests/unit/test_gem_synth_loop.py -v`
Expected: FAIL（当前 _tick_once 取 batch 不是 limit=1 循环）

- [ ] **Step 3: 改 `jfox/gem_synth/loop.py`**

Read 顶部 import，确认有 `import threading`（有）。加 `import time`（若没有）。把 `_tick_once` 整个函数体替换为时间预算循环：

```python
def _tick_once(stop_event: threading.Event) -> str:
    """同步执行一轮：时间预算内逐个合成锚点。

    每轮跑 cfg.interval_minutes（窗口），串行处理（一次取一个未处理锚点），
    直到窗口用完或无锚点。窗口跑满则下个 tick 立即接上 → 积压时连续跑。
    """
    gm = get_global_config_manager()
    gm.reload()
    cfg = gm.get_gem_synthesis_config()
    if not cfg.enabled:
        return "gem-synth 已禁用，跳过本轮"

    from jfox.fragment.store import default_db_path
    from ..config import use_kb

    log = SynthesisLog()
    tick_start = time.monotonic()
    budget_seconds = cfg.interval_minutes * 60
    success = 0
    failed = 0
    try:
        # 整轮只切一次 KB（避免每锚点 use_kb → _reset_singletons 重载模型）
        with use_kb(cfg.target_kb):
            while not stop_event.is_set():
                # 时间预算用完 → 停，留给下个 tick（back-to-back 连续跑）
                if time.monotonic() - tick_start >= budget_seconds:
                    break
                try:
                    anchors = find_anchors(
                        fragments_db=default_db_path(),
                        log=log,
                        anchor_types=cfg.anchor_types,
                        limit=1,  # 一次取一个，配合时间预算
                    )
                except Exception as e:
                    logger.exception("gem-synth 找锚点失败: %s", e)
                    break
                if not anchors:
                    break  # 无积压
                try:
                    result = synthesize_anchor(
                        anchors[0], log=log, cfg=cfg, stop_event=stop_event
                    )
                    if result is not None:
                        success += 1
                    else:
                        failed += 1
                except Exception as e:
                    logger.exception(
                        "gem-synth 合成锚点 #%s 异常: %s", anchors[0].get("fragment_id"), e
                    )
                    failed += 1
    finally:
        log.close()
    return f"本轮 success={success} failed={failed}（预算 {cfg.interval_minutes}min）"
```

（确保文件顶部 `import time` 存在；`import threading` 已有。）

- [ ] **Step 4: 跑确认通过 + 回归**

Run: `uv run pytest tests/unit/test_gem_synth_loop.py tests/unit/test_gem_synth_synthesizer.py -v`
Expected: PASS

- [ ] **Step 5: 提交**

```bash
git add jfox/gem_synth/loop.py tests/unit/test_gem_synth_loop.py
git commit -m "feat(gem-synth): time-budget tick loop (serial, interval-bounded)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: jfox gem-synth status 命令 + count_anchors（cli.py + anchors.py）

**Files:**
- Modify: `jfox/gem_synth/anchors.py`（加 count_anchors）
- Modify: `jfox/gem_synth/cli.py`（加 gem_synth_app + status）
- Modify: `jfox/cli.py`（挂载 gem_synth_app）
- Test: `tests/unit/test_gem_synth_cli.py`（扩展）

- [ ] **Step 1: 加 count_anchors 测试 + 实现到 anchors.py**

测试加到 `tests/unit/test_gem_synth_anchors.py`：
```python
def test_count_anchors(tmp_path):
    from jfox.fragment.store import FragmentStore
    from jfox.gem_synth.anchors import count_anchors
    from jfox.gem_synth.store import SynthesisLog
    store = FragmentStore(db_path=tmp_path / "f.db")
    store.insert("s1", "correction", "UserPromptSubmit", "不对", {})
    store.insert("s1", "decision", "UserPromptSubmit", "我决定", {})
    store.insert("s1", "user_input", "UserPromptSubmit", "hi", {})  # 非锚点
    store.close()
    log = SynthesisLog(db_path=tmp_path / "syn.db")
    n = count_anchors(fragments_db=tmp_path / "f.db", anchor_types=["correction", "decision", "ask_user_question"])
    assert n == 2
    log.close()
```

在 `jfox/gem_synth/anchors.py` 加 `count_anchors`（复用 `_anchor_where` 的 WHERE 逻辑）：
```python
def count_anchors(fragments_db: Path, anchor_types: List[str]) -> int:
    """高信号锚点总数（不区分是否已处理）—— status 命令算 pending 用。"""
    where = _anchor_where(anchor_types)
    if not where:
        return 0
    conn = sqlite3.connect(str(fragments_db))
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM session_fragments {where}").fetchone()
    finally:
        conn.close()
    return int(row[0]) if row else 0
```
（`_anchor_where`、`sqlite3`、`Path`、`List` 已在 anchors.py 导入。更新 `__all__` 加 `count_anchors`。）
Run: `uv run pytest tests/unit/test_gem_synth_anchors.py -v` → PASS。

- [ ] **Step 2: 加 status 命令测试到 `tests/unit/test_gem_synth_cli.py`**

```python
def test_gem_synth_status_shows_counts(tmp_path, monkeypatch):
    """jfox gem-synth status 显示 pending/success/failed"""
    from jfox.fragment.store import FragmentStore
    from jfox.gem_synth.store import SynthesisLog
    # 造 3 个锚点 + 处理 2 个（1 success 1 failed）→ pending 1
    fdb = tmp_path / "f.db"
    FragmentStore(db_path=fdb).insert  # 确保 default_db_path 指向临时
    # 用环境变量把两个 db 都指向临时
    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(fdb))
    sdb = tmp_path / "syn.db"
    monkeypatch.setenv("JFOX_SYNTHESIS_DB", str(sdb))
    store = FragmentStore(db_path=fdb)
    store.insert("s", "correction", "UserPromptSubmit", "不对", {})
    store.insert("s", "correction", "UserPromptSubmit", "错了", {})
    store.insert("s", "correction", "UserPromptSubmit", "应该", {})
    store.close()
    log = SynthesisLog(db_path=sdb)
    log.mark_processed(1, "c1")
    log.mark_failed(2, "boom")
    log.close()
    result = CliRunner().invoke(gem_synth_app, ["status", "--format", "json"])
    assert result.exit_code == 0
    import json as _j
    data = _j.loads(result.output)
    assert data["pending"] == 1
    assert data["success"] == 1
    assert data["failed"] == 1
```

- [ ] **Step 3: 跑确认失败**

Run: `uv run pytest tests/unit/test_gem_synth_cli.py -v`
Expected: FAIL（gem_synth_app / status 不存在）

- [ ] **Step 4: 加 gem_synth_app + status 到 `jfox/gem_synth/cli.py`**

Read `jfox/gem_synth/cli.py`（现有 candidates_app + list/show）。在文件末尾加 `gem_synth_app`（新的 Typer 子命令组）+ status 命令：

```python
gem_synth_app = typer.Typer(
    name="gem-synth",
    help="L3 宝石合成进度查看（pending/success/failed + 失败复核）",
    no_args_is_help=True,
)


@gem_synth_app.command("status")
def gem_synth_status(
    failed_only: bool = typer.Option(False, "--failed", help="只列失败锚点（人工复核）"),
    output_format: str = typer.Option("table", "--format", "-f", help="table, json"),
) -> None:
    """查看合成进度：待处理/成功/失败；--failed 列失败锚点"""
    from .store import SynthesisLog
    from .anchors import count_anchors
    from ..global_config import get_gem_config if False else None  # placeholder 删除
    from jfox.fragment.store import default_db_path

    log = SynthesisLog()
    try:
        counts = log.status_counts()
        success = counts.get("success", 0)
        failed = counts.get("failed", 0)
        # 高信号锚点总数 → pending = total - (success + failed)
        cfg = get_gem_synthesis_config_for_status()
        total = count_anchors(default_db_path(), anchor_types=cfg.anchor_types)
        pending = max(0, total - success - failed)

        if failed_only:
            failed_list = log.list_failed()
            if output_format == "json":
                _json_console_print({"failed": failed_list})
            else:
                t = Table(title=f"失败锚点（共 {len(failed_list)} 条，人工复核）")
                for c in ("碎片ID", "失败原因", "时间"):
                    t.add_column(c)
                for f in failed_list:
                    t.add_row(str(f["anchor_fragment_id"]), f["fail_reason"] or "", str(f["synthesized_at"]))
                console.print(t)
            return

        if output_format == "json":
            _json_console_print({"pending": pending, "success": success, "failed": failed, "total": total})
        else:
            console.print(f"[bold]合成进度[/bold]")
            console.print(f"  待处理（pending）:  {pending}")
            console.print(f"  成功（success）:    {success}")
            console.print(f"  失败（failed）:     {failed}")
            if failed:
                console.print(f"[dim]用 `jfox gem-synth status --failed` 查看失败锚点[/dim]")
    finally:
        log.close()
```

**重要**：上面有两处占位需替换为真实实现（Read cli.py 看 candidates_app 怎么用 `_json_console`/`console`，复用同款；`get_gem_synthesis_config_for_status()` 改为真实取配置）：
- `_json_console_print` → 复用 cli.py 已有的 `_json_console.print(_json.dumps(...))`（或 candidates_app 里的 typer.echo JSON 模式，**为一致用 candidates_app 同款**）。
- `get_gem_synthesis_config_for_status()` → `from ..global_config import get_global_config_manager` 然后 `get_global_config_manager().get_gem_synthesis_config()`。`count_anchors` 需要 `cfg.anchor_types`。

**最终 status 命令应该是**（替换上面占位后，无 `if False else None`、无 placeholder）：
```python
@gem_synth_app.command("status")
def gem_synth_status(
    failed_only: bool = typer.Option(False, "--failed", help="只列失败锚点（人工复核）"),
    output_format: str = typer.Option("table", "--format", "-f", help="table, json"),
) -> None:
    """查看合成进度：待处理/成功/失败；--failed 列失败锚点"""
    import json as _json_module
    from .store import SynthesisLog
    from .anchors import count_anchors
    from ..global_config import get_global_config_manager
    from jfox.fragment.store import default_db_path

    cfg = get_global_config_manager().get_gem_synthesis_config()
    log = SynthesisLog()
    try:
        counts = log.status_counts()
        success = counts.get("success", 0)
        failed = counts.get("failed", 0)
        total = count_anchors(default_db_path(), anchor_types=cfg.anchor_types)
        pending = max(0, total - success - failed)

        if failed_only:
            failed_list = log.list_failed()
            if output_format == "json":
                typer.echo(_json_module.dumps({"failed": failed_list}, ensure_ascii=False, indent=2))
            else:
                t = Table(title=f"失败锚点（共 {len(failed_list)} 条，人工复核）")
                for c in ("碎片ID", "失败原因", "时间"):
                    t.add_column(c)
                for f in failed_list:
                    t.add_row(str(f["anchor_fragment_id"]), f["fail_reason"] or "", str(f["synthesized_at"]))
                console.print(t)
            return

        if output_format == "json":
            typer.echo(_json_module.dumps({"pending": pending, "success": success, "failed": failed, "total": total}, ensure_ascii=False, indent=2))
        else:
            console.print("[bold]合成进度[/bold]")
            console.print(f"  待处理（pending）:  {pending}")
            console.print(f"  成功（success）:    {success}")
            console.print(f"  失败（failed）:     {failed}")
            if failed:
                console.print("[dim]用 `jfox gem-synth status --failed` 查看失败锚点[/dim]")
    except Exception as e:
        if output_format == "json":
            typer.echo(_json_module.dumps({"success": False, "error": str(e)}, ensure_ascii=False))
        else:
            console.print(f"[red]读取合成进度失败：{e}[/red]")
        raise typer.Exit(code=1)
    finally:
        log.close()


__all__ = ["candidates_app", "gem_synth_app"]
```
（用 `typer.echo` 输出 JSON，与 candidates show 一致，避免 Rich 二次转义。`console`/`Table`/`typer` 已在 cli.py 导入。）

- [ ] **Step 5: 挂载 gem_synth_app 到 `jfox/cli.py`**

在 `candidates_app` 挂载旁边（`from .gem_synth.cli import candidates_app` 那行附近）加：
```python
from .gem_synth.cli import gem_synth_app  # noqa: E402
```
和
```python
app.add_typer(gem_synth_app, name="gem-synth", help="L3 宝石合成进度查看")
```

- [ ] **Step 6: 跑测试 + 验证挂载**

Run:
```bash
uv run pytest tests/unit/test_gem_synth_cli.py tests/unit/test_gem_synth_anchors.py -v
uv run jfox gem-synth --help
```
Expected: 测试 PASS；help 显示 `status` 子命令。

- [ ] **Step 7: 提交**

```bash
git add jfox/gem_synth/anchors.py jfox/gem_synth/cli.py jfox/cli.py tests/unit/test_gem_synth_cli.py tests/unit/test_gem_synth_anchors.py
git commit -m "feat(cli): jfox gem-synth status (progress + failed review) + count_anchors

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: 收尾 — 回归 + lint + PR

- [ ] **Step 1: 全部 gem_synth 单测**

Run: `uv run pytest tests/unit/test_gem_synth_store.py tests/unit/test_gem_synth_anchors.py tests/unit/test_gem_synth_synthesizer.py tests/unit/test_gem_synth_loop.py tests/unit/test_gem_synth_cli.py -v`
Expected: PASS

- [ ] **Step 2: CI lint（jfox/ + tests/ 全量，别再像 #274 漏 tests/）**

Run:
```bash
uv run ruff check jfox/ tests/
uv run black jfox/gem_synth/ jfox/cli.py tests/unit/test_gem_synth_*.py
```

- [ ] **Step 3: 推送 + 开 PR**

```bash
git push -u origin feat/283-gem-synth-throttle-ledger
gh pr create --title "feat(gem-synth): time-budget throttle + synthesis ledger + status (#283)" \
  --body "实现 #283：① _tick_once 改时间预算循环（串行，interval 窗口自适应，去掉无上限）② synthesis_log 加 status/fail_reason + migration ③ 失败 mark_failed 跳过不重试 ④ jfox gem-synth status（进度 + --failed 捞失败）。设计见 docs/superpowers/specs/2026-06-25-gem-synth-throttle-ledger-design.md。Closes #283。"
```

---

## Self-Review 结果

**1. Spec 覆盖：**
- 时间预算限流（§1）→ Task 3 ✅
- synthesis_log ledger（§2）→ Task 1 ✅
- 失败标记不重试（§3）→ Task 2 ✅
- jfox gem-synth status（§4）→ Task 4 ✅
- schema migration（§5）→ Task 1（_maybe_migrate + test_migration）✅
- 范围（§6：不做 retry-failed / max_per_tick 计数 / 退避）→ 未含 ✅

**2. 占位符扫描：** Task 4 Step 4 有一个"占位需替换"的中间版本 —— 但紧接给了**最终无占位版本**（用 typer.echo + get_global_config_manager）。实现时用最终版本，忽略中间占位草稿。其余步骤完整代码。

**3. 签名一致性：**
- `SynthesisLog.mark_failed(anchor_id, fail_reason)` / `status_counts()` / `list_failed()` — Task 1 定义，Task 2/4 调用一致 ✅
- `synthesize_anchor` 各失败路径调 `log.mark_failed(anchor["fragment_id"], reason)` — Task 2，reason 字符串固定 ✅
- `find_anchors(limit=1)` — Task 3 调用，anchors.py 已有 limit 参数 ✅
- `count_anchors(fragments_db, anchor_types)` — Task 4 定义 + 调用一致 ✅
- `gem_synth_app` / `gem_synth_status` — Task 4 定义，cli.py 挂载一致 ✅
