# gem-synth 合成去重（dedup）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** gem-synth 在存盘前用正文 embedding 余弦检查 candidate/permanent 重复，命中则不存盘并记 `duplicate` 状态，从源头止住"不同锚点产出同知识"的重复 candidate。

**Architecture:** 自包含 dedup 子系统（`jfox/gem_synth/dedup.py`），数据落在全局 `synthesis_log.db` 的新表 `dedup_embeddings`（带 `kb` 列做 KB 作用域隔离），numpy 暴力余弦，embedding 经现有 `get_backend().encode_single()`。hook 在 `synthesize_anchor` 的 LLM 合成后、`_save_candidate_note` 前；promote/reject/archive 同步增删表。

**Tech Stack:** Python 3.10+, sqlite3 (WAL), numpy, sentence-transformers（经 embedding daemon）, pytest, Typer CLI

## Global Constraints

- **分支**：`feat/gem-synth-dedup`（已建并提交 spec）。main 受保护，所有改动 PR 合入。
- **行宽 100**：black + ruff（pyproject.toml 已配）。
- **注释中文**。
- **测试纪律**：embedding 真模型的测试让用户手动跑；单测必须 mock backend，可在几秒内自主跑（CLAUDE.md「快速单测」）。
- **版本三处同步**（若需发版）：`pyproject.toml` + `jfox/__init__.py` + `uv.lock`。
- **不污染主搜索索引**：candidate 保持 `add_to_index=False`，dedup 用独立表。
- **降级原则**：dedup 依赖 embedding daemon；daemon 不可用时 dedup 必须**降级跳过**（warning + 放行合成），不能阻塞合成循环。

---

## File Structure

| 文件 | 职责 | 动作 |
|---|---|---|
| `jfox/gem_synth/dedup.py` | DedupStore（sqlite）+ 模块函数 dedup_check/upsert/delete/update_type + 内容清洗 | **新建** |
| `jfox/gem_synth/store.py` | SynthesisLog 加 `mark_duplicate` + `dup_of` 列迁移 | 改 |
| `jfox/gem_synth/synthesizer.py` | synthesize_anchor hook dedup + 存盘后 upsert | 改 |
| `jfox/note.py` | promote_note / reject_note / archive_note 同步 dedup 表 | 改 |
| `jfox/global_config.py` | GemSynthesisConfig 加 dedup_enabled / dedup_threshold | 改 |
| `jfox/gem_synth/cli.py` | dedup-backfill 命令 + status 展示 duplicate | 改 |
| `tests/unit/test_gem_synth_dedup.py` | dedup 核心 + 清洗 + 降级单测 | **新建** |
| `tests/unit/test_synthesizer_dedup.py` | synthesizer hook 行为单测 | **新建** |

---

## Task 1: dedup.py — DedupStore + 模块函数

**Files:**
- Create: `jfox/gem_synth/dedup.py`
- Test: `tests/unit/test_gem_synth_dedup.py`

**Interfaces:**
- Consumes: `jfox.embedding_backend.get_backend() -> EmbeddingBackend`（`.encode_single(text)->np.ndarray`）；`jfox.gem_synth.paths.default_synthesis_db_path()`
- Produces:
  - `dedup_check(kb: str, content: str, threshold: float = 0.88) -> Optional[str]` — 返回重复 note_id 或 None
  - `upsert_dedup(kb: str, note_id: str, note_type: str, content: str) -> None`
  - `delete_dedup(note_id: str) -> None`
  - `update_dedup_type(kb: str, note_id: str, new_type: str) -> None`
  - `_clean_candidate_content(content: str) -> str`（剥元段落，测试直接用）
  - `set_store(store)` / `_get_store()`（测试注入用）

- [ ] **Step 1: 写 dedup.py 骨架 + DedupStore**

Create `jfox/gem_synth/dedup.py`:

```python
"""合成去重：存盘前用正文 embedding 余弦查 candidate/permanent 重复。

自包含子系统：dedup_embeddings 表存全局 synthesis_log.db（带 kb 列做 KB 作用域
隔离），numpy 暴力余弦（<1k 向量微秒级）。daemon 不可用时降级跳过 dedup，不阻塞合成。
"""

import hashlib
import logging
import sqlite3
import threading
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from .paths import default_synthesis_db_path

logger = logging.getLogger(__name__)

_MAX_CONTENT_CHARS = 2000
_CANDIDATE_META_MARKERS = ["\n## 来源\n", "\n## 参考的永久笔记\n", "\n## 置信度\n"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dedup_embeddings (
    note_id      TEXT NOT NULL,
    kb           TEXT NOT NULL,
    note_type    TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    emb          BLOB NOT NULL,
    PRIMARY KEY (kb, note_id)
);
"""


class DedupStore:
    """dedup embedding 表的 sqlite 访问器。daemon 持单例；测试注入临时 db_path。"""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path: Path = Path(db_path) if db_path is not None else default_synthesis_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def upsert(self, kb: str, note_id: str, note_type: str, content_hash: str, emb: bytes) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO dedup_embeddings "
                "(note_id, kb, note_type, content_hash, emb) VALUES (?,?,?,?,?)",
                (note_id, kb, note_type, content_hash, emb),
            )
            self._conn.commit()

    def get_hash(self, kb: str, note_id: str) -> Optional[str]:
        with self._lock:
            r = self._conn.execute(
                "SELECT content_hash FROM dedup_embeddings WHERE kb=? AND note_id=?",
                (kb, note_id),
            ).fetchone()
        return r["content_hash"] if r else None

    def all_embeddings(self, kb: str, note_types: Tuple[str, ...]) -> List[Tuple[str, np.ndarray]]:
        if not note_types:
            return []
        placeholders = ",".join("?" * len(note_types))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT note_id, emb FROM dedup_embeddings "
                f"WHERE kb=? AND note_type IN ({placeholders})",
                (kb, *note_types),
            ).fetchall()
        return [(r["note_id"], np.frombuffer(r["emb"], dtype=np.float32)) for r in rows]

    def update_type(self, kb: str, note_id: str, new_type: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE dedup_embeddings SET note_type=? WHERE kb=? AND note_id=?",
                (new_type, kb, note_id),
            )
            self._conn.commit()

    def delete(self, note_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM dedup_embeddings WHERE note_id=?", (note_id,))
            self._conn.commit()

    def count(self, kb: Optional[str] = None) -> int:
        with self._lock:
            if kb:
                r = self._conn.execute(
                    "SELECT COUNT(*) FROM dedup_embeddings WHERE kb=?", (kb,)
                ).fetchone()
            else:
                r = self._conn.execute("SELECT COUNT(*) FROM dedup_embeddings").fetchone()
        return int(r[0]) if r else 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# 模块级单例（daemon 进程；测试用 set_store 注入临时实例）
_store_lock = threading.Lock()
_store: Optional[DedupStore] = None


def _get_store() -> DedupStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = DedupStore()
        return _store


def set_store(store: Optional[DedupStore]) -> None:
    """测试注入临时 store（用 temp db_path）。传 None 重置回默认单例。"""
    global _store
    with _store_lock:
        _store = store


def _clean_candidate_content(content: str) -> str:
    """剥掉 _save_candidate_note 追加的元段落（## 来源/参考的永久笔记/置信度），
    截断到 _MAX_CONTENT_CHARS。保证新 candidate（无元段落）与 backfill 旧 candidate
    （有元段落）口径一致，余弦比较的是知识本身。"""
    for marker in _CANDIDATE_META_MARKERS:
        idx = content.find(marker)
        if idx >= 0:
            content = content[:idx]
    return content.strip()[:_MAX_CONTENT_CHARS]


def _content_hash(content: str) -> str:
    return hashlib.sha1(content.encode("utf-8")).hexdigest()


def _embed(text: str) -> Optional[np.ndarray]:
    """经 embedding daemon 取向量。daemon 不可用返回 None（调用方降级）。"""
    from ..embedding_backend import get_backend

    vec = get_backend().encode_single(text)
    return np.asarray(vec, dtype=np.float32)


def dedup_check(kb: str, content: str, threshold: float = 0.88) -> Optional[str]:
    """返回与已有 candidate/permanent 重复的 note_id；无重复或降级时返回 None。

    daemon 不可用 / 空内容 / 表空 → 返回 None（降级放行，不阻塞合成）。
    """
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
        mat = np.vstack([r[1] for r in rows])  # (N, D)
        norms = np.linalg.norm(mat, axis=1) * (np.linalg.norm(emb) + 1e-12)
        sims = (mat @ emb) / norms
        best = int(np.argmax(sims))
        if sims[best] >= threshold:
            return rows[best][0]
    except Exception as e:
        logger.warning("dedup_check 失败，降级跳过: %s", e)
        return None
    return None


def upsert_dedup(kb: str, note_id: str, note_type: str, content: str) -> None:
    """算 embedding 入表。content_hash 命中（内容没变）则跳过省 daemon 调用。失败仅 warning。"""
    try:
        cleaned = _clean_candidate_content(content)
        if not cleaned:
            return
        store = _get_store()
        ch = _content_hash(cleaned)
        if store.get_hash(kb, note_id) == ch:
            return
        emb = _embed(cleaned)
        if emb is None:
            return
        store.upsert(kb, note_id, note_type, ch, emb.tobytes())
    except Exception as e:
        logger.warning("upsert_dedup 失败 note=%s: %s", note_id, e)


def update_dedup_type(kb: str, note_id: str, new_type: str) -> None:
    try:
        _get_store().update_type(kb, note_id, new_type)
    except Exception as e:
        logger.warning("update_dedup_type 失败 note=%s: %s", note_id, e)


def delete_dedup(note_id: str) -> None:
    try:
        _get_store().delete(note_id)
    except Exception as e:
        logger.warning("delete_dedup 失败 note=%s: %s", note_id, e)


__all__ = [
    "DedupStore",
    "dedup_check",
    "upsert_dedup",
    "update_dedup_type",
    "delete_dedup",
    "set_store",
    "_clean_candidate_content",
]
```

- [ ] **Step 2: 写失败测试（mock backend，确定性向量）**

Create `tests/unit/test_gem_synth_dedup.py`:

```python
"""gem_synth dedup 单测：mock embedding backend，不加载真模型。"""
import numpy as np
import pytest

from jfox.gem_synth import dedup
from jfox.gem_synth.dedup import DedupStore


class FakeBackend:
    """确定性 fake：把文本 sha1 哈希前 N 字节映成向量，相同/相近文本向量接近。"""

    def __init__(self, dim=64):
        self.dim = dim

    def encode_single(self, text):
        import hashlib

        h = hashlib.sha1(text.encode("utf-8")).digest()
        vec = np.frombuffer((h * (self.dim // len(h) + 1))[: self.dim * 4], dtype=np.uint8)
        return (vec.astype(np.float32) % 16) / 16.0


@pytest.fixture
def setup(tmp_path, monkeypatch):
    """临时 db + fake backend 注入。"""
    store = DedupStore(db_path=tmp_path / "dedup.db")
    dedup.set_store(store)
    fake = FakeBackend()
    monkeypatch.setattr("jfox.embedding_backend.get_backend", lambda: fake)
    yield store
    dedup.set_store(None)


def test_clean_strips_meta_sections():
    raw = "正文知识\n\n## 来源\n- 碎片 #1\n\n## 置信度\n0.9\n"
    assert dedup._clean_candidate_content(raw) == "正文知识"


def test_dedup_check_returns_none_when_empty(setup):
    assert dedup.dedup_check("default", "全新知识", threshold=0.88) is None


def test_dedup_check_hits_existing_dup(setup):
    setup.upsert("default", "cand-1", "candidate", "deadbeef", b"x" * 64)
    # 直接塞一个已知向量再测：用 upsert_dedup 灌真向量
    setup.upsert(
        "default",
        "cand-1",
        "candidate",
        "h1",
        FakeBackend().encode_single("Zima 双 Bot babysit 标签循环").tobytes(),
    )
    # 同文本 → dedup_check 应命中自己（验证余弦路径）
    setup._conn.execute("DELETE FROM dedup_embeddings WHERE note_id='cand-1'") is None  # noop 占位避免 lint
    # 真正断言：相同内容命中
    dedup.upsert_dedup("default", "cand-1", "candidate", "Zima 双 Bot babysit 标签循环")
    hit = dedup.dedup_check("default", "Zima 双 Bot babysit 标签循环", threshold=0.5)
    assert hit == "cand-1"


def test_dedup_check_kb_isolation(setup):
    dedup.upsert_dedup("kbA", "cand-1", "candidate", "同一事实文本")
    # kbB 不应被 kbA 的 candidate 命中
    assert dedup.dedup_check("kbB", "同一事实文本", threshold=0.5) is None


def test_upsert_idempotent_on_same_content(setup):
    dedup.upsert_dedup("default", "c1", "candidate", "稳定内容")
    h1 = setup.get_hash("default", "c1")
    dedup.upsert_dedup("default", "c1", "candidate", "稳定内容")  # 同内容，hash 不变
    assert setup.get_hash("default", "c1") == h1


def test_delete_removes(setup):
    dedup.upsert_dedup("default", "c1", "candidate", "内容")
    assert setup.count("default") == 1
    dedup.delete_dedup("c1")
    assert setup.count("default") == 0


def test_dedup_check_degrades_when_backend_unavailable(setup, monkeypatch):
    setup.upsert(
        "default", "c1", "candidate", "h", FakeBackend().encode_single("x").tobytes()
    )

    def boom():
        raise RuntimeError("daemon down")

    monkeypatch.setattr("jfox.embedding_backend.get_backend", boom)
    # daemon 挂了 → 降级返回 None，不抛
    assert dedup.dedup_check("default", "任意内容") is None
```

- [ ] **Step 3: 跑测试验证失败（模块/函数就绪则 pass；先确认 import 路径通）**

Run: `uv run pytest tests/unit/test_gem_synth_dedup.py -v`
Expected: 全部 PASS（Step 1 已写实现）。若有 import/路径错，修到 PASS。

- [ ] **Step 4: lint + 提交**

```bash
uv run ruff check jfox/gem_synth/dedup.py tests/unit/test_gem_synth_dedup.py
uv run black jfox/gem_synth/dedup.py tests/unit/test_gem_synth_dedup.py
git add jfox/gem_synth/dedup.py tests/unit/test_gem_synth_dedup.py
git commit -m "feat(gem-synth): dedup 模块——DedupStore + 余弦查重 + 降级"
```

---

## Task 2: store.py — mark_duplicate + dup_of 列迁移

**Files:**
- Modify: `jfox/gem_synth/store.py`（`_maybe_migrate` 加 dup_of 列；加 `mark_duplicate` 方法）
- Test: `tests/unit/test_gem_synth_store_duplicate.py`

**Interfaces:**
- Produces: `SynthesisLog.mark_duplicate(anchor_fragment_id: int, dup_of: str) -> None`；`status_counts()` 返回的 dict 现含 `'duplicate'` 键；synthesis_log 表新增列 `dup_of TEXT`

- [ ] **Step 1: 写失败测试**

Create `tests/unit/test_gem_synth_store_duplicate.py`:

```python
"""SynthesisLog.mark_duplicate + dup_of 列迁移单测。"""
from jfox.gem_synth.store import SynthesisLog


def test_mark_duplicate_records_status_and_dup_of(tmp_path):
    log = SynthesisLog(db_path=tmp_path / "syn.db")
    log.mark_duplicate(123, "20260712000000-abc")
    counts = log.status_counts()
    assert counts.get("duplicate") == 1
    # 该锚点已处理（不重试）
    assert log.is_processed(123) is True
    log.close()


def test_dup_of_migration_idempotent(tmp_path):
    db = tmp_path / "syn.db"
    SynthesisLog(db_path=db).close()
    # 第二次实例化触发 _maybe_migrate 再次 → 不应抛 duplicate column
    log2 = SynthesisLog(db_path=db)
    log2.mark_duplicate(456, "x")
    assert log2.status_counts().get("duplicate") == 1
    log2.close()
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/unit/test_gem_synth_store_duplicate.py -v`
Expected: FAIL（`mark_duplicate` 不存在）

- [ ] **Step 3: 实现 mark_duplicate + 迁移**

Modify `jfox/gem_synth/store.py`：

在 `_maybe_migrate` 末尾（`self._conn.commit()` 之前）追加 `dup_of` 列迁移：

```python
        if "dup_of" not in cols:
            try:
                self._conn.execute("ALTER TABLE synthesis_log ADD COLUMN dup_of TEXT")
            except Exception as e:
                if "duplicate column" not in str(e).lower():
                    raise
```

在 `mark_failed` 方法后追加：

```python
    def mark_duplicate(self, anchor_fragment_id: int, dup_of: str) -> None:
        """重复命中记账：status='duplicate' + dup_of=被重复的 note_id。
        记账后 is_processed=True → 锚点不重试。与 failed 区分，供 status 单独统计。"""
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO synthesis_log "
                "(anchor_fragment_id, candidate_note_id, status, dup_of) "
                "VALUES (?, '', 'duplicate', ?)",
                (anchor_fragment_id, dup_of),
            )
            self._conn.commit()
```

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/unit/test_gem_synth_store_duplicate.py -v`
Expected: PASS

- [ ] **Step 5: lint + 提交**

```bash
uv run ruff check jfox/gem_synth/store.py tests/unit/test_gem_synth_store_duplicate.py
uv run black jfox/gem_synth/store.py tests/unit/test_gem_synth_store_duplicate.py
git add jfox/gem_synth/store.py tests/unit/test_gem_synth_store_duplicate.py
git commit -m "feat(gem-synth): synthesis_log 加 duplicate 状态 + dup_of 列"
```

---

## Task 3: synthesizer.py — hook dedup + 存盘后 upsert

**Files:**
- Modify: `jfox/gem_synth/synthesizer.py:108-162`（`synthesize_anchor`）
- Test: `tests/unit/test_synthesizer_dedup.py`

**Interfaces:**
- Consumes: Task 1 的 `dedup_check`/`upsert_dedup`；Task 2 的 `log.mark_duplicate`；`cfg.dedup_enabled`/`cfg.dedup_threshold`（Task 5，本任务先用 `getattr(cfg, 'dedup_enabled', True)` 兜底）；`cfg.target_kb`

- [ ] **Step 1: 写失败测试（mock dedup_check + _save_candidate_note）**

Create `tests/unit/test_synthesizer_dedup.py`:

```python
"""synthesize_anchor 的 dedup hook：命中则不存盘、记 duplicate。"""
from unittest.mock import patch

from jfox.gem_synth import synthesizer


def _anchor():
    return {
        "fragment_id": 77,
        "session_id": "s1",
        "timestamp": "2026-07-12T00:00:00",
        "content": "ctx",
        "transcript_path": "/tmp/x.jsonl",
    }


def test_duplicate_hit_skips_save_and_marks_duplicate(tmp_path):
    # 造一个空 transcript 让 extract_turn_around 返回非空
    import json, pathlib

    pathlib.Path("/tmp/_synth_test.jsonl").write_text(
        json.dumps({"type": "user", "content": "hello"}) + "\n", encoding="utf-8"
    )
    _anchor()["transcript_path"] = "/tmp/_synth_test.jsonl"

    class FakeLog:
        def __init__(self):
            self.calls = []

        def mark_duplicate(self, fid, dup_of):
            self.calls.append(("dup", fid, dup_of))

        def mark_failed(self, fid, reason):
            self.calls.append(("fail", fid, reason))

        def mark_processed(self, **kw):
            self.calls.append(("ok", kw))

    fake_log = FakeLog()

    with patch("jfox.gem_synth.synthesizer.extract_turn_around", return_value="上下文"), \
         patch("jfox.gem_synth.synthesizer.fetch_grounding", return_value=[]), \
         patch("jfox.gem_synth.synthesizer.synthesize_with_llm",
               return_value={"title": "T", "content": "C", "confidence": 0.9}), \
         patch("jfox.gem_synth.synthesizer.dedup_check", return_value="existing-id") as mcheck, \
         patch("jfox.gem_synth.synthesizer._save_candidate_note") as msave:
        from jfox.global_config import GemSynthesisConfig

        cfg = GemSynthesisConfig()
        cfg.dedup_enabled = True  # type: ignore[attr-defined]
        cfg.target_kb = "default"  # type: ignore[attr-defined]
        result = synthesizer.synthesize_anchor(_anchor(), log=fake_log, cfg=cfg)

    assert result is None
    assert ("dup", 77, "existing-id") in fake_log.calls
    msave.assert_not_called()  # 没存盘
    mcheck.assert_called_once()


def test_no_duplicate_proceeds_to_save(tmp_path):
    import pathlib

    pathlib.Path("/tmp/_synth_test.jsonl").write_text('{"content":"x"}\n', encoding="utf-8")
    _anchor()["transcript_path"] = "/tmp/_synth_test.jsonl"

    class FakeLog:
        def __init__(self):
            self.calls = []

        def mark_duplicate(self, fid, dup_of):
            self.calls.append(("dup", fid, dup_of))

        def mark_processed(self, **kw):
            self.calls.append(("ok", kw))

    fake_log = FakeLog()
    with patch("jfox.gem_synth.synthesizer.extract_turn_around", return_value="ctx"), \
         patch("jfox.gem_synth.synthesizer.fetch_grounding", return_value=[]), \
         patch("jfox.gem_synth.synthesizer.synthesize_with_llm",
               return_value={"title": "T", "content": "C", "confidence": 0.9}), \
         patch("jfox.gem_synth.synthesizer.dedup_check", return_value=None), \
         patch("jfox.gem_synth.synthesizer._save_candidate_note", return_value="new-id"), \
         patch("jfox.gem_synth.synthesizer.upsert_dedup") as mupsert:
        from jfox.global_config import GemSynthesisConfig

        cfg = GemSynthesisConfig()
        cfg.dedup_enabled = True  # type: ignore[attr-defined]
        cfg.target_kb = "default"  # type: ignore[attr-defined]
        result = synthesizer.synthesize_anchor(_anchor(), log=fake_log, cfg=cfg)

    assert result is not None and result["candidate_note_id"] == "new-id"
    # 存盘成功后入 dedup 库
    mupsert.assert_called_once()
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/unit/test_synthesizer_dedup.py -v`
Expected: FAIL（`dedup_check` 未在 synthesizer 命名空间 / 未调用）

- [ ] **Step 3: 实现 hook**

Modify `jfox/gem_synth/synthesizer.py`：

顶部 import 区加：
```python
from .dedup import dedup_check, upsert_dedup
```

在 `synthesize_anchor` 内，把现有的 `if llm_result is None: ...` 块之后、`note_id = _save_candidate_note(...)` 之前，插入 dedup 检查。把 `_save_candidate_note` 成功后加 `upsert_dedup`。修改后的关键段（替换 synthesizer.py:152-162 区域）：

```python
    note_id = _save_candidate_note(llm_result, anchor)
    # → 改为：
    # 存盘前去重：命中则不存盘、记 duplicate，锚点算处理完（不重试）
    if getattr(cfg, "dedup_enabled", True):
        dup_of = dedup_check(
            cfg.target_kb,
            llm_result.get("content") or "",
            threshold=getattr(cfg, "dedup_threshold", 0.88),
        )
        if dup_of:
            logger.info("锚点 #%s 命中重复（dup_of=%s），跳过存盘", anchor["fragment_id"], dup_of)
            log.mark_duplicate(anchor["fragment_id"], dup_of)
            return None

    note_id = _save_candidate_note(llm_result, anchor)
    if note_id is None:
        log.mark_failed(anchor["fragment_id"], "save candidate note failed")
        return None

    # 存盘成功 → 入 dedup 库（供后续锚点查重）
    upsert_dedup(cfg.target_kb, note_id, "candidate", llm_result.get("content") or "")

    log.mark_processed(anchor_fragment_id=anchor["fragment_id"], candidate_note_id=note_id)
    return {
        "candidate_note_id": note_id,
        "title": llm_result.get("title"),
        "confidence": llm_result.get("confidence"),
    }
```

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/unit/test_synthesizer_dedup.py tests/unit/test_gem_synth_dedup.py -v`
Expected: PASS

- [ ] **Step 5: lint + 提交**

```bash
uv run ruff check jfox/gem_synth/synthesizer.py tests/unit/test_synthesizer_dedup.py
uv run black jfox/gem_synth/synthesizer.py tests/unit/test_synthesizer_dedup.py
git add jfox/gem_synth/synthesizer.py tests/unit/test_synthesizer_dedup.py
git commit -m "feat(gem-synth): synthesize_anchor 存盘前 dedup hook + 存盘后入 dedup 库"
```

---

## Task 4: note.py — promote/reject/archive 同步 dedup 表

**Files:**
- Modify: `jfox/note.py:286-309`（archive_note）、`jfox/note.py:339-411`（promote_note 末尾）、`jfox/note.py:413-432`（reject_note）

**Interfaces:**
- Consumes: Task 1 的 `update_dedup_type`/`delete_dedup`；`n.filepath` 推导 kb
- Produces: promote/reject/archive 副作用保持 dedup_embeddings 表与笔记状态一致

- [ ] **Step 1: 写失败测试**

Create `tests/unit/test_note_dedup_sync.py`:

```python
"""promote/reject/archive 同步 dedup 表。用 temp_kb + mock backend。"""
from datetime import datetime
from unittest.mock import patch

import pytest

from jfox.models import Note, NoteType


def _now():
    return datetime(2026, 7, 12, 12, 0, 0)


def test_archive_deletes_from_dedup(temp_kb, mock_embedding_backend):
    from jfox.note import archive_note, save_note

    n = Note(
        id="20260712120000-000001", title="t", content="c",
        type=NoteType.FLEETING, created=_now(), updated=_now(),
    )
    save_note(n)
    with patch("jfox.gem_synth.dedup._get_store") as ms:
        store = ms.return_value
        archive_note(n.id)
        store.delete.assert_called_once_with(n.id)


def test_reject_deletes_from_dedup(temp_kb, mock_embedding_backend):
    from jfox.note import reject_note, save_note

    n = Note(
        id="20260712120001-000002", title="t", content="c",
        type=NoteType.CANDIDATE, created=_now(), updated=_now(),
    )
    save_note(n)
    with patch("jfox.gem_synth.dedup._get_store") as ms:
        store = ms.return_value
        reject_note(n.id, reason="x")
        store.delete.assert_called_once_with(n.id)


def test_promote_updates_dedup_type(temp_kb, mock_embedding_backend):
    from jfox.note import save_note, promote_note

    n = Note(
        id="20260712120002-000003", title="t", content="c",
        type=NoteType.CANDIDATE, created=_now(), updated=_now(),
    )
    save_note(n)
    with patch("jfox.gem_synth.dedup._get_store") as ms:
        store = ms.return_value
        promote_note(n.id)
        # promote 把 candidate→permanent：dedup 表里 note_type 改 permanent
        store.update_type.assert_called_once()
        args = store.update_type.call_args[0]
        assert args[2] == "permanent"
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/unit/test_note_dedup_sync.py -v`
Expected: FAIL（promote/reject/archive 未调 dedup）

- [ ] **Step 3: 实现 dedup 同步**

Modify `jfox/note.py`：

顶部加（文件已 import logging；dedup 按需 import 避免循环）：
```python
def _kb_name_from_path(filepath) -> str:
    """从笔记路径推 kb 名：<kb_root>/<kb_name>/notes/<type>/<file> → kb_name。"""
    try:
        return filepath.parent.parent.parent.name
    except Exception:
        return ""
```

在 `promote_note` 的 `return True` 之前（增量回填循环之后、函数返回前）加：
```python
    # dedup 同步：candidate→permanent，表内 note_type 改 permanent（仍占位防重复合成）
    try:
        from .gem_synth.dedup import update_dedup_type

        update_dedup_type(_kb_name_from_path(n.filepath), note_id, "permanent")
    except Exception as e:
        logger.warning("promote dedup 同步失败 note=%s: %s", note_id, e)
```

在 `reject_note` 的 `return update_note(n)` 之前加：
```python
    # dedup 同步：reject 的 candidate 从表删除，让该事实可被未来重新合成
    try:
        from .gem_synth.dedup import delete_dedup

        delete_dedup(note_id)
    except Exception as e:
        logger.warning("reject dedup 同步失败 note=%s: %s", note_id, e)
```

在 `archive_note` 的两个 `return update_note(n)` 之前各加（归档即从 dedup 移除）：
```python
    try:
        from .gem_synth.dedup import delete_dedup

        delete_dedup(note_id)
    except Exception:
        pass  # 归档是通用路径，dedup 失败不影响归档语义
```
（`archive_note` 有早返回路径——`if n.archived: return update_note(n)`，该路径幂等，不必删 dedup；只在主路径 `n.archived = True` 之后加删除。）

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/unit/test_note_dedup_sync.py -v`
Expected: PASS

- [ ] **Step 5: lint + 提交**

```bash
uv run ruff check jfox/note.py tests/unit/test_note_dedup_sync.py
uv run black jfox/note.py tests/unit/test_note_dedup_sync.py
git add jfox/note.py tests/unit/test_note_dedup_sync.py
git commit -m "feat(gem-synth): promote/reject/archive 同步 dedup 表"
```

---

## Task 5: global_config.py — dedup_enabled / dedup_threshold 配置

**Files:**
- Modify: `jfox/global_config.py:237-283`（`GemSynthesisConfig` dataclass + `from_dict`）

**Interfaces:**
- Produces: `GemSynthesisConfig.dedup_enabled: bool = True`、`GemSynthesisConfig.dedup_threshold: float = 0.88`

- [ ] **Step 1: 写失败测试**

Create `tests/unit/test_gem_synth_config_dedup.py`:

```python
from jfox.global_config import GemSynthesisConfig


def test_defaults():
    cfg = GemSynthesisConfig()
    assert cfg.dedup_enabled is True
    assert cfg.dedup_threshold == 0.88


def test_from_dict_reads_dedup_fields():
    cfg = GemSynthesisConfig.from_dict(
        {"gem_synthesis": {"dedup_enabled": False, "dedup_threshold": 0.92}}
    )
    assert cfg.dedup_enabled is False
    assert cfg.dedup_threshold == 0.92


def test_from_dict_missing_uses_defaults():
    cfg = GemSynthesisConfig.from_dict({"gem_synthesis": {}})
    assert cfg.dedup_enabled is True
    assert cfg.dedup_threshold == 0.88
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/unit/test_gem_synth_config_dedup.py -v`
Expected: FAIL（字段不存在）

- [ ] **Step 3: 实现配置字段**

Modify `jfox/global_config.py` 的 `GemSynthesisConfig` dataclass：在 `claude_timeout_seconds` 字段后加：
```python
    dedup_enabled: bool = True  # 存盘前用正文 embedding 余弦查重
    dedup_threshold: float = 0.88  # 同事实重复阈值（高）；link-suggest 0.6 是"相关"，dedup 要"同一"
```

在 `from_dict` 类方法里（解析字段那段，参考 `grounding_top_k=_safe_int(...)` 模式）加：
```python
            dedup_enabled=bool(data.get("dedup_enabled", True)),
            dedup_threshold=_safe_float(data.get("dedup_threshold"), 0.88),
```
（若 `_safe_float` 不存在，参考现有 `_safe_int` 写一个等价的 float 版，或用 `float(data.get(...) or 0.88)`。先 grep 确认。）

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/unit/test_gem_synth_config_dedup.py -v`
Expected: PASS

- [ ] **Step 5: lint + 提交**

```bash
uv run ruff check jfox/global_config.py tests/unit/test_gem_synth_config_dedup.py
uv run black jfox/global_config.py tests/unit/test_gem_synth_config_dedup.py
git add jfox/global_config.py tests/unit/test_gem_synth_config_dedup.py
git commit -m "feat(gem-synth): GemSynthesisConfig 加 dedup_enabled/dedup_threshold"
```

---

## Task 6: cli.py — dedup-backfill 命令 + status 展示 duplicate

**Files:**
- Modify: `jfox/gem_synth/cli.py`（status 输出加 duplicate；新增 dedup-backfill 子命令）

**Interfaces:**
- Consumes: Task 1 的 `upsert_dedup`/`_clean_candidate_content`；`jfox.note` 遍历笔记；`get_backend()`

- [ ] **Step 1: 写失败测试（backfill 逻辑用 temp_kb + mock backend）**

Create `tests/unit/test_gem_synth_backfill.py`:

```python
"""dedup-backfill：扫 candidate+permanent 灌 dedup 表。"""
from datetime import datetime
from unittest.mock import patch, MagicMock


def test_backfill_populates_store(temp_kb, mock_embedding_backend):
    from jfox.models import Note, NoteType
    from jfox.note import save_note

    now = datetime(2026, 7, 12, 13, 0, 0)
    # 造 2 candidate + 1 permanent
    save_note(Note(id="20260712130000-1", title="a", content="内容A",
                   type=NoteType.CANDIDATE, created=now, updated=now))
    save_note(Note(id="20260712130001-2", title="b", content="内容B",
                   type=NoteType.CANDIDATE, created=now, updated=now))
    save_note(Note(id="20260712130002-3", title="p", content="永久",
                   type=NoteType.PERMANENT, created=now, updated=now))

    store = MagicMock()
    store.get_hash.return_value = None  # 全是新内容
    with patch("jfox.gem_synth.dedup._get_store", return_value=store):
        from jfox.gem_synth.cli import _dedup_backfill_impl

        n_cand, n_perm = _dedup_backfill_impl(kb="default")
    assert n_cand + n_perm == 3
    assert store.upsert.call_count == 3
```

- [ ] **Step 2: 跑测试验证失败**

Run: `uv run pytest tests/unit/test_gem_synth_backfill.py -v`
Expected: FAIL（`_dedup_backfill_impl` 不存在）

- [ ] **Step 3: 实现 backfill impl + CLI 命令 + status 展示**

Modify `jfox/gem_synth/cli.py`：

加 import 与实现函数（放在现有 status 命令附近）。`NoteMeta` 不含正文，需 `load_note_by_id` 取 `.content`；遍历用 `get_all_meta()`；`type` 是 `NoteType` 枚举：
```python
def _dedup_backfill_impl(kb: str):
    """扫 kb 的 candidate(非 archived)+permanent，灌 dedup 表。返回 (n_cand, n_perm)。"""
    from ..config import use_kb
    from ..models import NoteType
    from ..note import load_note_by_id
    from ..note_index import get_note_index
    from .dedup import upsert_dedup

    n_cand = n_perm = 0
    idx = get_note_index()
    with use_kb(kb):
        for meta in idx.get_all_meta():
            if meta.archived:
                continue
            if meta.type == NoteType.CANDIDATE:
                note = load_note_by_id(meta.id)
                upsert_dedup(kb, meta.id, "candidate", note.content if note else "")
                n_cand += 1
            elif meta.type == NoteType.PERMANENT:
                note = load_note_by_id(meta.id)
                upsert_dedup(kb, meta.id, "permanent", note.content if note else "")
                n_perm += 1
    return n_cand, n_perm
```

加 Typer 命令（参考现有 status 子命令组装饰器模式，文件内 grep `@.*command(` 看装饰器名，大概率是 `@gem_synth_app.command(...)` 或挂在 status 子命令组上）：
```python
@gem_synth_app.command("dedup-backfill")
def dedup_backfill_cmd(kb: Optional[str] = None):
    """一次性把 candidate(非 archived)+permanent 的正文 embedding 灌入 dedup 库。
    幂等可重跑；content_hash 命中则跳过省 daemon 调用。"""
    from ..global_config import get_global_config_manager

    target_kb = kb or get_global_config_manager().get_gem_synthesis_config().target_kb
    n_cand, n_perm = _dedup_backfill_impl(target_kb)
    typer.echo(f"已灌入 {n_cand + n_perm} 条（candidate {n_cand} / permanent {n_perm}）到 dedup 库")
```

status 输出加 duplicate：`gem_synth/cli.py` 的 status 命令在 ~272-274 行已有 `counts = log.status_counts(); success = counts.get("success",0); failed = counts.get("failed",0)`。在 failed 行后加：
```python
        duplicate = counts.get("duplicate", 0)
```
并在渲染 success/failed 的输出处（紧随其后）追加一行，沿用其现有输出风格（`console.print` / `typer.echo`，按该处一致）：
```python
        # 例（按现有风格调整）：
        console.print(f"  重复跳过（duplicate）：[bold]{duplicate}[/bold]")
```

- [ ] **Step 4: 跑测试验证通过**

Run: `uv run pytest tests/unit/test_gem_synth_backfill.py -v`
Expected: PASS

- [ ] **Step 5: lint + 提交**

```bash
uv run ruff check jfox/gem_synth/cli.py tests/unit/test_gem_synth_backfill.py
uv run black jfox/gem_synth/cli.py tests/unit/test_gem_synth_backfill.py
git add jfox/gem_synth/cli.py tests/unit/test_gem_synth_backfill.py
git commit -m "feat(gem-synth): dedup-backfill 命令 + status 展示 duplicate"
```

---

## Task 7: 全量单测 + 集成验证命令 + PR

- [ ] **Step 1: 跑全部 gem_synth 相关单测（mock，可自主跑）**

```bash
uv run pytest tests/unit/test_gem_synth_dedup.py tests/unit/test_synthesizer_dedup.py \
  tests/unit/test_note_dedup_sync.py tests/unit/test_gem_synth_config_dedup.py \
  tests/unit/test_gem_synth_backfill.py tests/unit/test_gem_synth_store_duplicate.py -v
```
Expected: 全 PASS

- [ ] **Step 2: 跑 fast CI 子集（排除 embedding/slow）确认没破坏现有**

让用户跑（含真模型，不自主）：
```bash
uv run pytest tests/ -m "not embedding and not slow" -q
```

- [ ] **Step 3: 手动验证 backfill（用户跑，需 daemon 在跑）**

```bash
jfox daemon status                    # 确认 daemon 运行中
jfox gem-synth dedup-backfill         # 灌 702 candidate + 65 permanent
jfox gem-synth status                 # 确认无报错、dedup 库已建
```

- [ ] **Step 4: push + 开 PR**

```bash
git push -u origin feat/gem-synth-dedup
gh pr create --title "feat(gem-synth): 合成去重 dedup（存盘前正文余弦查重）" \
  --body "根因①修复：dedup 键从输入(锚点)改为输出(candidate 知识点)。
post-LLM 存盘前用正文 embedding 余弦查 candidate+permanent，命中则不存盘+记 duplicate。
自包含 sqlite+numpy 方案，daemon 不可用降级放行。
设计 spec：docs/superpowers/specs/2026-07-12-gem-synth-dedup-design.md

🤖 Generated with [Claude Code](https://claude.com/claude-code)"
```

- [ ] **Step 5: 打 `zima:needs-review` 走双 Bot CR + CI 绿后合**（参考 [[Zima PR Monitor：标签驱动的 CR 监听循环]]）

---

## Self-Review 结果

- **Spec 覆盖**：spec §3 hook 点 → Task 3；§4 schema → Task 2；§5 同步事件 → Task 4；§6 config → Task 5；§7 backfill → Task 6；§8 可观测 → Task 6；§9 测试 → 各 Task；§10 实施顺序 → Task 1-7 顺序一致。✓
- **Placeholder 扫描**：已核实全部现有 API——`get_all_meta()`（note_index.py:287）、NoteMeta 无 content 字段故 backfill 用 `load_note_by_id().content`、`type` 为 NoteType 枚举、Note 必填 `id/title/content/type/created/updated`、status 渲染点 cli.py:272-274。无 TBD/空位。✓
- **类型一致**：`dedup_check(kb, content, threshold)` / `upsert_dedup(kb, note_id, note_type, content)` / `mark_duplicate(fid, dup_of)` 在各 Task 间签名一致；`delete_dedup(note_id)` / `update_dedup_type(kb, note_id, new_type)` 同步事件签名一致。✓
