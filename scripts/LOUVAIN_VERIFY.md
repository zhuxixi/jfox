# Louvain 社区发现验证脚本

验证 GitHub issue [#439](https://github.com/zhuxixi/jfox/issues/439) 提出的 MOC 聚类算法改进方案：用 Louvain 社区发现替代生产代码中的连通分量，缓解语义连续语料的巨簇问题。

## 脚本定位

脚本保留一份旧版连通分量实现，仅作为 before/after 对比基线；生产指标直接调用 `jfox.moc.cluster.find_clusters_at_threshold()`，因此脚本始终能区分旧算法和当前生产算法。默认运行不重启 daemon，也不会写入知识库。

Louvain 通过优化模块度（社区内部连接较密、社区之间连接较疏）寻找真实的稠密主题核。它不是简单地切断所有弱边：如果语料本身只有一条连续的语义链、没有可识别的稠密核，Louvain 也可能保留一个社区。

## 快速开始

在项目根目录运行当前 default 知识库的对比：

```bash
uv run python scripts/louvain_verify.py
```

指定阈值或查看旧版最大簇的局部拆分：

```bash
uv run python scripts/louvain_verify.py --threshold 0.78
uv run python scripts/louvain_verify.py --top 3
```

脚本支持 `--kb` 读取其他已配置知识库；当前本机验收只使用 `default`，其他名称仅适用于对应环境确实存在时：

```bash
uv run python scripts/louvain_verify.py --kb office_hour
```

`--resolution` 仅用于实验比较，不代表生产 MOC CLI 的可调参数：

```bash
uv run python scripts/louvain_verify.py --resolution 1.2
```

## 输出说明

脚本输出五个部分。

### 1. 加载向量

```text
Step 1: 加载 permanent 笔记向量
  磁盘存在: <当前实际数量> 条
```

这里的数量随知识库增长而变化，不是固定验收值。

### 2. 旧版连通分量基线

```text
Step 2: 旧版连通分量基线（阈值 0.75）
  簇数: <实际数量>
  最大簇: <实际数量> 条
  孤儿数: <实际数量> 条
```

这部分由脚本内部的 `run_connected_components()` 计算，复现 #439 改造前的算法，不再调用已经切换到 Louvain 的生产函数。

### 3. 生产 Louvain 全局指标

```text
Step 3: 生产 Louvain 社区发现（阈值 0.75，seed=42）
  社区数: <实际数量>
  最大社区: <实际数量> 条
  孤儿数: <实际数量> 条
```

这部分直接调用生产 `find_clusters_at_threshold()`，使用带权边、`resolution=1.0` 和 `seed=42`。孤儿数表示没有进入达到 `min_size=3` 的簇或社区的节点数。

### 4. 旧版最大簇的局部主题样本

当旧版最大簇超过 50 条时，脚本会对它运行局部 Louvain，并展示每个社区的规模、关键词和前三条标题样本：

```text
Step 4.1: 对旧版最大簇 0（<实际数量> 条）运行 Louvain 主题拆分
  局部 Louvain 输出: <实际数量> 个社区
```

这部分用于人工检查主题边界，不应与全局生产 Louvain 社区数量混为一谈。旧版最大簇不超过 50 条时，脚本会跳过局部拆分，因为它已经落在 MOC 规模护栏内。

### 5. 局部对比总结

```text
--- 旧版最大簇局部拆分：簇 0 ---
  旧版连通分量: 1 个簇，<实际数量> 条
  局部 Louvain 社区发现: <实际数量> 个社区
    最大社区: <实际数量> 条
    可建 MOC 规模（5-50 条）: <实际数量> 个
    规模分布: [<实际值>]
    局部拆分孤儿数: <实际数量> 条
```

历史 spike 曾在特定快照中观察到 167 条巨簇拆成 9 个社区；这个结果用于说明方法可行，不是当前代码的硬编码断言。

## 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--kb` | 当前 | 知识库名称；本机当前使用 `default` |
| `--threshold` | 0.75 | 建边阈值（相似度 > threshold 才建边） |
| `--resolution` | 1.0 | 脚本实验参数；生产 MOC 固定使用 1.0，不暴露 CLI 选项 |
| `--top` | 1 | 对前 N 个旧版最大簇展示局部拆分 |

## 如何判断结果

验收不要求固定的笔记数、簇数或社区数，而关注当前数据上的三项证据：

1. 输出同时包含旧版连通分量基线和生产 Louvain 全局指标，且标签没有混淆。
2. 在当前 default 数据中，生产 Louvain 的最大社区相较旧版巨簇明显变小；若数据没有巨簇，应如实记录并说明无需局部拆分。
3. 对展示的社区标题样本做人工检查，确认没有明显主题混杂；出现混杂时再讨论阈值或语料边界，而不是默认认为算法一定能切开。

`--max-size 50` 是 MOC 生成护栏。Louvain 不保证所有社区都小于 50 条；超过护栏时仍由 `moc create` 拒绝，用户可以在 dry-run 中提高阈值或人工选择其他社区。

## 历史背景快照

此前的验证记录包含以下历史数据：`office_hour` 773 条、`default` 571 条；在旧阈值下曾出现 97% 或 91% 进入最大连通簇，以及 167/741 条巨簇拆成 9/13 个社区。这些数据依赖当时的知识库内容和向量快照，随笔记增删会变化，因此只作为背景，不作为自动验收门槛。

## 依赖

- NetworkX >= 3.0（已在 `pyproject.toml` 的 dependencies 中）
- jfox 包（通过 `uv run` 加载）

## 相关资源

- [#439 - Louvain 实现提案](https://github.com/zhuxixi/jfox/issues/439)
- [#437 - 语义连续语料的根因分析](https://github.com/zhuxixi/jfox/issues/437)
- [Louvain 算法论文](https://arxiv.org/abs/0803.0476)
- [NetworkX 社区发现文档](https://networkx.org/documentation/stable/reference/algorithms/community.html)
