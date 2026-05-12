# Claude Code Plugin Marketplace 开发指南

基于 jfox 插件开发和官方插件逆向分析总结的实战指南。覆盖插件结构、Schema、开发、发布全流程。

---

## 1. 概述

### 什么是 Claude Code 插件

Claude Code 插件是自包含的目录，用于扩展 Claude Code 的能力。一个插件可以包含：

| 组件 | 作用 | 调用方式 |
|------|------|---------|
| Skills | 技能指令（带上下文的复杂工作流） | `/plugin-name:skill-name` |
| Commands | 轻量级斜杠命令（单文件 .md） | `/plugin-name:command-name` |
| Agents | 子代理定义 | 由 skills/commands 调度 |
| Hooks | 事件钩子（SessionStart、PreToolUse 等） | 自动触发 |
| MCP Servers | 外部工具服务器 | 自动加载 |
| LSP Servers | 语言服务器 | 自动加载 |
| Themes / Output Styles | 主题和输出样式 | 自动加载 |

### 插件 vs 独立 `.claude/` 配置

| | 独立 `.claude/skills/` | 插件 |
|---|---|---|
| 命名空间 | `/hello` | `/my-plugin:hello` |
| 版本管理 | 无 | `plugin.json` 的 `version` 字段 |
| 分发 | 手动复制 / symlink | Marketplace 安装 |
| 适用场景 | 个人 / 单项目 | 团队共享、开源分发 |

### 官方参考文档

- [Plugins 创建指南](https://code.claude.com/docs/en/plugins.md)
- [Plugins Reference（完整 Schema）](https://code.claude.com/docs/en/plugins-reference.md)
- [Plugin Marketplaces](https://code.claude.com/docs/en/plugin-marketplaces.md)
- [Plugin Dependencies](https://code.claude.com/docs/en/plugin-dependencies.md)
- [Skills](https://code.claude.com/docs/en/skills.md)

---

## 2. 目录结构

### 标准布局

```
my-plugin/                     # 插件根目录
├── .claude-plugin/            # 元数据目录（只有 plugin.json 在这里）
│   ├── plugin.json            # 插件清单
│   └── marketplace.json       # Marketplace 注册（可选）
├── skills/                    # Skills（每个子目录一个 SKILL.md）
│   └── my-skill/
│       ├── SKILL.md
│       ├── scripts/           # 辅助脚本
│       └── references/        # 按需加载的参考文档
├── commands/                  # Slash commands（每个 .md 文件一个命令）
│   └── deploy.md
├── agents/                    # Agent 定义
│   └── reviewer.md
├── hooks/                     # 钩子
│   └── hooks.json
├── bin/                       # 可执行文件（自动加入 PATH）
├── .mcp.json                  # MCP 服务器定义
├── .lsp.json                  # LSP 服务器配置
├── settings.json              # 默认设置
├── LICENSE
└── README.md
```

> **关键规则**：`commands/`、`skills/`、`agents/` 等组件目录必须在 `.claude-plugin/` 的**同级**，即插件根目录下。**不要**放在 `.claude-plugin/` 里面。

### 官方插件实例

| 插件 | 类型 | 结构特点 |
|------|------|---------|
| `superpowers` | Skills-only | 14 个 skills + 1 agent + hooks，无 commands |
| `commit-commands` | Commands-only | 3 个 command .md 文件，最简结构 |
| `firecrawl` | Skills + Commands + MCP | 入口 skill + 7 个关联 skill + command |
| `plugin-dev` | 全组件 | skills + commands + agents + scripts |

---

## 3. plugin.json 完整 Schema

位置：`<plugin-root>/.claude-plugin/plugin.json`

> `plugin.json` 是**可选的**。如果省略，Claude Code 自动发现组件并从目录名推导插件名。但发布到 marketplace 时**强烈建议**提供。

### 必填字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | 插件标识符（kebab-case，无空格）。用于命名空间 `/my-plugin:skill` |

### 元数据字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `version` | string | 语义化版本（如 `"1.0.0"`）。设置后用户只在版本更新时获得新版本；不设置则用 git commit SHA |
| `description` | string | 插件用途简述 |
| `author` | object | `{"name": "...", "email": "...", "url": "..."}`。`name` 必填 |
| `homepage` | string | 文档 URL |
| `repository` | string | 源码仓库 URL |
| `license` | string | SPDX 标识（如 `"MIT"`） |
| `keywords` | array | 搜索标签 |

### 组件路径字段

| 字段 | 类型 | 默认位置 | 说明 |
|------|------|---------|------|
| `skills` | string/array | `skills/` | Skill 目录路径 |
| `commands` | string/array | `commands/` | Command 文件/目录路径 |
| `agents` | string/array | `agents/` | Agent 文件路径 |
| `hooks` | string/array/object | `hooks/hooks.json` | Hook 配置 |
| `mcpServers` | string/array/object | `.mcp.json` | MCP 服务器配置 |
| `lspServers` | string/array/object | `.lsp.json` | LSP 服务器配置 |
| `monitors` | string/array | `monitors/monitors.json` | 后台监控 |

> **路径解析**：`./` 相对于 `.claude-plugin/` 目录。自定义路径**替换**默认位置（不追加）。保留默认的同时添加更多，需在数组中包含默认路径。

### 高级字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `userConfig` | object | 用户可配置的值，安装时提示输入。支持 `string`、`number`、`boolean`、`directory`、`file` 类型 |
| `dependencies` | array | 依赖的其他插件。支持 semver 版本范围 |
| `channels` | array | 消息注入通道（Telegram、Slack 等） |

### 环境变量

| 变量 | 说明 |
|------|------|
| `${CLAUDE_PLUGIN_ROOT}` | 插件安装目录的绝对路径（更新时会变） |
| `${CLAUDE_PLUGIN_DATA}` | 持久化数据目录 `~/.claude/plugins/data/{id}/`（更新后保留） |
| `${user_config.KEY}` | userConfig 中用户配置的值 |

### 完整示例

```json
{
  "name": "enterprise-tools",
  "version": "2.1.0",
  "description": "Enterprise workflow automation tools",
  "author": {
    "name": "Enterprise Team",
    "email": "team@example.com"
  },
  "homepage": "https://docs.example.com/plugins/enterprise-tools",
  "license": "MIT",
  "keywords": ["enterprise", "workflow"],
  "skills": ["./skills/"],
  "commands": ["./commands/"],
  "agents": ["./agents/"],
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Write|Edit",
        "hooks": [{"type": "command", "command": "${CLAUDE_PLUGIN_ROOT}/scripts/validate.sh"}]
      }
    ]
  },
  "mcpServers": {
    "db": {
      "command": "${CLAUDE_PLUGIN_ROOT}/servers/db-server",
      "args": ["--config", "${CLAUDE_PLUGIN_DATA}/config.json"]
    }
  },
  "dependencies": [
    "helper-lib",
    {"name": "secrets-vault", "version": "~2.1.0"}
  ],
  "userConfig": {
    "api_endpoint": {
      "type": "string",
      "title": "API Endpoint",
      "description": "Your team's API endpoint"
    }
  }
}
```

### 最小示例（推荐：依赖自动发现）

```json
{
  "name": "my-plugin",
  "description": "My awesome plugin",
  "version": "1.0.0",
  "author": {"name": "Your Name"},
  "license": "MIT"
}
```

不声明 `skills`、`commands` 等字段时，Claude Code 自动从默认位置发现组件。**这是官方插件的主流做法**，也是 jfox 最终采用的方案：插件源位于 `packages/cc-plugin/`，5 个 skill 自动从 `packages/cc-plugin/skills/` 被发现。

---

## 4. marketplace.json Schema

位置：`<repo-root>/.claude-plugin/marketplace.json`

当你的仓库包含一个或多个插件并希望通过 marketplace 分发时需要此文件。

### 必填字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `name` | string | Marketplace 标识符（kebab-case）。**保留字**：`claude-code-marketplace`、`claude-plugins-official` 等官方名称 |
| `owner` | object | `{"name": "..."}` 必填 |
| `plugins` | array | 可安装的插件列表 |

### 可选元数据

| 字段 | 类型 | 说明 |
|------|------|------|
| `metadata.description` | string | Marketplace 描述 |
| `metadata.version` | string | Marketplace 版本 |
| `metadata.pluginRoot` | string | 相对路径前缀 |

### Plugin Entry 字段

```json
{
  "name": "my-plugin",          // 必填：插件名
  "source": "./",               // 必填：插件根目录（相对 marketplace.json）
  "description": "...",         // 可选
  "version": "1.0.0",          // 可选
  "author": {"name": "..."},    // 可选
  "category": "workflow",       // 可选
  "keywords": ["..."],          // 可选
  "strict": true                // 可选，默认 true
}
```

### Source 类型

| 类型 | 格式 |
|------|------|
| 相对路径 | `"./plugins/my-plugin"` |
| GitHub | `{"source": "github", "repo": "org/repo"}` |
| Git URL | `{"source": "url", "url": "https://..."}` |
| Git 子目录 | `{"source": "git-subdir", "url": "...", "path": "..."}` |
| npm | `{"source": "npm", "package": "..."}` |

### Strict Mode

- `strict: true`（默认）：`plugin.json` 是权威来源，marketplace entry 补充
- `strict: false`：marketplace entry 是完整定义。如果插件也有 `plugin.json` 会导致冲突

### 完整示例

```json
{
  "name": "my-marketplace",
  "owner": {"name": "Your Name"},
  "metadata": {
    "description": "My plugin collection",
    "version": "1.0.0"
  },
  "plugins": [
    {
      "name": "my-plugin",
      "source": "./",
      "description": "My awesome plugin",
      "version": "1.0.0",
      "author": {"name": "Your Name"},
      "category": "workflow"
    }
  ]
}
```

---

## 5. Skills 开发

### 目录结构

```
skills/
└── my-skill/                # 目录名 = skill 名（kebab-case）
    ├── SKILL.md             # 必填：Skill 定义
    ├── scripts/             # 可选：可执行脚本
    ├── references/          # 可选：按需加载的参考文档
    ├── rules/               # 可选：补充规则
    └── examples/            # 可选：示例文件
```

### SKILL.md 格式

```markdown
---
name: my-skill
description: |
  一句话描述 skill 的用途和触发条件。
  描述是主要的激活机制——描述越精确，自动触发越准确。
allowed-tools:
  - Bash(my-tool *)
---

## 指令正文

这里是 skill 的完整指令。当用户触发这个 skill 时，
Claude Code 会加载这段内容作为上下文。

### 步骤
1. 第一步
2. 第二步

### 关联 Skills
- [相关 skill](../other-skill/SKILL.md)
```

### Frontmatter 字段

| 字段 | 必填 | 说明 |
|------|------|------|
| `name` | 是 | Skill 名称，必须匹配目录名 |
| `description` | 是 | 用途描述，决定自动触发时机 |
| `allowed-tools` | 否 | 白名单工具列表 |

### 自动发现 vs 显式声明

**自动发现**（推荐）：不声明 `skills` 字段，Claude Code 自动扫描 `skills/` 下所有包含 `SKILL.md` 的子目录。

**显式声明**：在 `plugin.json` 中列出特定 skill 路径。这会**替换**自动发现，只加载列出的 skill。firecrawl 用这种方式将 `firecrawl-cli` 设为入口，其他 skill 通过入口 SKILL.md 中的相对链接按需加载。

---

## 6. Commands 开发

> Commands 是**遗留格式**。新插件建议使用 Skills。Commands 适合简单的、单次执行的指令。

### 文件格式

`commands/<name>.md`，每个 `.md` 文件自动成为一个 `/plugin-name:command-name` 命令。

```markdown
---
description: 创建一个 git commit
allowed-tools: Bash(git add:*), Bash(git status:*), Bash(git commit:*)
argument-hint: <commit-message>
---

## 上下文

- 当前 git 状态: !`git status`
- 当前分支: !`git branch --show-current`
- 最近提交: !`git log --oneline -10`

## 任务

根据上述变更创建一个 git commit。
```

### Frontmatter 字段

| 字段 | 说明 |
|------|------|
| `description` | 命令列表中显示的一行描述 |
| `allowed-tools` | 白名单工具（逗号分隔） |
| `argument-hint` | 参数提示（如 `<documentation-url>`） |
| `disable-model-invocation` | 是否禁止调用子代理（默认 `false`） |

### 动态上下文注入

用 `` !`command` `` 语法在命令加载时注入 shell 输出：

```markdown
- 当前状态: !`git status`
- 分支: !`git branch --show-current`
```

### 自动发现

Commands 通过自动发现工作——`commands/` 目录下所有 `.md` 文件都会被发现。**不需要在 plugin.json 中显式声明**（参见踩坑记录第 10 节）。

---

## 7. Agents 开发

### 文件格式

`agents/<name>.md`：

```markdown
---
name: my-agent
description: |
  Use this agent when the user asks to "review code" or "check for bugs".

  <example>
  Context: User wants code reviewed
  user: "Review this PR for security issues"
  assistant: "I'll use the code-reviewer agent to analyze this PR."
  <commentary>
  User requesting code review, trigger agent.
  </commentary>
  </example>
model: inherit
---

Agent 的完整指令...
```

### Frontmatter 字段

| 字段 | 说明 |
|------|------|
| `name` | Agent 名称 |
| `description` | 用途描述，含触发条件示例 |
| `model` | 使用的模型（如 `inherit`、`haiku`、`sonnet`） |

---

## 8. Hooks、MCP、LSP 集成

### Hooks

`hooks/hooks.json`：

```json
{
  "hooks": {
    "SessionStart": [
      {
        "matcher": "startup|clear|compact",
        "hooks": [
          {
            "type": "command",
            "command": "${CLAUDE_PLUGIN_ROOT}/hooks/session-start",
            "async": false
          }
        ]
      }
    ]
  }
}
```

**关键**：始终用 `${CLAUDE_PLUGIN_ROOT}` 引用插件内路径，不要硬编码。

### MCP Servers

`.mcp.json` 或 `plugin.json` 的 `mcpServers` 字段：

```json
{
  "mcpServers": {
    "my-server": {
      "command": "${CLAUDE_PLUGIN_ROOT}/bin/server",
      "args": ["--port", "3000"]
    }
  }
}
```

### LSP Servers

`.lsp.json` 或 `plugin.json` 的 `lspServers` 字段：

```json
{
  "lspServers": {
    "go": {
      "command": "gopls",
      "args": ["serve"],
      "extensionToLanguage": {".go": "go"}
    }
  }
}
```

### 跨平台 Hook 脚本

官方 superpowers 插件使用 polyglot 脚本 `run-hook.cmd`，同时兼容 Windows 和 Unix：

```bash
: << 'CMDBLOCK'
@echo off
:: Windows portion...
exit /b %ERRORLEVEL%
:CMDBLOCK
#!/bin/bash
# Unix portion...
```

---

## 9. 发布与分发

### 创建 Marketplace 仓库

1. 创建 GitHub 仓库
2. 添加 `.claude-plugin/plugin.json` 和 `.claude-plugin/marketplace.json`
3. 添加 skills、commands 等组件
4. 推送到 GitHub

### 用户安装

```bash
# 1. 添加 marketplace
claude plugin marketplace add owner/repo

# 2. 安装插件
claude plugin install plugin-name@marketplace-name

# 3. 在 session 中加载
/reload-plugins

# 4. 验证
/doctor
```

或在 Claude Code session 内：

```
/plugin install plugin-name@marketplace-name
```

### 版本管理

| 方式 | 行为 |
|------|------|
| 设 `version`（如 `"1.0.0"`） | 用户只在版本号变更时获得更新 |
| 不设 `version` | 每次新的 git commit SHA 都是新版本 |

**依赖版本 tag**：使用 `{plugin-name}--v{version}` 格式的 git tag（如 `git tag secrets-vault--v2.1.0`）。

### 更新流程

当插件有新版本时：

```bash
# 1. 更新 marketplace 缓存
claude plugin marketplace update marketplace-name

# 2. 重新安装获取新版本
claude plugin install plugin-name@marketplace-name

# 3. 重新加载
/reload-plugins
```

### 安装作用域

| Scope | 配置文件 | 用途 |
|-------|---------|------|
| `user`（默认） | `~/.claude/settings.json` | 个人所有项目 |
| `project` | `.claude/settings.json` | 团队共享（入库） |
| `local` | `.claude/settings.local.json` | 项目专属（不入库） |

### 团队预配置

在 `.claude/settings.json` 中：

```json
{
  "extraKnownMarketplaces": {
    "my-tools": {
      "source": {"source": "github", "repo": "org/plugins"}
    }
  },
  "enabledPlugins": {
    "my-plugin@my-tools": true
  }
}
```

### 提交到官方 Marketplace

访问 [claude.ai/settings/plugins/submit](https://claude.ai/settings/plugins/submit) 提交。

---

## 10. 踩坑记录（jfox 实战）

> **注**：以下 5 个坑是 2026-05 重组前（PR #210/#213/#214 时期）的历史记录。重组后（PR #216 响应）的当前布局见**附录**。这些教训仍然有效，对照学习自动发现 + 标准目录的价值。

### 坑 1：`./commands/` 路径解析错误

**现象**：`/doctor` 报 5 个 commands 路径找不到：

```
jfox@jfox-skills [jfox]: Path not found: ...\cache\...\commands\jfox-common
```

**原因**：`plugin.json` 位于 `.claude-plugin/plugin.json`，`./commands/` 解析为 `.claude-plugin/commands/`（不存在），但 `commands/` 实际在仓库根目录。

**首次尝试修复**：改用 `../commands/`。

### 坑 2：`../commands/` 被 Validator 拒绝

**现象**：

```
Plugin jfox has an invalid manifest file.
Validation errors: commands: Invalid input
```

**原因**：Claude Code 的 plugin validator 不接受 `..` 相对路径（安全考虑）。

### 最终解决：去掉 commands 字段，用自动发现

```json
{
  "name": "jfox",
  "description": "...",
  "version": "0.1.2",
  "author": {"name": "zhuxixi"},
  "license": "MIT",
  "keywords": ["zettelkasten", "knowledge-management", "cli"],
  "skills": [
    "./skills-recommend/claude-code/jfox-common",
    "./skills-recommend/claude-code/jfox-ingest",
    "./skills-recommend/claude-code/jfox-organize",
    "./skills-recommend/claude-code/jfox-search",
    "./skills-recommend/claude-code/jfox-session-summary"
  ]
}
```

**教训**：官方插件（superpowers、commit-commands、code-review、plugin-dev 等）几乎都**不显式声明** skills/commands 路径，完全依赖自动发现。

### 坑 3：skills 路径 `./skills-recommend/` 为什么能工作？

**现象**：skills 用 `./skills-recommend/claude-code/...` 没报错。

**原因**：Marketplace 安装时整个仓库被 clone 到缓存目录。缓存结构：

```
~/.claude/plugins/cache/jfox-skills/jfox/0.1.2/
├── .claude-plugin/
│   └── plugin.json        # ./skills-recommend/ → .claude-plugin/skills-recommend/（不存在！）
├── skills-recommend/       # 实际在根目录
└── commands/               # 实际在根目录
```

但 Claude Code 实际上会从**仓库根目录**（而非 `.claude-plugin/` 目录）解析 skills 路径，所以 `./skills-recommend/` 能找到。**commands 的解析规则可能不同**，导致只有 commands 报错。

### 坑 4：插件版本 vs Python 包版本

**现象**：混淆两套版本号。

| | jfox Python 包 | jfox 插件 |
|---|---|---|
| 版本文件 | `pyproject.toml`、`__init__.py` | `plugin.json`、`marketplace.json` |
| 版本号 | `0.8.0` | `0.1.2` |
| 发版方式 | `/release` skill + PyPI | 改 version → PR → merge |
| 更新方式 | `pip install -U jfox` | `claude plugin marketplace update` + reinstall |

**教训**：两套版本独立管理，需要明确区分。

### 坑 5：Junction Link vs Plugin 安装

**旧方式**（手动 junction）：

```powershell
New-Item -ItemType Junction -Path ~/.claude/skills/jfox-common -Target ~/work/personal/jfox/skills-recommend/claude-code/jfox-common
```

**新方式**（marketplace 插件）：

```bash
claude plugin marketplace add zhuxixi/jfox
claude plugin install jfox@jfox-skills
```

**区别**：

| | Junction | Plugin |
|---|---|---|
| 命名空间 | `/jfox-common` | `/jfox:jfox-common` |
| 版本管理 | 无 | 有 |
| 分发 | 手动 | marketplace |
| 更新 | 手动重建 | 一条命令 |

### 核心教训总结

1. **依赖自动发现**，不要显式声明 skills/commands 路径（除非需要入口控制如 firecrawl）
2. **不要用 `../`**，validator 会拒绝
3. **`plugin.json` 只放元数据**，让 Claude Code 自动扫描目录
4. **提交前跑 `claude plugin validate .`**（如果有这个命令）或 `/doctor`
5. **用 `--plugin-dir` 本地测试**：`claude --plugin-dir ./my-plugin`
6. **两套版本号独立管理**

---

## 11. CLI 命令参考

### 插件管理

| 命令 | 说明 |
|------|------|
| `claude plugin install <name@marketplace> [--scope user\|project\|local]` | 安装插件 |
| `claude plugin uninstall <name@marketplace> [--keep-data] [--prune]` | 卸载插件 |
| `claude plugin enable <name@marketplace>` | 启用已禁用的插件 |
| `claude plugin disable <name@marketplace>` | 禁用（不卸载） |
| `claude plugin update [name]` | 更新到最新版本 |
| `claude plugin list [--json] [--available]` | 列出已安装插件 |
| `claude plugin prune [--dry-run]` | 清理孤立的依赖 |
| `claude plugin tag [--push] [--dry-run]` | 创建发布 git tag |
| `claude plugin validate .` | 验证插件/marketplace 结构 |

### Marketplace 管理

| 命令 | 说明 |
|------|------|
| `claude plugin marketplace add <source> [--scope ...] [--sparse ...]` | 添加 marketplace |
| `claude plugin marketplace list` | 列出已配置的 marketplace |
| `claude plugin marketplace update [name]` | 刷新 marketplace 缓存 |
| `claude plugin marketplace remove <name>` | 移除 marketplace |

### Session 内命令

| 命令 | 说明 |
|------|------|
| `/plugin install <name@marketplace>` | 在 session 内安装插件 |
| `/plugin uninstall <name@marketplace>` | 在 session 内卸载插件 |
| `/plugin enable <name@marketplace>` | 启用插件 |
| `/plugin disable <name@marketplace>` | 禁用插件 |
| `/reload-plugins` | 重新加载所有插件 |
| `/doctor` | 检查插件错误 |

### Source 格式

```bash
# GitHub 仓库
claude plugin marketplace add owner/repo

# Git URL
claude plugin marketplace add https://gitlab.com/company/plugins.git

# 带分支/tag
claude plugin marketplace add https://gitlab.com/company/plugins.git#v1.0.0

# 本地路径
claude plugin marketplace add ./my-marketplace

# 远程 JSON
claude plugin marketplace add https://example.com/marketplace.json
```

---

## 12. 最佳实践清单

### 开发

- [x] 用 `skills/` 而非 `commands/` 开发新功能（commands 是遗留格式）
- [x] Skill description 是主要激活机制，写清楚触发条件
- [x] 用 `${CLAUDE_PLUGIN_ROOT}` 引用插件内路径，不要硬编码
- [x] 用 `${CLAUDE_PLUGIN_DATA}` 存储跨版本持久化数据
- [x] `plugin.json` 只放元数据，组件路径留给自动发现
- [x ] 不要用 `../` 相对路径

### 测试

- [x] 用 `claude --plugin-dir ./my-plugin` 本地测试
- [x] 安装后用 `/doctor` 检查错误
- [x] 用 `/reload-plugins` 确认加载成功

### 发布

- [x] 设显式 `version` 字段（避免每次 commit 都触发更新）
- [x] 遵循 semver（`MAJOR.MINOR.PATCH`）
- [x] 包含 `README.md` 和 `LICENSE`
- [x] 提交前跑 `claude plugin validate .`

### 版本管理

- [x] 插件版本与项目版本独立管理
- [x] 依赖版本用 `{plugin-name}--v{version}` 格式 git tag
- [x] 更新流程：marketplace update → reinstall → reload

---

## 附录：jfox 插件最终结构

```
jfox/                                  # 仓库根目录
├── .claude-plugin/
│   └── marketplace.json               # Marketplace 注册（source: ./packages/cc-plugin）
├── packages/
│   └── cc-plugin/                     # Claude Code 插件源
│       ├── .claude-plugin/
│       │   └── plugin.json            # 插件清单（仅元数据，无 skills 声明 → auto-discovery）
│       └── skills/                    # 自动发现的 skills
│           ├── kb/SKILL.md
│           ├── ingest/SKILL.md
│           ├── organize/SKILL.md
│           ├── search/SKILL.md
│           └── session-summary/SKILL.md
├── skills-recommend/
│   ├── kimi-cli/                      # Kimi CLI 版 skills（保留 jfox-X 前缀，不被打包）
│   └── README.md
├── jfox/                              # Python 包源码
├── .claude/                           # 内嵌 skills（release、ci）
└── ...
```

**当前状态**（2026-05-12，response to #216）：
- 插件版本：`0.1.2`（建议下次发版 bump 至 `0.2.0` 反映破坏性 rename）
- Python 包版本：`0.8.0`
- Skills 通过 auto-discovery（无 skills 字段）
- Commands 已删除（曾是 skill shim 反模式）
- Skill 命名移除 `jfox-` 前缀：`/jfox:search` / `/jfox:kb` / `/jfox:ingest` / `/jfox:organize` / `/jfox:session-summary`
- Plugin source 拆出至 `packages/cc-plugin/`，与 `skills-recommend/kimi-cli/` 解耦
