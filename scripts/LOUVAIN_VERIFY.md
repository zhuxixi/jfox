# Louvain 社区发现验证脚本

验证 GitHub issue [#439](https://github.com/zhuxixi/jfox/issues/439) 提出的 MOC 聚类算法改进方案：用 Louvain 社区发现替代连通分量，解决语义连续领域语料的巨簇问题。

## 背景

当前 jfox moc 使用的连通分量算法在语义连续语料上存在**传递性焊接**问题（[#437](https://github.com/zhuxixi/jfox/issues/437)）：

- A 像 B、B 像 C → A/C 通过 B 被焊进同一簇（哪怕 A/C 本身不像）
- 结果：「一个糊糊 + 满地孤儿」，中间不存在能切出干净主题边界的甜点区
- 实测：`office_hour` 库（773 条）0.65 阈值下 97% 聚成一簇；`default` 库（571 条）91% 聚成一簇

Louvain 算法通过优化**模块度**（内紧外松）主动切断弱连接，能将巨簇拆成子系统级 MOC。

## 快速开始

### 默认用法（当前知识库 + 阈值 0.75）

```bash
cd /path/to/jfox
uv run python scripts/louvain_verify.py
```

### 指定知识库

```bash
# 验证 office_hour 知识库
uv run python scripts/louvain_verify.py --kb office_hour

# 验证 work 知识库
uv run python scripts/louvain_verify.py --kb work
```

### 调整阈值和分辨率

```bash
# 提高阈值到 0.78（更严格的边界）
uv run python scripts/louvain_verify.py --threshold 0.78

# 调整 Louvain 分辨率（>1.0 拆更细，<1.0 合并更多）
uv run python scripts/louvain_verify.py --resolution 1.2

# 组合使用
uv run python scripts/louvain_verify.py --kb office_hour --threshold 0.76 --resolution 0.9
```

### 验证多个最大簇

```bash
# 对前 3 个最大簇都运行 Louvain（默认只验证第 1 个）
uv run python scripts/louvain_verify.py --top 3
```

## 输出说明

脚本输出分四个部分：

### 1. 加载向量

```text
Step 1: 加载 permanent 笔记向量
  磁盘存在: 571 条
```

### 2. 连通分量聚类（当前算法）

```text
Step 2: 连通分量聚类（阈值 0.75）
  簇数: 22
    簇 0: 167 条 — pi 型 CR workflow 模板必须强制 zima-review XML ...
    簇 1: 13 条 — jfox delete 的 backlinks 清理设计（#386） ...
    ...
```

显示当前算法在指定阈值下的聚类结果。**簇 0 是最大簇**（通常是巨簇）。

### 3. Louvain 社区发现

```text
Step 3.1: 对簇 0（167 条）运行 Louvain
  Louvain 输出: 9 个社区

  社区 0: 38 条
    关键词: agent, patch, board, npm, 已安装
    成员示例（前 3 条）:
      - pi 扩展纯函数的 Node 直跑测试法
      - pi 已安装 @plannotator/pi-extension
      - pi 已安装 pi-agentsmd
      ... 还有 35 条

  社区 1: 26 条
    关键词: zima, Zima, bot, webhook, jfox
    ...
```

对巨簇运行 Louvain，输出拆分后的子社区。每个社区显示：

- 规模（成员数量）
- 关键词（从标题自动提取的高频词，辅助判断主题）
- 成员示例（前 3 条标题）

### 4. 对比总结

```text
--- 对比：簇 0 ---
  连通分量（当前）: 1 个簇，167 条
  Louvain 社区发现: 9 个社区
    最大社区: 38 条
    可建 MOC 规模（5-50 条）: 9 个
    规模分布: [38, 26, 23, 22, 20, 12, 10, 8, 8]
```

对比两种算法的输出：

- **连通分量**：巨簇规模（通常超 `--max-size 50` 护栏）
- **Louvain**：拆成几个社区、最大社区规模、可直接建 MOC 的社区数量、规模分布

## 参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--kb` | 当前 | 知识库名称（如 `office_hour`、`work`） |
| `--threshold` | 0.75 | 建边阈值（相似度 > threshold 才建边） |
| `--resolution` | 1.0 | Louvain 分辨率（1.0 标准，>1.0 拆更细，<1.0 合并更多） |
| `--top` | 1 | 验证前 N 个最大簇 |

## 预期结果

根据 `default` 知识库的验证结果（571 条 permanent，AI 开发工作流领域）：

- **连通分量（当前）**：0.75 阈值下，167 条笔记聚成 1 个巨簇（超护栏）
- **Louvain**：巨簇拆成 9 个子社区，规模 8-38 条，全部可建 MOC

9 个子社区的自动识别主题：

1. pi 扩展开发生态（38 条）
2. Zima webhook 调度与双 Bot（26 条）
3. Zima CR 与 GitHub 自动化（23 条）
4. 跨 Agent 平台迁移（22 条）
5. pi-agent-board TUI 层（20 条）
6. pi-agent-board session 管理（12 条）
7. cwd/worktree 管理（10 条）
8. Git 操作踩坑集（8 条）
9. 模型与 Ollama Cloud（8 条）

**主题边界清晰，无需人工分层即可直接建 MOC。**

## 如何解读结果

### 1. 关键词准确度

关键词是从标题提取的高频词，用于快速判断社区主题。如果关键词与你的实际子系统对应（如 `webhook`、`TUI`、`session`），说明 Louvain 识别出了真实的边界；如果关键词杂乱无章，可能需要调整 `--resolution` 参数。

### 2. 规模分布合理性

理想的规模分布是「多个 10-30 条的中型社区 + 少量 5-10 条的小社区」。如果出现：

- **过度拆分**（大量 3-5 条的碎片社区）→ 降低 `--resolution`（如 0.8）
- **拆分不足**（仍有 50+ 条的大社区）→ 提高 `--resolution`（如 1.2）

### 3. 边界清晰度判断

查看每个社区的成员示例，判断笔记是否真的属于同一子系统。如果成员标题主题混杂，说明 Louvain 切错了边界——可能是：

- 阈值过低（建了太多弱边）→ 提高 `--threshold`
- 笔记真的没有子系统边界（高度交织）→ Louvain 也无法拆分，需人工分层

## 典型使用场景

### 场景 1：评估自己的知识库是否适合 Louvain

```bash
# 跑默认参数，看巨簇能否拆开
uv run python scripts/louvain_verify.py

# 如果拆成了合理的子社区 → 你的库适合 Louvain
# 如果输出还是一个大簇 → 你的库可能没有子系统边界，或需调参
```

### 场景 2：为 #439 实现寻找最佳默认参数

```bash
# 在多个知识库上扫参数组合
for kb in default office_hour work; do
  for t in 0.70 0.75 0.78; do
    for r in 0.8 1.0 1.2; do
      echo "=== $kb threshold=$t resolution=$r ==="
      uv run python scripts/louvain_verify.py --kb $kb --threshold $t --resolution $r
    done
  done
done
```

记录每个组合的「可建 MOC 数量」和「主题边界合理性」，找到最佳默认值。

### 场景 3：复现 #437 案例

```bash
# 在 office_hour 库上运行（需要先配置该知识库）
uv run python scripts/louvain_verify.py --kb office_hour --threshold 0.78

# 预期：741 条巨簇拆成 10-15 个子社区
```

## 依赖

- NetworkX >= 3.0（已在 `pyproject.toml` 的 `dependencies`）
- jfox 包（通过 `uv run` 自动加载）

## 相关资源

- [#439 - Louvain 实现提案](https://github.com/zhuxixi/jfox/issues/439)
- [#437 - 语义连续语料的根因分析](https://github.com/zhuxixi/jfox/issues/437)
- [Louvain 算法论文](https://arxiv.org/abs/0803.0476)
- [NetworkX 社区发现文档](https://networkx.org/documentation/stable/reference/algorithms/community.html)
