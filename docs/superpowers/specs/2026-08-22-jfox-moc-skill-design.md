# Design: jfox-moc skill + jfox-organize 密度交接（#417）

> Issue: #417（Epic #376 子任务）｜状态：已与用户确认（2026-08-22）

## 背景

Epic #376「引入 MOC / structure note 层」拆出的子任务：#390 诊断命令（✅ v1.8.0）、#413 CLI 生成/维护（✅ v1.9.0）均已完成。CLI 侧 `jfox moc diagnose / create / update` + `structure` note type 已就绪，本设计负责 **skill 层编排**——在 CLI 之上编排人工确认环节。

方案 C（用户选定）：独立 `jfox-moc` skill + `jfox-organize` 只加一处「密度交接」触发点 + `jfox-overview` 路由更新。仅 pi 版，不动 kimi-cli。

## 决策依据

- **为什么独立 skill 而非并入 organize**：工作流节奏不同——organize 是一次性清理（inbox 空了就结束），MOC 是持续维护循环（新笔记加入需同步 update）。独立后每个 skill 单一职责，触发词不互相污染。
- **为什么 organize 加密度交接**：呼应 #390 设计哲学（诊断先行、按密度信号建 MOC）。图谱优化阶段发现主题密集/孤儿多，正是建 MOC 的涌现触发点。
- 与 #413 ADR 永久笔记「后续 jfox-moc skill 在这两个命令之上编排人工确认环节」一致。

## 文件改动

```
skills-recommend/pi/jfox-moc/SKILL.md   # 新增：MOC 地图层生成与维护
skills-recommend/pi/jfox-organize/SKILL.md  # 修改：Step 3 末尾加「密度交接」小节（唯一改动点）
skills-recommend/pi/jfox-overview/SKILL.md  # 修改：路由表 + 工作流示例加 jfox-moc
```

## 1. jfox-moc/SKILL.md 设计

### frontmatter

- `name: jfox-moc`
- description 说明：MOC 地图层生成与维护——诊断主题簇密度、半自动生成 structure note、定期 diff 维护成员。
- 触发词：「建 MOC」「MOC」「知识地图」「地图」「structure note」「主题导航」「主题簇」「moc create」「moc update」「moc diagnose」「生成地图」。**刻意不含**「整理」「组织」等 organize 类词，避免路由歧义。

### 核心工作流（5 步，编排人工确认）

1. **诊断**：`jfox moc diagnose --json` → 呈现 coverage 口径对比、阈值扫描、主题簇（hub + members）、孤儿清单。
2. **草稿确认**：选定簇 → `jfox moc create --cluster <i> --threshold <t> [--title <主题名>]`（dry-run 默认）→ 展示草稿（hub 置顶、按共享 tag 分组、成员清单）→ 人工确认主题名与成员取舍（可增删）。
3. **落盘**：确认后 `--yes` 重跑 → 生成 structure note、回填成员 backlinks。
4. **维护**：定期 `jfox moc update --format json` 看 diff（add/remove/kept）→ 人工确认后 `--yes` 应用。**只摘死链**（磁盘存在性为准，防 stale index），语义漂移不自动摘除。
5. **孤儿收纳**：`create --include-orphans` 并入「待归类」小节；或移交 organize 图谱优化补链。

### 内嵌原则

- **涌现原则**：不预先为所有主题建 MOC，按 diagnose 密度信号逐个建。
- **规模护栏**：簇超 `--max-size`（默认 50）时拒绝生成，提示提高 `--threshold` 拆细子簇再建。
- **稳定骨架**：MOC links 只链接 permanent；session 走动态「近期活动」区段，不固化进骨架。
- **导航入口**：structure 类型默认可被 hybrid search 命中，agent 搜到 MOC 即获鸟瞰图。

### 命令参数对齐（与 CLI v1.9.0 实测契约一致）

| CLI 参数 | skill 中的用法 |
|---|---|
| `diagnose --thresholds 0.55,0.6,0.65,0.7 --top N` | 默认阈值串；大 KB 调大 top |
| `create --cluster <i> --threshold <t> --max-size 50` | 默认 dry-run；确认后加 `--yes` |
| `update [--id <moc_id>]` | 缺省扫全部 structure note |
| 所有命令 `--kb` / `--format json` | 复用 jfox-common §4.1 共享约定 |

## 2. jfox-organize 改动（唯一改动点）

Step 3 图谱优化末尾追加小节：

```markdown
### 密度交接（MOC 触发点）

图谱优化发现某主题笔记数量多（靠搜索/双链找不全）或孤儿笔记密集时，
说明该主题已达建 MOC 阈值——移交 `/skill:jfox-moc`（moc diagnose → create）。

职责边界：organize 管单条笔记加链接；jfox-moc 管主题簇地图。
```

不改 description / 触发词 / 其他任何内容。

## 3. jfox-overview 改动

- 路由表加一行：`| MOC 地图层（诊断/生成/维护主题地图） | jfox-moc | 建 MOC / 知识地图 / structure |`
- 「知识库维护」工作流示例补链路：`jfox-organize`（图谱优化发现密度）→ `jfox-moc`（建/维护主题地图）。

## 4. 验证

1. skill 中所有命令/参数与 CLI 实际输出契约一致（`jfox moc --help` + 真实 KB dry-run 比对）。
2. 真实簇走通：diagnose → create dry-run → 人工确认 → `--yes` 落盘 → update diff（在真实 KB，不落垃圾——用 dry-run 验证即可，落盘前经用户确认）。
3. 触发词自检：与其他 15 个 skill 无重叠歧义。
4. organize diff 只有 Step 3 末尾一处新增。

## 非目标

- 不动 CLI 代码（#413 已完成）
- 不动 kimi-cli 那套 skill
- 不做笔记演化/保鲜回路（#389 backlog）
- 不在 ranking 层给 structure 加权（#376 定为后续优化）
