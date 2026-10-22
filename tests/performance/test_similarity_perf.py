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
