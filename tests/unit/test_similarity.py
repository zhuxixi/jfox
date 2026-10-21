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
