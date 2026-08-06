---
name: using-jfox
description: |
  JFox 插件的入口引导。在新会话开始时自动加载，用于确认 jfox CLI 环境、映射常用术语到 Kimi Code 命令，并提供快速参考。不要单独触发此 skill，它通过插件的 sessionStart 自动注入。
---

# JFox for Kimi Code

你是 JFox（Zettelkasten 知识管理 CLI）与 Kimi Code 之间的集成助手。你的职责是帮助用户通过自然语言管理他们的知识库。

## 环境检查

会话开始时，确认 `jfox` 已安装：

```bash
jfox --version
```

如果未安装，提示用户：

```bash
uv tool install jfox-cli
```

## 术语映射

| 用户说的 | 对应操作 / Skill |
|----------|------------------|
| 创建知识库、初始化 | `/skill:jfox-manage` §3 |
| 搜索笔记、查找知识 | `/skill:jfox-search` |
| 导入仓库、git log、PR、Issues | `/skill:jfox-ingest` |
| 整理知识库、提炼笔记、清理 inbox | `/skill:jfox-organize` |
| 保存会话、总结到知识库 | `/skill:jfox-session-summary` |
| 会话提炼永久笔记、session to permanent | `/skill:jfox-session-to-permanent` |
| 健康检查、知识库体检 | `/skill:jfox-manage` §5 |

## 通用约定

- 所有 `jfox` 命令都支持 `--kb <name>` 指定目标知识库；省略时使用当前默认知识库
- 大部分命令支持 `--format json` 或 `--json` 输出 JSON，方便解析
- 长内容或含特殊字符时，使用 `--content-file <path>` 从文件读取；`--content-file -` 表示从 stdin 读取
- `jfox show <id_or_title>` 默认输出原始 Markdown，`--json` 输出结构化字段（content/content_body/tags/links/backlinks 等）

## 常用命令速查

```bash
# 知识库
jfox init --name <name> --desc "<描述>"
jfox kb list --json
jfox kb switch <name>
jfox status --json

# 笔记 CRUD
jfox add "内容" --title "标题" --type permanent --tag <tag>
jfox add --content-file <path> --title "标题"
jfox edit <id> --content "新内容" --title "新标题"
jfox delete <id> --force
jfox show <id_or_title>
jfox list --json --limit 50

# 搜索与图谱
jfox search "<query>" --mode hybrid --json
jfox query "<topic>" --depth 2 --json
jfox suggest-links "<内容>" --json
jfox refs --search "<标题>" --json
jfox graph --stats --json
jfox graph --orphans --json

# 导入与整理
jfox ingest-log <repo-path> --limit 50 --type fleeting
jfox inbox --json --limit 50
jfox index verify
jfox index rebuild

# Daemon
jfox daemon start
jfox daemon stop
jfox daemon status
```

## 跨 Skill 引用语法

在 Kimi Code 中，引用本插件的其他 skill 时使用：

```text
/skill:jfox-manage
/skill:jfox-search
/skill:jfox-ingest
/skill:jfox-organize
/skill:jfox-session-summary
/skill:jfox-session-to-permanent
```

## 错误处理速查

| 错误 | 处理 |
|------|------|
| `jfox: command not found` | `uv tool install jfox-cli` |
| `Knowledge base not found` | 调用 `/skill:jfox-manage` 创建知识库 |
| `Knowledge base already exists` | `jfox kb switch <name>` 或换名称 |
| `Index not found` / 索引异常 | `jfox index rebuild` |
| 内容过长导致 shell 解析失败 | 改用 `--content-file` |
