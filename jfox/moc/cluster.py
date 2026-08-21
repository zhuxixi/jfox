"""Pure helpers and result models for MOC density diagnostics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence

import networkx as nx
import numpy as np

from ..bm25_index import BM25Index
from ..config import ZKConfig
from ..graph import KnowledgeGraph
from ..models import NoteType
from ..note_index import get_note_index
from ..vector_store import VectorStore


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
class SuggestedReport:
    """Detailed clusters selected at the suggested threshold."""

    threshold: float
    clusters: List[ClusterSummary] = field(default_factory=list)


@dataclass
class MocDiagnoseReport:
    """Complete report returned by the MOC density diagnostic service."""

    coverage: CoverageReport
    threshold_sweep: List[ThresholdSummary] = field(default_factory=list)
    suggest: Optional[SuggestedReport] = None
    orphans: OrphanSummary = field(default_factory=OrphanSummary)
    warnings: List[str] = field(default_factory=list)


class MocDiagnoseError(RuntimeError):
    """Raised when the permanent-note vector data cannot be diagnosed."""


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


def _mean_similarity(similarity: np.ndarray, indices: Sequence[int], index: int) -> float:
    """Return a member's mean similarity to the other members of its cluster."""
    peers = [peer for peer in indices if peer != index]
    if not peers:
        return 0.0
    return float(np.mean(similarity[index, peers]))


def _cluster_members(
    cluster: Sequence[int],
    ids: Sequence[str],
    titles: Sequence[str],
    similarity: np.ndarray,
    link_degrees: Dict[str, int],
    graph_available: bool,
) -> ClusterSummary:
    """Build a detailed cluster and choose its hub deterministically."""
    members = [
        ClusterMember(
            id=ids[index],
            title=titles[index],
            link_degree=link_degrees.get(ids[index], 0),
            mean_similarity=_mean_similarity(similarity, cluster, index),
        )
        for index in cluster
    ]
    if graph_available:
        hub = max(members, key=lambda member: (member.link_degree, -len(member.title), member.id))
    else:
        hub = max(members, key=lambda member: (member.mean_similarity, member.id))
    return ClusterSummary(size=len(members), members=members, hub=hub)


def diagnose_moc_density(
    config: ZKConfig,
    thresholds: Sequence[float],
    min_size: int,
    suggest_threshold: float,
    top: int,
) -> MocDiagnoseReport:
    """Diagnose semantic density among live permanent notes.

    This function only reads note metadata, indexes, and stored embeddings. It
    never calls the embedding backend and never mutates any index or note.
    """
    if min_size < 2:
        raise ValueError("min_size must be at least 2")
    if top < 1:
        raise ValueError("top must be at least 1")

    note_index = get_note_index(config)
    live_meta = {
        meta.id: meta
        for meta in note_index.get_all_meta()
        if meta.type == NoteType.PERMANENT and not meta.archived
    }
    coverage = CoverageReport(filesystem=len(live_meta))

    vector_store = VectorStore(persist_directory=config.chroma_dir)
    vector_ids, vector_metadata, raw_embeddings = vector_store.get_all_embeddings("permanent")
    coverage.vector = len(vector_ids)

    live_ids: List[str] = []
    live_titles: List[str] = []
    live_embeddings: List[np.ndarray] = []
    seen_live_ids = set()
    orphan_count = 0
    for index, note_id in enumerate(vector_ids):
        if note_id not in live_meta or note_id in seen_live_ids:
            orphan_count += 1
            continue
        seen_live_ids.add(note_id)
        live_ids.append(note_id)
        metadata = vector_metadata[index] if index < len(vector_metadata) else {}
        live_titles.append(str(metadata.get("title") or live_meta[note_id].title))
        live_embeddings.append(raw_embeddings[index])
    coverage.vector_orphans = orphan_count

    if not live_embeddings:
        raise MocDiagnoseError(
            "No live permanent-note embeddings found; run `jfox index rebuild` first"
        )

    embeddings = np.asarray(live_embeddings, dtype=np.float32)
    similarity = compute_similarity(embeddings)

    bm25_index = BM25Index(index_dir=config.zk_dir)
    bm25_count = sum(1 for note_type in bm25_index.doc_types if note_type == NoteType.PERMANENT.value)
    coverage.bm25 = bm25_count
    coverage.bm25_coverage_ratio = (
        bm25_count / coverage.filesystem if coverage.filesystem else None
    )
    if coverage.bm25_coverage_ratio is not None and coverage.bm25_coverage_ratio < 0.9:
        coverage.warnings.append(
            f"BM25 permanent coverage {coverage.bm25_coverage_ratio:.0%} < 90%"
        )
    if coverage.vector_orphans:
        coverage.warnings.append(f"Vector index contains {coverage.vector_orphans} permanent orphan(s)")

    threshold_sweep = [
        build_threshold_summary(similarity, threshold, min_size) for threshold in thresholds
    ]
    matching = [
        summary
        for summary in threshold_sweep
        if np.isclose(summary.threshold, suggest_threshold, atol=1e-9)
    ]
    if not matching:
        raise ValueError("suggest_threshold must be included in thresholds")
    suggested_summary = matching[0]

    graph_available = False
    link_degrees: Dict[str, int] = {}
    warnings = list(coverage.warnings)
    try:
        knowledge_graph = KnowledgeGraph(config).build()
        graph_available = True
        link_degrees = {
            note_id: knowledge_graph.graph.in_degree(note_id)
            + knowledge_graph.graph.out_degree(note_id)
            for note_id in live_ids
        }
    except Exception as exc:
        warnings.append(f"Knowledge graph unavailable: {exc}")

    detailed_clusters = [
        _cluster_members(
            cluster,
            live_ids,
            live_titles,
            similarity,
            link_degrees,
            graph_available,
        )
        for cluster in suggested_summary.clusters
    ]
    detailed_clusters.sort(
        key=lambda cluster: (
            -cluster.size,
            cluster.hub.title if cluster.hub else "",
            cluster.hub.id if cluster.hub else "",
        )
    )
    suggested = SuggestedReport(
        threshold=suggested_summary.threshold,
        clusters=detailed_clusters[:top],
    )

    semantic_orphans = set(semantic_orphan_indices(len(live_ids), suggested_summary.clusters))
    graph_orphans = {
        index for index, note_id in enumerate(live_ids) if graph_available and link_degrees[note_id] == 0
    }
    orphan_indices = sorted(semantic_orphans | graph_orphans)
    orphan_notes = [
        ClusterMember(
            id=live_ids[index],
            title=live_titles[index],
            link_degree=link_degrees.get(live_ids[index], 0),
            mean_similarity=0.0,
        )
        for index in orphan_indices
    ]

    return MocDiagnoseReport(
        coverage=coverage,
        threshold_sweep=threshold_sweep,
        suggest=suggested,
        orphans=OrphanSummary(count=len(orphan_notes), notes=orphan_notes),
        warnings=warnings,
    )
