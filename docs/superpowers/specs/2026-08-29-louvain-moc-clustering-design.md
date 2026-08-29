# Design: 用 Louvain 社区发现替代 MOC 连通分量聚类（issue #439）

- **日期**：2026-08-29
- **Issue**：[#439](https://github.com/zhuxixi/jfox/issues/439)
- **前置验证**：PR #441（`scripts/louvain_verify.py`）
- **目标版本**：v1.12.0

## 1. 背景与目标

`jfox moc diagnose` 当前在相似度图上使用连通分量（connected components）查找主题簇：只要两条笔记的相似度超过阈值就连边，再把所有可传递连接的节点放进同一簇。这个算法在语义连续的语料上会产生传递性焊接：A 像 B、B 像 C，即使 A 与 C 不像，三者也会被合并。

历史 spike 快照曾观察到这个问题：旧的 `default` 快照中 571 条 permanent 笔记在 0.65 阈值下有 91% 进入最大连通簇，`office_hour` 快照中 773 条笔记有 97% 进入最大连通簇。这些数字是历史数据集的证据，不是本次实现的固定验收阈值。

本次目标是将生产聚类算法替换为 NetworkX 内置的 Louvain 社区发现。Louvain 通过模块度优化寻找“内部连接较密、外部连接较疏”的社区，在存在多个稠密主题核时可以拆解传递性巨簇；它不能保证把没有真实主题边界的纯链式语料拆开。

## 2. 本机约束与范围

本次以当前机器为验收基准：只有 `default` 知识库，GPU 为 NVIDIA GeForce RTX 2080 Ti，`device: auto` 实际解析为 CUDA，模型为 GPU 默认的 `BAAI/bge-m3`（1024 维）。PR #453 只修改 CPU 默认模型，GPU 的 bge-m3 未变，因此不需要重建向量或重新标定 0.75 阈值。

本次改动只覆盖 MOC 聚类及其默认参数，不重启 daemon，不改 embedding、vector store、检索链路或其他 CLI。由于 MOC 目前尚未正式投入使用，本次不设计 feature flag、双算法并存或数据迁移流程；已有 structure 笔记也不会被代码自动改写。

## 3. 方案决策

| 方案 | 内容 | 决策 |
|------|------|------|
| A. 直接替换 | 生产函数改用加权 Louvain，固定 `seed=42` 与 `resolution=1.0`，同步默认阈值并补测试 | **采用**：改动小、API 不变，符合 issue 目标 |
| B. 暴露 resolution | 在生产 CLI 增加 Louvain 分辨率参数 | 不采用：当前没有用户需求，增加参数和测试面 |
| C. Feature flag | 配置项保留连通分量与 Louvain 两套生产算法 | 不采用：当前没有正式用户，双路径只会增加维护成本 |

## 4. 生产算法设计

修改 `jfox/moc/cluster.py` 的 `find_clusters_at_threshold()`，保持现有签名和返回类型：

```python
def find_clusters_at_threshold(
    similarity: np.ndarray, threshold: float, min_size: int
) -> List[List[int]]:
```

函数继续使用 `matrix > threshold` 建图，但把相似度写入边权：

```python
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
clusters = [cluster for cluster in clusters if len(cluster) >= min_size]
return sorted(clusters, key=lambda cluster: (-len(cluster), cluster[0]))
```

关键约束如下：

1. 使用 `networkx.algorithms.community.louvain_communities`，不增加依赖；项目已经依赖 `networkx>=3.0`。
2. 相似度作为 `weight`，不能退回无权图，否则会丢失稠密程度信息。
3. 固定 `seed=42`，保证同一输入的社区划分和 CLI 输出可复现。
4. 固定 `resolution=1.0`，本次不作为生产函数或 CLI 参数暴露。
5. 保持 `min_size` 过滤、簇内排序和簇间排序逻辑，返回 `List[List[int]]`。
6. 空图、单点社区和小于 `min_size` 的社区沿用现有过滤语义，不新增特殊分支。

同时更新函数及相关 orphan 字段的 docstring，准确说明当前“语义孤儿”是“没有进入任何达到 `min_size` 的 Louvain 社区”，而不是“没有任何相似邻居”。

## 5. 默认阈值与影响面

修改 `jfox/moc/cli.py` 的四处默认值：

| 命令/参数 | 当前 | 新值 |
|-----------|------|------|
| `moc create --threshold` | 0.65 | 0.75 |
| `moc update --threshold` | 0.65 | 0.75 |
| `moc diagnose --thresholds` | `0.55,0.6,0.65,0.7` | `0.70,0.75,0.78,0.80` |
| `moc diagnose --suggest-threshold` | 0.65 | 0.75 |

默认值变化只影响 MOC 三个命令的“不传参数”行为。用户显式传入旧阈值仍然有效；`search`、`add`、`suggest-links`、`graph` 和其他非 MOC 命令不变。已建 MOC 不会因为默认值或算法替换自动改写；主动执行 `moc update` 时仍遵守现有 update diff 语义，算法变化本身不会自动摘除已有成员。

## 6. 验证脚本设计

`louvain_verify.py` 必须保留独立的旧算法基线，不能继续通过已经改成 Louvain 的生产函数冒充连通分量。新增脚本内部 helper：

```python
def run_connected_components(
    similarity: np.ndarray,
    threshold: float,
    min_size: int,
) -> List[List[int]]:
    """Reproduce the pre-#439 clustering algorithm for comparison only."""
```

脚本在同一份相似度矩阵上分别计算：

- 旧算法：脚本内部的 `run_connected_components()`；
- 新算法：生产函数 `find_clusters_at_threshold()`，默认固定 `seed=42` 和 `resolution=1.0`。

脚本输出两种算法的簇数量、最大簇规模和孤儿数，并展示新算法社区的规模与标题样本。详细主题样本继续针对旧版最大巨簇做局部 Louvain 拆分，以便和历史 spike 的观察对象保持一致；整体指标必须来自生产函数，不能把脚本自己的实验 helper 当成生产结果。脚本现有的 `--resolution` 仅作为实验工具保留；本次正式验收使用默认值 1.0，生产 CLI 不暴露该参数。

## 7. 测试策略

测试放在仓库现有的 `tests/unit/test_moc_cluster.py` 和 `tests/unit/test_moc_cli.py`，不新建不存在的 `tests/moc/` 目录。新增或调整以下测试：

1. **双核弱桥**：两个 5 节点完全子图，内部权重 0.8，跨核只有一条 0.66 边，阈值 0.65；断言结果是两个 5 节点社区。这是核心回归，旧连通分量会返回一个 10 节点簇。
2. **完全图**：6 节点完全图，边权 0.85，阈值 0.65；断言仍是一个 6 节点社区。
3. **确定性与参数**：同一矩阵多次执行结果一致，并通过 mock 检查生产调用传入 `weight="weight"`、`resolution=1.0`、`seed=42`。
4. **CLI 默认值**：help 输出确认 create/update 使用 0.75，diagnose 使用 `0.70,0.75,0.78,0.80` 和 0.75。

## 8. 验收方案

验收分为代码层和效果层，不依赖 daemon：

```bash
uv run pytest tests/unit/test_moc_cluster.py -v
uv run pytest tests/unit/test_moc_cli.py tests/unit/test_moc_create_cli.py tests/unit/test_moc_update_cli.py -v
uv run python scripts/louvain_verify.py --top 1
```

代码层要求所有 MOC 单元测试和相关 CLI 测试通过，弱桥测试必须证明核心行为已从“一个巨簇”变为“两个稠密社区”。

效果层使用当前唯一的 `default` 知识库，记录当次运行的实际 permanent 数量和新旧算法指标。验收关注三点：旧算法仍能复现巨簇基线；新算法的最大社区明显小于旧巨簇；社区规模和标题样本经人工检查后没有明显主题混杂。历史的“9 个社区”“571 条笔记”只作为背景，不作为硬编码断言。

验收结果回贴 issue #439。CHANGELOG 不在本功能 PR 中预建带日期的版本段；v1.12.0 发版时由 release 流程收录 #439，并补充本节记录的用户可见行为变化。

## 9. 非目标与回滚

本次不做以下工作：

- 不新增 Python 依赖；
- 不暴露生产 `--resolution`；
- 不保留生产连通分量 feature flag；
- 不自动迁移或批量改写已有 MOC；
- 不修改 `--max-size` 护栏、embedding、vector store 或检索链路；
- 不为尚未正式使用的 MOC 设计数据恢复流程。

代码回滚使用 Git revert 即可。由于本次没有 schema、索引或 daemon 迁移，且功能尚未正式使用，回滚不需要额外数据操作。
