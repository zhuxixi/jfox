# JFox Agent Skills

为各类 AI 编程助手提供的 JFox 知识管理操作技能定义。

## 目录结构

```
skills-recommend/
├── claude-code/          # Claude Code 专用 SKILL.md 格式
│   ├── jfox-ingest/      # 数据导入（git log / GitHub PR / Issues）
│   ├── jfox-organize/    # 知识库整理与提炼（fleeting → permanent）
│   ├── jfox-search/      # 知识库搜索与图谱查询
│   ├── jfox-session-summary/  # 会话总结写入知识库
│   └── jfox-common/      # 知识库管理 + 健康检查
└── kimi-cli/             # Kimi CLI 适配版 SKILL.md
    ├── jfox-ingest/
    ├── jfox-organize/
    ├── jfox-search/
    ├── jfox-session-summary/
    └── jfox-common/
```

## 使用方法

### Claude Code

直接复制到 `~/.claude/skills/` 即可使用：

```bash
# 复制全部 skills
cp -r skills-recommend/claude-code/* ~/.claude/skills/

# 或复制单个 skill
cp -r skills-recommend/claude-code/jfox-search ~/.claude/skills/
```

复制后即可通过斜杠命令调用：
- `/jfox-common` — 创建/管理知识库、健康检查
- `/jfox-ingest` — 从仓库导入 git log / PR / Issues 为 fleeting 笔记
- `/jfox-organize` — 整理知识库、提炼 permanent 笔记、生成 [[wiki links]]
- `/jfox-search` — 搜索笔记、图谱查询、链接推荐
- `/jfox-session-summary` — 将会话总结写入知识库作为 fleeting 笔记

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

### OpenCode / Codex / Cursor 等

这些 Agent 的 skill/instruction 格式各不相同，但核心逻辑是通用的。参考 `claude-code/` 或 `kimi-cli/` 下的 SKILL.md 内容，将其适配为对应平台的格式：

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
