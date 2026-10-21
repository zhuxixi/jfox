"""Similarity baseline and candidate dedup judgment for the S2 gate.

Pure functions live at the top of the module; the I/O layer (Chroma snapshot,
note index, embedding daemon) lives below and is imported lazily so importing
this module never loads a model or ChromaDB.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Mapping, Optional, Sequence

import numpy as np

from .config import ZKConfig
from .models import NoteType
from .note_index import NoteMeta


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
        return LiveRecords(
            ids=[], titles=[], matrix=np.empty((0, matrix.shape[1]), dtype=np.float32)
        )
    return LiveRecords(
        ids=[record[0] for record in records],
        titles=[record[1] for record in records],
        matrix=np.asarray([record[2] for record in records], dtype=np.float32),
    )


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
