---
name: jfox-overview
description: |
  Answer meta or overview questions about jfox as a whole—what jfox can do, how to get
  started, or which jfox skill/command fits the user's goal.
  Triggers on: "jfox 能做什么", "jfox 怎么用", "知识库怎么用", "我该用哪个 jfox 命令",
  "我该用哪个 jfox skill", "jfox 有哪些功能", "jfox 入门", "jfox overview",
  "what can jfox do", "which jfox skill", "jfox 总览".
  This skill orients the user and routes to the specific skill; it is not for performing
  a concrete action.
---

# JFox 总览与路由

JFox 是一个本地优先的 Zettelkasten 知识管理 CLI：混合搜索（BM25 + 语义）、知识图谱、多知识库，并提供 Claude Code / Kimi Code 插件集成。

本 skill **只做总览与路由**：帮你判断「该用哪个 skill」，然后把具体动作派发出去。它不自己执行搜索 / 导入 / 整理 / 保存会话 / 管理这些动作。

## 环境检查

确认 jfox 已安装：

```bash
jfox --version
```

未安装时：

```bash
uv tool install jfox-cli
```

## 我该用哪个 skill

| 你想做的 | 用这个 skill | 典型触发词 |
|---------|-------------|-----------|
| 搜索 / 查找笔记、检索知识 | `jfox-search` | 搜索 / 查找 / find |
| 把 git 仓库 / PR / issues 导入成素材 | `jfox-ingest` | 导入仓库 / ingest repo |
| 提炼 fleeting→permanent、清理 inbox、补 wiki link、优化图谱 | `jfox-organize` | 整理 / 提炼 / clean inbox |
| 诊断主题簇密度、生成/维护 MOC 地图（structure note） | `jfox-moc` | 建 MOC / 知识地图 / structure |
| 过审 gem-synth 候选宝石、晋升为 permanent 或拒绝归档 | `jfox-promote` | 过审 candidate / promote / L5 晋升 |
| 把当前会话总结存入知识库（存档，不提炼） | `jfox-session-summary` | 保存会话 / save session |
| 把当前会话里的现状/事实/决策提炼为 permanent（强制去重 + 落库前审阅） | `jfox-session-to-permanent` | 提炼到永久笔记 / session to permanent |
| 创建 / 切换 / 删除知识库、命令参考、健康检查、daemon | `jfox-common` | 创建知识库 / kb status / 健康检查 |
| 把读过的书作为资产管进书架（PDF + scan2book bundle） | `jfox-bookshelf` | 书架 / 加书 / bookshelf |
| 触发 GitHub Actions CI 测试 | `jfox-ci` | 跑测试 / 跑 ci / run tests |
| 发版（bump → CHANGELOG → PR → Release） | `jfox-release` | 发版 / release / bump version |
| 发 cc-plugin（Claude Code marketplace） | `jfox-release-cc-plugin` | 发 cc-plugin / plugin 发版 |
| 发 kimi-plugin | `jfox-release-kimi-plugin` | 发 kimi-plugin / bump kimi version |
| 三件套编排发版（jfox + cc + kimi） | `jfox-release-all` | 全发 / release all / 三件套发版 |

15 个 skill 一句话职责：

- **jfox-search** — 笔记检索：BM25 / 语义 / 混合搜索 + 知识图谱查询。
- **jfox-ingest** — git 仓库 → fleeting 素材笔记（git log / PR / issues）。
- **jfox-organize** — fleeting → permanent 提炼 + 图谱优化（orphans / 补链）。
- **jfox-moc** — MOC 地图层：诊断主题簇密度、半自动生成/维护 structure note（dry-run 确认制）。
- **jfox-promote** — gem-synth 候选宝石过审（三模式：客观去重 / 簇级 triage / 单条 A/B/C + 冗余维度）。
- **jfox-session-summary** — 当前会话 → 知识库笔记（存档，不提炼）。
- **jfox-session-to-permanent** — 当前会话 → permanent：把当前现状/事实/ADR 沉淀为永久笔记（强制去重 + 落库前审阅）。
- **jfox-common** — 知识库生命周期 + 笔记 CRUD 权威参考 + 健康检查 + embedding daemon。
- **jfox-bookshelf** — 书架资产管理：PDF + scan2book bundle，纯文件管理不进索引。
- **jfox-ci** — 触发 GitHub Actions CI（fast / full / core）。
- **jfox-release** — jfox CLI 版本发布：bump → CHANGELOG verify → PR → GitHub Release。
- **jfox-release-cc-plugin** — cc-plugin（Claude Code marketplace）发版：三处版本同步 bump → PR。
- **jfox-release-kimi-plugin** — kimi-plugin 发版：单一版本号 bump → PR。
- **jfox-release-all** — 三件套编排发版：detect 改动 → 跳过无改动者 → 批量 bump PR → jfox Release。

## 笔记模型（一句话）

JFox 笔记分 fleeting / literature / permanent 三类（另有 session / candidate / structure——MOC 地图笔记），靠 `[[wiki link]]` 互链。完整的模型与提炼流程见 **jfox-organize** skill（Step 1 收件箱分析、Step 2 提炼）；候选宝石的来龙去脉见 **jfox-promote** skill；structure 类型的地图层管理见 **jfox-moc** skill。

## 典型复合工作流

1. **沉淀新知识**：`jfox-ingest`（导入素材为 fleeting）→ `jfox-organize`（提炼成 permanent + 补 `[[wiki link]]`）→ `jfox-search`（日后检索复用）。
2. **知识闭环（含 AI 合成）**：碎片采集（后台）→ gem-synth 合成 candidate → `jfox-promote`（过审晋升 permanent）→ `jfox-search`。
3. **会话沉淀**：只需存档对话用 `jfox-session-summary`（存为 session 笔记，记录行为历史）；要把这次对话里的当前现状（事实/决策/ADR）提炼为 permanent，用 `jfox-session-to-permanent`（强制去重 + 落库前审阅）。
4. **知识库维护**：`jfox-common`（§5 体检 / 衰减信号检测）→ `jfox-organize`（清理 orphans / 补链接；图谱优化发现主题密集时交接 jfox-moc）→ `jfox-moc`（建/维护主题地图）。
5. **发版**：`jfox-ci`（PR 前跑 fast 测试）→ `jfox-release`（bump + CHANGELOG + PR + Release）；多组件同时发用 `jfox-release-all` 编排。

## 公共约定（一句话）

所有 jfox 命令支持 `--kb <name>` 指定知识库、`--json`（等价于 `--format json`）输出 JSON、`--content-file <path>` 从文件读取长内容。完整约定见 **jfox-common** skill §4.1。

## 本 skill 不做

- 不执行具体动作（搜索 / 导入 / 整理 / 过审 / 保存会话 / 管理 / 书架 / CI / 发版）——交给对应 skill。
- 不重复各 skill 的命令速查——命令在各 skill 内有权威版本。
