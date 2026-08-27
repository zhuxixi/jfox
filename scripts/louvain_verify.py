#!/usr/bin/env python3
"""Louvain 社区发现验证脚本 —— MOC 聚类算法改进评估。

对比当前的连通分量算法与 Louvain 社区发现在语义连续语料上的表现。
验证 GitHub issue #439 提出的改进方案：用 Louvain 替代连通分量，解决巨簇问题。

用法：
    # 使用默认知识库、默认阈值 0.75
    uv run python scripts/louvain_verify.py

    # 指定知识库和阈值
    uv run python scripts/louvain_verify.py --kb office_hour --threshold 0.78

    # 调整 Louvain resolution 参数（>1.0 拆更细，<1.0 合并更多）
    uv run python scripts/louvain_verify.py --resolution 1.2

依赖：
    - NetworkX >= 3.0（已在 pyproject.toml）
    - jfox 包已安装（uv run 自动处理）

相关 issue：
    - #439（Louvain 实现提案）
    - #437（语义连续语料的根因分析）
"""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path
from typing import List, Tuple

import networkx as nx
import numpy as np
from networkx.algorithms import community

# 插入 jfox 包路径（uv run 环境下不需要，但直接 python 运行时需要）
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))

from jfox.config import ZKConfig, use_kb
from jfox.moc.cluster import compute_similarity, find_clusters_at_threshold
from jfox.note_index import get_note_index
from jfox.vector_store import VectorStore


def load_permanent_embeddings(
    kb_name: str | None = None,
) -> Tuple[List[str], List[str], np.ndarray]:
    """加载指定知识库的 permanent 笔记向量。

    返回:
        (note_ids, note_titles, embeddings) 三元组
    """
    if kb_name:
        with use_kb(kb_name):
            return _load_embeddings_impl()
    else:
        return _load_embeddings_impl()


def _load_embeddings_impl() -> Tuple[List[str], List[str], np.ndarray]:
    """实际加载逻辑（在正确的 kb 上下文中执行）。"""
    config = ZKConfig()
    vector_store = VectorStore(config.chroma_dir)
    vector_store.init()

    vector_ids, _, raw_embeddings = vector_store.get_all_embeddings("permanent")

    # 过滤磁盘存在的笔记
    note_index = get_note_index()
    live_meta = {
        m.id: m for m in note_index.get_all_meta() if m.type.value == "permanent"
    }

    records = []
    for index, note_id in enumerate(vector_ids):
        if note_id in live_meta:
            records.append((note_id, live_meta[note_id].title, raw_embeddings[index]))

    live_ids = [r[0] for r in records]
    live_titles = [r[1] for r in records]
    live_embeddings = np.asarray([r[2] for r in records], dtype=np.float32)

    return live_ids, live_titles, live_embeddings


def run_louvain_on_cluster(
    cluster_indices: List[int],
    similarity: np.ndarray,
    threshold: float,
    resolution: float,
) -> List[List[int]]:
    """对给定簇运行 Louvain 社区发现。

    Args:
        cluster_indices: 簇内笔记的全局索引
        similarity: 全局相似度矩阵
        threshold: 建边阈值（相似度 > threshold 才建边）
        resolution: Louvain 分辨率参数（1.0 标准，>1.0 拆更细，<1.0 合并更多）

    Returns:
        社区列表（每个社区是全局索引列表）
    """
    subgraph = nx.Graph()
    subgraph.add_nodes_from(cluster_indices)

    # 建边：簇内任意两节点相似度 > threshold 则建边，权重 = 相似度
    for i, idx_i in enumerate(cluster_indices):
        for idx_j in cluster_indices[i + 1 :]:
            sim = similarity[idx_i, idx_j]
            if sim > threshold:
                subgraph.add_edge(idx_i, idx_j, weight=float(sim))

    # 运行 Louvain（seed 固定保证可重复）
    communities = community.louvain_communities(
        subgraph, weight="weight", resolution=resolution, seed=42
    )

    # 转回全局索引 + 按规模排序
    result = [sorted(comm) for comm in communities]
    return sorted(result, key=lambda c: (-len(c), c[0]))


def extract_keywords(titles: List[str], min_count: int = 2) -> str:
    """从标题中提取高频关键词。"""
    import re

    words = []
    for title in titles:
        # 提取中文词（长度 >= 2）和英文词（长度 >= 3）
        words.extend(re.findall(r"[\u4e00-\u9fff]{2,}|[a-zA-Z]{3,}", title))

    common = Counter(words).most_common(5)
    return ", ".join(w for w, c in common if c >= min_count)


def main() -> None:
    """主函数：运行验证流程。"""
    parser = argparse.ArgumentParser(
        description="验证 Louvain 社区发现算法在 MOC 聚类上的效果"
    )
    parser.add_argument(
        "--kb", type=str, default=None, help="知识库名称（默认使用当前知识库）"
    )
    parser.add_argument(
        "--threshold", type=float, default=0.75, help="建边阈值（默认 0.75）"
    )
    parser.add_argument(
        "--resolution", type=float, default=1.0, help="Louvain 分辨率（默认 1.0）"
    )
    parser.add_argument(
        "--top", type=int, default=1, help="验证前 N 个最大簇（默认 1）"
    )
    args = parser.parse_args()

    kb_display = args.kb if args.kb else "default"
    print(f"=== 知识库: {kb_display} | 阈值: {args.threshold} ===\n")

    # Step 1: 加载向量
    print("Step 1: 加载 permanent 笔记向量")
    live_ids, live_titles, live_embeddings = load_permanent_embeddings(args.kb)
    print(f"  磁盘存在: {len(live_ids)} 条\n")

    # Step 2: 连通分量聚类（当前算法）
    print(f"Step 2: 连通分量聚类（阈值 {args.threshold}）")
    similarity = compute_similarity(live_embeddings)
    clusters_cc = find_clusters_at_threshold(similarity, args.threshold, min_size=3)
    print(f"  簇数: {len(clusters_cc)}")

    if not clusters_cc:
        print("  ERROR: 没有簇，无法继续")
        return

    # 显示前几个簇的规模
    for i, cluster in enumerate(clusters_cc[: min(5, len(clusters_cc))]):
        sample_title = live_titles[cluster[0]][:50]
        print(f"    簇 {i}: {len(cluster)} 条 — {sample_title} ...")
    print()

    # Step 3: 对前 N 个最大簇运行 Louvain
    for cluster_idx in range(min(args.top, len(clusters_cc))):
        mega_cluster = clusters_cc[cluster_idx]
        if len(mega_cluster) <= 50:
            print(
                f"簇 {cluster_idx} 规模 {len(mega_cluster)} 已在 MOC 护栏内，跳过 Louvain"
            )
            continue

        print(
            f"Step 3.{cluster_idx + 1}: 对簇 {cluster_idx}"
            f"（{len(mega_cluster)} 条）运行 Louvain"
        )
        communities = run_louvain_on_cluster(
            mega_cluster, similarity, args.threshold, args.resolution
        )

        print(f"  Louvain 输出: {len(communities)} 个社区\n")

        # 显示每个社区
        for i, comm in enumerate(communities):
            titles = [live_titles[idx] for idx in comm]
            keywords = extract_keywords(titles, min_count=2)

            print(f"  社区 {i}: {len(comm)} 条")
            print(f"    关键词: {keywords}")
            print(f"    成员示例（前 3 条）:")
            for title in titles[:3]:
                print(f"      - {title[:70]}")
            if len(comm) > 3:
                print(f"      ... 还有 {len(comm) - 3} 条")
            print()

        # Step 4: 对比总结
        print(f"--- 对比：簇 {cluster_idx} ---")
        print(f"  连通分量（当前）: 1 个簇，{len(mega_cluster)} 条")
        print(f"  Louvain 社区发现: {len(communities)} 个社区")

        sizes = sorted([len(c) for c in communities], reverse=True)
        moc_ready = [s for s in sizes if 5 <= s <= 50]
        print(f"    最大社区: {sizes[0]} 条")
        print(f"    可建 MOC 规模（5-50 条）: {len(moc_ready)} 个")
        print(f"    规模分布: {sizes[:10]}")
        print()


if __name__ == "__main__":
    main()
