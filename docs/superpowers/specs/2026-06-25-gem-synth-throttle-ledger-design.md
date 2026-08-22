# gem_synth 限流 + 合成进度 ledger 设计（Issue #283）

- **关联 Issue**: #283（gem_synth 缺 max_per_tick 限流 + 合成进度 ledger）
- **前置**: #274（L3 宝石合成，1.2.0）、#261（碎片采集）
- **父**: #249（Loop Engineering）
- **日期**: 2026-06-25
- **状态**: 设计已确认

## 0. 目标

给 L3 gem_synth 循环加三个东西，使其能**安全、可观测地**消化碎片积压：

1. **时间预算限流** —— 每个 tick（= `interval_minutes` 窗口）串行处理锚点直到时间用完，自适应、429 零风险
2. **合成 ledger** —— `synthesis_log` 升级为带 status（success/failed）+ fail_reason 的记账表
3. **失败 = 标记跳过（不重试）** + **`jfox gem-synth status`** 看进度 + 捞失败

**阻塞**：启用 `gem_synthesis.enabled=true` 之前应先解决（当前无上限会一次跑 ~100 调用 + 失败无限重试）。

## 1. 时间预算限流（替代 max_per_tick 计数）

**用户决策**：不用计数上限（`max_per_tick`），改用**时间预算**。每个 tick 串行处理锚点，一直跑到 `interval_minutes`（窗口）用完或无锚点。

**理由**（用户）：

- 每次合成 ~5min（模型推理 + 整理），30min 窗口自然 ~5-6 个（30÷5），无需硬计数
- 自适应：合成快就多跑、慢就少跑，填满窗口不浪费
- 积压时连续跑：tick 跑满 30min → 下个 tick 立即接上（back-to-back）→ 一直跑到清完（过夜连续 ~11h 清 ~107 个）；清完后 tick 空转、30min 巡一次
- 429 零风险（串行 ~5min/次，~12 次/h）

**实现**（`gem_synth/loop.py _tick_once`）：

```python
def _tick_once(stop_event):
    cfg = reload + get_gem_synthesis_config()
    if not cfg.enabled: return "disabled"
    log = SynthesisLog()
    tick_start = monotonic()
    success = failed = 0
    try:
        while not stop_event.is_set():
            # 时间预算用完 → 停（留给下个 tick）
            if monotonic() - tick_start >= cfg.interval_minutes * 60:
                break
            anchors = find_anchors(limit=1)   # 取下一个未处理
            if not anchors: break              # 无积压
            result = synthesize_anchor(anchors[0], log, cfg, stop_event)
            if result is not None: success += 1
            else: failed += 1                  # synthesize_anchor 内部已 mark_failed
    finally:
        log.close()
    return f"本轮 success={success} failed={failed}"
```

- `interval_minutes`（现有配置，默认 30）即时间预算，**不新增 config**
- `find_anchors(limit=1)` 每次取一个未处理锚点（含 pending，不含 success/failed）
- async loop 仍按 `interval_minutes` 调度；tick 跑满则 back-to-back，空转则等满

## 2. synthesis_log → 合成 ledger（扩展现有表）

当前 schema（仅去重）：

```sql
CREATE TABLE synthesis_log (
    anchor_fragment_id  INTEGER PRIMARY KEY,
    candidate_note_id   TEXT NOT NULL,
    synthesized_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**扩展**为带 status + fail_reason：

```sql
CREATE TABLE synthesis_log (
    anchor_fragment_id  INTEGER PRIMARY KEY,
    candidate_note_id   TEXT,           -- success 时有；failed 时 NULL
    status              TEXT NOT NULL DEFAULT 'success',  -- success | failed
    fail_reason         TEXT,           -- failed 时记原因
    synthesized_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

**Migration**：建表 SQL 加新列；对已存在的表用 `ALTER TABLE ADD COLUMN`（status 默认 'success'，fail_reason NULL）。`SynthesisLog.__init__` 建表时 `CREATE TABLE IF NOT EXISTS` 不触发改列 —— 需要 schema 版本检测 + ALTER 升级（见 §5）。

**`SynthesisLog` 方法变更**：

- `mark_processed(anchor_id, candidate_note_id)` → 保持（记 success）
- 新增 `mark_failed(anchor_id, fail_reason)` → 记 status='failed' + fail_reason，candidate_note_id=NULL
- `is_processed(anchor_id)` → 保持（任意 status 行 = 已处理，不重试）
- `filter_unprocessed(ids)` → 保持
- 新增 `status_counts()` → `{success: N, failed: M}`
- 新增 `list_failed(limit)` → `[{anchor_fragment_id, fail_reason, synthesized_at}]`（供 status 命令捞失败）

## 3. 失败 = 标记跳过（不重试）

**用户决策**：失败**不重试**，直接标记 `failed` + 原因，跳过。用户过夜跑完后人工捞一遍 failed 的。

**改动**（`gem_synth/synthesizer.py synthesize_anchor`）：当前所有失败路径 `return None`（不记账 → 下轮重试）。改为每条失败路径**先 `log.mark_failed(anchor_id, reason)` 再 return None**：

| 失败路径 | fail_reason |
|---------|-------------|
| 无 transcript_path | `no transcript_path` |
| transcript 提取不到上下文（空） | `empty transcript context` |
| LLM 返 None（解析失败/超时/非 JSON） | `llm failed: {简短原因}` |
| _save_candidate_note 失败（写盘/构造异常） | `save failed: {e}` |

（synthesize_anchor 内部 try/except 已有；把 mark_failed 接入各路径。成功路径不变：mark_processed。）

**后果**：失败锚点被隔离（不重试、不浪费配额），ledger 可查。偶发 429 也会被标 failed —— 用户接受（人工捞重跑）。**未来**可选加 `jfox gem-synth retry-failed`（清 failed 状态重新入队），本阶段不做（YAGNI）。

## 4. `jfox gem-synth status` 命令

新增 `gem_synth_app`（Typer 子命令组，仿 `auto_summary_app`），挂 `status` 命令：

```bash
$ jfox gem-synth status
合成进度：
  待处理（pending）:  103
  成功（success）:      2
  失败（failed）:       2

$ jfox gem-synth status --failed
失败的锚点（人工复核）：
  #42  no transcript_path
  #58  llm failed: 返回非 JSON
```

- `pending` = 高信号锚点总数（fragments.db 里 correction/decision/AskUserQuestion）− ledger 里已处理（success+failed）
- `success/failed` 来自 `log.status_counts()`
- `--failed` 列出 `log.list_failed()`（fragment_id + fail_reason）
- `--format json` 支持（结构化输出）

**子命令组挂载**：`jfox/cli.py` 加 `from .gem_synth.cli import gem_synth_app` + `app.add_typer(gem_synth_app, name="gem-synth")`（与现有 `candidates_app` 共存于 `gem_synth/cli.py`）。

## 5. Schema 迁移（synthesis_log）

`SynthesisLog.__init__` 现在直接 `CREATE TABLE IF NOT EXISTS`（不改已存在表）。需加**版本化升级**：

```python
def _maybe_migrate(self):
    cols = {row["name"] for row in self._conn.execute("PRAGMA table_info(synthesis_log)")}
    if "status" not in cols:
        self._conn.execute("ALTER TABLE synthesis_log ADD COLUMN status TEXT NOT NULL DEFAULT 'success'")
    if "fail_reason" not in cols:
        self._conn.execute("ALTER TABLE synthesis_log ADD COLUMN fail_reason TEXT")
    self._conn.commit()
```

（`__init__` 建表后调 `_maybe_migrate`。新表 schema 直接含 status/fail_reason；旧表 ALTER 升级。简单 robust，无需 schema_version 表。）

## 6. 范围

**本 issue 做：**

- `_tick_once` 时间预算循环（去掉隐式 limit=100，改 limit=1 + 时间检查）
- `synthesis_log` 加 status + fail_reason 列 + migration
- `SynthesisLog.mark_failed` / `status_counts` / `list_failed`
- `synthesize_anchor` 失败路径全部 mark_failed
- `jfox gem-synth status`（含 `--failed`、`--format json`）

**不做：**

- `retry-failed` 命令（YAGNI，用户暂手动捞）
- max_per_tick 计数（用时间预算替代）
- 429 退避（失败即标 failed 跳过，不做退避重试）
- ledger 的 pending 队列表（pending = 算出来的，不持久化）

## 7. 模块改动

| 文件 | 改动 |
|------|------|
| `jfox/gem_synth/store.py` | schema 加 status/fail_reason + `_maybe_migrate`；加 `mark_failed`/`status_counts`/`list_failed` |
| `jfox/gem_synth/synthesizer.py` | 各失败路径 mark_failed；返回值可带 reason |
| `jfox/gem_synth/loop.py` | `_tick_once` 改时间预算循环（limit=1 + 时间检查） |
| `jfox/gem_synth/cli.py` | 新增 `gem_synth_app` + `status` 命令（含 `--failed`） |
| `jfox/cli.py` | 挂载 `gem_synth_app`（name="gem-synth"） |

## 8. 测试

- `store.py`：mark_failed / status_counts / list_failed / migration（旧表升级）—— 纯 SQLite 单测
- `synthesizer.py`：各失败路径 → mark_failed 被调（mock log）
- `loop.py`：时间预算循环 —— mock monotonic 验证超时停 + limit=1 逐个 + success/failed 计数
- `cli.py`：`status` / `status --failed` 输出格式 —— temp KB + ledger
