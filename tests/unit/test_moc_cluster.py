"""Tests for pure semantic clustering helpers."""

import numpy as np
import pytest
from jfox.moc.cluster import (
    build_threshold_summary,
    compute_similarity,
    find_clusters_at_threshold,
    semantic_orphan_indices,
)

VECTORS = np.array(
    [
        [1.0, 0.0, 0.0],
        [0.99, 0.01, 0.0],
        [0.0, 1.0, 0.0],
        [0.01, 0.99, 0.0],
        [0.0, 0.0, 1.0],
    ],
    dtype=np.float32,
)


def test_compute_similarity_normalizes_rows_and_zeros_diagonal():
    similarity = compute_similarity(VECTORS)

    assert similarity.shape == (5, 5)
    np.testing.assert_allclose(np.diag(similarity), 0.0)
    assert similarity[0, 1] > 0.99
    assert similarity[0, 2] < 0.1


def test_find_clusters_returns_two_pairs_and_one_semantic_orphan():
    similarity = compute_similarity(VECTORS)

    clusters = find_clusters_at_threshold(similarity, threshold=0.9, min_size=2)

    assert clusters == [[0, 1], [2, 3]]
    assert semantic_orphan_indices(5, clusters) == [4]


def test_clusters_are_sorted_by_size_then_first_member():
    similarity = compute_similarity(
        np.array(
            [
                [1.0, 0.0],
                [0.99, 0.01],
                [0.98, 0.02],
                [0.0, 1.0],
                [0.01, 0.99],
            ],
            dtype=np.float32,
        )
    )

    assert find_clusters_at_threshold(similarity, threshold=0.9, min_size=2) == [
        [0, 1, 2],
        [3, 4],
    ]


def test_compute_similarity_empty_matrix():
    similarity = compute_similarity(np.empty((0, 0), dtype=np.float32))

    assert similarity.shape == (0, 0)
    assert similarity.dtype == np.float32


def test_compute_similarity_zero_vector_is_finite():
    similarity = compute_similarity(np.array([[0.0, 0.0], [1.0, 0.0]], dtype=np.float32))

    assert np.isfinite(similarity).all()
    np.testing.assert_allclose(similarity, np.zeros((2, 2), dtype=np.float32))


def test_compute_similarity_rejects_non_matrix_input():
    with pytest.raises(ValueError, match="two-dimensional"):
        compute_similarity(np.array([1.0, 0.0], dtype=np.float32))


def test_find_clusters_rejects_invalid_inputs():
    with pytest.raises(ValueError, match="at least 2"):
        find_clusters_at_threshold(np.eye(2), threshold=0.5, min_size=1)

    with pytest.raises(ValueError, match="square"):
        find_clusters_at_threshold(np.zeros((2, 3)), threshold=0.5, min_size=2)


def test_find_clusters_all_unrelated_returns_no_clusters():
    similarity = np.zeros((3, 3), dtype=np.float32)

    assert find_clusters_at_threshold(similarity, threshold=0.5, min_size=2) == []
    assert semantic_orphan_indices(3, []) == [0, 1, 2]


def test_find_clusters_all_similar_returns_one_cluster():
    similarity = np.full((3, 3), 0.9, dtype=np.float32)
    np.fill_diagonal(similarity, 0.0)

    assert find_clusters_at_threshold(similarity, threshold=0.5, min_size=2) == [[0, 1, 2]]


def test_build_threshold_summary_reports_cluster_and_orphan_counts():
    similarity = compute_similarity(VECTORS)

    summary = build_threshold_summary(similarity, threshold=0.9, min_size=2)

    assert summary.threshold == 0.9
    assert summary.cluster_count == 2
    assert summary.max_cluster_size == 2
    assert summary.orphan_count == 1
    assert summary.clusters == [[0, 1], [2, 3]]
