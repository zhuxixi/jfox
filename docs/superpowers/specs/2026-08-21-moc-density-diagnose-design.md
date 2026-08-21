# Spec: `jfox moc diagnose` — MOC 密度诊断命令

> Issue: #390（Epic #376 首个子任务）
> 日期: 2026-08-16
> 状态: 待用户批准

## 1. 背景与目标

Epic #376 要在 jfox 引入 MOC / structure note 层。按 Zettelkasten 涌现原则，MOC 不应预先为所有主题创建，需要一个诊断工具量化回答：**现在哪些 permanent 主题簇密度已够，该建 MOC 了？**

本命令是 Epic 的破冰任务：只读诊断，不写任何笔记，输出数据驱动后续 `moc create` 的决策。

调研已确认（2026-08-16 实测，见 #390 评论）：
- 本机 KB permanent 实际 375–382 条（#376 背景中「1471」系 BM25 全类型总数误读，已在 #376 评论修正）
- 读全量向量 0.53s，377×377 余弦矩阵 52ms / 1.1MB —— 纯 CPU numpy 完全够用，不碰 GPU daemon
- bge-m3 嵌入空间下 0.5 阈值无区分度（平均 190 邻居），必须多档阈值对比
- BM25 覆盖率倒退问题已由 #391 / PR #396、#401 / PR #402、#403 / PR #404 修复；2026-08-21 全量重建后，按 frontmatter ID 核对 permanent 覆盖率为 99.8%（524/525）。本命令保留口径检查，用于发现未来回归

## 2. 范围与非目标

**范围**：仅 permanent 笔记。session / candidate / fleeting 不参与聚类、不出现在口径检查表。

**非目标**：
- 不生成 / 修改任何笔记（MOC 生成是后续子 issue）
- 不动 candidate 层（promote 簇级 triage 是另一套机械去重）
- 不修复索引口径异常（#391 的职责，本命令只如实报告）
- 不引入新第三方依赖（纯 numpy + 现有 networkx）

## 3. 设计决策表（已与用户对齐）

| # | 决策 | 结论 | 理由 |
|---|------|------|------|
| 1 | 命令形态 | 新开 `jfox moc` sub-app，诊断是首个子命令 `jfox moc diagnose` | 语义聚类与双链图谱是两个数据源；为后续 create/list/refresh 预留 |
| 2 | 聚类算法 | 纯 numpy 余弦相似度 + 阈值连通分量（networkx 复用现有依赖） | sklearn/HDBSCAN 依赖成本对诊断工具不成比例 |
| 3 | 计算方案 | 纯 CPU 读 ChromaDB 已存向量，不碰 embedding daemon | 实测 52ms，GPU 无收益且有搬运/依赖成本 |
| 4 | 阈值策略 | 多档阈值（默认 0.55/0.6/0.65/0.7）簇分布对比 | bge-m3 空间单一阈值无区分度 |
| 5 | 口径检查 | 只查 permanent 三口径（文件系统/向量库/BM25） | MOC 只活在 permanent 范畴内 |
| 6 | MOC 与 session 的关系 | 诊断不 cover session；未来 MOC 笔记骨架只链 permanent，session 走「近期动态」查询时聚合 | session 定期归档，固化链接会制造死链；session 是 permanent 3 倍，进聚类淹没信号 |

## 4. 类型定位（用户澄清，设计前提）

- **fleeting**: 想法/代办临时捕获，最终消化（转 permanent 或删掉）
- **session**: 过程记录 + 周报/日报原料，不删，近期留检索、老的定期归档
- **permanent**: 事实与长久知识，MOC 的唯一宿主类型

## 5. 命令契约

```
jfox moc diagnose [OPTIONS]

Options:
  --thresholds TEXT       阈值档位，逗号分隔（默认 "0.55,0.6,0.65,0.7"）
  --min-size INTEGER      簇最小报告规模（默认 3）
  --suggest-threshold F   建议清单使用哪档阈值（默认 0.65，须在 --thresholds 内）
  --top INTEGER           建议清单最多列几簇（默认 10）
  --kb, -k TEXT           目标知识库
  --format, -f TEXT       输出格式: table | json（默认 table）
  --json                  --format json 快捷方式
```

退出码：0 正常；1 错误（向量库未初始化、无 permanent 等）。

## 6. 数据流

```
CLI (moc/cli.py)
  └─ diagnose() (moc/cluster.py)
       ├─ ① 口径检查: 数 notes/permanent/*.md；vector_store type=permanent 计数；BM25 type=permanent 计数
       │    （任一源失败该行标 N/A，不中断）
       ├─ ② vector_store.get_all_embeddings(note_type="permanent")
       │    → (ids, metadatas, embeddings: np.ndarray[N,1024])
       │    孤儿过滤: 按 note_index/frontmatter 的真实 note ID 剔除已不存在笔记的向量
       │    （实测 permanent 有 63 条孤儿），孤儿数计入口径检查报告，不参与聚类；
       │    禁止复用只认 18 位 ID 的 indexer._extract_note_id_from_filename()，它会误判旧文件名
       ├─ ③ L2 归一化 → sim = E @ E.T（对角线置 0）
       ├─ ④ 每档阈值: sim > t 连边 → nx.connected_components → 过滤 ≥min_size 簇
       ├─ ⑤ KnowledgeGraph.build() → 双链度数 + orphan 集合
       │    （build 失败则降级：跳过双链指标并警告，不中断）
       ├─ ⑥ 簇摘要: 每簇成员 note_id/标题；簇内 hub = 成员中双链度数最高者（无链接信息时用簇内平均相似度最高者）
       └─ ⑦ 孤立笔记: 双链孤立 ∪ 语义孤立（当前 suggest 档下不属于任何 ≥min_size 簇）
  └─ 格式化输出 (table 四节 / json)
```

## 7. 输出格式

### 7.1 Table（默认）

```
① permanent 口径健康检查
┌──────────┬───────┐
│ 口径      │ 条数   │
├──────────┼───────┤
│ 文件系统  │ 375   │
│ 向量库    │ 382   │
│ BM25     │ 70 ⚠️ │
└──────────┴───────┘
⚠️ BM25 permanent 覆盖率 18%，低于 90%（索引健康问题请查 #391 类问题）

② 阈值敏感性
┌──────┬──────────┬────────┬──────────┐
│ 阈值  │ 簇数≥N条  │ 最大簇  │ 语义孤立  │
└──────┴──────────┴────────┴──────────┘
（每档阈值一行）

③ 建议建 MOC 的簇（阈值 0.65，top 10）
1. [38 条] hub:「<标题>」（双链度 15）
   成员示例: 标题A / 标题B / 标题C（至多 5 个）
...

④ 孤立笔记（双链孤立 ∪ 语义孤立）
共 N 条，列前 10 条标题
```

### 7.2 JSON（`--format json`）

```json
{
  "success": true,
  "kb": "default",
  "coverage": {
    "filesystem": 375,
    "vector": 382,
    "vector_orphans": 7,
    "bm25": 70,
    "bm25_coverage_ratio": 0.186,
    "warnings": ["BM25 permanent 覆盖率 18% < 90%"]
  },
  "threshold_sweep": [
    {"threshold": 0.55, "cluster_count": 2, "max_cluster_size": 210, "orphan_count": 12}
  ],
  "suggest": {
    "threshold": 0.65,
    "clusters": [
      {
        "size": 38,
        "hub": {"id": "...", "title": "...", "link_degree": 15},
        "members": [{"id": "...", "title": "..."}]
      }
    ]
  },
  "orphans": {
    "count": 98,
    "notes": [{"id": "...", "title": "...", "link_orphan": true, "semantic_orphan": true}]
  }
}
```

## 8. 组件设计与改动面

| 文件 | 改动 | 说明 |
|------|------|------|
| `jfox/moc/__init__.py` | 新建 | 子包入口 |
| `jfox/moc/cluster.py` | 新建 | 纯逻辑：`compute_similarity()` / `find_clusters_at_threshold()` / `diagnose()` 返回 `DiagnoseReport` 数据类；不 import typer/rich |
| `jfox/moc/cli.py` | 新建 | Typer sub-app `moc_app`，`diagnose` 子命令；注册进 `cli.py` |
| `jfox/vector_store.py` | +约 15 行 | `get_all_embeddings(note_type: Optional[str]) -> (ids, metadatas, np.ndarray)`，用 `collection.get(include=['embeddings','metadatas'])`；空库返回空数组 |
| `jfox/moc/cluster.py` 内 | 孤儿过滤逻辑 | 拉取后按 note_index/frontmatter 的真实 ID 剔除已不存在笔记的向量（实测 63 条孤儿），孤儿数计入口径检查；禁止复用 legacy 文件名解析器 |
| `jfox/cli.py` | +2 行 | `app.add_typer(moc_app, name="moc")` |
| `tests/unit/test_moc_cluster.py` | 新建 | 纯 numpy 逻辑单测，造假向量矩阵，不加载模型 → 进 Fast CI |

## 9. 错误处理与降级

| 场景 | 行为 |
|------|------|
| 向量库未初始化 / 无 permanent 向量 | 报错并提示先建索引，exit 1 |
| 孤儿过滤后向量为空 | 正常输出（簇列表为空），口径检查报告孤儿数 |
| BM25 / 文件系统计数失败 | 该行显示 N/A + warning，不中断 |
| KnowledgeGraph build 失败 | 跳过双链指标（hub 退化为簇内平均相似度最高者，无双链孤立标注）+ warning，不中断 |
| `--suggest-threshold` 不在 `--thresholds` 内 | 参数校验报错，exit 1 |
| permanent 条数 < min-size | 正常输出（簇列表为空，孤立=全部），不报错 |

## 10. 测试策略

- **单元测试**（Fast CI 兼容，无 embedding 标记）：
  - 构造 6 条 4 维假向量（两个明显簇 + 一个孤立点），验证多档阈值下簇划分正确
  - 边界：空输入、单节点、全相似（一团）、全不相似（全孤立）
  - `get_all_embeddings` 的空库行为（mock collection）
- **CLI 测试**：mock `diagnose()` 返回固定 `DiagnoseReport`，验证 `--format json` 结构、参数校验（suggest-threshold 不在档位内报错）
- **手工验收**：对本机真实 KB 跑 `jfox moc diagnose`，人工 sanity check 簇划分合理性（对应 #390 验收标准）

## 11. 未来方向（不在本 spec，后续子 issue 定调）

- `jfox moc create <topic>`：按诊断结果生成 MOC 笔记（新 note type `structure`，骨架只链 permanent，#376 评论已确认 search 链路兼容）
- MOC 笔记「近期动态」区段：查询时聚合链到成员的近期 session（不写死链接，session 归档自然滑出时间窗口）
- `jfox moc list` / `refresh`：MOC 清单与更新
- 诊断规模到 10 万条级时：全量矩阵 → HNSW top-k 稀疏图（复用 ChromaDB 索引），而非 GPU
- 簇代表词自动提取（标题分词高频词），当前 MVP 用 hub 标题代替
