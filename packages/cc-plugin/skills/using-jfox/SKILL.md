---
name: using-jfox
description: |
  Use when the user asks meta or overview questions about jfox as a whole — what jfox
  can do, how to get started, or which jfox skill/command fits their goal. Triggers on
  "jfox 能做什么", "jfox 怎么用", "知识库怎么用", "我该用哪个 jfox 命令", "我该用哪个
  jfox skill", "jfox 有哪些功能", "jfox 入门", "jfox overview", "what can jfox do",
  "which jfox skill". This skill orients the user and routes to the specific skill; it
  is not for performing a concrete action.
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
| 搜索 / 查找笔记、检索知识 | `search` | 搜索 / 查找 / find |
| 把 git 仓库 / PR / issues 导入成素材 | `ingest` | 导入仓库 / ingest repo |
| 提炼 fleeting→permanent、清理 inbox、补 wiki link、优化图谱 | `organize` | 整理 / 提炼 / clean inbox |
| 把当前会话总结存入知识库 | `session-summary` | 保存会话 / save session |
| 从当前会话提炼可复用知识为 permanent | `session-to-permanent` | 提炼到永久笔记 / session to permanent |
| 创建 / 切换 / 删除知识库、命令参考、健康检查、daemon | `manage` | 创建知识库 / kb status / 健康检查 |

6 个 skill 一句话职责：

- **search** — 笔记检索：BM25 / 语义 / 混合搜索 + 知识图谱查询。
- **ingest** — git 仓库 → fleeting 素材笔记（git log / PR / issues）。
- **organize** — fleeting → permanent 提炼 + 图谱优化（orphans / 补链）。
- **session-summary** — 当前会话 → 知识库笔记（存档型，直接写入）。
- **session-to-permanent** — 当前会话 → permanent（先比对已有 permanent 去重，审阅后落库）。
- **manage** — 知识库生命周期 + 笔记 CRUD 权威参考 + 健康检查 + embedding daemon。

## 笔记模型（一句话）

JFox 笔记分 fleeting / literature / permanent 三类，靠 `[[wiki link]]` 互链。完整的模型与提炼流程见 **organize** skill（Step 1 收件箱分析、Step 2 提炼）。

## 典型复合工作流

1. **沉淀新知识**：`ingest`（导入素材为 fleeting）→ `organize`（提炼成 permanent + 补 `[[wiki link]]`）→ `search`（日后检索复用）。
2. **会话沉淀**：会话末尾按需选择——`session-summary`（整段对话存档）或 `session-to-permanent`（提炼可复用知识为 permanent，先去重再审阅落库）。
3. **知识库维护**：`manage`（§5 体检 / 衰减信号检测）→ `organize`（清理 orphans / 补链接）。

## 公共约定（一句话）

所有 jfox 命令支持 `--kb <name>` 指定知识库、`--json`（等价于 `--format json`）输出 JSON、`--content-file <path>` 从文件读取长内容。完整约定见 **manage** skill §4.1。

## 本 skill 不做

- 不执行具体动作（搜索 / 导入 / 整理 / 保存会话 / 管理）——交给对应 skill。
- 不重复各 skill 的命令速查——命令在各 skill 内有权威版本。
