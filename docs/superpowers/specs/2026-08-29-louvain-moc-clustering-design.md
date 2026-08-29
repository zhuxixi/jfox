# Design: 用 Louvain 社区发现替代 MOC 连通分量聚类（issue #439）

- **日期**: 2026-08-29
- **Issue**: [#439](https://github.com/zhuxixi/jfox/issues/439)
- **前置验证**: PR #441（`scripts/louvain_verify.py`）
- **目标版本**: v1.12.0

## 1. 背景与问题

`jfox moc diagnose` 用连通分量（connected components）在相似度图上找主题簇，只要两条笔记的余弦相似度超过阈值就连边，然后取连通块作为候选 MOC。这个算法在语义连续的语料上会**传递性焊接**：A 像 B、B 像 C，即使 A 和 C 毫不相关，三者也会被并进同一个簇。

实测后果（阈值 0.65）：

| 知识库 | 笔记数 | 最大簇占比 |
|--------|--------|-----------|
| office_hour | 773 | 97% 聚成一簇 |
| default | 571 | 91% 聚成一簇 |

巨簇没有任何 MOC 价值——一个包含 90% 笔记的「主题」等于没有主题。

Louvain 社区发现通过**模块度优化**（modularity optimization）识别图中的稠密核：它不看单条边是否超阈值，而是找「内部连接远密于外部连接」的节点组。spike 验证（2026-08-28）把 default 库 167 条的巨簇拆成 9 个主题清晰的子社区，规模 8–38 条，全部落在 5–50 条的可建 MOC 区间内。

## 2. 方案决策

| 方案 | 内容 | 取舍 |
|------|------|------|
| **A. 最小改动（选定）** | 只换算法 + 调阈值 + 补测试 | 风险最低，API 不变，spike 约束已定死，范围清晰 |
| B. 同时暴露 `--resolution` | A + 新增分辨率参数 | YAGNI：当前无需求，0.75 已验证充分；加参数增测试负担，后续按需加是安全的向后兼容改动 |
| C. feature flag 双算法共存 | 配置项切换新旧算法 | 过度设计：与 issue「替代」的目标不符；复杂度翻倍；已定的「不自动迁移」策略已经提供了渐进过渡 |

**选 A**。

## 3. 改动清单

| 文件 | 改动 |
|------|------|
| `jfox/moc/cluster.py` | `find_clusters_at_threshold()` 内的聚类算法（约 6 行核心） |
| `jfox/moc/cli.py` | 四处默认阈值（343、485、531、533 行） |
| `tests/moc/test_louvain_*.py` | 三个新回归测试 |
| `CHANGELOG.md` | 语义漂移与迁移说明 |

**不改动**：`find_clusters_at_threshold()` 的签名与返回类型、`semantic_orphan_indices()` 的实现、`draft.py` 的 `--max-size` 护栏、`compute_similarity()` 与 vector_store 等上游模块。

**无新依赖**：Louvain 用 NetworkX 3.0+ 内置的 `networkx.algorithms.community.louvain_communities`（项目已依赖 `networkx>=3.0`，本机为 3.6.1），与 `scripts/louvain_verify.py` 使用的是同一实现。

## 4. 算法实现

`find_clusters_at_threshold()` 内部，建图后的聚类逻辑替换如下。

改动前（连通分量，忽略边权重）：

```python
rows, columns = np.where(np.triu(matrix > threshold, k=1))
graph.add_edges_from(zip(rows.tolist(), columns.tolist()))

clusters = [sorted(component) for component in nx.connected_components(graph)]
```

改动后（Louvain，相似度作为边权重）：

```python
from networkx.algorithms import community

rows, columns = np.where(np.triu(matrix > threshold, k=1))
weighted_edges = [
    (int(row), int(column), float(matrix[row, column]))
    for row, column in zip(rows.tolist(), columns.tolist())
]
graph.add_weighted_edges_from(weighted_edges)

communities = community.louvain_communities(
    graph, weight="weight", resolution=1.0, seed=42
)
clusters = [sorted(members) for members in communities]
```

四个约束：

1. **带权图**：相似度作为边权重传入（`weight="weight"`）。连通分量忽略权重，Louvain 需要权重来算模块度。
2. **`seed=42`**：Louvain 的节点遍历顺序含随机性，固定种子保证同一输入永远得到同一划分，否则 diagnose 结果不可复现、测试无法断言。
3. **`resolution=1.0`**：标准模块度分辨率，本次不暴露为参数。
4. **返回格式不变**：`louvain_communities` 返回 `List[Set[int]]`，转成 `List[List[int]]` 后，下游的 `min_size` 过滤与排序逻辑完全复用。

阈值仍然决定建图（`matrix > threshold` 才连边），Louvain 只改变「在这张图上如何划分社区」。

## 5. 阈值调整与影响面

四处默认值从 0.65 改为 0.75（`diagnose` 的 sweep 列表同步上移）：

| 位置 | 参数 | 改动 |
|------|------|------|
| `cli.py:343` | `moc create --threshold` | 0.65 → 0.75 |
| `cli.py:485` | `moc update --threshold` | 0.65 → 0.75 |
| `cli.py:531` | `moc diagnose --thresholds` | `"0.55,0.6,0.65,0.7"` → `"0.70,0.75,0.78,0.80"` |
| `cli.py:533` | `moc diagnose --suggest-threshold` | 0.65 → 0.75 |

理由：spike 实测在 bge-m3 向量下，0.65 属于「全聚一团」区间，0.75 才是产出合理粒度社区的可用值。sweep 区间同步上移到 0.70–0.80，避免继续扫描无意义的低阈值。

**影响面仅限 MOC 三个命令**。已用 grep 确认 `0.65` 不在 `jfox/moc/` 之外的生产代码中出现，`search`、`add`、`suggest-links`、`graph` 等命令的行为零变化。显式传 `--threshold 0.65` 仍然生效，向后兼容。

**本机环境不受 PR #453 影响**：#453 只改 CPU 默认模型（all-MiniLM-L6-v2 → bge-small-zh-v1.5），GPU 路径的 `BAAI/bge-m3` 未变。本机 RTX 2080 Ti、`device: auto` 解析为 cuda、模型为 bge-m3（1024 维），因此 0.75 的标定数据仍然有效，无需重新标定。

## 6. 测试策略

三个回归测试，全部用手工构造的相似度矩阵，不依赖 embedding 或 ChromaDB，属于秒级单元测试。

| 测试 | 构造 | 断言 |
|------|------|------|
| 双核弱桥 | 两个 5 节点核（内部 0.8），核间一条 0.66 弱边 | Louvain 拆成 2 簇（连通分量会焊成 1 簇） |
| 完全图 | 6 节点完全图，边权 0.85 | 仍为 1 簇，验证不过度拆碎 |
| 确定性 | 同一矩阵连续跑 3 次 | 三次结果完全一致（簇数、成员、顺序） |

双核弱桥是本次改动的核心回归：弱桥权重 0.66 高于阈值 0.65，所以两个核在图上是连通的，连通分量必然合并；Louvain 因为桥的权重远低于核内部权重，模块度优化会把它划成两个社区。这个测试直接锁住「不再传递性焊接」这一行为。

```bash
uv run pytest tests/moc/ -k louvain
```

## 7. 验收方案

分两层，效果层复用已合并的验证脚本，无需新写工具。

**代码层**：三个回归测试通过。

**效果层**：在 worktree 内跑 `uv run python scripts/louvain_verify.py`，对 default 知识库（609 条 permanent 笔记，bge-m3 向量）输出新旧算法对比，指标为簇数量、最大簇规模、孤儿数。预期新算法把巨簇拆成多个 5–50 条的社区，最大簇占比从 90% 级别显著下降。对比结果贴回 issue #439 作为验收证据。

## 8. 边界情况

| 情况 | 行为 |
|------|------|
| 无边图（阈值过高） | Louvain 输出全部为单点社区，经 `min_size` 过滤后全进孤儿池，与连通分量一致 |
| 社区小于 `min_size` | 由现有过滤逻辑剔除，不进 MOC 候选 |
| 社区超过 `--max-size` | `draft.py` 现有 ValueError 护栏照旧拦下并提示提高阈值（本次不改） |

## 9. 语义漂移（须进 CHANGELOG）

**语义孤儿的定义变了**。原义是「与任何笔记都不连通」，新义是「不属于任何稠密社区」。Louvain 会把边缘节点归入小社区，这些社区被 `min_size` 过滤后进入孤儿池，因此**孤儿数量会上升**，这是算法特性而非退化。

**diagnose 历史输出不可比**。默认阈值与聚类算法同时变化，升级前后的 diagnose 数字没有可比性。

## 10. 迁移与回滚

**已建 MOC 不自动迁移**。现有 MOC 笔记内容不做任何改写。只有主动执行 `jfox moc update` 时才用新算法重算成员并报告 diff（应加入、应移出的笔记），是否落盘由 `--yes` 决定。这样每个 MOC 的新旧差异都能被逐个审阅。

**回滚**：`git revert` 即可。无数据迁移、无 schema 变更、无索引重建，已建 MOC 笔记不受影响。

## 11. 非目标

- 不暴露 `--resolution` 参数（YAGNI，后续按需加）
- 不做 feature flag 或双算法共存
- 不自动迁移已建 MOC
- 不改 `--max-size` 护栏逻辑
- 不碰 `compute_similarity`、vector_store、检索链路（#442–#447 属独立轨道）
