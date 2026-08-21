"""MOC 诊断与结构笔记辅助功能。"""

from __future__ import annotations

from importlib import import_module
from typing import Any


class MocDiagnoseError(RuntimeError):
    """永久笔记向量数据无法安全诊断时抛出。"""


# 保留子包公开接口，但仅在调用方访问具体聚类符号时加载重依赖。
_CLUSTER_EXPORTS = {
    "ClusterMember",
    "ClusterSummary",
    "CoverageReport",
    "MocDiagnoseReport",
    "OrphanNote",
    "OrphanSummary",
    "ThresholdSummary",
    "build_threshold_summary",
    "compute_similarity",
    "find_clusters_at_threshold",
    "semantic_orphan_indices",
}


def __getattr__(name: str) -> Any:
    """按需加载聚类接口，避免普通 CLI 启动加载重依赖。"""
    if name not in _CLUSTER_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    cluster_module = import_module(".cluster", __name__)
    value = getattr(cluster_module, name)
    globals()[name] = value
    return value


__all__ = [
    "ClusterMember",
    "ClusterSummary",
    "CoverageReport",
    "MocDiagnoseError",
    "MocDiagnoseReport",
    "OrphanNote",
    "OrphanSummary",
    "ThresholdSummary",
    "build_threshold_summary",
    "compute_similarity",
    "find_clusters_at_threshold",
    "semantic_orphan_indices",
]
