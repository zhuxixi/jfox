---
name: jfox-moc
description: |
  Build and maintain MOC (Map of Content) structure notes for a Zettelkasten
  knowledge base. Diagnose topic cluster density, semi-automatically generate
  structure notes from clusters, and keep members in sync as notes evolve.
  Triggers on: "建 MOC", "MOC", "知识地图", "地图", "structure note",
  "主题导航", "主题簇", "生成地图", "moc create", "moc update",
  "moc diagnose".
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

## Step 2: 草稿与确认

选定簇后 dry-run 生成草稿（默认不落盘）：

```bash
jfox moc create --cluster <i> --threshold <t> --title "<主题名>" --json
```

- `--cluster`：簇序号（从 0 起，对应 diagnose 输出顺序）
- `--threshold`：默认 0.75；簇过大被拒时提高阈值拆细子簇再建。显式传入其他阈值仍然有效
- `--title`：MOC 标题（缺省自动从簇内归纳）

展示草稿给用户确认（hub 置顶、按共享 tag 分组、成员清单）。**人工确认主题名与成员取舍**，需修改时用 `--title` / 换簇 / 换阈值重跑 dry-run。

**规模护栏**：簇超过 `--max-size`（默认 50）时拒绝生成——这是特性不是 bug，提高 `--threshold` 拆细再建。Louvain 能识别稠密社区，但不保证每个社区都小于护栏；纯链式语料也可能保持为一个社区。

## Step 3: 落盘

用户确认后加 `--yes`：

```bash
jfox moc create --cluster <i> --threshold <t> --title "<主题名>" --yes
```

自动完成：生成 structure note + 成员 backlinks 回填。孤儿可收纳：加 `--include-orphans`（并入「待归类」小节，孤儿 id 同样进 links）。

## Step 4: 维护

新笔记加入主题后 MOC 会过时，定期 diff 维护：

```bash
jfox moc update --json                # 全部 structure note 与最新簇 diff（dry-run 默认）
jfox moc update --id <moc_id> --json  # 单条 MOC
```

- diff 语义：`add` 新增成员、`remove` 死链（仅以磁盘存在性判定，防 stale index）、`kept` 保留
- **只摘死链，语义漂移不自动摘除**——笔记偏离主题不自动移除，交人工判断
- 确认 diff 后加 `--yes` 应用

维护节奏建议：每批次新笔记落库后跑一次，或随 organize 定期整理一起做。注意：新笔记的 MOC 归属主路径是沉淀时确认（session-to-permanent + `jfox moc add-member`，见下节），本命令是批量兜底。

## 单成员增删：add-member / remove-member

对单个成员做精准增删（也承接 session-to-permanent 沉淀时的归属挂载）：

```bash
jfox moc add-member <moc_id> <note_id> --json                   # 挂入成员（默认按成员 tags 匹配既有分组）
jfox moc add-member <moc_id> <note_id> --group "<组名>" --json  # 显式指定落位分组
jfox moc remove-member <moc_id> <note_id> --json                # 摘除成员（正文行 + links + backlinks 对称清理）
```

- **参数只用笔记 ID**，不解析标题（规避同名标题歧义）；`--group` 不能用「近期活动」「待归类」两个保留区段。
- **幂等且自修复**：重复 add 不产生重复行；frontmatter links、正文成员行、成员 backlinks 三处缺哪补哪，已一致时返回 no-op。
- **正文成员行一律 `[[ID|标题]]`**——ID 是链接目标，标题只是显示别名，规避标题含 `#` 被截断、同名标题解析歧义两类死链。不要新写只有标题的 `[[标题]]` 成员链接。
- **存量旧标题行安全处理**：标题全库唯一时可被 add 原地改写为 ID 形式、被 remove 删除；同名歧义时不猜测，保留旧行并返回 warning（`partial: true`）。不做全库自动迁移。
- **归档与自链**：已归档的 MOC 或成员拒绝 add；remove 允许清理死链（成员已删除时只清 links 与正文 ID 行）。
- `partial: true` 表示主操作已成功但仍有未收敛状态，`warnings` 会给出具体 ID 和重试命令。

**职责定位**：session-to-permanent 沉淀新笔记时的归属确认是主路径——新笔记落库即入图；`moc update` 是批量兜底，负责漏挂的存量笔记与语义漂移的 diff 审阅，不承担单条精准操作。

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
