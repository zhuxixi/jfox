---
name: jfox-organize
description: Use when user wants to organize their Zettelkasten, refine fleeting notes into permanent notes, add wiki links, or optimize the knowledge graph. Triggers on "整理知识库", "清理 inbox", "提炼笔记", "组织笔记", "看看有什么可以整理的", "合并笔记", "生成链接", "organize", "process inbox", "refine notes", "knowledge graph optimization".
---

# JFox 知识库整理与提炼

JFox 的核心提炼技能。将原始 fleeting 笔记转化为结构良好、互相链接的 permanent 知识。

三步流程：收件箱分析 → 提炼（fleeting → permanent，自动生成 `[[wiki links]]`）→ 图谱优化。

此外支持在整理过程中直接创建和编辑笔记。

## 前置条件

知识库中已有笔记。如果知识库为空，建议先运行 `/jfox-ingest` 导入内容。

## Step 1: Inbox 分析

```bash
jfox inbox --json --limit 50
```

列出所有 fleeting（未处理）笔记。对结果进行分组分析：

1. **按 `source:*` 标签分组**：例如所有 `source:git-log` 的笔记归为一组
2. **组内识别可合并子组**：主题相近、相关的 commits/issues 归入同一子组
3. 向用户展示提炼建议：

```
收件箱: N 条 fleeting 笔记

提炼建议:
1. [合并] 15 条 jfox git-log commits → "JFox 近期开发总结" (permanent)
2. [合并] 5 条 jfox PR → "JFox PR 技术决策汇总" (permanent)
3. [逐条] 3 条手动输入笔记 → 逐条处理
4. [删除] 2 条过时笔记 → 清理
```

等待用户确认要执行哪些建议。

## Step 2: 提炼（fleeting → permanent）

这是本技能的核心能力。对用户确认的每条建议执行提炼：

### 提炼流程

1. **分析**：阅读分组内的 fleeting 笔记，提取核心知识点
2. **查找关联**：
   ```bash
   jfox suggest-links "<提炼后的内容摘要>" --format json
   ```
   筛选 score >= 0.6 的关联笔记
3. **生成 permanent 笔记**：将核心知识点整理为结构化内容，嵌入 `[[wiki links]]` 关联到已有笔记
4. **批量交叉链接**：如果同一批正在创建多条 permanent 笔记，在它们之间也添加 `[[links]]`
5. **插入**：
   ```bash
   jfox add "<包含 [[links]] 的内容>" --title "<标题>" --type permanent --tag <tag1> --tag <tag2> [--kb <name>]
   ```
6. **删除源 fleeting**：
   ```bash
   jfox delete <原始-id> --force
   ```

> **注意**：`jfox add` 和 `jfox delete` 使用 `--json`/`--no-json`（默认开启），不要用 `--format json`。

### 提炼策略表

| 来源 | 策略 | permanent 示例 |
|------|------|---------------|
| git-log（多个 commits） | 按时间段/主题合并，提取技术决策和变更摘要 | "JFox v0.1.4 技术变更总结" |
| github-pr（多个 PRs） | 提取核心设计决策、争议点、最终方案 | "JFox PR#94 编辑命令的设计讨论" |
| github-issue（多个 issues） | 提取问题本质、解决方案、经验教训 | "JFox BM25 索引问题及修复方案" |
| 手动输入 | 根据内容判断是否值得提炼，内容足够成熟则转为 permanent | — |

## Step 3: 图谱优化

### 查找孤立笔记

```bash
jfox graph --orphans --json
```

对每条孤立的 permanent 笔记：

1. 获取笔记内容
2. 查找关联：
   ```bash
   jfox suggest-links "<内容>" --format json
   ```
3. 如果有匹配度 >= 0.6 的结果，建议添加链接：
   ```bash
   jfox edit <孤立笔记_id> --content "原内容... [[相关笔记标题]]"
   ```

> **注意**：`jfox edit` 使用 `--json`/`--no-json`（默认开启），不要用 `--format json`。

### 确认改善

```bash
jfox graph --stats --json
```

向用户报告前后对比：

| 指标 | 含义 | 健康目标 |
|------|------|---------|
| `avg_degree` | 平均每条笔记的链接数 | > 2.0 |
| `isolated_nodes` | 无链接的孤立笔记数 | < 总数的 20% |

展示整理前后的指标变化。

## 直接创建笔记

在整理过程中，用户可能想直接创建或编辑一条笔记：

**创建笔记**：
```bash
jfox add "<内容>" --title "<标题>" --type <fleeting|permanent> --tag <tags> [--kb <name>]
```

对于 permanent 笔记，先运行 `jfox suggest-links` 查找 `[[wiki links]]` 再插入。

**编辑已有笔记**：
```bash
# 编辑内容和标题
jfox edit <note_id> --content "新内容" --title "新标题" --tag <tag>

# 在指定知识库中编辑
jfox edit <note_id> --kb <kb-name> --content "新内容"
```

**笔记类型选择参考**：

| 类型 | 使用场景 | 示例 |
|------|---------|------|
| `fleeting` | 快速想法、临时记录，稍后提炼 | "突然想到一个 API 设计思路" |
| `permanent` | 成熟的知识、长期有效的洞察 | "总结出一条设计原则" |

默认类型：`fleeting`（快速记录，后续用本技能提炼）。

## 命令参考

```bash
jfox inbox --json --limit <N>                # 查看收件箱临时笔记
jfox add "<content>" --type permanent --title "<title>" --tag <tags>  # 添加精炼笔记
jfox edit <id> --content "新内容"              # 编辑已有笔记（保留 ID 和时间戳）
jfox delete <id> --force                      # 删除原始笔记
jfox suggest-links "<content>" --format json  # 推荐链接
jfox graph --orphans --json                   # 查找孤立笔记
jfox graph --stats --json                     # 图谱统计指标
jfox list --format json --limit <N>           # 列出笔记
jfox daily --json                             # 查看今天的笔记
```

## 错误处理

- **收件箱为空** → 告知用户 "收件箱为空，无需整理"，可跳到 Step 3 图谱优化
- **`jfox suggest-links` 返回低匹配度**（score < 0.6）→ 跳过链接推荐，不强制添加
- **`jfox delete` 目标 ID 不存在** → 报告错误，跳过继续处理其他笔记
- **`jfox add` / `jfox edit` / `jfox delete` 使用 `--json`/`--no-json`**，不要用 `--format json`

## 使用建议

- **定期整理**：建议每周处理一次收件箱，避免 fleeting 笔记堆积超过 30 条
- **大胆链接**：Zettelkasten 的价值在于连接，而非数量。多使用 `[[links]]` 连接相关概念
- **用标签分组，用链接表达思想**：`--tag` 按主题归类，`[[links]]` 按思维关联
