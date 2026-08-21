# Spec: 新增 structure note type + MOC 生成/维护命令（#413）

> Epic #376 第二个子任务。上游：#390 诊断（v1.8.0 已发布）。下游：jfox-moc skill。
> 调研：见 issue #413 评论（轮 1 实现链路、轮 2 设计边界）。

## 1. 目标

给 jfox 补「主题层」的生成能力：

1. 新增第 6 种笔记类型 `structure`，承载地图型笔记（MOC）。
2. 新增 `jfox moc create`：消费诊断簇 → 生成 MOC 草稿 → 人工确认落盘。
3. 新增 `jfox moc update`：重扫簇 → diff 现有 MOC 成员 → 确认增删，防死链。

一句话：**把 diagnose 发现的「该建 MOC 的主题簇」变成活的、可维护的 MOC 笔记。**

## 2. 非目标

- 不预先为所有主题建 MOC（涌现原则，按密度信号逐个建）
- 不做笔记演化/保鲜回路（#389 backlog）
- 不做「近期活动」动态区段聚合（本 issue 只定义正文小节约定，不实现）
- 不动 candidate 层 / promote 簇级 triage
- 不做 ranking 层 structure 加权（Epic 决策：后续优化，MVP 不需要）

## 3. 心智模型

```
diagnose（已有）                    create（本 issue）                 update（本 issue）
  Chroma 快照                          ┌─ 规模护栏：簇 > max-size 拒绝 ─┐
  → 余弦相似度矩阵                      │  → 提示提高阈值/选子簇         │
  → 连通分量簇                          ▼                               ▼
  → ClusterSummary{size, hub,      草稿渲染（tags 分组 + 成员列表）   重扫簇 vs MOC.links
      members[]}                   → dry-run 展示                     → diff（新增/已归档/死链）
                                   → --yes 落盘 structure/            → 确认应用，回填 backlinks
                                     YYYYMMDDHHMMSS-{slug}.md
```

## 4. 核心决策

### D1：`NoteType.STRUCTURE = "structure"`，MVP 无特有 frontmatter 字段

- 备选 A：复用 permanent + 特殊 tag。否决——类型语义混淆（导航 vs 内容），且搜索筛选、归档语义要特殊 case。
- 备选 B：structure + 特有字段（如 `members:` 列表）。否决——`links: List[str]` 就是成员列表（笔记 ID），无需重复字段；`topic` 已有先例表明"类型特有字段"会加重序列化特判面。
- 理由：candidate 先例（cc53815）证明枚举加值改动面 = models.py 数行 + 测试；筛选三层（vector/bm25/search）字符串透传零改动；目录 `notes_dir/value` 自动生成 `structure/`。

### D2：命令形态 `jfox moc create` / `jfox moc update`

- 备选：`moc generate` / `moc build`。否决——create/update 与 jfox 现有动词风格（add/edit/delete）一致，且 update 语义（维护）没有对等动词。
- 备选：organize Step 4。否决——CLI 命令是基础层，skill（jfox-moc）在命令之上编排；organize 流程由 skill 串联。
- 命令挂 `jfox moc` 子命令组（与 diagnose 同级）。

### D3：草稿-确认交互（dry-run 默认 + `--yes` 落盘）

- 默认行为：输出草稿（table 预览 + `--format json` 完整契约），**不落盘**。
- `--yes`：跳过确认直接落盘（非交互脚本场景）。
- 标题缺失时交互：`typer.confirm` 让用户确认自动候选标题或输入自定义。
- 理由：遵循现有先例（delete --force、model download --force、kb remove --force），CLI 面向 agent 与脚本，默认安全。

### D4：规模护栏 `--max-size`（默认 50）

- 簇 size > max-size → typed error，不生成草稿；提示用更高 `--threshold` 拆分或指定子簇。
- 理由：实测 483 条超载簇一个 MOC 装不下；MOC 的价值在「可读的导航入口」，50 条已是人读上限的宽松值。
- 护栏只拦自动路径，人工可 `--max-size 1000` 显式覆盖（知道自己在干什么）。

### D5：MOC 正文格式（人可读的导航笔记）

```markdown
---
id: ...
title: <hub 标题派生，可人工改>
type: structure
created/updated/tags/links/backlinks: 常规字段
---

# <主题名>

一句话职责（草稿留空或从 hub 标题派生，人工补）。

## <tag 分组 A>          ← 成员按共享 tag 分组（≥2 条同 tag 成组）
- [[成员标题]] — <link_degree> 链 / <mean_similarity> 语义贴近度
...

## 其他
- [[...]] ...

## 近期活动             ← 本 issue 只定义小节约定，内容后续动态聚合
（留空占位）
```

- 分组规则：成员 tag 交集计数，≥2 条共享 tag 且覆盖簇内 ≥10% 成员者成组；余下「其他」。
- 排序：组内按 mean_similarity 降序（最贴近簇中心在前）；hub 笔记置顶标记。
- 正文正文用 wiki 链接 `[[标题]]`（现有双链语法），frontmatter links 记录 ID。

### D6：成员过滤（谁进 MOC）

- 只收 live、未归档的 permanent（与 diagnose 口径一致）。
- 落盘前校验每个成员文件存在；已归档/ghost 的成员跳过并计入 warning。
- `--include-orphans`：孤儿笔记并入候选（「待归类」小节）；默认不含孤儿。

### D7：update 语义（维护 = 重扫 + diff）

- 输入：`--id <MOC id>`（默认全部 structure 笔记，逐个 diff）。
- 过程：重扫当前 KB 簇（相同阈值/参数）→ 计算「MOC 当前 links 集合」与「簇成员集合」的差集：
  - **建议新增**：簇内新笔记（语义贴近且不在 links 中）
  - **建议摘除**：links 中已归档/不存在（死链）的成员
  - **保持不动**：links 中仍 live 的成员（即使语义漂移——不主动删，除非死链；语义漂移的摘除是人工判断）
- `--yes` 应用增删并回填成员 backlinks；默认 dry-run 输出 diff 表。

### D8：backlinks 回填

- create/update 落盘后，成员笔记 frontmatter 的 backlinks 应包含 MOC id。
- 沿用现有 backlinks 自动生成机制（note.py 写路径）；如现有机制只处理「保存时自扫」，则 create/update 显式触发一次回填。实现时验证，不改 backlinks 架构（#287 缓存优化不在本 issue）。

### D9：复用 diagnose 基建

- 聚类计算直接调 `moc/cluster.py` 的函数（find_clusters_at_threshold 等），不重写。
- 沿用一致性快照只读路径（防撕裂快照）+ 5000 条上限 + typed error 风格。

## 5. 组件契约

### 5.1 models.py

```python
class NoteType(Enum):
    ...
    STRUCTURE = "structure"  # 地图型笔记（MOC），导航/组织层
```

### 5.2 `jfox moc create`

```
jfox moc create [OPTIONS]
  --threshold FLOAT    [default: 0.65]
  --cluster INTEGER    [default: 0]  # 0-based，按 size 降序（diagnose 顺序）
  --max-size INTEGER   [default: 50]
  --title TEXT         # 默认 hub 标题派生
  --include-orphans
  --yes                 # 跳过确认落盘
  --format table|json   # [default: table]
```

JSON 契约（`--format json`）:

```json
{
  "success": true,
  "cluster": {"threshold": 0.65, "size": 42, "hub": {...}},
  "draft": {
    "title": "...",
    "groups": [{"name": "tag-a", "members": [{...member}]}, ...],
    "orphan_bucket": [...],
    "total_members": 42
  },
  "created": null | {"id": "...", "filepath": "..."},
  "warnings": [...]
}
```

### 5.3 `jfox moc update`

```
jfox moc update [OPTIONS]
  --id TEXT      # MOC 笔记 id；缺省=全部 structure 逐个 diff
  --threshold FLOAT  [default: 0.65]
  --yes
  --format table|json
```

JSON 契约: `{"success": true, "updates": [{"moc_id": ..., "add": [...], "remove": [...], "kept": N}], "warnings": [...]}`

## 6. 错误与降级

| 情形 | 行为 |
|------|------|
| 簇 size > max-size | typed error + 建议（提阈值/选子簇/显式覆盖） |
| 向量库空/无 embedding | 复用 diagnose 现有错误路径 |
| 快照不稳定（daemon 写入中） | 复用 diagnose 的重试/typed error |
| 成员已归档/文件缺失 | 跳过 + warning，不中断 |
| 标题重复（同名 structure 已存在） | 复用 add 的 slug/防重机制（#383 若已修则复用） |

## 7. 测试要点

1. NoteType.STRUCTURE 枚举 + to_markdown/from_markdown roundtrip。
2. cli --type 错误消息动态覆盖全部 6 类型（顺带修 candidate 遗漏的小债）。
3. `moc create`：dry-run 不落盘；--yes 落盘 `structure/` 目录 + links 正确；超限拒绝；孤儿并入候选。
4. `moc update`：新增成员进 links；死链摘除；live 成员不被误删；backlinks 回填正确。
5. structure 笔记可被 `jfox search`（hybrid）命中、`jfox list --type structure` 可见。
6. JSON 契约快照测试（与 diagnose 现有契约测试同风格）。

## 8. 已确认决策（2026-08-22 用户拍板）

1. ✅ 命令名 `moc create` / `moc update`
2. ✅ `--max-size` 默认 50（超载簇强制先拆细）
3. ✅ MOC 正文按共享 tag 分组（≥2 条共享 tag 成组，余下「其他」）
4. ✅ 孤儿收纳走 `create --include-orphans`（并入「待归类」小节）
