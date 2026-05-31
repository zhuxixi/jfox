# JFox Agent Skills (Non-Claude Code)

为非 Claude Code 平台准备的 JFox 知识管理 SKILL.md 集合。

> **Claude Code 用户请通过 marketplace 安装**（`/plugin marketplace add zhuxixi/jfox`），不要从此目录拷贝。
> Claude Code 的官方插件源在 `packages/cc-plugin/`，使用 auto-discovery 加载 `packages/cc-plugin/skills/` 下的 5 个 skill。

## 目录结构

```
skills-recommend/
├── kimi-cli/             # Kimi CLI 适配版 SKILL.md
│   ├── jfox-ingest/
│   ├── jfox-organize/
│   ├── jfox-search/
│   ├── jfox-session-summary/
│   └── jfox-common/
└── pi/                   # pi coding agent 适配版 SKILL.md
    ├── jfox-ingest/
    ├── jfox-organize/
    ├── jfox-search/
    ├── jfox-session-summary/
    ├── jfox-common/
    ├── jfox-ci/
    └── jfox-release/
```

## 使用方法

### Kimi CLI

Kimi CLI 使用与 Claude Code 相同的 SKILL.md 格式，通过 `description` 中的关键词自然语言触发：

```bash
# 复制全部 skills
mkdir -p ~/.config/agents/skills/
cp -r skills-recommend/kimi-cli/* ~/.config/agents/skills/

# 或复制单个 skill
cp -r skills-recommend/kimi-cli/jfox-search ~/.config/agents/skills/
```

复制后 Kimi CLI 会根据对话内容自动触发对应的 skill：
- **jfox-common** — 创建/管理知识库、健康检查
- **jfox-ingest** — 从仓库导入 git log / PR / Issues 为 fleeting 笔记
- **jfox-organize** — 整理知识库、提炼 permanent 笔记、生成 [[wiki links]]
- **jfox-search** — 搜索笔记、图谱查询、链接推荐
- **jfox-session-summary** — 将会话总结写入知识库作为 fleeting 笔记

Kimi CLI 也兼容 `~/.kimi/skills/` 和 `~/.claude/skills/` 目录。

### pi coding agent

pi 支持 [Agent Skills 标准](https://agentskills.io/specification)，通过 `SKILL.md` 的 `description` 自然语言触发，也支持 `/skill:name` 显式调用。

pi 会自动发现以下位置的 skills：
- 全局：`~/.pi/agent/skills/`、`~/.agents/skills/`
- 项目级：`.pi/skills/`、`.agents/skills/`
- Package：`package.json` 中 `pi.skills` 指定的目录

**安装方式一：手动复制**
```bash
# 复制到全局 skills 目录
mkdir -p ~/.pi/agent/skills/
cp -r skills-recommend/pi/* ~/.pi/agent/skills/
```

**安装方式二：通过 pi package（零侵入，推荐）**
```bash
pi install git:github.com/zhuxixi/jfox
```
安装后 pi 会自动识别 `skills-recommend/pi/` 下的所有 skills。

**pi 版 skill 列表：**
- **jfox-common** — 创建/管理知识库、笔记 CRUD、健康检查、Daemon 管理
- **jfox-ingest** — 从仓库导入 git log / PR / Issues 为 fleeting 笔记
- **jfox-organize** — 整理知识库、提炼 permanent 笔记、生成 [[wiki links]]
- **jfox-search** — 搜索笔记、图谱查询、链接推荐
- **jfox-session-summary** — 将会话总结写入知识库
- **jfox-ci** — 触发 GitHub Actions CI 工作流
- **jfox-release** — 版本发布（bump → CHANGELOG → PR → Release）

**与 kimi-cli 版的差异：**
- description 中英双语，触发词覆盖更广
- 交叉引用使用 pi 的 `/skill:name` 语法
- 额外包含 `jfox-ci` 和 `jfox-release`（从 `.claude/skills/` 移植）
- 内容以 cc-plugin 的详细版为基础，保持中文主体

### OpenCode / Codex / Cursor 等

这些 Agent 的 skill/instruction 格式各不相同，但核心逻辑是通用的。参考 `kimi-cli/` 下的 SKILL.md 内容，将其适配为对应平台的格式：

| 平台 | 适配方式 |
|------|---------|
| **OpenCode** | 将 SKILL.md 内容放入 agent 指令或 custom instruction |
| **Codex** | 写入 `codex.md` 或 AGENTS.md 中的指令段落 |
| **Cursor** | 写入 `.cursor/rules/` 下的 rule 文件 |
| **其他** | 将命令参考和工作流提取为 system prompt 片段 |

### 通用适配要点

每个 skill 包含以下可复用信息：
1. **触发条件** — 什么场景下使用该 skill
2. **命令映射** — 用户意图对应的 jfox CLI 命令
3. **工作流程** — 操作步骤和决策逻辑
4. **命令参考** — 完整的 CLI 命令速查

## 前置条件

需要先安装 jfox CLI：

```bash
uv tool install jfox-cli
```

详见：https://github.com/zhuxixi/jfox
