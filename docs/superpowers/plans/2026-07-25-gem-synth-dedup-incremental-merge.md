# gem-synth dedup 增量合并 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** gem-synth dedup 命中 candidate 时，按相似度分带提取增量并补进已有 candidate 草稿（而非整条跳过），损失的那 ~20% 真增量得以保留。

**Architecture:** 在 #308 的二值跳过基础上，`dedup_check` 返回 `DedupHit(note_id, note_type, score)`；`synthesize_anchor` 据分带决策——permanent / 近逐字(≥0.96) / merge 关 → 维持跳过；candidate 合并带(0.88–0.96) → 调一次 `extract_delta_with_llm` 提取增量，有实质增量则 `_merge_delta_into_candidate` 追加 `## 补充` 段 + 重算 dedup embedding + 记 `merged`。任何失败回退 `mark_duplicate`。

**Tech Stack:** Python ≥ 3.10，sqlite3 + numpy（dedup），subprocess claude -p（LLM），dataclasses（Note/DedupHit），Typer（CLI）。

## Global Constraints

- **分支**：`worktree-issue-309-dedup-incremental-merge`（worktree 内，main 受保护禁直推）
- **Line length 100**：black + ruff 都要过（CI lint 跑两步；提交前 `uv run ruff check` + `uv run black --check`，无 black 用 `uv run --with black==26.3.1 black --check`）
- **注释/文档中文**
- **TDD**：每个任务先写失败测试 → 跑红 → 实现 → 跑绿 → commit
- **lazy import 纪律**：synthesizer.py / llm.py 不被 `jfox/__init__` 模块级加载（仅 lifecycle.py 经 register 挂钩），其顶层 import 不触发 eager numpy；勿在 lifecycle.py 回调体外顶层加重依赖
- **commit 粒度**：每个 Task 一个 commit，`git add <具体文件>`（别 `git add -A`）
- **spec**：`docs/superpowers/specs/2026-07-25-gem-synth-dedup-incremental-merge-design.md`（已写）是真相源；本 plan 与之冲突以 spec 为准

## File Structure

| 文件 | 责任 | 动作 |
|------|------|------|
| `jfox/gem_synth/dedup.py` | `DedupHit` dataclass + `dedup_check` 返回富对象 | 改 |
| `jfox/gem_synth/store.py` | `mark_merged` 记账 | 加方法 |
| `jfox/gem_synth/llm.py` | `extract_delta_with_llm` + DELTA_SYSTEM_PROMPT | 加 |
| `jfox/global_config.py` | `dedup_merge_enabled` 字段 | 改 |
| `jfox/gem_synth/synthesizer.py` | dedup 分支重写 + `_merge_delta_into_candidate` + `_NEAR_VERBATIM_THRESHOLD` | 改 |
| `jfox/gem_synth/cli.py` | `gem-synth status` 显示 merged | 改 |
| `tests/unit/test_gem_synth_dedup.py` | DedupHit 断言 | 改 |
| `tests/unit/test_gem_synth_store.py` | mark_merged | 加 |
| `tests/unit/test_gem_synth_llm.py` | extract_delta_with_llm | 加 |
| `tests/unit/test_gem_synth_config_dedup.py` | dedup_merge_enabled | 加 |
| `tests/unit/test_synthesizer_dedup.py` | mock 改 DedupHit + 合并路径 | 改+加 |
| `CLAUDE.md` | gem_synth 模块说明 | 改 |

---

### Task 1: dedup_check 返回 DedupHit（行为保持重构）

**Files:**
- Modify: `jfox/gem_synth/dedup.py`（`DedupStore.all_embeddings` + `dedup_check`）
- Modify: `jfox/gem_synth/synthesizer.py:191-204`（dedup 分支 unpack `hit.note_id`）
- Test: `tests/unit/test_gem_synth_dedup.py`、`tests/unit/test_synthesizer_dedup.py`

**Interfaces:**
- Produces: `DedupHit` dataclass（`note_id: str`, `note_type: str`, `score: float`）；`dedup_check(kb, content, threshold=0.88) -> Optional[DedupHit]`

> 行为保持：此 Task 不引入合并逻辑，只改返回类型 + 让 synthesizer 解包 `hit.note_id`。所有现有测试调整 mock 后应仍绿。

- [ ] **Step 1: 写失败测试（dedup_check 返回 DedupHit）**

在 `tests/unit/test_gem_synth_dedup.py` 顶部 import 加 `DedupHit`：
```python
from jfox.gem_synth.dedup import DedupHit, DedupStore
```
改 `test_dedup_check_hits_existing_dup`：
```python
def test_dedup_check_hits_existing_dup(setup):
    dedup.upsert_dedup("default", "cand-1", "candidate", "Zima 双 Bot babysit 标签循环")
    hit = dedup.dedup_check("default", "Zima 双 Bot babysit 标签循环", threshold=0.5)
    assert isinstance(hit, DedupHit)
    assert hit.note_id == "cand-1"
    assert hit.note_type == "candidate"
    assert hit.score >= 0.5
```
新增（permanent 也带 type）：
```python
def test_dedup_check_returns_permanent_type(setup):
    dedup.upsert_dedup("default", "perm-1", "permanent", "某永久知识结论")
    hit = dedup.dedup_check("default", "某永久知识结论", threshold=0.5)
    assert isinstance(hit, DedupHit)
    assert hit.note_type == "permanent"
```
在 `tests/unit/test_synthesizer_dedup.py` 顶部 import：
```python
from jfox.gem_synth.dedup import DedupHit
```
改 `test_duplicate_hit_skips_save_and_marks_duplicate` 的 dedup_check mock（score 用 0.99，留待 Task 6 后仍走 skip 路径）：
```python
        patch(
            "jfox.gem_synth.synthesizer.dedup_check",
            return_value=DedupHit("existing-id", "candidate", 0.99),
        ) as mcheck,
```

- [ ] **Step 2: 跑红**

Run: `uv run pytest tests/unit/test_gem_synth_dedup.py::test_dedup_check_hits_existing_dup tests/unit/test_synthesizer_dedup.py -v`
Expected: FAIL（`DedupHit` 未定义 / `hit == "cand-1"` 比较 dataclass 失败）

- [ ] **Step 3: 实现 DedupHit + dedup_check 改返回**

`jfox/gem_synth/dedup.py`，在 import 区下、`_SCHEMA` 前加：
```python
from dataclasses import dataclass


@dataclass
class DedupHit:
    """dedup 命中结果：note_id + note_type（candidate/permanent）+ 余弦分数。

    note_type 供合成侧分流（permanent 跳过、candidate 进合并带）；score 供分带
    （≥0.96 近逐字省 LLM，0.88–0.96 才提取增量）。"""

    note_id: str
    note_type: str
    score: float
```
`DedupStore.all_embeddings` 改为多 select `note_type`：
```python
    def all_embeddings(self, kb: str, note_types: Tuple[str, ...]) -> List[Tuple[str, str, np.ndarray]]:
        """返回 [(note_id, note_type, emb)]。note_type 供合成侧分流的富返回。"""
        if not note_types:
            return []
        placeholders = ",".join("?" * len(note_types))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT note_id, note_type, emb FROM dedup_embeddings "
                f"WHERE kb=? AND note_type IN ({placeholders})",
                (kb, *note_types),
            ).fetchall()
        return [(r["note_id"], r["note_type"], np.frombuffer(r["emb"], dtype=np.float32)) for r in rows]
```
`dedup_check` 改返回 `Optional[DedupHit]`（更新 docstring + 把 `rows[best][0]` 换成构造 DedupHit；`rows[best][1]` 是 note_type、`sims[best]` 是 score）：
```python
def dedup_check(kb: str, content: str, threshold: float = 0.88) -> Optional[DedupHit]:
    """返回与已有 candidate/permanent 最相似的 DedupHit；无重复或降级时返回 None。

    daemon 不可用 / 空内容 / 表空 → 返回 None（降级放行，不阻塞合成）。
    返回富对象（note_id + note_type + score）供 #309 增量合并分带决策。"""
    try:
        cleaned = _clean_candidate_content(content)
        if not cleaned:
            return None
        emb = _embed(cleaned)
        if emb is None:
            return None
        rows = _get_store().all_embeddings(kb, ("candidate", "permanent"))
        if not rows:
            return None
        mat = np.vstack([r[2] for r in rows])  # (N, D)；rows 现为 (id, type, emb)
        norms = (np.linalg.norm(mat, axis=1) + 1e-12) * (np.linalg.norm(emb) + 1e-12)
        sims = (mat @ emb) / norms
        np.nan_to_num(sims, nan=-1.0, copy=False)
        best = int(np.argmax(sims))
        if sims[best] >= threshold:
            return DedupHit(rows[best][0], rows[best][1], float(sims[best]))
    except Exception as e:
        logger.warning("dedup_check 失败，降级跳过: %s", e)
        return None
    return None
```
`__all__` 加 `"DedupHit"`。

- [ ] **Step 4: 实现 synthesizer 解包 hit.note_id**

`jfox/gem_synth/synthesizer.py:196-204`，把：
```python
        dup_of = dedup_check(
            kb_name,
            content,
            threshold=getattr(cfg, "dedup_threshold", 0.88),
        )
        if dup_of:
            logger.info("锚点 #%s 命中重复（dup_of=%s），跳过存盘", anchor["fragment_id"], dup_of)
            log.mark_duplicate(anchor["fragment_id"], dup_of)
            return None
```
改为：
```python
        hit = dedup_check(
            kb_name,
            content,
            threshold=getattr(cfg, "dedup_threshold", 0.88),
        )
        if hit:
            logger.info(
                "锚点 #%s 命中重复（dup_of=%s, score=%.3f），跳过存盘",
                anchor["fragment_id"],
                hit.note_id,
                hit.score,
            )
            log.mark_duplicate(anchor["fragment_id"], hit.note_id)
            return None
```

- [ ] **Step 5: 跑绿**

Run: `uv run pytest tests/unit/test_gem_synth_dedup.py tests/unit/test_synthesizer_dedup.py -v`
Expected: PASS（含新增 permanent-type 与既有全部用例）

- [ ] **Step 6: lint + commit**

```bash
uv run ruff check jfox/gem_synth/dedup.py jfox/gem_synth/synthesizer.py tests/unit/test_gem_synth_dedup.py tests/unit/test_synthesizer_dedup.py
uv run --with black==26.3.1 black --check jfox/gem_synth/dedup.py jfox/gem_synth/synthesizer.py tests/unit/test_gem_synth_dedup.py tests/unit/test_synthesizer_dedup.py
git add jfox/gem_synth/dedup.py jfox/gem_synth/synthesizer.py tests/unit/test_gem_synth_dedup.py tests/unit/test_synthesizer_dedup.py
git commit -m "refactor(gem-synth): dedup_check 返回 DedupHit(note_id+type+score)

行为保持：只富化返回类型，synthesizer 解包 hit.note_id，为 #309 增量合并
分带决策铺路。permanent/note_type/score 后续用于 candidate-only 合并分流。"
```

---

### Task 2: SynthesisLog.mark_merged

**Files:**
- Modify: `jfox/gem_synth/store.py`（加 `mark_merged`）
- Test: `tests/unit/test_gem_synth_store.py`

**Interfaces:**
- Produces: `SynthesisLog.mark_merged(anchor_fragment_id: int, target_note_id: str) -> None`；写入 `status='merged'` + `candidate_note_id=target_note_id`，`is_processed` 仍 True。

- [ ] **Step 1: 写失败测试**

`tests/unit/test_gem_synth_store.py` 加：
```python
def test_mark_merged_writes_status_and_target(tmp_path):
    from jfox.gem_synth.store import SynthesisLog

    log = SynthesisLog(db_path=tmp_path / "s.db")
    log.mark_merged(7, "cand-target-1")
    assert log.is_processed(7) is True  # merged 也算已处理，锚点不重试
    counts = log.status_counts()
    assert counts.get("merged") == 1
    log.close()


def test_mark_merged_then_duplicate_distinct_counts(tmp_path):
    """merged 与 duplicate 分别计数（status CLI 可观测合并 vs 跳过）。"""
    from jfox.gem_synth.store import SynthesisLog

    log = SynthesisLog(db_path=tmp_path / "s.db")
    log.mark_merged(1, "t1")
    log.mark_duplicate(2, "t2")
    counts = log.status_counts()
    assert counts == {"merged": 1, "duplicate": 1}
    log.close()
```

- [ ] **Step 2: 跑红**

Run: `uv run pytest tests/unit/test_gem_synth_store.py::test_mark_merged_writes_status_and_target -v`
Expected: FAIL（`AttributeError: mark_merged`）

- [ ] **Step 3: 实现 mark_merged**

`jfox/gem_synth/store.py`，`mark_duplicate` 方法后加：
```python
    def mark_merged(self, anchor_fragment_id: int, target_note_id: str) -> None:
        """合并记账：status='merged' + candidate_note_id=被补入的目标 candidate。
        记账后 is_processed=True → 锚点不重试。与 duplicate 区分，供 status 单独
        统计「命中后增量合并」vs「直接跳过」。复用现有列，无需 schema 变更。"""
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO synthesis_log "
                "(anchor_fragment_id, candidate_note_id, status) VALUES (?, ?, 'merged')",
                (anchor_fragment_id, target_note_id),
            )
            self._conn.commit()
```

- [ ] **Step 4: 跑绿**

Run: `uv run pytest tests/unit/test_gem_synth_store.py -v`
Expected: PASS（含新增两例 + 既有全过）

- [ ] **Step 5: lint + commit**

```bash
uv run ruff check jfox/gem_synth/store.py tests/unit/test_gem_synth_store.py
uv run --with black==26.3.1 black --check jfox/gem_synth/store.py tests/unit/test_gem_synth_store.py
git add jfox/gem_synth/store.py tests/unit/test_gem_synth_store.py
git commit -m "feat(gem-synth): SynthesisLog.mark_merged 记合并状态

#309 增量合并命中后记 status=merged + 目标 candidate_note_id，与 duplicate
区分供 status 观测；is_processed 仍 True 不重试。复用现有列无 schema 变更。"
```

---

### Task 3: extract_delta_with_llm

**Files:**
- Modify: `jfox/gem_synth/llm.py`（加 `DELTA_SYSTEM_PROMPT` + `extract_delta_with_llm` + `__all__`）
- Test: `tests/unit/test_gem_synth_llm.py`

**Interfaces:**
- Consumes: `_invoke_claude(prompt, cfg, stop_event)`、`_parse_json_lenient(inner)`
- Produces: `extract_delta_with_llm(new_content: str, existing_content: str, cfg: GemSynthesisConfig, stop_event: Optional[threading.Event]=None) -> Optional[Dict]`；返回 `{has_delta: bool, delta: str, conflict: Optional[str]}` 或 None

- [ ] **Step 1: 写失败测试**

`tests/unit/test_gem_synth_llm.py` 顶部 import 改：
```python
from jfox.gem_synth.llm import _build_prompt, extract_delta_with_llm, synthesize_with_llm
```
加：
```python
def test_extract_delta_parses_has_delta_true():
    """有增量：LLM 返回 has_delta=true + delta 正文，解析为 dict。"""
    inner = json.dumps({"has_delta": True, "delta": "新增：标签被移除≠审完", "conflict": None})
    fake_output = json.dumps({"result": inner})
    with patch("jfox.gem_synth.llm._invoke_claude", return_value=fake_output):
        result = extract_delta_with_llm("new", "existing", cfg=MagicMock())
    assert result is not None
    assert result["has_delta"] is True
    assert "标签被移除" in result["delta"]


def test_extract_delta_parses_has_delta_false():
    """无实质增量：has_delta=false，delta 空。"""
    inner = json.dumps({"has_delta": False, "delta": "", "conflict": None})
    with patch("jfox.gem_synth.llm._invoke_claude", return_value=json.dumps({"result": inner})):
        result = extract_delta_with_llm("new", "existing", cfg=MagicMock())
    assert result is not None
    assert result["has_delta"] is False


def test_extract_delta_parses_conflict():
    """矛盾被标出：conflict 非空。"""
    inner = json.dumps(
        {"has_delta": True, "delta": "B 主张 30min", "conflict": "与 X 的 60min 矛盾"}
    )
    with patch("jfox.gem_synth.llm._invoke_claude", return_value=json.dumps({"result": inner})):
        result = extract_delta_with_llm("new", "existing", cfg=MagicMock())
    assert result["conflict"] == "与 X 的 60min 矛盾"


def test_extract_delta_strips_fence():
    """LLM 把 JSON 包围栏时也能解析（复用 _parse_json_lenient）。"""
    inner = json.dumps({"has_delta": True, "delta": "d", "conflict": None})
    fenced = f"```json\n{inner}\n```"
    with patch("jfox.gem_synth.llm._invoke_claude", return_value=json.dumps({"result": fenced})):
        result = extract_delta_with_llm("new", "existing", cfg=MagicMock())
    assert result is not None and result["has_delta"] is True


def test_extract_delta_none_on_missing_has_delta():
    """缺 has_delta 键 → None（调用方降级 mark_duplicate）。"""
    inner = json.dumps({"delta": "d"})  # 无 has_delta
    with patch("jfox.gem_synth.llm._invoke_claude", return_value=json.dumps({"result": inner})):
        assert extract_delta_with_llm("new", "existing", cfg=MagicMock()) is None


def test_extract_delta_none_on_exception():
    with patch("jfox.gem_synth.llm._invoke_claude", side_effect=RuntimeError("boom")):
        assert extract_delta_with_llm("new", "existing", cfg=MagicMock()) is None
```

- [ ] **Step 2: 跑红**

Run: `uv run pytest tests/unit/test_gem_synth_llm.py -k extract_delta -v`
Expected: FAIL（`ImportError: cannot import name 'extract_delta_with_llm'`）

- [ ] **Step 3: 实现 extract_delta_with_llm**

`jfox/gem_synth/llm.py`，`SYSTEM_PROMPT` 定义后加第二个 system prompt：
```python
DELTA_SYSTEM_PROMPT = """你是知识增量提取器。给定一条已有笔记 X 和一条新候选 Y（两者讲同一件事），
提取 Y 相对 X 的**有效增量**——新角度、补充事实、或差异。严格输出 JSON：
{
  "has_delta": true/false（Y 是否相对 X 有实质新增；近乎雷同给 false）,
  "delta": "Markdown 增量正文；无增量则空串",
  "conflict": "Y 与 X 矛盾处的简述；无矛盾则 null"
}
只比较知识本身，忽略格式差异。不要重复 X 已有的内容。直接输出 JSON 对象本身，不要用 markdown 代码围栏包裹。"""
```
文件末尾（`synthesize_with_llm` 之后、`__all__` 之前）加：
```python
def _build_delta_prompt(new_content: str, existing_content: str) -> str:
    """组装增量提取 prompt：已有笔记 + 新候选。"""
    return f"""## 已有笔记 X
{existing_content}

## 新候选 Y
{new_content}

提取 Y 相对 X 的有效增量。只输出 JSON。"""


def extract_delta_with_llm(
    new_content: str,
    existing_content: str,
    cfg: GemSynthesisConfig,
    stop_event: Optional[threading.Event] = None,
) -> Optional[Dict[str, Any]]:
    """提取新 candidate 相对已有 candidate 的有效增量。失败返回 None（调用方降级跳过）。

    复用 synthesize_with_llm 的两层 JSON 解析（claude --output-format json 的 result
    包装）+ _parse_json_lenient（容忍围栏/前导文本）。缺 has_delta 键视为无效 → None。
    stop_event 透传给 _invoke_claude，daemon shutdown 可中断。
    """
    try:
        prompt = _build_delta_prompt(new_content, existing_content)
        raw = _invoke_claude(prompt, cfg, stop_event)
        wrapper = json.loads(raw)
        inner = wrapper.get("result", raw) if isinstance(wrapper, dict) else raw
        parsed = _parse_json_lenient(inner)
        if not isinstance(parsed, dict) or "has_delta" not in parsed:
            logger.warning("delta LLM 输出缺 has_delta: %r", parsed)
            return None
        return parsed
    except Exception as e:
        logger.exception("delta LLM 提取失败: %s", e)
        return None
```
`_invoke_claude` 需要能接 `DELTA_SYSTEM_PROMPT`——当前 `_invoke_claude` 硬编码 `SYSTEM_PROMPT` 到 `--append-system-prompt`。改为参数化：把 `_invoke_claude` 签名加 `system_prompt: str = SYSTEM_PROMPT`，cmd 里 `SYSTEM_PROMPT` 换成 `system_prompt`。`synthesize_with_llm` 调用处不动（用默认）；`extract_delta_with_llm` 调 `_invoke_claude(prompt, cfg, stop_event, system_prompt=DELTA_SYSTEM_PROMPT)`。

> 改 `_invoke_claude` 签名：在 `def _invoke_claude(prompt, cfg, stop_event=None):` 后加默认参 `system_prompt: str = SYSTEM_PROMPT`，函数体 `--append-system-prompt` 后的 `SYSTEM_PROMPT` 改 `system_prompt`。既有 `synthesize_with_llm` / 既有测试不传该参 → 用默认，行为不变。

`__all__` 加 `"extract_delta_with_llm"`。

- [ ] **Step 4: 跑绿**

Run: `uv run pytest tests/unit/test_gem_synth_llm.py -v`
Expected: PASS（新增 6 例 + 既有全过）

- [ ] **Step 5: lint + commit**

```bash
uv run ruff check jfox/gem_synth/llm.py tests/unit/test_gem_synth_llm.py
uv run --with black==26.3.1 black --check jfox/gem_synth/llm.py tests/unit/test_gem_synth_llm.py
git add jfox/gem_synth/llm.py tests/unit/test_gem_synth_llm.py
git commit -m "feat(gem-synth): extract_delta_with_llm 提取候选相对已有笔记的增量

#309：dedup 命中后调一次 LLM 问「新候选相对已有笔记多了什么」，输出
{has_delta, delta, conflict}。复用 _invoke_claude（参数化 system_prompt）
+ _parse_json_lenient。失败/缺键返回 None 供调用方降级跳过。"
```

---

### Task 4: GemSynthesisConfig.dedup_merge_enabled

**Files:**
- Modify: `jfox/global_config.py`（`GemSynthesisConfig` 字段 + `from_dict`）
- Test: `tests/unit/test_gem_synth_config_dedup.py`

**Interfaces:**
- Produces: `GemSynthesisConfig.dedup_merge_enabled: bool`（默认 True）

- [ ] **Step 1: 写失败测试**

`tests/unit/test_gem_synth_config_dedup.py` 加：
```python
def test_dedup_merge_enabled_defaults_true():
    assert GemSynthesisConfig().dedup_merge_enabled is True


def test_dedup_merge_enabled_from_dict():
    cfg = GemSynthesisConfig.from_dict({"dedup_merge_enabled": False})
    assert cfg.dedup_merge_enabled is False


def test_dedup_merge_enabled_missing_uses_default():
    cfg = GemSynthesisConfig.from_dict({})
    assert cfg.dedup_merge_enabled is True
```

- [ ] **Step 2: 跑红**

Run: `uv run pytest tests/unit/test_gem_synth_config_dedup.py -k merge -v`
Expected: FAIL（`AttributeError: dedup_merge_enabled`）

- [ ] **Step 3: 实现**

`jfox/global_config.py`，`GemSynthesisConfig` 字段区 `dedup_threshold` 那行后加：
```python
    dedup_merge_enabled: bool = True  # 命中 candidate 时提取增量补入（#309）；False 回 #308 二值跳过
```
`from_dict` 的 return 里，`dedup_threshold=...` 之后加：
```python
            dedup_merge_enabled=bool(data.get("dedup_merge_enabled", True)),
```

- [ ] **Step 4: 跑绿**

Run: `uv run pytest tests/unit/test_gem_synth_config_dedup.py -v`
Expected: PASS（新增 3 例 + 既有全过）

- [ ] **Step 5: lint + commit**

```bash
uv run ruff check jfox/global_config.py tests/unit/test_gem_synth_config_dedup.py
uv run --with black==26.3.1 black --check jfox/global_config.py tests/unit/test_gem_synth_config_dedup.py
git add jfox/global_config.py tests/unit/test_gem_synth_config_dedup.py
git commit -m "feat(gem-synth): GemSynthesisConfig.dedup_merge_enabled 默认 True

#309 增量合并开关。与 dedup_enabled 正交：dedup_enabled=False 整条关；
dedup_merge_enabled=False 则命中仍走 #308 二值跳过。"
```

---

### Task 5: _merge_delta_into_candidate

**Files:**
- Modify: `jfox/gem_synth/synthesizer.py`（加 `_merge_delta_into_candidate` + import `update_note`/`load_note_by_id`）
- Test: `tests/unit/test_synthesizer_dedup.py`

**Interfaces:**
- Consumes: `Note`（models）、`update_note(note, add_to_index=False)`、`upsert_dedup(kb, note_id, note_type, content)`
- Produces: `_merge_delta_into_candidate(existing_note: Note, delta: Dict, anchor: Dict, kb: str) -> bool`；追加 `## 补充` 段 + `update_note` + 重算 embedding；失败返回 False

- [ ] **Step 1: 写失败测试**

`tests/unit/test_synthesizer_dedup.py` 加：
```python
def test_merge_appends_delta_section_and_recomputes_embedding():
    """有增量时：追加 ## 补充 段、update_note 落盘、upsert_dedup 用合并后内容重算。"""
    from datetime import datetime

    from jfox.models import GemLevel, Note, NoteType

    existing = Note(
        id="20260725000000",
        title="Zima 双 Bot CR",
        content="## 双 Bot 工作流\ncc + kimi 轮询",
        type=NoteType.CANDIDATE,
        created=datetime(2026, 7, 25),
        updated=datetime(2026, 7, 25),
        gem_level=GemLevel.FLAWED.value,
        status="pending",
    )
    delta = {"has_delta": True, "delta": "标签被移除≠审完", "conflict": None}
    anchor = {"fragment_id": 42, "timestamp": "2026-07-25T20:00:00"}

    with (
        patch("jfox.gem_synth.synthesizer.update_note") as mupdate,
        patch("jfox.gem_synth.synthesizer.upsert_dedup") as mupsert,
    ):
        ok = synthesizer._merge_delta_into_candidate(existing, delta, anchor, "default")

    assert ok is True
    # 正文被追加了 ## 补充 段 + delta 内容
    assert "## 补充（来自锚点 #42" in existing.content
    assert "标签被移除≠审完" in existing.content
    mupdate.assert_called_once_with(existing, add_to_index=False)
    # 重算 embedding 用的是合并后的正文（关键：内容已变）
    mupsert.assert_called_once()
    assert mupsert.call_args[0][0] == "default"
    assert mupsert.call_args[0][1] == "20260725000000"
    assert "标签被移除≠审完" in mupsert.call_args[0][3]


def test_merge_includes_conflict_marker():
    """LLM 标了矛盾时，追加段含 ⚠️ 矛盾 行。"""
    from datetime import datetime

    from jfox.models import GemLevel, Note, NoteType

    existing = Note(
        id="20260725000001",
        title="T",
        content="原结论",
        type=NoteType.CANDIDATE,
        created=datetime(2026, 7, 25),
        updated=datetime(2026, 7, 25),
        gem_level=GemLevel.FLAWED.value,
        status="pending",
    )
    delta = {"has_delta": True, "delta": "B 主张 30min", "conflict": "与 X 的 60min 矛盾"}

    with (
        patch("jfox.gem_synth.synthesizer.update_note"),
        patch("jfox.gem_synth.synthesizer.upsert_dedup"),
    ):
        synthesizer._merge_delta_into_candidate(existing, delta, {}, "default")

    assert "⚠️ 矛盾" in existing.content
    assert "60min" in existing.content


def test_merge_returns_false_on_update_failure():
    """update_note 抛异常 → 返回 False（调用方降级 mark_duplicate）。"""
    from jfox.models import Note, NoteType

    existing = Note(
        id="x",
        title="T",
        content="c",
        type=NoteType.CANDIDATE,
        created=__import__("datetime").datetime(2026, 7, 25),
        updated=__import__("datetime").datetime(2026, 7, 25),
    )
    with (
        patch("jfox.gem_synth.synthesizer.update_note", side_effect=RuntimeError("io")),
        patch("jfox.gem_synth.synthesizer.upsert_dedup"),
    ):
        ok = synthesizer._merge_delta_into_candidate(
            existing, {"has_delta": True, "delta": "d", "conflict": None}, {}, "default"
        )
    assert ok is False
```

- [ ] **Step 2: 跑红**

Run: `uv run pytest tests/unit/test_synthesizer_dedup.py -k merge -v`
Expected: FAIL（`AttributeError: _merge_delta_into_candidate`）

- [ ] **Step 3: 实现**

`jfox/gem_synth/synthesizer.py` 顶部 import 改（`from ..note import save_note` → 加 `update_note`；`from .dedup import _resolve_kb_name, dedup_check, upsert_dedup` 已有 `upsert_dedup`）：
```python
from ..note import load_note_by_id, save_note, update_note
```
在 `_save_candidate_note` 之前（或 `_persist_note` 之后）加：
```python
def _merge_delta_into_candidate(
    existing_note: Note, delta: Dict[str, Any], anchor: Dict[str, Any], kb: str
) -> bool:
    """把增量补进已有 candidate 草稿（in-place 追加）。失败返回 False（调用方降级跳过）。

    调用方已 load + 校验过 existing_note（非 None / 非 archived / type=CANDIDATE），
    本函数只负责：追加 `## 补充（来自锚点 #X）` 段 → update_note 落盘 → 重算 dedup
    embedding（内容已变，content_hash 变 → upsert_dedup 重 embed，防后续查重失明）。

    delta: {has_delta: True, delta: str, conflict: Optional[str]}（extract_delta_with_llm 返回）。
    """
    try:
        delta_text = delta.get("delta") or ""
        section = f"\n\n## 补充（来自锚点 #{anchor.get('fragment_id')} @ {anchor.get('timestamp')})\n{delta_text}\n"
        conflict = delta.get("conflict")
        if conflict:
            section += f"\n> ⚠️ 矛盾：{conflict}\n"
        existing_note.content = existing_note.content + section
        update_note(existing_note, add_to_index=False)
        upsert_dedup(kb, existing_note.id, "candidate", existing_note.content)
        return True
    except Exception as e:
        logger.exception("合并增量进 candidate 失败 note=%s: %s", existing_note.id, e)
        return False
```

- [ ] **Step 4: 跑绿**

Run: `uv run pytest tests/unit/test_synthesizer_dedup.py -k merge -v`
Expected: PASS（3 例全过）

- [ ] **Step 5: lint + commit**

```bash
uv run ruff check jfox/gem_synth/synthesizer.py tests/unit/test_synthesizer_dedup.py
uv run --with black==26.3.1 black --check jfox/gem_synth/synthesizer.py tests/unit/test_synthesizer_dedup.py
git add jfox/gem_synth/synthesizer.py tests/unit/test_synthesizer_dedup.py
git commit -m "feat(gem-synth): _merge_delta_into_candidate 增量补入 candidate

#309：把 delta 追加成 ## 补充 段（含来源锚点 + 可选矛盾标注），update_note
落盘 + 重算 dedup embedding（合并后内容已变）。失败返回 False 供降级。"
```

---

### Task 6: synthesize_anchor dedup 分支重写（接入合并）

**Files:**
- Modify: `jfox/gem_synth/synthesizer.py:191-204`（dedup 分支决策树）+ 模块常量 + import
- Test: `tests/unit/test_synthesizer_dedup.py`

**Interfaces:**
- Consumes: Task 1 `DedupHit`/`dedup_check`、Task 3 `extract_delta_with_llm`、Task 4 `cfg.dedup_merge_enabled`、Task 5 `_merge_delta_into_candidate`、`load_note_by_id`、`_clean_candidate_content`

- [ ] **Step 1: 写失败测试**

`tests/unit/test_synthesizer_dedup.py` 加（复用文件既有 `_anchor()` + patch 风格）：
```python
def test_candidate_merge_band_triggers_merge_and_mark_merged():
    """candidate + 0.88–0.96 合并带 + merge 开 + 有增量 → 调 extract_delta、
    _merge、mark_merged（非 mark_duplicate）。"""
    from jfox.gem_synth.dedup import DedupHit

    class FakeLog:
        def __init__(self):
            self.calls = []

        def mark_duplicate(self, fid, dup_of):
            self.calls.append(("dup", fid, dup_of))

        def mark_merged(self, fid, target):
            self.calls.append(("merged", fid, target))

    cfg = GemSynthesisConfig()
    cfg.dedup_enabled = True  # type: ignore[attr-defined]
    cfg.dedup_merge_enabled = True  # type: ignore[attr-defined]
    cfg.target_kb = "default"  # type: ignore[attr-defined]

    with (
        patch("jfox.gem_synth.synthesizer.extract_turn_around", return_value="ctx"),
        patch("jfox.gem_synth.synthesizer.fetch_grounding", return_value=[]),
        patch(
            "jfox.gem_synth.synthesizer.synthesize_with_llm",
            return_value={"title": "T", "content": "C", "confidence": 0.9},
        ),
        patch(
            "jfox.gem_synth.synthesizer.dedup_check",
            return_value=DedupHit("cand-target", "candidate", 0.91),
        ),
        patch(
            "jfox.gem_synth.synthesizer.extract_delta_with_llm",
            return_value={"has_delta": True, "delta": "新增点", "conflict": None},
        ),
        patch("jfox.gem_synth.synthesizer.load_note_by_id") as mload,
        patch("jfox.gem_synth.synthesizer._merge_delta_into_candidate", return_value=True) as mmerge,
    ):
        mload.return_value = _existing_candidate()  # 真 Note：过 type=CANDIDATE guard
        fake_log = FakeLog()
        result = synthesizer.synthesize_anchor(_anchor(), log=fake_log, cfg=cfg)

    assert result is None  # 合并不产新 candidate
    assert ("merged", 77, "cand-target") in fake_log.calls
    mmerge.assert_called_once()


def test_permanent_hit_still_skips_no_delta_call():
    """命中 permanent → mark_duplicate，不调 extract_delta（scope 外）。"""
    from jfox.gem_synth.dedup import DedupHit

    class FakeLog:
        def __init__(self):
            self.calls = []

        def mark_duplicate(self, fid, dup_of):
            self.calls.append(("dup", fid, dup_of))

        def mark_merged(self, fid, target):
            self.calls.append(("merged", fid, target))

    cfg = GemSynthesisConfig()
    cfg.dedup_enabled = True  # type: ignore[attr-defined]
    cfg.dedup_merge_enabled = True  # type: ignore[attr-defined]
    cfg.target_kb = "default"  # type: ignore[attr-defined]

    with (
        patch("jfox.gem_synth.synthesizer.extract_turn_around", return_value="ctx"),
        patch("jfox.gem_synth.synthesizer.fetch_grounding", return_value=[]),
        patch(
            "jfox.gem_synth.synthesizer.synthesize_with_llm",
            return_value={"title": "T", "content": "C", "confidence": 0.9},
        ),
        patch(
            "jfox.gem_synth.synthesizer.dedup_check",
            return_value=DedupHit("perm-target", "permanent", 0.91),
        ),
        patch("jfox.gem_synth.synthesizer.extract_delta_with_llm") as mdelta,
        patch("jfox.gem_synth.synthesizer._merge_delta_into_candidate") as mmerge,
    ):
        fake_log = FakeLog()
        synthesizer.synthesize_anchor(_anchor(), log=fake_log, cfg=cfg)

    assert ("dup", 77, "perm-target") in fake_log.calls
    mdelta.assert_not_called()
    mmerge.assert_not_called()


def test_near_verbatim_skips_delta_call():
    """candidate 但 score≥0.96（近逐字）→ mark_duplicate，省 LLM 不调 extract_delta。"""
    from jfox.gem_synth.dedup import DedupHit

    class FakeLog:
        def __init__(self):
            self.calls = []

        def mark_duplicate(self, fid, dup_of):
            self.calls.append(("dup", fid, dup_of))

        def mark_merged(self, fid, target):
            self.calls.append(("merged", fid, target))

    cfg = GemSynthesisConfig()
    cfg.dedup_enabled = True  # type: ignore[attr-defined]
    cfg.dedup_merge_enabled = True  # type: ignore[attr-defined]
    cfg.target_kb = "default"  # type: ignore[attr-defined]

    with (
        patch("jfox.gem_synth.synthesizer.extract_turn_around", return_value="ctx"),
        patch("jfox.gem_synth.synthesizer.fetch_grounding", return_value=[]),
        patch(
            "jfox.gem_synth.synthesizer.synthesize_with_llm",
            return_value={"title": "T", "content": "C", "confidence": 0.9},
        ),
        patch(
            "jfox.gem_synth.synthesizer.dedup_check",
            return_value=DedupHit("cand-target", "candidate", 0.97),
        ),
        patch("jfox.gem_synth.synthesizer.extract_delta_with_llm") as mdelta,
    ):
        fake_log = FakeLog()
        synthesizer.synthesize_anchor(_anchor(), log=fake_log, cfg=cfg)

    assert ("dup", 77, "cand-target") in fake_log.calls
    mdelta.assert_not_called()


def test_merge_disabled_skips_delta_call():
    """dedup_merge_enabled=False → candidate 合并带也走 mark_duplicate，不调 delta LLM。"""
    from jfox.gem_synth.dedup import DedupHit

    class FakeLog:
        def __init__(self):
            self.calls = []

        def mark_duplicate(self, fid, dup_of):
            self.calls.append(("dup", fid, dup_of))

    cfg = GemSynthesisConfig()
    cfg.dedup_enabled = True  # type: ignore[attr-defined]
    cfg.dedup_merge_enabled = False  # type: ignore[attr-defined]
    cfg.target_kb = "default"  # type: ignore[attr-defined]

    with (
        patch("jfox.gem_synth.synthesizer.extract_turn_around", return_value="ctx"),
        patch("jfox.gem_synth.synthesizer.fetch_grounding", return_value=[]),
        patch(
            "jfox.gem_synth.synthesizer.synthesize_with_llm",
            return_value={"title": "T", "content": "C", "confidence": 0.9},
        ),
        patch(
            "jfox.gem_synth.synthesizer.dedup_check",
            return_value=DedupHit("cand-target", "candidate", 0.91),
        ),
        patch("jfox.gem_synth.synthesizer.extract_delta_with_llm") as mdelta,
    ):
        fake_log = FakeLog()
        synthesizer.synthesize_anchor(_anchor(), log=fake_log, cfg=cfg)

    assert ("dup", 77, "cand-target") in fake_log.calls
    mdelta.assert_not_called()


def test_delta_llm_returns_none_degrades_to_skip():
    """delta LLM 失败 → 降级 mark_duplicate。"""
    from jfox.gem_synth.dedup import DedupHit

    class FakeLog:
        def __init__(self):
            self.calls = []

        def mark_duplicate(self, fid, dup_of):
            self.calls.append(("dup", fid, dup_of))

        def mark_merged(self, fid, target):
            self.calls.append(("merged", fid, target))

    cfg = GemSynthesisConfig()
    cfg.dedup_enabled = True  # type: ignore[attr-defined]
    cfg.dedup_merge_enabled = True  # type: ignore[attr-defined]
    cfg.target_kb = "default"  # type: ignore[attr-defined]

    with (
        patch("jfox.gem_synth.synthesizer.extract_turn_around", return_value="ctx"),
        patch("jfox.gem_synth.synthesizer.fetch_grounding", return_value=[]),
        patch(
            "jfox.gem_synth.synthesizer.synthesize_with_llm",
            return_value={"title": "T", "content": "C", "confidence": 0.9},
        ),
        patch(
            "jfox.gem_synth.synthesizer.dedup_check",
            return_value=DedupHit("cand-target", "candidate", 0.91),
        ),
        patch("jfox.gem_synth.synthesizer.load_note_by_id", return_value=_existing_candidate()),
        patch("jfox.gem_synth.synthesizer.extract_delta_with_llm", return_value=None),
        patch("jfox.gem_synth.synthesizer._merge_delta_into_candidate") as mmerge,
    ):
        fake_log = FakeLog()
        synthesizer.synthesize_anchor(_anchor(), log=fake_log, cfg=cfg)

    assert ("dup", 77, "cand-target") in fake_log.calls
    mmerge.assert_not_called()


def test_delta_has_delta_false_skips():
    """LLM 判无实质增量 → mark_duplicate（不合并）。"""
    from jfox.gem_synth.dedup import DedupHit

    class FakeLog:
        def __init__(self):
            self.calls = []

        def mark_duplicate(self, fid, dup_of):
            self.calls.append(("dup", fid, dup_of))

        def mark_merged(self, fid, target):
            self.calls.append(("merged", fid, target))

    cfg = GemSynthesisConfig()
    cfg.dedup_enabled = True  # type: ignore[attr-defined]
    cfg.dedup_merge_enabled = True  # type: ignore[attr-defined]
    cfg.target_kb = "default"  # type: ignore[attr-defined]

    with (
        patch("jfox.gem_synth.synthesizer.extract_turn_around", return_value="ctx"),
        patch("jfox.gem_synth.synthesizer.fetch_grounding", return_value=[]),
        patch(
            "jfox.gem_synth.synthesizer.synthesize_with_llm",
            return_value={"title": "T", "content": "C", "confidence": 0.9},
        ),
        patch(
            "jfox.gem_synth.synthesizer.dedup_check",
            return_value=DedupHit("cand-target", "candidate", 0.91),
        ),
        patch("jfox.gem_synth.synthesizer.load_note_by_id", return_value=_existing_candidate()),
        patch(
            "jfox.gem_synth.synthesizer.extract_delta_with_llm",
            return_value={"has_delta": False, "delta": "", "conflict": None},
        ),
        patch("jfox.gem_synth.synthesizer._merge_delta_into_candidate") as mmerge,
    ):
        fake_log = FakeLog()
        synthesizer.synthesize_anchor(_anchor(), log=fake_log, cfg=cfg)

    assert ("dup", 77, "cand-target") in fake_log.calls
    mmerge.assert_not_called()


def test_delta_load_race_degrades_to_skip():
    """命中后 load_note_by_id 返回 None（已被删/reject）→ mark_duplicate 降级。"""
    from jfox.gem_synth.dedup import DedupHit

    class FakeLog:
        def __init__(self):
            self.calls = []

        def mark_duplicate(self, fid, dup_of):
            self.calls.append(("dup", fid, dup_of))

    cfg = GemSynthesisConfig()
    cfg.dedup_enabled = True  # type: ignore[attr-defined]
    cfg.dedup_merge_enabled = True  # type: ignore[attr-defined]
    cfg.target_kb = "default"  # type: ignore[attr-defined]

    with (
        patch("jfox.gem_synth.synthesizer.extract_turn_around", return_value="ctx"),
        patch("jfox.gem_synth.synthesizer.fetch_grounding", return_value=[]),
        patch(
            "jfox.gem_synth.synthesizer.synthesize_with_llm",
            return_value={"title": "T", "content": "C", "confidence": 0.9},
        ),
        patch(
            "jfox.gem_synth.synthesizer.dedup_check",
            return_value=DedupHit("cand-gone", "candidate", 0.91),
        ),
        patch("jfox.gem_synth.synthesizer.load_note_by_id", return_value=None),
        patch("jfox.gem_synth.synthesizer.extract_delta_with_llm") as mdelta,
    ):
        fake_log = FakeLog()
        synthesizer.synthesize_anchor(_anchor(), log=fake_log, cfg=cfg)

    assert ("dup", 77, "cand-gone") in fake_log.calls
    mdelta.assert_not_called()  # load 失败就不调 delta LLM
```
新增测试顶部需加 import + 一个构造已有 candidate 的小工具（`_try_merge_delta` 会读 `existing.type/.archived/.content`，必须用真 `Note`，不能 `object()`——否则 `.type` AttributeError 被吞 → 误降级 mark_duplicate）：
```python
from datetime import datetime

from jfox.gem_synth.dedup import DedupHit
from jfox.global_config import GemSynthesisConfig
from jfox.models import GemLevel, Note, NoteType


def _existing_candidate():
    """构造一个 pending candidate 给 load_note_by_id 返回（_try_merge_delta guard 用）。"""
    return Note(
        id="cand-target",
        title="T",
        content="已有正文",
        type=NoteType.CANDIDATE,
        created=datetime(2026, 7, 25),
        updated=datetime(2026, 7, 25),
        gem_level=GemLevel.FLAWED.value,
        status="pending",
    )
```
> 文件内既有 `from jfox.gem_synth.dedup import DedupHit`（Task 1 加）与函数内 `from jfox.global_config import GemSynthesisConfig`——顶部统一加后，把函数内那两处冗余 import 删掉。

- [ ] **Step 2: 跑红**

Run: `uv run pytest tests/unit/test_synthesizer_dedup.py -v`
Expected: 新增 7 例 FAIL（synthesizer 还未接合并逻辑：candidate 0.91 仍走 mark_duplicate、permanent/near-verbatim 不分流）

- [ ] **Step 3: 实现决策树**

`jfox/gem_synth/synthesizer.py` 顶部 import 加：
```python
from .dedup import DedupHit, _clean_candidate_content, _resolve_kb_name, dedup_check, upsert_dedup
from .llm import extract_delta_with_llm, synthesize_with_llm
```
（替换原 `from .dedup import _resolve_kb_name, dedup_check, upsert_dedup` 与 `from .llm import synthesize_with_llm`；`_clean_candidate_content` 用于喂 delta LLM 比对口径）

模块常量（`_strip_leading_h1` 附近）加：
```python
# 近逐字阈值：cosine ≥ 此值视为近乎逐字重复，跳过 delta LLM 省成本（backlog 大量逐字 dup）。
# 0.88–0.96 才进入「提取增量」合并带。v1 不暴露配置（YAGNI）。
_NEAR_VERBATIM_THRESHOLD = 0.96
```
把 Task 1 写的 dedup 段（从 `hit = dedup_check(...)` 到 `if hit:` 块末尾 `return None`）整段替换为：
```python
        hit = dedup_check(
            kb_name,
            content,
            threshold=getattr(cfg, "dedup_threshold", 0.88),
        )
        if hit:
            # 增量合并决策（#309）：仅 candidate + 合并带(0.88–0.96) + merge 开 才提取增量；
            # permanent / 近逐字 / merge 关 / 任何失败 → 一律 mark_duplicate 跳过（不阻塞合成）
            merge_eligible = (
                getattr(cfg, "dedup_merge_enabled", True)
                and hit.note_type == "candidate"
                and hit.score < _NEAR_VERBATIM_THRESHOLD
            )
            merged = False
            if merge_eligible:
                merged = _try_merge_delta(hit, content, anchor, cfg, kb_name, stop_event)
            if merged:
                log.mark_merged(anchor["fragment_id"], hit.note_id)
                logger.info(
                    "锚点 #%s 命中重复并增量合并进 %s（score=%.3f）",
                    anchor["fragment_id"],
                    hit.note_id,
                    hit.score,
                )
            else:
                log.mark_duplicate(anchor["fragment_id"], hit.note_id)
                logger.info(
                    "锚点 #%s 命中重复（dup_of=%s, score=%.3f），跳过存盘",
                    anchor["fragment_id"],
                    hit.note_id,
                    hit.score,
                )
            return None
```
在 `_merge_delta_into_candidate` 之前加辅助 `_try_merge_delta`（封装 load→extract→merge，任一失败返回 False）：
```python
def _try_merge_delta(
    hit: DedupHit,
    new_content: str,
    anchor: Dict[str, Any],
    cfg: GemSynthesisConfig,
    kb: str,
    stop_event: Optional[threading.Event],
) -> bool:
    """命中 candidate 合并带时：load 已有 → 提取增量 → 合并。任一步失败/无增量返回 False
    （调用方据此 mark_duplicate 降级，不阻塞合成）。"""
    try:
        existing = load_note_by_id(hit.note_id)
        if existing is None or existing.type != NoteType.CANDIDATE or existing.archived:
            logger.info("合并目标 %s 不可用（已删/晋升/归档），降级跳过", hit.note_id)
            return False
        delta = extract_delta_with_llm(
            new_content=new_content,
            existing_content=_clean_candidate_content(existing.content),
            cfg=cfg,
            stop_event=stop_event,
        )
        if delta is None or not delta.get("has_delta"):
            logger.info("锚点 #%s 无实质增量，跳过", anchor.get("fragment_id"))
            return False
        return _merge_delta_into_candidate(existing, delta, anchor, kb)
    except Exception as e:
        logger.exception("增量合并流程异常，降级跳过: %s", e)
        return False
```
> `synthesize_anchor` 签名已有 `stop_event`；`NoteType` 已在文件顶部 import（`from ..models import GemLevel, Note, NoteType`）。

- [ ] **Step 4: 跑绿**

Run: `uv run pytest tests/unit/test_synthesizer_dedup.py tests/unit/test_gem_synth_dedup.py -v`
Expected: PASS（新增 7 例 + 既有全过；Task 1 改过的 near-verbatim mock(0.99) 走 skip 路径仍绿）

- [ ] **Step 5: lint + commit**

```bash
uv run ruff check jfox/gem_synth/synthesizer.py tests/unit/test_synthesizer_dedup.py
uv run --with black==26.3.1 black --check jfox/gem_synth/synthesizer.py tests/unit/test_synthesizer_dedup.py
git add jfox/gem_synth/synthesizer.py tests/unit/test_synthesizer_dedup.py
git commit -m "feat(gem-synth): dedup 命中 candidate 时增量合并（#309）

synthesize_anchor dedup 分支重写：candidate + 0.88–0.96 合并带 + merge 开 →
load 已有 → extract_delta_with_llm → 有增量则 _merge_delta_into_candidate
+ mark_merged。permanent/近逐字(≥0.96)/merge 关/任何失败 → mark_duplicate
跳过（铁律：不阻塞合成）。"
```

---

### Task 7: gem-synth status 显示 merged

**Files:**
- Modify: `jfox/gem_synth/cli.py`（`gem_synth_status` table + JSON + pending 计算）
- Test: `tests/unit/test_gem_synth_cli.py`

**Interfaces:**
- Consumes: Task 2 `mark_merged`（`status_counts()` 已自动 GROUP 出 merged）

- [ ] **Step 1: 写失败测试**

镜像既有 `test_gem_synth_status_shows_counts`（env var 隔离 DB + 真 FragmentStore/SynthesisLog），`tests/unit/test_gem_synth_cli.py` 加：
```python
def test_gem_synth_status_shows_merged(tmp_path, monkeypatch):
    """status 显示 merged 计数，并从 pending 扣除 merged。"""
    from jfox.fragment.store import FragmentStore
    from jfox.gem_synth.cli import gem_synth_app
    from jfox.gem_synth.store import SynthesisLog

    fdb = tmp_path / "f.db"
    sdb = tmp_path / "syn.db"
    monkeypatch.setenv("JFOX_FRAGMENTS_DB", str(fdb))
    monkeypatch.setenv("JFOX_SYNTHESIS_DB", str(sdb))

    store = FragmentStore(db_path=fdb)
    for i in range(5):
        store.insert("s", "correction", "UserPromptSubmit", f"c{i}", {})
    store.close()

    log = SynthesisLog(db_path=sdb)
    log.mark_processed(1, "c1")
    log.mark_merged(2, "c-target")  # Task 2 加的方法
    log.close()

    result = CliRunner().invoke(gem_synth_app, ["status", "--format", "json"])
    assert result.exit_code == 0
    data = json.loads(result.output)
    assert data["merged"] == 1
    # total=5, success=1, failed=0, duplicate=0, merged=1 → pending=3
    assert data["pending"] == 3
```

- [ ] **Step 2: 跑红**

Run: `uv run pytest tests/unit/test_gem_synth_cli.py -k merged -v`
Expected: FAIL（JSON 无 `merged` 键 / pending 未扣 merged）

- [ ] **Step 3: 实现**

`jfox/gem_synth/cli.py` `gem_synth_status` 里，`counts = log.status_counts()` 之后取 merged：
```python
        merged = counts.get("merged", 0)
```
pending 计算改（在原 `pending = max(0, total - success - failed - duplicate)` 处）：
```python
        pending = max(0, total - success - failed - duplicate - merged)
```
JSON 输出 dict 加 `"merged": merged,`。table 分支加一行（`console.print(f"  重复跳过（duplicate）：...")` 之后）：
```python
            console.print(f"  合并补入（merged）：  {merged}")
```

- [ ] **Step 4: 跑绿**

Run: `uv run pytest tests/unit/test_gem_synth_cli.py -v`
Expected: PASS（新增 + 既有全过）

- [ ] **Step 5: lint + commit**

```bash
uv run ruff check jfox/gem_synth/cli.py tests/unit/test_gem_synth_cli.py
uv run --with black==26.3.1 black --check jfox/gem_synth/cli.py tests/unit/test_gem_synth_cli.py
git add jfox/gem_synth/cli.py tests/unit/test_gem_synth_cli.py
git commit -m "feat(gem-synth): status 显示 merged 计数并从 pending 扣除

#309：增量合并命中记 status=merged，status CLI 单独展示「合并补入」并把它
从 pending 里扣除（merged 锚点也算已处理）。"
```

---

### Task 8: 文档同步

**Files:**
- Modify: `CLAUDE.md`（`gem_synth/` 模块说明）
- Grep: cc-plugin / kimi-plugin skill 文档有无 dedup 行为描述

- [ ] **Step 1: CLAUDE.md gem_synth 行**

`grep -n "gem_synth/" CLAUDE.md` 找到模块表里 `gem_synth/` 那行，补 dedup 增量合并描述。例如把
```
| `gem_synth/` | L3 宝石合成：daemon 循环围绕锚点用 transcript + 永久笔记基准合成 candidate 笔记；存盘前 `dedup.py` 正文余弦查重；`lifecycle.py` 订阅 note 的 delete/archive/promote/reject 事件同步 dedup 表 |
```
更新为追加「命中 candidate 时 `synthesizer.py` 增量合并（提取 delta 补入，#309）」。

- [ ] **Step 2: grep skill 文档**

```bash
grep -rn "dedup\|去重\|重复跳过\|0.88" packages/cc-plugin/skills packages/kimi-plugin .claude/skills 2>/dev/null
```
若命中描述 dedup「跳过/丢弃」语义处，改为体现「命中 candidate 时增量合并（可关）」。无命中则跳过。

- [ ] **Step 3: commit**

```bash
git add CLAUDE.md  # 及 step2 改到的 skill 文件
git commit -m "docs(gem-synth): 同步 dedup 增量合并行为说明（#309）

CLAUDE.md gem_synth 模块表 + skill 文档里 dedup 语义由「整条跳过」改为
「命中 candidate 时增量合并（permanent 仍跳过，可 dedup_merge_enabled 关）」。"
```

---

## 完成验证（PR 前自跑）

- [ ] 全部 unit 测试绿（不跑 embedding/slow）：
  ```bash
  uv run pytest tests/unit/test_gem_synth_dedup.py tests/unit/test_gem_synth_store.py tests/unit/test_gem_synth_llm.py tests/unit/test_gem_synth_config_dedup.py tests/unit/test_synthesizer_dedup.py tests/unit/test_gem_synth_cli.py tests/unit/test_note_dedup_sync.py tests/unit/test_gem_synth_lifecycle.py tests/unit/test_gem_synth_backfill.py -v
  ```
- [ ] lint 双过：`uv run ruff check jfox/ tests/` + `uv run --with black==26.3.1 black --check jfox/ tests/`
- [ ] 把 spec 文件 `docs/superpowers/specs/2026-07-25-gem-synth-dedup-incremental-merge-design.md` 与本 plan 一并 commit 进 PR 分支（worktree 首个 commit 或独立 docs commit）

> **集成测试**（`tests/integration/test_gem_synth_flow.py`、`-m "not embedding and not slow"`）由用户手动跑（CLAUDE.md 测试纪律：几秒内 unit 自跑，全量/集成不自主跑）。
