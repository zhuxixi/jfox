"""MOC 密度诊断的纯逻辑辅助函数与结果模型。"""

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
from ..vector_store import VectorStore, VectorStoreReadError
from . import MocDiagnoseError

# 当前算法会构造 N×N 稠密矩阵，限制规模以避免内存无界增长。
MAX_DENSE_CLUSTER_NOTES = 5000


@dataclass
class ClusterMember:
    """参与语义聚类的笔记。"""

    id: str
    title: str
    link_degree: int = 0
    mean_similarity: float = 0.0


@dataclass
class ClusterSummary:
    """建议建立 MOC 的聚类及其代表成员。"""

    size: int
    members: List[ClusterMember] = field(default_factory=list)
    hub: Optional[ClusterMember] = None


@dataclass
class ThresholdSummary:
    """单个相似度阈值下的聚类分布。"""

    threshold: float
    cluster_count: int
    max_cluster_size: int
    orphan_count: int
    clusters: List[List[int]] = field(default_factory=list)


@dataclass
class CoverageReport:
    """文件系统及各索引中的永久笔记数量。"""

    filesystem: Optional[int] = 0
    vector: Optional[int] = 0
    vector_orphans: int = 0
    bm25: Optional[int] = 0
    bm25_coverage_ratio: Optional[float] = None
    warnings: List[str] = field(default_factory=list)


@dataclass
class OrphanNote:
    """带有明确孤立来源标记的活跃永久笔记。"""

    id: str
    title: str
    link_orphan: bool
    semantic_orphan: bool
    link_degree: int = 0
    mean_similarity: float = 0.0


@dataclass
class OrphanSummary:
    """在语义或显式链接上未形成连接的笔记。"""

    count: int = 0
    notes: List[OrphanNote] = field(default_factory=list)


@dataclass
class SuggestedReport:
    """建议阈值下选出的聚类详情。"""

    threshold: float
    clusters: List[ClusterSummary] = field(default_factory=list)


@dataclass
class MocDiagnoseReport:
    """MOC 密度诊断服务返回的完整报告。"""

    coverage: CoverageReport
    threshold_sweep: List[ThresholdSummary] = field(default_factory=list)
    suggest: Optional[SuggestedReport] = None
    orphans: OrphanSummary = field(default_factory=OrphanSummary)
    warnings: List[str] = field(default_factory=list)


def compute_similarity(embeddings: np.ndarray) -> np.ndarray:
    """计算已存向量行的余弦相似度矩阵。

    零范数行保持为零，避免产生 NaN；对角线清零，因为笔记不应成为自己的语义邻居。
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
    """用严格相似度阈值查找相连的语义聚类。

    仅当 ``similarity > threshold`` 时建立边。连通分量成员数至少达到
    ``min_size`` 才会报告，因此单节点分量会成为语义孤立点。
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
    """返回未出现在任何合格聚类中的已排序节点索引。"""
    if node_count < 0:
        raise ValueError("node_count must not be negative")

    clustered = {index for cluster in clusters for index in cluster}
    return [index for index in range(node_count) if index not in clustered]


def build_threshold_summary(
    similarity: np.ndarray, threshold: float, min_size: int
) -> ThresholdSummary:
    """构建单个阈值的精简分布摘要。"""
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
    """返回成员与同簇其他成员的平均相似度。"""
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
    """构建聚类详情并以确定性规则选择中心笔记。"""
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
    """诊断活跃永久笔记之间的语义密度。

    此函数只读取笔记元数据、索引和已存向量，不调用向量后端，也不修改索引或笔记。
    """
    if min_size < 2:
        raise ValueError("min_size must be at least 2")
    if top < 1:
        raise ValueError("top must be at least 1")

    warnings: List[str] = []
    try:
        note_index = get_note_index(config)
        live_meta = {
            meta.id: meta
            for meta in note_index.get_all_meta()
            if meta.type == NoteType.PERMANENT and not meta.archived
        }
        filesystem_count: Optional[int] = len(live_meta)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        live_meta = {}
        filesystem_count = None
        warnings.append(f"Filesystem coverage unavailable: {exc}")

    coverage = CoverageReport(filesystem=filesystem_count, warnings=[])

    vector_store = VectorStore(persist_directory=config.chroma_dir)
    try:
        vector_ids, vector_metadata, raw_embeddings = vector_store.get_all_embeddings("permanent")
    except VectorStoreReadError as exc:
        raise MocDiagnoseError(str(exc)) from exc
    if len(vector_ids) != len(vector_metadata):
        raise MocDiagnoseError(
            f"Corrupt permanent vector data: ids={len(vector_ids)}, metadata={len(vector_metadata)}"
        )
    if raw_embeddings.ndim != 2 or raw_embeddings.shape[0] != len(vector_ids):
        raise MocDiagnoseError(
            f"Corrupt permanent vector data: ids={len(vector_ids)}, "
            f"embeddings_shape={raw_embeddings.shape}"
        )
    coverage.vector = len(vector_ids)
    if not vector_ids:
        raise MocDiagnoseError("No permanent-note embeddings found; run `jfox index rebuild` first")

    records = []
    seen_live_ids = set()
    orphan_count = 0
    if filesystem_count is None:
        warnings.append("Permanent scope unavailable; semantic clustering was skipped")
        warnings.append(
            f"Vector index contains {len(vector_ids)} permanent row(s); orphan verification skipped"
        )
    else:
        for index, note_id in enumerate(vector_ids):
            metadata = vector_metadata[index]
            if metadata is None:
                metadata = {}
            elif not isinstance(metadata, dict):
                raise MocDiagnoseError(
                    f"Corrupt permanent vector metadata for {note_id}: expected an object"
                )
            if note_id not in live_meta or note_id in seen_live_ids:
                orphan_count += 1
                continue
            seen_live_ids.add(note_id)
            records.append((note_id, live_meta[note_id].title, raw_embeddings[index]))
    records.sort(key=lambda record: record[0])
    live_ids = [record[0] for record in records]
    live_titles = [record[1] for record in records]
    title_by_id = {note_id: meta.title for note_id, meta in live_meta.items()}
    live_embeddings = [record[2] for record in records]
    coverage.vector_orphans = orphan_count

    live_note_count = len(live_embeddings)
    if live_note_count > MAX_DENSE_CLUSTER_NOTES:
        raise MocDiagnoseError(
            f"当前稠密聚类算法最多支持 {MAX_DENSE_CLUSTER_NOTES} 条活跃永久笔记，"
            f"本次共有 {live_note_count} 条；未生成不完整建议。"
            "未来需改用稀疏图或分块算法，请缩小知识库范围后重试。"
        )

    embeddings = np.asarray(live_embeddings, dtype=np.float32).reshape(
        (len(live_embeddings), raw_embeddings.shape[1])
    )
    similarity = compute_similarity(embeddings)

    if filesystem_count is None:
        coverage.bm25 = None
        coverage.bm25_coverage_ratio = None
        warnings.append("BM25 coverage unavailable: permanent scope unavailable")
    else:
        try:
            bm25_index = BM25Index(index_dir=config.zk_dir)
            load_status = getattr(bm25_index, "load_status", "loaded")
            load_error = getattr(bm25_index, "load_error", None)
            if load_status in {"missing", "invalid"}:
                raise OSError(load_error or f"BM25 index load status is {load_status}")
            if getattr(bm25_index, "needs_rebuild", False) is True:
                raise OSError("BM25 index needs rebuild")
            bm25_ids = list(bm25_index.doc_ids)
            bm25_types = list(bm25_index.doc_types)
            if len(bm25_ids) != len(bm25_types):
                raise ValueError("BM25 document IDs and types have different lengths")
            live_bm25_ids = {
                note_id
                for note_id, note_type in zip(bm25_ids, bm25_types)
                if note_type == NoteType.PERMANENT.value and note_id in live_meta
            }
            coverage.bm25 = len(live_bm25_ids)
            coverage.bm25_coverage_ratio = (
                coverage.bm25 / coverage.filesystem if coverage.filesystem else None
            )
            if coverage.bm25_coverage_ratio is not None and coverage.bm25_coverage_ratio < 0.9:
                warnings.append(f"BM25 permanent coverage {coverage.bm25_coverage_ratio:.0%} < 90%")
        except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
            coverage.bm25 = None
            coverage.bm25_coverage_ratio = None
            warnings.append(f"BM25 coverage unavailable: {exc}")
    if coverage.vector_orphans:
        warnings.append(f"Vector index contains {coverage.vector_orphans} permanent orphan(s)")
    coverage.warnings = list(warnings)

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
            for note_id in live_meta
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

    semantic_orphan_indices_set = set(
        semantic_orphan_indices(len(live_ids), suggested_summary.clusters)
    )
    semantic_orphan_ids = {live_ids[index] for index in semantic_orphan_indices_set}
    graph_orphan_ids = {
        note_id for note_id in live_meta if graph_available and link_degrees.get(note_id, 0) == 0
    }
    orphan_ids = sorted(semantic_orphan_ids | graph_orphan_ids)
    vector_index_by_id = {note_id: index for index, note_id in enumerate(live_ids)}
    orphan_notes = []
    for note_id in orphan_ids:
        index = vector_index_by_id.get(note_id)
        mean_similarity = float(np.mean(similarity[index])) if index is not None else 0.0
        orphan_notes.append(
            OrphanNote(
                id=note_id,
                title=title_by_id.get(note_id, note_id),
                link_orphan=note_id in graph_orphan_ids,
                semantic_orphan=note_id in semantic_orphan_ids,
                link_degree=link_degrees.get(note_id, 0),
                mean_similarity=mean_similarity,
            )
        )

    return MocDiagnoseReport(
        coverage=coverage,
        threshold_sweep=threshold_sweep,
        suggest=suggested,
        orphans=OrphanSummary(count=len(orphan_notes), notes=orphan_notes),
        warnings=warnings,
    )
