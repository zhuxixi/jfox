# JFox Kimi Code Plugin

JFox 知识管理 CLI 的 [Kimi Code CLI](https://www.kimi.com/code) 插件。

## 功能

提供与 Claude Code 插件 `packages/cc-plugin/` 对齐的 10 个核心 skill：

| Skill | 用途 | 触发示例 |
|-------|------|----------|
| `jfox-manage` | 知识库管理、笔记 CRUD、健康检查、配置调优 | “创建知识库”、“知识库体检” |
| `jfox-search` | 搜索笔记、图谱查询、链接推荐 | “搜索 jfox 笔记”、“推荐链接” |
| `jfox-ingest` | 从 Git 仓库导入 git log / PR / Issues | “导入这个仓库” |
| `jfox-organize` | 整理知识库、提炼 permanent 笔记 | “整理知识库”、“清理 inbox” |
| `jfox-promote` | 过审 candidate 笔记，晋升为 permanent 或拒绝 | “candidate 过审”、“审阅候选宝石” |
| `jfox-session-summary` | 把当前会话总结写入知识库 | “保存这次会话”、“总结到知识库” |
| `jfox-session-to-permanent` | 从当前会话提炼可复用知识为 permanent（先去重、审阅后落库） | “提炼到永久笔记”、“session to permanent” |
| `jfox-template` | 管理笔记模板 | “创建会议模板”、“模板列表” |
| `jfox-auto-summary` | 管理 Claude Code 会话自动总结 | “启用自动总结”、“清理 ledger” |
| `jfox-admin` | 系统维护：性能监控、模型下载、自升级 | “升级 jfox”、“下载模型”、“性能报告” |

此外，`using-jfox` skill 会在每次新会话/恢复会话时自动加载，提供环境检查和命令速查。

## 前置条件

- Kimi Code CLI >= 0.2.0（本插件使用 `~/.kimi-code/skills/` 迁移后的插件机制）
- jfox CLI 已安装：
  ```bash
  uv tool install jfox-cli
  ```

## 安装

### 方式一：本地 zip 安装（开发测试）

```bash
cd packages/kimi-plugin
zip -r /tmp/jfox-kimi-plugin.zip .
```

在 Kimi Code CLI 中：

```bash
/plugins install /tmp/jfox-kimi-plugin.zip
/new
```

### 方式二：从 GitHub 安装（推荐）

等待 marketplace 上架后：

```bash
/plugins install github:zhuxixi/jfox?path=packages/kimi-plugin
/new
```

> 具体 git URL 格式以 Kimi Code CLI 当时支持的为准。

### 方式三：本地目录（热更新开发）

```bash
/plugins install /path/to/jfox/packages/kimi-plugin
/new
```

修改 skill 文件后，使用 `/reload` 或重启会话生效。

## 验证

```bash
/plugins info jfox
/skill:jfox-manage
```

## 与 Claude Code 插件的差异

| 项目 | Claude Code (`packages/cc-plugin`) | Kimi Code (`packages/kimi-plugin`) |
|------|------------------------------------|------------------------------------|
| 插件 manifest | `.claude-plugin/plugin.json` | `kimi.plugin.json` |
| Skill 引用语法 | `/jfox:manage` | `/skill:jfox-manage` |
| 自动加载 | 无（marketplace 机制不同） | `sessionStart.skill` 自动加载 `using-jfox` |
| 核心技能 | manage / search / ingest / organize / promote / session-summary / session-to-permanent / template / auto-summary / admin | jfox-manage / jfox-search / jfox-ingest / jfox-organize / jfox-promote / jfox-session-summary / jfox-session-to-permanent / jfox-template / jfox-auto-summary / jfox-admin |

## 文件结构

```text
packages/kimi-plugin/
├── kimi.plugin.json
├── README.md
└── skills/
    ├── using-jfox/
    │   └── SKILL.md
    ├── jfox-manage/
    │   └── SKILL.md
    ├── jfox-search/
    │   └── SKILL.md
    ├── jfox-ingest/
    │   └── SKILL.md
    ├── jfox-organize/
    │   └── SKILL.md
    ├── jfox-promote/
    │   └── SKILL.md
    ├── jfox-session-summary/
    │   └── SKILL.md
    ├── jfox-session-to-permanent/
    │   └── SKILL.md
    ├── jfox-template/
    │   └── SKILL.md
    ├── jfox-auto-summary/
    │   └── SKILL.md
    └── jfox-admin/
        └── SKILL.md
```

## 已知限制

- 本插件通过 `Bash` 调用本地 `jfox` CLI，因此依赖用户已安装 `jfox-cli` 并正确配置 PATH。
- 当前未提供 MCP server；后续可能通过 MCP 封装高频命令以提升稳定性。

## 许可证

MIT
