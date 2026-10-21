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


def nearest_neighbor_scores(matrix: np.ndarray, chunk_size: int = DEFAULT_CHUNK_SIZE) -> np.ndarray:
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


def quantiles(values: Sequence[float], ps: Sequence[float] = QUANTILE_POINTS) -> Dict[str, float]:
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


def classify_verdict(percentile: float, pass_below: int = 50, gray_below: int = 90) -> str:
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
