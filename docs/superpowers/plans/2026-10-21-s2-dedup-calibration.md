# S2 判重口径与分位标定 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `jfox-session-to-permanent` 的 S2② 去重闸门用「同口径 + 本库分位」判定，替代跨粒度绝对 cosine 阈值。

**Architecture:** 新增 `jfox/similarity.py`（纯函数 + I/O 分层）与 `jfox/similarity_cli.py`（`stats` / `check` 两个只读子命令）。基线 = live permanent 向量的最近邻 top-1 分布；候选 = 草稿 `title\n正文` 的 top-1 在该分布中的分位。三平台 skill 改为调用 `similarity check` 并按 `new/gray/covered/unavailable` 分流。

**Tech Stack:** Python 3.10+、Typer、Rich、NumPy、ChromaDB（只读快照）、pytest、Typer CliRunner。

**Spec:** `docs/superpowers/specs/2026-10-21-s2-dedup-calibration-design.md`

## Global Constraints

- 不新增依赖；只用现有 NumPy / Typer / Rich / pytest。
- 候选编码必须 `daemon_only=True`（daemon 不可用直接 `unavailable`，不回退本地模型加载）。
- 根 CLI 启动不得加载 ChromaDB / sentence-transformers：`similarity_cli` 顶层只 import typer/rich/config，重模块在命令函数内延迟 import。
- `jfox add` 的 0.95 与 gem_synth 的 0.88 不改。
- 三份 session-to-permanent SKILL.md 的闸门语义必须一致（pi / cc / kimi）。
- `docs/cli-reference.md` 是生成物，禁止手改；必须跑 `uv run python scripts/generate_docs.py` 并提交。
- 测试函数名/文件名避开 `vector` / `semantic` / `embedding` / `search` 子串（conftest 自动标记会把它们踢出 Fast CI）。
- 单测不加载真实模型、不读写真实 KB；集成测试用确定性 stub + `tmp_path`/`temp_kb`。
- 代码注释用英文；commit message 用 conventional commits。
- 每个 task 结束前跑该 task 的测试命令并确认通过；不要用「全量测试」替代 task 级验证。

## Review Focus

- **空库 / permanent < 30**：必须返回 `unavailable`（skill 降人工），不能崩溃、不能当作 `new` 通过。
- **daemon 不可用 / 维度不匹配**：必须返回 `unavailable`，不能回退本地模型加载、不能抛未捕获异常。
- **缓存损坏或过期**：必须忽略缓存并重算；重算失败返回 `unavailable`，不能 500/崩溃。
- **缓存键陈旧（改了正文但没 reindex）**：7 天上限 + `--refresh` 兜底；判定只看 top-1 的相对分位，不能把陈旧缓存当致命错误。
- **标题缺失 / 内容文件不可读**：缺标题要带 warning 且仍出 verdict；文件不可读要 `success:false` + 非零退出，不能静默当空内容。

---

### Task 1: 纯相似度函数

**Files:**
- Create: `jfox/similarity.py`
- Test: `tests/unit/test_similarity.py`

**Interfaces:**
- Consumes: NumPy only.
- Produces:
  - `serialize_document(title: str, content: str) -> str`
  - `nearest_neighbor_scores(matrix: np.ndarray, chunk_size: int = 512) -> np.ndarray`
  - `nearest_neighbor_scores_for(queries, corpus, *, query_indices=None, chunk_size=512) -> np.ndarray`
  - `quantiles(values, ps=(50,75,90,95,99)) -> dict[str, float]`
  - `percentile_rank(value: float, sorted_values) -> float`
  - `classify_verdict(percentile: float, pass_below: int = 50, gray_below: int = 90) -> str`
  - `baseline_is_usable(note_count: int) -> bool`
  - `MIN_BASELINE_NOTES = 30`, `DEFAULT_CHUNK_SIZE = 512`

- [ ] **Step 1: 写失败测试**

```python
"""纯相似度函数的单元测试（不读盘、不加载模型）。"""

import numpy as np
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.similarity import (
    MIN_BASELINE_NOTES,
    baseline_is_usable,
    classify_verdict,
    nearest_neighbor_scores,
    percentile_rank,
    quantiles,
    serialize_document,
)


def test_document_serialization_matches_index_contract():
    assert serialize_document("标题", "正文") == "标题\n正文"
    assert serialize_document("", "正文") == "\n正文"


def test_nearest_neighbor_excludes_self():
    matrix = np.eye(3, dtype=np.float32)
    scores = nearest_neighbor_scores(matrix)
    assert scores.shape == (3,)
    assert np.allclose(scores, 0.0)


def test_nearest_neighbor_finds_the_closest_other_row():
    matrix = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.9, 0.1, 0.0],
            [0.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    scores = nearest_neighbor_scores(matrix)
    assert scores[0] >= 0.99
    assert scores[1] >= 0.99
    assert scores[2] < 0.2


def test_nearest_neighbor_zero_norm_row_scores_zero():
    matrix = np.array(
        [
            [0.0, 0.0, 0.0],
            [1.0, 0.0, 0.0],
        ],
        dtype=np.float32,
    )
    scores = nearest_neighbor_scores(matrix)
    assert scores[0] == 0.0


def test_nearest_neighbor_single_note_scores_zero():
    scores = nearest_neighbor_scores(np.array([[1.0, 0.0]], dtype=np.float32))
    assert scores.tolist() == [0.0]


def test_quantiles_on_empty_returns_zeros():
    result = quantiles(np.array([], dtype=np.float32))
    assert result == {f"p{p}": 0.0 for p in (50, 75, 90, 95, 99)}


def test_quantiles_standard_points():
    values = np.arange(1, 101, dtype=np.float32)
    result = quantiles(values)
    assert result["p50"] == pytest.approx(50.5, abs=0.6)
    assert result["p99"] == pytest.approx(99.01, abs=0.6)


def test_percentile_rank_boundaries_and_ties():
    values = np.array([0.5, 0.6, 0.6, 0.9], dtype=np.float32)
    assert percentile_rank(0.0, values) == 0.0
    assert percentile_rank(0.5, values) == 0.0
    assert percentile_rank(0.6, values) == 25.0
    assert percentile_rank(1.0, values) == 100.0
    assert percentile_rank(0.6, np.array([], dtype=np.float32)) == 0.0


def test_classify_verdict_boundaries():
    assert classify_verdict(0.0) == "new"
    assert classify_verdict(49.9) == "new"
    assert classify_verdict(50.0) == "gray"
    assert classify_verdict(89.9) == "gray"
    assert classify_verdict(90.0) == "covered"
    assert classify_verdict(100.0) == "covered"


def test_classify_verdict_rejects_invalid_policy():
    with pytest.raises(ValueError):
        classify_verdict(50.0, pass_below=90, gray_below=50)
    with pytest.raises(ValueError):
        classify_verdict(50.0, pass_below=-1, gray_below=90)
    with pytest.raises(ValueError):
        classify_verdict(50.0, pass_below=50, gray_below=101)


def test_baseline_min_notes_boundary():
    assert not baseline_is_usable(MIN_BASELINE_NOTES - 1)
    assert baseline_is_usable(MIN_BASELINE_NOTES)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_similarity.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jfox.similarity'`

- [ ] **Step 3: 写最小实现**

```python
"""Similarity baseline and candidate dedup judgment for the S2 gate.

Pure functions live at the top of the module; the I/O layer (Chroma snapshot,
note index, embedding daemon) lives below and is imported lazily so importing
this module never loads a model or ChromaDB.
"""

from __future__ import annotations

from typing import Dict, Optional, Sequence

import numpy as np

MIN_BASELINE_NOTES = 30
MAX_BASELINE_QUERIES = 512
DEFAULT_CHUNK_SIZE = 512
QUANTILE_POINTS = (50, 75, 90, 95, 99)


def serialize_document(title: str, content: str) -> str:
    """Mirror vector_store.add_note's indexed document exactly.

    Keep this identical to ``jfox/vector_store.py`` ``add_note``:
    ``document = f"{note.title}\\n{note.content}"``.
    """
    return f"{title}\n{content}"


def _normalize_rows(matrix: np.ndarray) -> np.ndarray:
    arr = np.asarray(matrix, dtype=np.float32)
    if arr.ndim != 2:
        raise ValueError("matrix must be two-dimensional")
    norms = np.linalg.norm(arr, axis=1, keepdims=True)
    return np.divide(arr, norms, out=np.zeros_like(arr), where=norms != 0)


def nearest_neighbor_scores_for(
    queries: np.ndarray,
    corpus: np.ndarray,
    *,
    query_indices: Optional[Sequence[int]] = None,
    chunk_size: int = DEFAULT_CHUNK_SIZE,
) -> np.ndarray:
    """Return each query row's max cosine against the corpus, excluding self.

    ``query_indices[i]`` is the corpus row corresponding to query row ``i``;
    it is excluded from that row's maximum. Zero-norm rows score 0.
    """
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    normalized_queries = _normalize_rows(queries)
    normalized_corpus = _normalize_rows(corpus)
    query_count = normalized_queries.shape[0]
    corpus_count = normalized_corpus.shape[0]
    if query_count == 0:
        return np.empty(0, dtype=np.float32)
    if corpus_count == 0:
        return np.zeros(query_count, dtype=np.float32)

    scores = np.zeros(query_count, dtype=np.float32)
    for start in range(0, query_count, chunk_size):
        end = min(start + chunk_size, query_count)
        block = normalized_queries[start:end] @ normalized_corpus.T
        if query_indices is not None:
            for local, corpus_index in enumerate(query_indices[start:end]):
                if 0 <= corpus_index < corpus_count:
                    block[local, corpus_index] = -np.inf
        row_max = block.max(axis=1)
        row_max[~np.isfinite(row_max)] = 0.0
        scores[start:end] = row_max
    return scores


def nearest_neighbor_scores(
    matrix: np.ndarray, chunk_size: int = DEFAULT_CHUNK_SIZE
) -> np.ndarray:
    """Return each row's nearest-neighbor cosine within the same matrix."""
    arr = np.asarray(matrix, dtype=np.float32)
    if arr.ndim != 2:
        raise ValueError("matrix must be two-dimensional")
    return nearest_neighbor_scores_for(
        arr,
        arr,
        query_indices=list(range(arr.shape[0])),
        chunk_size=chunk_size,
    )


def quantiles(
    values: Sequence[float], ps: Sequence[float] = QUANTILE_POINTS
) -> Dict[str, float]:
    """Return ``pXX`` quantiles; empty input yields zeros for every point."""
    arr = np.asarray(values, dtype=np.float32)
    if arr.size == 0:
        return {f"p{int(point)}": 0.0 for point in ps}
    return {f"p{int(point)}": float(np.percentile(arr, point)) for point in ps}


def percentile_rank(value: float, sorted_values: Sequence[float]) -> float:
    """Return the percentage of values strictly below ``value``."""
    arr = np.sort(np.asarray(sorted_values, dtype=np.float32))
    if arr.size == 0:
        return 0.0
    return float(100.0 * np.searchsorted(arr, value, side="left") / arr.size)


def classify_verdict(
    percentile: float, pass_below: int = 50, gray_below: int = 90
) -> str:
    """Map a percentile to ``new`` / ``gray`` / ``covered``."""
    if not 0 <= pass_below < gray_below <= 100:
        raise ValueError("require 0 <= pass_below < gray_below <= 100")
    if percentile < pass_below:
        return "new"
    if percentile < gray_below:
        return "gray"
    return "covered"


def baseline_is_usable(note_count: int) -> bool:
    """A baseline needs enough notes for stable percentiles."""
    return note_count >= MIN_BASELINE_NOTES
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_similarity.py -v`
Expected: PASS（11 passed）

- [ ] **Step 5: 提交**

```bash
git add jfox/similarity.py tests/unit/test_similarity.py
git commit -m "feat(similarity): add pure baseline and verdict helpers (#586)"
```

---

### Task 2: live permanent 快照过滤 + classifier 迁移

**Files:**
- Modify: `jfox/similarity.py`
- Modify: `jfox/moc/cluster.py`（删除本地 `classify_vector_id`，改为 re-export）
- Test: `tests/unit/test_similarity.py`

**Interfaces:**
- Consumes: `NoteMeta`（`jfox/note_index.py`）、`NoteType`（`jfox/models.py`）、`VectorStore`（延迟 import）。
- Produces:
  - `classify_vector_id(note_id: str, permanent_meta: Mapping[str, NoteMeta]) -> Literal["ghost","archived","live"]`
  - `@dataclass LiveRecords(ids: list[str], titles: list[str], matrix: np.ndarray)`
  - `filter_live_records(vector_ids, vector_meta, embeddings, permanent_meta) -> LiveRecords`
  - `load_live_records(cfg: ZKConfig) -> LiveRecords`
  - `SimilarityError(RuntimeError)`

- [ ] **Step 1: 写失败测试**

追加到 `tests/unit/test_similarity.py`：

```python
from jfox.models import NoteType
from jfox.note_index import NoteMeta
from jfox.similarity import (
    SimilarityError,
    classify_vector_id,
    filter_live_records,
)


def _meta(note_id: str, title: str, *, archived: bool = False) -> NoteMeta:
    return NoteMeta(
        id=note_id,
        title=title,
        type=NoteType.PERMANENT,
        archived=archived,
    )


def test_classify_vector_id_three_way():
    permanent = {"live-1": _meta("live-1", "Live"), "arch-1": _meta("arch-1", "Old", archived=True)}
    assert classify_vector_id("live-1", permanent) == "live"
    assert classify_vector_id("arch-1", permanent) == "archived"
    assert classify_vector_id("ghost-1", permanent) == "ghost"


def test_filter_live_records_skips_archived_and_ghost():
    embeddings = np.eye(3, dtype=np.float32)
    records = filter_live_records(
        ["live-1", "arch-1", "ghost-1"],
        [{"title": "Live"}, {"title": "Old"}, None],
        embeddings,
        {"live-1": _meta("live-1", "Live"), "arch-1": _meta("arch-1", "Old", archived=True)},
    )
    assert records.ids == ["live-1"]
    assert records.titles == ["Live"]
    assert records.matrix.shape == (1, 3)


def test_filter_live_records_dedupes_repeated_ids_and_sorts():
    embeddings = np.eye(3, dtype=np.float32)
    records = filter_live_records(
        ["b", "a", "a"],
        [{}, {}, {}],
        embeddings,
        {"a": _meta("a", "A"), "b": _meta("b", "B")},
    )
    assert records.ids == ["a", "b"]
    assert records.titles == ["A", "B"]
    assert records.matrix.shape == (2, 3)


def test_filter_live_records_rejects_corrupt_shapes():
    with pytest.raises(SimilarityError):
        filter_live_records(["a", "b"], [{}], np.eye(2, dtype=np.float32), {"a": _meta("a", "A")})
    with pytest.raises(SimilarityError):
        filter_live_records(["a"], [{}], np.eye(2, dtype=np.float32), {"a": _meta("a", "A")})
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_similarity.py -v`
Expected: FAIL with `ImportError: cannot import name 'SimilarityError'`

- [ ] **Step 3: 实现过滤与迁移**

在 `jfox/similarity.py` 顶部 import 区加：

```python
from typing import Literal

from .index_state import load_index_state
from .models import NoteType
from .note_index import NoteMeta
```

在 `MIN_BASELINE_NOTES` 之前加：

```python
class SimilarityError(RuntimeError):
    """Raised when the permanent vector snapshot cannot be read safely."""


@dataclass
class LiveRecords:
    """Live permanent notes with their stored vectors, sorted by note id."""

    ids: List[str]
    titles: List[str]
    matrix: np.ndarray


def classify_vector_id(
    note_id: str, permanent_meta: Mapping[str, NoteMeta]
) -> Literal["ghost", "archived", "live"]:
    """Classify a permanent vector row as ghost / archived / live.

    ghost: no matching permanent note on disk; archived: frontmatter marks it
    archived; live: active permanent note. Duplicate rows are handled by the
    caller's ``seen`` set, not here.
    """
    meta = permanent_meta.get(note_id)
    if meta is None:
        return "ghost"
    if meta.archived:
        return "archived"
    return "live"


def filter_live_records(
    vector_ids: Sequence[str],
    vector_meta: Sequence[Optional[Mapping[str, Any]]],
    embeddings: np.ndarray,
    permanent_meta: Mapping[str, NoteMeta],
) -> LiveRecords:
    """Filter a Chroma snapshot down to live permanent rows.

    Archived, ghost and duplicate id rows are skipped; records are sorted by
    note id so downstream sampling is deterministic.
    """
    matrix = np.asarray(embeddings, dtype=np.float32)
    if len(vector_ids) != len(vector_meta):
        raise SimilarityError(
            f"Corrupt permanent vector data: ids={len(vector_ids)}, metadata={len(vector_meta)}"
        )
    if matrix.ndim != 2 or matrix.shape[0] != len(vector_ids):
        raise SimilarityError(
            f"Corrupt permanent vector data: ids={len(vector_ids)}, "
            f"embeddings_shape={matrix.shape}"
        )
    records: List[tuple[str, str, np.ndarray]] = []
    seen = set()
    for index, note_id in enumerate(vector_ids):
        if note_id in seen:
            continue
        if classify_vector_id(note_id, permanent_meta) != "live":
            continue
        seen.add(note_id)
        records.append((note_id, permanent_meta[note_id].title, matrix[index]))
    records.sort(key=lambda record: record[0])
    if not records:
        return LiveRecords(ids=[], titles=[], matrix=np.empty((0, matrix.shape[1]), dtype=np.float32))
    return LiveRecords(
        ids=[record[0] for record in records],
        titles=[record[1] for record in records],
        matrix=np.asarray([record[2] for record in records], dtype=np.float32),
    )


def load_live_records(cfg: ZKConfig) -> LiveRecords:
    """Read the current Chroma snapshot and filter it to live permanent notes."""
    from .note_index import get_note_index
    from .vector_store import VectorStore, VectorStoreReadError

    note_index = get_note_index(cfg)
    permanent_meta = {
        meta.id: meta for meta in note_index.get_all_meta() if meta.type == NoteType.PERMANENT
    }
    vector_store = VectorStore(persist_directory=cfg.chroma_dir)
    try:
        vector_ids, vector_meta, embeddings = vector_store.get_all_embeddings("permanent")
    except VectorStoreReadError as exc:
        raise SimilarityError(str(exc)) from exc
    return filter_live_records(vector_ids, vector_meta, embeddings, permanent_meta)
```

在 `jfox/moc/cluster.py`：

1. 删除本地 `classify_vector_id` 函数（原 164–178 行）。
2. 在 `from ..note_index import NoteMeta, get_note_index` 改为 `from ..note_index import get_note_index`。
3. 在 import 区加 `from ..similarity import classify_vector_id  # noqa: F401`（re-export，保持 `tests/unit/test_moc_cluster.py:16` 的导入路径）。
4. 从 `typing` 去掉 `Literal`，确认 `Mapping`/`NoteMeta` 不再被使用后一并去掉。

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
uv run pytest tests/unit/test_similarity.py tests/unit/test_moc_cluster.py -v
```
Expected: PASS（新增 4 个 + 既有 MOC 测试全绿）

- [ ] **Step 5: 提交**

```bash
git add jfox/similarity.py jfox/moc/cluster.py tests/unit/test_similarity.py
git commit -m "refactor(similarity): share live permanent snapshot filtering (#586)"
```

---

### Task 3: 基线与缓存

**Files:**
- Modify: `jfox/similarity.py`
- Test: `tests/unit/test_similarity.py`

**Interfaces:**
- Consumes: Task 1/2 的函数；`load_index_state(cfg)`。
- Produces:
  - `@dataclass Baseline(model, dimension, note_count, sampled, quantiles, nn_values, index_rebuilt_at, computed_at, from_cache=False)`
  - `baseline_public_dict(baseline) -> dict`
  - `stats_path(cfg) -> Path`
  - `load_cached_baseline(cfg, *, model, dimension, note_count, index_rebuilt_at, now=None) -> Optional[Baseline]`
  - `save_cached_baseline(cfg, baseline) -> bool`
  - `current_model_name(cfg) -> str`
  - `compute_baseline(cfg, *, refresh=False, records=None, model=None, now=None) -> Optional[Baseline]`

- [ ] **Step 1: 写失败测试**

追加到 `tests/unit/test_similarity.py`：

```python
from datetime import datetime, timedelta
import json

from jfox.config import ZKConfig
from jfox.similarity import (
    Baseline,
    compute_baseline,
    load_cached_baseline,
    save_cached_baseline,
    stats_path,
)


def _records(matrix):
    from jfox.similarity import LiveRecords

    return LiveRecords(
        ids=[f"n{i}" for i in range(matrix.shape[0])],
        titles=[f"T{i}" for i in range(matrix.shape[0])],
        matrix=np.asarray(matrix, dtype=np.float32),
    )


def _cfg(tmp_path):
    cfg = ZKConfig(base_dir=tmp_path)
    cfg.ensure_dirs()
    return cfg


def _baseline(**overrides):
    data = dict(
        model="stub",
        dimension=3,
        note_count=3,
        sampled=False,
        quantiles={"p50": 0.5, "p75": 0.6, "p90": 0.7, "p95": 0.8, "p99": 0.9},
        nn_values=np.array([0.4, 0.5, 0.6], dtype=np.float32),
        index_rebuilt_at="2026-10-21T00:00:00",
        computed_at="2026-10-21T00:00:00",
    )
    data.update(overrides)
    return Baseline(**data)


def test_baseline_cache_roundtrip(tmp_path):
    cfg = _cfg(tmp_path)
    baseline = _baseline()
    assert save_cached_baseline(cfg, baseline)
    loaded = load_cached_baseline(
        cfg,
        model="stub",
        dimension=3,
        note_count=3,
        index_rebuilt_at="2026-10-21T00:00:00",
        now=datetime(2026, 10, 21, 1, 0, 0),
    )
    assert loaded is not None
    assert loaded.from_cache is True
    assert loaded.quantiles["p99"] == pytest.approx(0.9)
    assert np.allclose(loaded.nn_values, [0.4, 0.5, 0.6])


def test_baseline_cache_invalidated_by_key_change(tmp_path):
    cfg = _cfg(tmp_path)
    save_cached_baseline(cfg, _baseline())
    assert (
        load_cached_baseline(
            cfg,
            model="other",
            dimension=3,
            note_count=3,
            index_rebuilt_at="2026-10-21T00:00:00",
        )
        is None
    )
    assert (
        load_cached_baseline(
            cfg,
            model="stub",
            dimension=4,
            note_count=3,
            index_rebuilt_at="2026-10-21T00:00:00",
        )
        is None
    )
    assert (
        load_cached_baseline(
            cfg,
            model="stub",
            dimension=3,
            note_count=4,
            index_rebuilt_at="2026-10-21T00:00:00",
        )
        is None
    )


def test_baseline_cache_expires_after_seven_days(tmp_path):
    cfg = _cfg(tmp_path)
    save_cached_baseline(cfg, _baseline())
    loaded = load_cached_baseline(
        cfg,
        model="stub",
        dimension=3,
        note_count=3,
        index_rebuilt_at="2026-10-21T00:00:00",
        now=datetime(2026, 10, 29, 0, 0, 1),
    )
    assert loaded is None


def test_baseline_cache_corruption_is_ignored(tmp_path):
    cfg = _cfg(tmp_path)
    stats_path(cfg).write_text("{not json", encoding="utf-8")
    assert (
        load_cached_baseline(
            cfg,
            model="stub",
            dimension=3,
            note_count=3,
            index_rebuilt_at="2026-10-21T00:00:00",
        )
        is None
    )
    stats_path(cfg).write_text(
        json.dumps({"version": 1}), encoding="utf-8"
    )
    assert (
        load_cached_baseline(
            cfg,
            model="stub",
            dimension=3,
            note_count=3,
            index_rebuilt_at="2026-10-21T00:00:00",
        )
        is None
    )


def test_compute_baseline_returns_none_below_minimum(tmp_path):
    cfg = _cfg(tmp_path)
    records = _records(np.eye(3, dtype=np.float32))
    assert compute_baseline(cfg, records=records, model="stub") is None


def test_compute_baseline_uses_cache_then_refresh(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    records = _records(np.eye(35, dtype=np.float32))
    monkeypatch.setattr(
        "jfox.similarity.load_index_state",
        lambda cfg=None: {"last_rebuild": "2026-10-21T00:00:00"},
    )
    first = compute_baseline(cfg, records=records, model="stub", now=datetime(2026, 10, 21, 1))
    assert first is not None and first.from_cache is False
    second = compute_baseline(cfg, records=records, model="stub", now=datetime(2026, 10, 21, 2))
    assert second is not None and second.from_cache is True
    refreshed = compute_baseline(
        cfg, records=records, model="stub", refresh=True, now=datetime(2026, 10, 21, 3)
    )
    assert refreshed is not None and refreshed.from_cache is False


def test_compute_baseline_samples_above_query_cap(tmp_path, monkeypatch):
    cfg = _cfg(tmp_path)
    records = _records(np.eye(513, dtype=np.float32))
    monkeypatch.setattr(
        "jfox.similarity.load_index_state",
        lambda cfg=None: {"last_rebuild": "2026-10-21T00:00:00"},
    )
    baseline = compute_baseline(cfg, records=records, model="stub", now=datetime(2026, 10, 21, 1))
    assert baseline is not None
    assert baseline.sampled is True
    assert baseline.note_count == 513
    assert len(baseline.nn_values) == 512
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_similarity.py -v`
Expected: FAIL with `ImportError: cannot import name 'Baseline'`

- [ ] **Step 3: 实现 Baseline 与缓存**

在 `jfox/similarity.py` 追加（放在 `load_live_records` 之后）：

```python
STATS_FILENAME = "similarity_stats.json"
STATS_VERSION = 1
CACHE_MAX_AGE = timedelta(days=7)


@dataclass
class Baseline:
    """Nearest-neighbor distribution for the current permanent snapshot."""

    model: str
    dimension: int
    note_count: int
    sampled: bool
    quantiles: Dict[str, float]
    nn_values: np.ndarray
    index_rebuilt_at: Optional[str]
    computed_at: str
    from_cache: bool = False

    def to_cache_dict(self) -> dict:
        return {
            "version": STATS_VERSION,
            "model": self.model,
            "dimension": self.dimension,
            "note_count": self.note_count,
            "sampled": self.sampled,
            "quantiles": self.quantiles,
            "nn_values": [float(value) for value in self.nn_values],
            "index_rebuilt_at": self.index_rebuilt_at,
            "computed_at": self.computed_at,
        }


def baseline_public_dict(baseline: Baseline) -> dict:
    """Return the stable public shape (no raw nn_values array)."""
    return {
        "p50": baseline.quantiles.get("p50", 0.0),
        "p75": baseline.quantiles.get("p75", 0.0),
        "p90": baseline.quantiles.get("p90", 0.0),
        "p95": baseline.quantiles.get("p95", 0.0),
        "p99": baseline.quantiles.get("p99", 0.0),
        "note_count": baseline.note_count,
        "sampled": baseline.sampled,
    }


def stats_path(cfg: ZKConfig) -> Path:
    return cfg.zk_dir / STATS_FILENAME


def load_cached_baseline(
    cfg: ZKConfig,
    *,
    model: str,
    dimension: int,
    note_count: int,
    index_rebuilt_at: Optional[str],
    now: Optional[datetime] = None,
) -> Optional[Baseline]:
    """Load a cache entry when every key matches and it is under 7 days old."""
    try:
        data = json.loads(stats_path(cfg).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    if not isinstance(data, dict) or data.get("version") != STATS_VERSION:
        return None
    if data.get("model") != model or data.get("dimension") != dimension:
        return None
    if data.get("note_count") != note_count:
        return None
    if data.get("index_rebuilt_at") != index_rebuilt_at:
        return None
    try:
        computed_at = datetime.fromisoformat(data["computed_at"])
        quantiles_data = {str(key): float(value) for key, value in data["quantiles"].items()}
        nn_values = np.asarray([float(value) for value in data["nn_values"]], dtype=np.float32)
    except (KeyError, TypeError, ValueError):
        return None
    if computed_at.tzinfo is not None:
        computed_at = computed_at.astimezone().replace(tzinfo=None)
    current = now or datetime.now()
    if current - computed_at > CACHE_MAX_AGE:
        return None
    if len(nn_values) != min(note_count, MAX_BASELINE_QUERIES):
        return None
    return Baseline(
        model=model,
        dimension=dimension,
        note_count=note_count,
        sampled=bool(data.get("sampled")),
        quantiles=quantiles_data,
        nn_values=np.sort(nn_values),
        index_rebuilt_at=index_rebuilt_at,
        computed_at=data["computed_at"],
        from_cache=True,
    )


def save_cached_baseline(cfg: ZKConfig, baseline: Baseline) -> bool:
    """Atomically write the cache; failures are reported, never fatal."""
    import tempfile

    path = stats_path(cfg)
    tmp: Optional[str] = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(baseline.to_cache_dict(), handle, ensure_ascii=False)
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


def current_model_name(cfg: ZKConfig) -> str:
    """Best-effort model label without loading the model."""
    return str(cfg.embedding_model or "auto")


def compute_baseline(
    cfg: ZKConfig,
    *,
    refresh: bool = False,
    records: Optional[LiveRecords] = None,
    model: Optional[str] = None,
    now: Optional[datetime] = None,
) -> Optional[Baseline]:
    """Compute (or load) the nearest-neighbor baseline for live permanent notes."""
    live = records if records is not None else load_live_records(cfg)
    note_count = len(live.ids)
    if not baseline_is_usable(note_count):
        return None
    dimension = int(live.matrix.shape[1]) if live.matrix.size else 0
    model_name = model or current_model_name(cfg)
    state = load_index_state(cfg) or {}
    index_rebuilt_at = state.get("last_rebuild") if isinstance(state, dict) else None
    if not refresh:
        cached = load_cached_baseline(
            cfg,
            model=model_name,
            dimension=dimension,
            note_count=note_count,
            index_rebuilt_at=index_rebuilt_at,
            now=now,
        )
        if cached is not None:
            return cached

    sampled = note_count > MAX_BASELINE_QUERIES
    if sampled:
        step = max(1, note_count // MAX_BASELINE_QUERIES)
        query_indices = list(range(0, note_count, step))[:MAX_BASELINE_QUERIES]
        nn_scores = nearest_neighbor_scores_for(
            live.matrix[query_indices],
            live.matrix,
            query_indices=query_indices,
        )
    else:
        nn_scores = nearest_neighbor_scores(live.matrix)

    baseline = Baseline(
        model=model_name,
        dimension=dimension,
        note_count=note_count,
        sampled=sampled,
        quantiles=quantiles(nn_scores),
        nn_values=np.sort(nn_scores),
        index_rebuilt_at=index_rebuilt_at,
        computed_at=(now or datetime.now()).isoformat(timespec="seconds"),
    )
    save_cached_baseline(cfg, baseline)
    return baseline
```

在文件顶部补 `import json`、`import os`、`from pathlib import Path`、`from datetime import datetime, timedelta`、`from dataclasses import dataclass`、`from .config import ZKConfig`。

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_similarity.py -v`
Expected: PASS（全部通过；Task 3 新增 7 个用例）

- [ ] **Step 5: 提交**

```bash
git add jfox/similarity.py tests/unit/test_similarity.py
git commit -m "feat(similarity): cache the nearest-neighbor baseline (#586)"
```

---

### Task 4: 候选判定

**Files:**
- Modify: `jfox/similarity.py`
- Test: `tests/unit/test_similarity.py`

**Interfaces:**
- Consumes: Task 1–3 的 `Baseline` / `LiveRecords` / `classify_verdict` / `serialize_document`。
- Produces:
  - `check_candidate(cfg, title, content, *, exclude_id=None, top=3, pass_below=50, gray_below=90, refresh=False, records=None, baseline=None, backend=None) -> dict`

- [ ] **Step 1: 写失败测试**

追加到 `tests/unit/test_similarity.py`：

```python
from jfox.similarity import check_candidate


class _StubBackend:
    def __init__(self, unit_vector):
        self.unit_vector = np.asarray(unit_vector, dtype=np.float32)

    def encode_single(self, text, *, daemon_only=False):
        assert daemon_only is True
        return self.unit_vector


def _check_baseline():
    return _baseline(
        note_count=3,
        quantiles={"p50": 0.6, "p75": 0.7, "p90": 0.8, "p95": 0.9, "p99": 0.95},
        nn_values=np.array([0.5, 0.6, 0.7, 0.8, 0.9, 0.95], dtype=np.float32),
    )


def _check_records():
    return _records(np.eye(3, dtype=np.float32))


@pytest.mark.parametrize(
    ("unit_vector", "expected"),
    [
        ([0.4, 0.916, 0.0], "new"),
        ([0.8, 0.6, 0.0], "gray"),
        ([1.0, 0.0, 0.0], "covered"),
    ],
)
def test_check_candidate_three_verdicts(tmp_path, unit_vector, expected):
    cfg = _cfg(tmp_path)
    payload = check_candidate(
        cfg,
        "草稿标题",
        "草稿正文",
        records=_check_records(),
        baseline=_check_baseline(),
        backend=_StubBackend(unit_vector),
    )
    assert payload["success"] is True
    assert payload["verdict"] == expected
    assert payload["top1"]["id"] == "n0"
    assert payload["policy"] == {"pass_below": 50, "gray_below": 90}


def test_check_candidate_unavailable_without_baseline(tmp_path):
    cfg = _cfg(tmp_path)
    payload = check_candidate(
        cfg,
        "标题",
        "正文",
        records=_check_records(),
        baseline=None,
        backend=_StubBackend([1.0, 0.0, 0.0]),
    )
    assert payload["success"] is True
    assert payload["verdict"] == "unavailable"
    assert "baseline" in payload["unavailable_reason"]


def test_check_candidate_unavailable_on_backend_error(tmp_path):
    cfg = _cfg(tmp_path)

    class _Boom:
        def encode_single(self, text, *, daemon_only=False):
            raise RuntimeError("daemon down")

    payload = check_candidate(
        cfg,
        "标题",
        "正文",
        records=_check_records(),
        baseline=_check_baseline(),
        backend=_Boom(),
    )
    assert payload["verdict"] == "unavailable"
    assert "embedding unavailable" in payload["unavailable_reason"]


def test_check_candidate_unavailable_on_dimension_mismatch(tmp_path):
    cfg = _cfg(tmp_path)
    payload = check_candidate(
        cfg,
        "标题",
        "正文",
        records=_check_records(),
        baseline=_check_baseline(),
        backend=_StubBackend([1.0, 0.0]),
    )
    assert payload["verdict"] == "unavailable"
    assert "dimension mismatch" in payload["unavailable_reason"]


def test_check_candidate_excludes_edit_target(tmp_path):
    cfg = _cfg(tmp_path)
    payload = check_candidate(
        cfg,
        "标题",
        "正文",
        exclude_id="n0",
        records=_check_records(),
        baseline=_check_baseline(),
        backend=_StubBackend([1.0, 0.0, 0.0]),
    )
    assert payload["top1"]["id"] != "n0"
    assert payload["verdict"] in {"new", "gray", "covered"}


def test_check_candidate_title_missing_warning(tmp_path):
    cfg = _cfg(tmp_path)
    payload = check_candidate(
        cfg,
        "",
        "正文",
        records=_check_records(),
        baseline=_check_baseline(),
        backend=_StubBackend([1.0, 0.0, 0.0]),
    )
    assert "title missing" in payload["warnings"][0]


def test_check_candidate_rejects_invalid_policy(tmp_path):
    cfg = _cfg(tmp_path)
    with pytest.raises(ValueError):
        check_candidate(
            cfg,
            "标题",
            "正文",
            pass_below=90,
            gray_below=50,
            records=_check_records(),
            baseline=_check_baseline(),
            backend=_StubBackend([1.0, 0.0, 0.0]),
        )
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_similarity.py -v`
Expected: FAIL with `ImportError: cannot import name 'check_candidate'`

- [ ] **Step 3: 实现 `check_candidate`**

在 `jfox/similarity.py` 追加：

```python
def _unavailable(
    reason: str,
    *,
    cfg: ZKConfig,
    candidate: dict,
    baseline: Optional[Baseline],
    pass_below: int,
    gray_below: int,
    warnings: List[str],
) -> dict:
    return {
        "success": True,
        "kb": cfg.base_dir.name,
        "candidate": candidate,
        "top1": None,
        "matches": [],
        "baseline": baseline_public_dict(baseline) if baseline is not None else None,
        "policy": {"pass_below": pass_below, "gray_below": gray_below},
        "verdict": "unavailable",
        "unavailable_reason": reason,
        "warnings": warnings,
    }


def check_candidate(
    cfg: ZKConfig,
    title: str,
    content: str,
    *,
    exclude_id: Optional[str] = None,
    top: int = 3,
    pass_below: int = 50,
    gray_below: int = 90,
    refresh: bool = False,
    records: Optional[LiveRecords] = None,
    baseline: Optional[Baseline] = None,
    backend: Any = None,
) -> dict:
    """Compare a candidate note against the library and return a verdict.

    ``backend`` is injectable for tests; production callers leave it ``None``
    so the embedding daemon is used with ``daemon_only=True``.
    """
    import math

    if not 0 <= pass_below < gray_below <= 100:
        raise ValueError("require 0 <= pass_below < gray_below <= 100")
    if top < 1:
        raise ValueError("top must be at least 1")

    warnings: List[str] = []
    if not title:
        warnings.append("title missing; comparison may be less accurate")
    candidate = {"title": title, "chars": len(content)}

    live = records if records is not None else load_live_records(cfg)
    base = baseline if baseline is not None else compute_baseline(cfg, refresh=refresh, records=live)
    if base is None:
        return _unavailable(
            f"baseline needs at least {MIN_BASELINE_NOTES} permanent notes",
            cfg=cfg,
            candidate=candidate,
            baseline=None,
            pass_below=pass_below,
            gray_below=gray_below,
            warnings=warnings,
        )
    if live.matrix.size == 0:
        return _unavailable(
            "no permanent notes with embeddings",
            cfg=cfg,
            candidate=candidate,
            baseline=base,
            pass_below=pass_below,
            gray_below=gray_below,
            warnings=warnings,
        )

    if backend is None:
        from .embedding_backend import get_backend

        backend = get_backend()
    try:
        vector = np.asarray(
            backend.encode_single(serialize_document(title, content), daemon_only=True),
            dtype=np.float32,
        )
    except Exception as exc:
        return _unavailable(
            f"embedding unavailable: {exc}",
            cfg=cfg,
            candidate=candidate,
            baseline=base,
            pass_below=pass_below,
            gray_below=gray_below,
            warnings=warnings,
        )
    if vector.ndim != 1 or vector.shape[0] != live.matrix.shape[1]:
        return _unavailable(
            "embedding dimension mismatch; run `jfox index rebuild`",
            cfg=cfg,
            candidate=candidate,
            baseline=base,
            pass_below=pass_below,
            gray_below=gray_below,
            warnings=warnings,
        )

    norms = np.linalg.norm(live.matrix, axis=1)
    denominator = np.where(norms == 0, 1.0, norms) * (float(np.linalg.norm(vector)) or 1.0)
    scores = (live.matrix @ vector) / denominator
    if exclude_id is not None:
        for index, note_id in enumerate(live.ids):
            if note_id == exclude_id:
                scores[index] = -np.inf

    order = np.argsort(-scores)[:top]
    matches = []
    for index in order:
        score = float(scores[index])
        if not math.isfinite(score):
            continue
        matches.append(
            {
                "id": live.ids[index],
                "title": live.titles[index],
                "score": round(score, 6),
                "percentile": round(percentile_rank(score, base.nn_values), 1),
            }
        )
    if not matches:
        return _unavailable(
            "no comparable permanent notes after exclusion",
            cfg=cfg,
            candidate=candidate,
            baseline=base,
            pass_below=pass_below,
            gray_below=gray_below,
            warnings=warnings,
        )

    top1 = matches[0]
    verdict = classify_verdict(float(top1["percentile"]), pass_below, gray_below)
    return {
        "success": True,
        "kb": cfg.base_dir.name,
        "candidate": candidate,
        "top1": top1,
        "matches": matches,
        "baseline": baseline_public_dict(base),
        "policy": {"pass_below": pass_below, "gray_below": gray_below},
        "verdict": verdict,
        "unavailable_reason": None,
        "warnings": warnings,
    }
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_similarity.py -v`
Expected: PASS（全部通过；Task 4 新增 9 个用例，含 3 个参数化 verdict）

- [ ] **Step 5: 提交**

```bash
git add jfox/similarity.py tests/unit/test_similarity.py
git commit -m "feat(similarity): judge candidates by library percentile (#586)"
```

---

### Task 5: CLI 子应用与注册

**Files:**
- Create: `jfox/similarity_cli.py`
- Modify: `jfox/cli.py`（注册子应用）
- Test: `tests/integration/test_similarity_cli.py`

**Interfaces:**
- Consumes: Task 1–4 的 `compute_baseline` / `baseline_public_dict` / `check_candidate` / `load_live_records` / `current_model_name`。
- Produces:
  - `similarity_app`（Typer）
  - `jfox similarity stats --json`
  - `jfox similarity check --content-file/--content --json`

- [ ] **Step 1: 写失败测试**

```python
"""CLI contract tests for `jfox similarity` (deterministic stub, no model)."""

import json
from datetime import datetime

import numpy as np
import pytest
from typer.testing import CliRunner

from jfox.cli import app
from jfox.config import ZKConfig
from jfox.similarity import Baseline, LiveRecords

pytestmark = [pytest.mark.integration, pytest.mark.fast]

runner = CliRunner()


def _cfg(tmp_path):
    cfg = ZKConfig(base_dir=tmp_path)
    cfg.ensure_dirs()
    return cfg


def _records():
    return LiveRecords(
        ids=["n0", "n1", "n2"],
        titles=["T0", "T1", "T2"],
        matrix=np.eye(3, dtype=np.float32),
    )


def _baseline():
    return Baseline(
        model="stub",
        dimension=3,
        note_count=3,
        sampled=False,
        quantiles={"p50": 0.6, "p75": 0.7, "p90": 0.8, "p95": 0.9, "p99": 0.95},
        nn_values=np.array([0.5, 0.6, 0.7, 0.8, 0.9, 0.95], dtype=np.float32),
        index_rebuilt_at=None,
        computed_at=datetime(2026, 10, 21, 0, 0, 0).isoformat(),
    )


class _StubBackend:
    def __init__(self, unit_vector):
        self.unit_vector = np.asarray(unit_vector, dtype=np.float32)

    def encode_single(self, text, *, daemon_only=False):
        return self.unit_vector


def _patch_common(monkeypatch, tmp_path, *, with_baseline=True):
    cfg = _cfg(tmp_path)
    monkeypatch.setattr("jfox.similarity_cli._current_config", lambda: cfg)
    monkeypatch.setattr("jfox.similarity.load_live_records", lambda cfg: _records())
    monkeypatch.setattr(
        "jfox.similarity.compute_baseline",
        lambda cfg, **kwargs: _baseline() if with_baseline else None,
    )
    return cfg


def test_stats_json_contract(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path)
    result = runner.invoke(app, ["similarity", "stats", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["success"] is True
    assert payload["note_count"] == 3
    assert payload["baseline"]["p99"] == pytest.approx(0.95)
    assert payload["policy"] == {"pass_below": 50, "gray_below": 90}


def test_stats_unavailable_when_baseline_missing(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path, with_baseline=False)
    result = runner.invoke(app, ["similarity", "stats", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["baseline"] is None
    assert payload["unavailable_reason"]


@pytest.mark.parametrize(
    ("unit_vector", "expected"),
    [
        ([0.4, 0.916, 0.0], "new"),
        ([0.8, 0.6, 0.0], "gray"),
        ([1.0, 0.0, 0.0], "covered"),
    ],
)
def test_check_json_verdicts(monkeypatch, tmp_path, unit_vector, expected):
    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr("jfox.embedding_backend.get_backend", lambda: _StubBackend(unit_vector))
    result = runner.invoke(
        app,
        ["similarity", "check", "--content", "草稿正文", "--title", "草稿标题", "--json"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["verdict"] == expected
    assert payload["top1"]["id"] == "n0"


def test_check_requires_exactly_one_content_source(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path)
    result = runner.invoke(app, ["similarity", "check", "--json"])
    assert result.exit_code == 1
    payload = json.loads(result.output)
    assert payload["success"] is False


def test_check_title_missing_warning(monkeypatch, tmp_path):
    _patch_common(monkeypatch, tmp_path)
    monkeypatch.setattr(
        "jfox.embedding_backend.get_backend", lambda: _StubBackend([1.0, 0.0, 0.0])
    )
    result = runner.invoke(app, ["similarity", "check", "--content", "正文", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert "title missing" in payload["warnings"][0]
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/integration/test_similarity_cli.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'jfox.similarity_cli'`

- [ ] **Step 3: 实现 CLI 与注册**

```python
"""CLI for the similarity baseline and S2 dedup judgment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import NoReturn, Optional

import typer
from rich.console import Console
from rich.table import Table

from .config import ZKConfig, config, use_kb

similarity_app = typer.Typer(
    name="similarity",
    help="查看相似度基线并判定候选笔记",
    no_args_is_help=True,
)

_json_console = Console(legacy_windows=False, highlight=False, markup=False, no_color=True)
_console = Console(legacy_windows=False, no_color=True, highlight=False)


def _current_config() -> ZKConfig:
    return ZKConfig.for_kb(config.base_dir)


def _fail(message: str, output_format: str) -> NoReturn:
    if output_format == "json":
        _json_console.print(
            json.dumps({"success": False, "error": message}, ensure_ascii=False),
            soft_wrap=True,
        )
    else:
        _console.print(f"Error: {message}")
    raise typer.Exit(1)


@similarity_app.command("stats", help="显示永久笔记的最近邻相似度分布。")
def stats_cmd(
    kb: Optional[str] = typer.Option(None, "--kb", "-k"),
    refresh: bool = typer.Option(False, "--refresh"),
    output_format: str = typer.Option("table", "--format", "-f"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """显示当前知识库的相似度基线。"""
    if json_output:
        output_format = "json"
    if output_format not in {"table", "json"}:
        _fail("format must be table or json", output_format)

    try:
        with use_kb(kb):
            cfg = _current_config()
            from .similarity import (
                MIN_BASELINE_NOTES,
                baseline_public_dict,
                compute_baseline,
                current_model_name,
                load_live_records,
            )

            records = load_live_records(cfg)
            baseline = compute_baseline(cfg, refresh=refresh, records=records)
            payload = {
                "success": True,
                "kb": cfg.base_dir.name,
                "model": current_model_name(cfg),
                "dimension": int(records.matrix.shape[1]) if records.matrix.size else 0,
                "note_count": len(records.ids),
                "sampled": baseline.sampled if baseline is not None else False,
                "baseline": baseline_public_dict(baseline) if baseline is not None else None,
                "policy": {"pass_below": 50, "gray_below": 90},
                "cached": baseline.from_cache if baseline is not None else False,
                "computed_at": baseline.computed_at if baseline is not None else None,
                "unavailable_reason": (
                    None
                    if baseline is not None
                    else f"baseline needs at least {MIN_BASELINE_NOTES} permanent notes"
                ),
            }
    except Exception as exc:
        _fail(str(exc), output_format)

    if output_format == "json":
        _json_console.print(json.dumps(payload, ensure_ascii=False, indent=2), soft_wrap=True)
        return

    _console.print(
        f"KB: {payload['kb']}  model: {payload['model']}  "
        f"dim: {payload['dimension']}  notes: {payload['note_count']}"
    )
    if payload["baseline"] is None:
        _console.print(f"Unavailable: {payload['unavailable_reason']}")
        return
    table = Table(show_header=True, box=None)
    table.add_column("quantile")
    table.add_column("score")
    for key in ("p50", "p75", "p90", "p95", "p99"):
        table.add_row(key, f"{payload['baseline'][key]:.3f}")
    _console.print(table)


@similarity_app.command("check", help="把候选笔记与库比较并给出分位判定。")
def check_cmd(
    content_file: Optional[Path] = typer.Option(None, "--content-file"),
    content: Optional[str] = typer.Option(None, "--content"),
    title: Optional[str] = typer.Option(None, "--title"),
    exclude_id: Optional[str] = typer.Option(None, "--exclude-id"),
    top: int = typer.Option(3, "--top"),
    pass_below: int = typer.Option(50, "--pass-below"),
    gray_below: int = typer.Option(90, "--gray-below"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k"),
    refresh: bool = typer.Option(False, "--refresh"),
    output_format: str = typer.Option("table", "--format", "-f"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    """比较候选笔记与库内永久笔记。"""
    if json_output:
        output_format = "json"
    if output_format not in {"table", "json"}:
        _fail("format must be table or json", output_format)
    if (content_file is None) == (content is None):
        _fail("exactly one of --content-file / --content is required", output_format)
    if not 0 <= pass_below < gray_below <= 100:
        _fail("require 0 <= pass-below < gray-below <= 100", output_format)

    if content_file is not None:
        try:
            text = content_file.read_text(encoding="utf-8")
        except OSError as exc:
            _fail(f"cannot read content file: {exc}", output_format)
    else:
        text = content or ""

    try:
        with use_kb(kb):
            cfg = _current_config()
            from .similarity import check_candidate

            payload = check_candidate(
                cfg,
                title or "",
                text,
                exclude_id=exclude_id,
                top=top,
                pass_below=pass_below,
                gray_below=gray_below,
                refresh=refresh,
            )
    except Exception as exc:
        _fail(str(exc), output_format)

    if output_format == "json":
        _json_console.print(json.dumps(payload, ensure_ascii=False, indent=2), soft_wrap=True)
        return

    _console.print(f"Verdict: {payload['verdict']}")
    if payload.get("unavailable_reason"):
        _console.print(f"Reason: {payload['unavailable_reason']}")
    for match in payload["matches"]:
        _console.print(
            f"- {match['score']:.3f} ({match['percentile']:.1f}%) "
            f"{match['title']} ({match['id']})"
        )
    for warning in payload.get("warnings", []):
        _console.print(f"Warning: {warning}")
```

在 `jfox/cli.py` 的 MOC 注册之后加：

```python
# Similarity 子命令组（S2 判重基线，延迟加载重依赖）
from .similarity_cli import similarity_app  # noqa: E402

app.add_typer(similarity_app, name="similarity", help="查看相似度基线并判定候选笔记")
```

- [ ] **Step 4: 运行测试确认通过**

Run:
```bash
uv run pytest tests/integration/test_similarity_cli.py -v
time uv run python -c "import jfox.cli"
```
Expected: 7 passed；import 时间仍 < 1s（无 ChromaDB/模型加载）

- [ ] **Step 5: 提交**

```bash
git add jfox/similarity_cli.py jfox/cli.py tests/integration/test_similarity_cli.py
git commit -m "feat(cli): add similarity stats and check commands (#586)"
```

---

### Task 6: 生成文档与英文描述

**Files:**
- Modify: `docs/cli-descriptions.yaml`
- Modify: `docs/cli-reference.md`（生成物）
- Test: 命令级校验（A11）

**Interfaces:**
- Consumes: Task 5 注册的三个命令路径。
- Produces: `docs/cli-reference.md` 含 `jfox similarity` / `stats` / `check`。

- [ ] **Step 1: 加三条英文描述**

在 `docs/cli-descriptions.yaml` 的 `commands:` 下（按现有字母序插入 `jfox similarity` 附近）加：

```yaml
  "jfox similarity":
    description: "Inspect similarity baselines and judge candidate notes against the library."
  "jfox similarity stats":
    description: "Show the nearest-neighbor similarity distribution for permanent notes."
  "jfox similarity check":
    description: "Compare a candidate note against the library and report a percentile verdict."
```

- [ ] **Step 2: 先跑生成器确认当前命令集合**

Run: `uv run python scripts/generate_docs.py`
Expected: 成功；`git diff --stat` 只显示 `docs/cli-reference.md`（若描述缺失会在这里报 `Missing English CLI descriptions`）

- [ ] **Step 3: 运行漂移校验**

Run:
```bash
uv run python scripts/generate_docs.py
git diff --exit-code -- docs/cli-reference.md docs/plugin-inventory.md
```
Expected: diff 为空（第二次生成幂等）

- [ ] **Step 4: 提交**

```bash
git add docs/cli-descriptions.yaml docs/cli-reference.md
git commit -m "docs(cli): document similarity stats and check (#586)"
```

---

### Task 7: 三平台闸门与命令参考

**Files:**
- Modify: `skills-recommend/pi/jfox-session-to-permanent/SKILL.md`
- Modify: `packages/cc-plugin/skills/session-to-permanent/SKILL.md`
- Modify: `packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md`
- Modify: `skills-recommend/pi/jfox-common/SKILL.md`
- Modify: `packages/cc-plugin/skills/manage/SKILL.md`
- Modify: `packages/kimi-plugin/skills/jfox-manage/SKILL.md`
- Test: `tests/unit/test_session_dedup_skill_docs.py`

**Interfaces:**
- Consumes: `jfox similarity check --title <t> --content-file <f> --json` 的输出契约（`verdict` / `percentile` / `unavailable_reason`）。
- Produces: 三平台文本语义一致；三份命令参考含新命令。

- [ ] **Step 1: 写失败测试**

```python
"""Static contracts for the S2 dedup gate docs across three platforms."""

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[2]
SESSION_SKILLS = [
    REPO_ROOT / "skills-recommend/pi/jfox-session-to-permanent/SKILL.md",
    REPO_ROOT / "packages/cc-plugin/skills/session-to-permanent/SKILL.md",
    REPO_ROOT / "packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md",
]
COMMAND_REFS = [
    REPO_ROOT / "skills-recommend/pi/jfox-common/SKILL.md",
    REPO_ROOT / "packages/cc-plugin/skills/manage/SKILL.md",
    REPO_ROOT / "packages/kimi-plugin/skills/jfox-manage/SKILL.md",
]


def test_platform_docs_use_similarity_gate():
    for path in SESSION_SKILLS:
        text = path.read_text(encoding="utf-8")
        assert "jfox similarity check" in text
        assert "verdict=new" in text or "`verdict=new`" in text
        assert "unavailable" in text
        assert "0.5–0.65" not in text
        assert text.count("--mode semantic") == 0


def test_s2_recheck_is_pinned_to_similarity_gate():
    for path in SESSION_SKILLS:
        text = path.read_text(encoding="utf-8")
        assert "落库前重跑一次 `jfox similarity check`" in text


def test_command_references_list_similarity():
    for path in COMMAND_REFS:
        text = path.read_text(encoding="utf-8")
        assert "jfox similarity stats" in text
        assert "jfox similarity check" in text
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_session_dedup_skill_docs.py -v`
Expected: FAIL（三份 SKILL.md 仍含 `--mode semantic` / `0.5–0.65`）

- [ ] **Step 3: 改三份 S2② 行**

把三份文件里 `| S2 去重余量 | ... |` 整行替换为（平台措辞可微调，语义必须一致）：

```markdown
| S2 去重余量 | ① `jfox search --type permanent` 无「已覆盖」命中；② 追加 `jfox similarity check --title "<草稿标题>" --content-file <草稿正文文件> --json`：`verdict=new` 通过；`gray` 灰色区降人工；`covered` 降人工并按「可补充/已覆盖」走原流程；`unavailable` / 命令不存在 / 无 verdict 字段 / 非零退出 = 信号缺失 → 降人工（fail-closed，不得退回 0.5/0.65）；分位阈值由 `jfox similarity stats` 暴露，初始 50/90，dogfood 校准；③ 补查 `jfox search --type candidate` 无同主题 pending；④ 落库前重跑一次 `jfox similarity check`（防并行会话窗口，基线有缓存） | 灰色区/异常降人工 |
```

- [ ] **Step 4: 改三份 Step 5 自动档代码块**

把：

```bash
# 落库前重跑一次 search 复核去重结论（S2④，防并行会话窗口）
jfox search "<草稿一句话摘要>" --mode semantic --json
```

替换为：

```bash
# 落库前重跑一次 similarity check 复核去重结论（S2④，防并行会话窗口）
jfox similarity check --title "<标题>" --content-file /tmp/note-draft.md --json
```

三份文件都要改（pi 行号约 282，cc/kimi 约 292）。

- [ ] **Step 5: 三份命令参考各加一行**

在每份命令参考的对应小节加：

```markdown
- `jfox similarity stats --json` — 查看本库最近邻相似度分位（p50/p75/p90/p95/p99）。
- `jfox similarity check --title "<标题>" --content-file <草稿> --json` — 候选去重判定：`new` / `gray` / `covered` / `unavailable`。
```

- [ ] **Step 6: 运行测试与 lint**

Run:
```bash
uv run pytest tests/unit/test_session_dedup_skill_docs.py tests/unit/test_moc_skill_docs.py -v
npx --yes markdownlint-cli2 skills-recommend/pi/jfox-session-to-permanent/SKILL.md packages/cc-plugin/skills/session-to-permanent/SKILL.md packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md skills-recommend/pi/jfox-common/SKILL.md packages/cc-plugin/skills/manage/SKILL.md packages/kimi-plugin/skills/jfox-manage/SKILL.md
```
Expected: pytest 全绿；markdownlint 0 issues

- [ ] **Step 7: 提交**

```bash
git add skills-recommend/pi/jfox-session-to-permanent/SKILL.md \
  packages/cc-plugin/skills/session-to-permanent/SKILL.md \
  packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md \
  skills-recommend/pi/jfox-common/SKILL.md \
  packages/cc-plugin/skills/manage/SKILL.md \
  packages/kimi-plugin/skills/jfox-manage/SKILL.md \
  tests/unit/test_session_dedup_skill_docs.py
git commit -m "docs(skill): switch S2 dedup gate to similarity check (#586)"
```

---

### Task 8: 全量验收与性能护栏

**Files:**
- Create: `tests/performance/test_similarity_perf.py`
- Test: 全量 A1–A11

**Interfaces:**
- Consumes: Task 1–7 全部。
- Produces: A10 性能护栏；验收记录。

- [ ] **Step 1: 写性能测试**

```python
"""Performance guard for the chunked nearest-neighbor helper."""

import time

import numpy as np
import pytest

from jfox.similarity import nearest_neighbor_scores

pytestmark = [pytest.mark.performance, pytest.mark.slow]


def test_large_matrix_is_chunked_and_bounded():
    matrix = np.random.default_rng(42).random((5000, 512), dtype=np.float32)
    started = time.perf_counter()
    scores = nearest_neighbor_scores(matrix, chunk_size=512)
    elapsed = time.perf_counter() - started
    assert scores.shape == (5000,)
    assert np.all(scores >= 0.0)
    assert elapsed < 10.0
```

- [ ] **Step 2: 跑 task 级测试**

```bash
uv run pytest tests/unit/test_similarity.py tests/integration/test_similarity_cli.py tests/unit/test_session_dedup_skill_docs.py -v
```
Expected: 全绿。

- [ ] **Step 3: 跑 Fast 回归（非 embedding / 非 slow）**

```bash
uv run pytest tests/ -m "not embedding and not slow" -q
```
Expected: 全绿；若出现既有 flaky，记录并在重跑后确认。

- [ ] **Step 4: 静态检查**

```bash
uv run ruff check jfox/similarity.py jfox/similarity_cli.py tests/unit/test_similarity.py tests/integration/test_similarity_cli.py
uv run black --check jfox/similarity.py jfox/similarity_cli.py tests/unit/test_similarity.py tests/integration/test_similarity_cli.py
uv run python scripts/generate_docs.py
git diff --exit-code -- docs/cli-reference.md docs/plugin-inventory.md
```
Expected: ruff/black 通过；生成文档 diff 为空。

- [ ] **Step 5: 跑性能测试（本机，单独）**

```bash
uv run pytest tests/performance/test_similarity_perf.py -v
```
Expected: PASS（本机 < 10s；CI Fast 不跑，因带 `slow` 标记）。

- [ ] **Step 6: 提交**

```bash
git add tests/performance/test_similarity_perf.py
git commit -m "test(similarity): guard chunked baseline performance (#586)"
```

---

## Self-Review

**1. Spec coverage**

| Spec 章节 | 任务 |
|---|---|
| §4.1 序列化 | Task 1（`serialize_document`）+ A2 测试 |
| §4.2 基线过滤/统计/抽样 | Task 2（过滤）+ Task 3（统计/抽样）+ A3 |
| §4.3 `stats` | Task 5 + A5 |
| §4.4 `check` | Task 4 + Task 5 + A6 |
| §4.5 判定策略 | Task 1（`classify_verdict`）+ A1 |
| §4.6 缓存/失效 | Task 3 + A4 |
| §4.7 三平台集成 | Task 7 + A7 |
| §5 数据流 | Task 4/5/7 |
| §6 降级路径 | Task 4（unavailable）+ Task 5（错误映射）+ U2 |
| §7 A1–A11 | Task 1–8；A9/A11 在 Task 6/8 |
| §8 可测性拆分 | Task 1–5 的测试分层 |
| §9 部署前提 | Task 7 文本 + U3（用户在合并后执行） |
| §10 风险 | Review Focus + 降级测试 |
| §12 #585 同步 | 本计划不改 #585 模板；spec §12 已留硬约束 |

**2. Placeholder scan**: 无 TBD/TODO；每个代码步骤有实际代码；命令有明确预期。

**3. Type consistency**: `Baseline` 字段、`LiveRecords` 字段、`check_candidate` 参数在各 task 中一致；CLI 调用的函数名与 Task 1–4 的 Produces 一致。

**4. Review Focus**: 五个失败模式分别在 Task 3（缓存损坏/过期）、Task 4（空库/daemon/维度/标题）、Task 5（内容源/错误映射）有测试；U1/U2/U3 覆盖真实运行与降级。

## Execution Handoff

计划已保存到 `docs/superpowers/plans/2026-10-21-s2-dedup-calibration.md`。按 `subagent-driven-development` 执行：每个 task 派 fresh implementer，task 级 reviewer 审核后再进下一个；最后做一次全分支 review。
