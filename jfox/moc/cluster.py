"""Pure helpers and result models for MOC density diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional, Sequence

import networkx as nx
import numpy as np


@dataclass
class ClusterMember:
    """A note participating in a semantic cluster."""

    id: str
    title: str
    link_degree: int = 0
    mean_similarity: float = 0.0


@dataclass
class ClusterSummary:
    """A suggested MOC cluster and its representative member."""

    size: int
    members: List[ClusterMember] = field(default_factory=list)
    hub: Optional[ClusterMember] = None


@dataclass
class ThresholdSummary:
    """Cluster distribution at one similarity threshold."""

    threshold: float
    cluster_count: int
    max_cluster_size: int
    orphan_count: int
    clusters: List[List[int]] = field(default_factory=list)


@dataclass
class CoverageReport:
    """Permanent-note counts across the filesystem and indexes."""

    filesystem: int = 0
    vector: int = 0
    vector_orphans: int = 0
    bm25: int = 0
    bm25_coverage_ratio: Optional[float] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class OrphanSummary:
    """Notes that are not connected semantically or by explicit links."""

    count: int = 0
    notes: List[ClusterMember] = field(default_factory=list)


@dataclass
class MocDiagnoseReport:
    """Complete report returned by the MOC density diagnostic service."""

    coverage: CoverageReport
    threshold_sweep: List[ThresholdSummary] = field(default_factory=list)
    suggest: Optional[ThresholdSummary] = None
    orphans: OrphanSummary = field(default_factory=OrphanSummary)
    warnings: List[str] = field(default_factory=list)


def compute_similarity(embeddings: np.ndarray) -> np.ndarray:
    """Compute a cosine-similarity matrix for stored embedding rows.

    Rows with zero norm remain zero instead of producing NaN values.  The
    diagonal is cleared because a note is not its own semantic neighbour.
    """
    matrix = np.asarray(embeddings, dtype=np.float32)
    if matrix.ndim != 2:
        raise ValueError("embeddings must be a two-dimensional matrix")
    if matrix.shape[0] == 0:
        return np.empty((0, 0), dtype=np.float32)

    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    normalized = np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms != 0)
    similarity = normalized @ normalized.T
    np.fill_diagonal(similarity, 0.0)
    return similarity


def find_clusters_at_threshold(
    similarity: np.ndarray, threshold: float, min_size: int
) -> List[List[int]]:
    """Find connected semantic clusters using a strict similarity threshold.

    Similarity edges are created only when ``similarity > threshold``.  A
    connected component is reported only when it has at least ``min_size``
    members; singleton components therefore become semantic orphans.
    """
    if min_size < 2:
        raise ValueError("min_size must be at least 2")

    matrix = np.asarray(similarity)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise ValueError("similarity must be a square matrix")

    graph = nx.Graph()
    graph.add_nodes_from(range(matrix.shape[0]))
    rows, columns = np.where(np.triu(matrix > threshold, k=1))
    graph.add_edges_from(zip(rows.tolist(), columns.tolist()))

    clusters = [sorted(component) for component in nx.connected_components(graph)]
    clusters = [component for component in clusters if len(component) >= min_size]
    return sorted(clusters, key=lambda component: (-len(component), component[0]))


def semantic_orphan_indices(node_count: int, clusters: Sequence[Sequence[int]]) -> List[int]:
    """Return sorted node indices absent from all qualifying clusters."""
    if node_count < 0:
        raise ValueError("node_count must not be negative")

    clustered = {index for cluster in clusters for index in cluster}
    return [index for index in range(node_count) if index not in clustered]


def build_threshold_summary(
    similarity: np.ndarray, threshold: float, min_size: int
) -> ThresholdSummary:
    """Build the compact distribution summary for one threshold."""
    matrix = np.asarray(similarity)
    if matrix.ndim != 2 or matrix.shape[0] != matrix.shape[1]:
        raise ValueError("similarity must be a square matrix")

    clusters = find_clusters_at_threshold(matrix, threshold, min_size)
    orphan_count = len(semantic_orphan_indices(matrix.shape[0], clusters))
    return ThresholdSummary(
        threshold=float(threshold),
        cluster_count=len(clusters),
        max_cluster_size=max((len(cluster) for cluster in clusters), default=0),
        orphan_count=orphan_count,
        clusters=clusters,
    )
