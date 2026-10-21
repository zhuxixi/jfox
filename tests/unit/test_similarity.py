"""纯相似度函数的单元测试（不读盘、不加载模型）。"""

import json
from datetime import datetime

import numpy as np
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.config import ZKConfig
from jfox.models import NoteType
from jfox.note_index import NoteMeta
from jfox.similarity import (
    MIN_BASELINE_NOTES,
    Baseline,
    SimilarityError,
    baseline_is_usable,
    classify_vector_id,
    classify_verdict,
    compute_baseline,
    filter_live_records,
    load_cached_baseline,
    nearest_neighbor_scores,
    percentile_rank,
    quantiles,
    save_cached_baseline,
    serialize_document,
    stats_path,
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


def _meta(note_id: str, title: str, *, archived: bool = False) -> NoteMeta:
    return NoteMeta(
        id=note_id,
        title=title,
        type=NoteType.PERMANENT,
        archived=archived,
    )


def test_classify_stored_id_three_way():
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
    stats_path(cfg).write_text(json.dumps({"version": 1}), encoding="utf-8")
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


def test_baseline_cache_null_quantiles_is_ignored(tmp_path):
    cfg = _cfg(tmp_path)
    stats_path(cfg).write_text(
        json.dumps(
            {
                "version": 1,
                "model": "stub",
                "dimension": 3,
                "note_count": 3,
                "sampled": False,
                "quantiles": None,
                "nn_values": [],
                "index_rebuilt_at": "2026-10-21T00:00:00",
                "computed_at": "2026-10-21T00:00:00",
            }
        ),
        encoding="utf-8",
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


def test_compute_baseline_samples_above_sampling_cap(tmp_path, monkeypatch):
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


from jfox.similarity import check_candidate


class _StubBackend:
    def __init__(self, unit_vector):
        self.unit_vector = np.asarray(unit_vector, dtype=np.float32)

    def encode_single(self, text, *, daemon_only=False):
        assert daemon_only is True
        return self.unit_vector


def _check_baseline():
    return _baseline(
        note_count=6,
        quantiles={"p50": 0.6, "p75": 0.7, "p90": 0.8, "p95": 0.9, "p99": 0.95},
        nn_values=np.array([0.5, 0.6, 0.7, 0.8, 0.9, 0.95], dtype=np.float32),
    )


def _check_records():
    return _records(np.eye(3, dtype=np.float32))


@pytest.mark.parametrize(
    ("unit_vector", "expected"),
    [
        # Negative second component keeps n0 top-1 while its cosine is 0.4 (p0 -> new).
        ([0.4, -0.916, 0.0], "new"),
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
