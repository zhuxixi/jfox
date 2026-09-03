---
name: jfox-moc
description: |
  Build and maintain MOC (Map of Content) structure notes for a Zettelkasten
  knowledge base. Diagnose topic cluster density, semi-automatically generate
  structure notes from clusters, and keep members in sync as notes evolve.
  Triggers on: "建 MOC", "MOC", "知识地图", "地图", "structure note",
  "主题导航", "主题簇", "生成地图", "moc create", "moc update",
  "moc diagnose", "批量建 MOC", "MOC 冷启动", "MOC 重构",
  "MOC 覆盖度", "MOC 合并", "MOC 归档".
---

# JFox MOC 地图层

为知识库建立「主题地图层」：诊断永久笔记的主题簇密度，半自动生成 MOC（structure note），并随笔记演化持续维护。

**半自动原则：机器出草稿、人确认落盘**——所有生成/更新先 dry-run 展示 diff，人工确认后才 `--yes` 落盘，绝不静默创建。

> 复用 `/skill:jfox-common` §4.1 共享约定（`--kb` / `--json`，等价于 `--format json`）。

## 何时用

- 知识库 permanent 笔记超过 500–700 条，或某主题笔记靠搜索/双链已「找不全」
- `/skill:jfox-organize` 图谱优化阶段发现主题密集/孤儿多（密度交接）
- 用户说「建 MOC」「做个知识地图」「这个主题有哪些笔记」

**涌现原则**：不预先为所有主题建 MOC——先跑 diagnose 看密度信号，只对有真实规模的主题簇逐个建。

## Step 1: 诊断

```bash
jfox moc diagnose --json --top 10
```

输出解读（JSON 契约）：

- `coverage`：三口径计数（filesystem / vector / bm25）+ `warnings`——口径不一致（如 `vector_orphans` 异常偏高）时先修复索引（见 jfox-common §5），别在 stale 索引上建 MOC
- `threshold_sweep`：各阈值下的簇数与最大簇——用于调阈值
- `suggest`：建议主题簇（`size` / `hub` / `members`，按语义相似度聚类）；生产聚类使用带权 Louvain 社区发现，固定 `seed=42` 和 `resolution=1.0`，以保证结果可复现
- `orphans`：无链接孤儿清单（MOC 收纳候选）

向用户呈现：哪些主题簇已达建 MOC 规模、建议主题名、孤儿情况。

**簇序号时效**：`seed=42` 只保证同一知识库状态下的结果可复现；库一变动（新建/归档 MOC、改笔记标题）Louvain 重跑结果即变，旧簇序号全部失效。每次 create 前重新 diagnose，用 hub 标题确认目标簇，不认旧序号（实测：知识库变动后差点把 CR 簇当 skill 簇建）。

## Step 2: 草稿与确认

选定簇后 dry-run 生成草稿（默认不落盘）：

```bash
jfox moc create --cluster <i> --threshold <t> --title "<主题名>" --json
```

- `--cluster`：簇序号（从 0 起，对应 diagnose 输出顺序）
- `--threshold`：默认 0.75；簇过大被拒时提高阈值拆细子簇再建。显式传入其他阈值仍然有效
- `--title`：MOC 标题（缺省自动从簇内归纳）

展示草稿给用户确认（hub 置顶、按共享 tag 分组、成员清单）。**人工确认主题名与成员取舍**，需修改时用 `--title` / 换簇 / 换阈值重跑 dry-run。

**审成员时效性**：确认草稿前先读成员笔记全文，识别失效/过时笔记——先归档或更新成员，再落盘。直接建 MOC 会把过时结论固化进地图（实测：双 bot 时代的笔记在单 bot 化后已失效）。

**规模护栏**：簇超过 `--max-size`（默认 50）时拒绝生成——这是特性不是 bug，提高 `--threshold` 拆细再建。Louvain 能识别稠密社区，但不保证每个社区都小于护栏；纯链式语料也可能保持为一个社区。

## Step 3: 落盘

用户确认后加 `--yes`：

```bash
jfox moc create --cluster <i> --threshold <t> --title "<主题名>" --yes
```

自动完成：生成 structure note + 成员 backlinks 回填。孤儿可收纳：加 `--include-orphans`（并入「待归类」小节，孤儿 id 同样进 links）。

**管道语法铁律**：MOC 正文一律用 `[[ID|标题]]`（管道左侧 ID 是解析目标，右侧标题仅作显示）。一条规则挡两个坑：

- **同名标题歧义**：`[[标题]]` 解析走「精确标题 → 标题包含」fallback，同名笔记（session-to-permanent 重复产出是主因）会解析到非预期的那条
- **标题含 `#` 截断**：`#` 是锚点分隔符，标题含 issue 号的笔记会被截断，静默丢成员（实测丢 #158/#195 两条）

\#458 修复前，`moc create` 产物正文仍是 `[[标题]]`——`--yes` 落盘前检查成员清单，把标题含 `#` 或有同名风险的成员改写为 `[[ID|标题]]`；#458 修复后 create 产物自动免疫，手写正文仍须遵守。

## Step 4: 维护

新笔记加入主题后 MOC 会过时，定期 diff 维护：

```bash
jfox moc update --json                # 全部 structure note 与最新簇 diff（dry-run 默认）
jfox moc update --id <moc_id> --json  # 单条 MOC
```

- diff 语义：`add` 新增成员、`remove` 死链（仅以磁盘存在性判定，防 stale index）、`kept` 保留
- **只摘死链，语义漂移不自动摘除**——笔记偏离主题不自动移除，交人工判断
- 确认 diff 后加 `--yes` 应用

维护节奏建议：每批次新笔记落库后跑一次，或随 organize 定期整理一起做。

## 批量建设与成员质量审查（冷启动/重构）

适用场景：从 0 批量建多个 MOC，或大规模重构现有地图层（归档/合并旧 MOC）。单 MOC 日常生命周期走 Step 1-4；批量场景在每一步上多一道质量闸。

### 批量主流程

diagnose → 逐簇 dry-run + 审成员时效性（Step 2 规则）→ 落盘并执行管道铁律（Step 3 规则）→ 覆盖度核查 →（可选）合并/归档。每建完一个 MOC 立即做覆盖度核查，不要攒到全部建完。

### 无独立簇时：手动建 MOC

语义聚类聚不出簇的主题（平台层笔记被大簇吸收、provider 配置散落各簇等）走手动路径：

1. 关键词搜索收集候选成员（多组关键词覆盖同义表述）
2. 与现有 MOC 成员做差集，排除已归属笔记
3. 分组呈现给用户确认主题名与成员取舍
4. 确认后落盘：`jfox add --type structure --tag moc --title "<主题名>" --content-file <草稿.md>`，正文成员一律 `[[ID|标题]]`（Step 3 铁律）

手动建的 MOC 与 create 产物同受 `moc update` 管理（update 按 type=structure 扫描，与创建方式无关）。#484（moc add-member 命令）落地后手动补成员可简化；落地前手动加成员会踩 #470（edit 用正文解析结果覆盖 frontmatter links 且不去重）——正文 wiki-links 与 frontmatter links 必须同步维护。

### 覆盖度核查

语义聚类会漏掉主题相关笔记（实测：CR MOC 初版漏 16 条，含 2 条核心根笔记）。每个 MOC 建完后必做：

1. 主题关键词 `jfox search "<关键词>" --mode hybrid --type permanent`，多组关键词各取 top 20-50
2. 搜索结果与 MOC 成员 links 做差集
3. 差集中确实属于主题的，按手动路径补入

附：`jfox list --type structure` 默认 limit 10 会漏 MOC，盘点全量 MOC 时 `--limit 20` 起步。

### 合并与归档处置

- **旧 MOC 无意义 → 归档**：`jfox archive <moc_id>`。structure note 归档不影响成员笔记（实测：2026-08-27 测试批次 7 个 MOC 全部归档）
- **两 MOC 主题重叠 → 合并**：保留主题更准确的 MOC，把另一 MOC 的独有成员按手动路径补入，然后归档被并者（实测：TUI MOC 并入 pi-agent-board 大 MOC）

## 关键原则

- MOC 默认阈值与聚类算法只影响 `moc create`、`moc update`、`moc diagnose`；其他 jfox 命令不受影响。生产 Louvain 不通过 MOC CLI 暴露 `resolution` 参数。

- MOC 稳定骨架只链接 permanent；session 不固化进骨架（近期活动动态引用，不入 links）
- structure 类型默认可被 hybrid search 命中——检索到 MOC 即获主题鸟瞰图，顺 links 定位具体笔记
- MOC 成员即 `links`（笔记 ID 列表），改成员就是改 links

## 错误处理

- `No structure notes found` → 先 `jfox moc create` 建第一条
- 簇超过 `--max-size` 被拒 → 提高 `--threshold` 拆细（Step 2）
- coverage 三口径不一致 → 先修索引（jfox-common §5），stale 索引会产出错误成员
- 孤儿过多（> 总 permanent 20%）→ 先走 `/skill:jfox-organize` 图谱优化补链，剩余再 `--include-orphans` 收纳

## 与 jfox-organize 的边界

- organize 管单条笔记加链接（inbox 提炼 + 图谱补链）
- jfox-moc 管主题簇地图（诊断 → 生成 → 维护）
- 组织中发现密度信号 → 移交本 skill；本 skill 发现孤儿太多 → 移交 organize
