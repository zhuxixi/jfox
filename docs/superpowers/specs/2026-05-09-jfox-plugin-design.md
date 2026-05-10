# JFox Claude Code Plugin 设计文档

**日期**: 2026-05-09
**Issue**: [#209](https://github.com/zhuxixi/jfox/issues/209)
**状态**: Draft

## 概述

将 jfox 仓库中的 `skills-recommend/claude-code/` 下 5 个 skill 改造为标准 Claude Code plugin，支持 marketplace 添加和安装。Plugin 留在 jfox 仓库内，不创建独立仓库。

## 目标

- 社区用户可以通过 marketplace 一键安装 jfox plugin
- 同时支持 skill 自动触发和 slash command 手动调用
- 不改动现有 `skills-recommend/` 目录结构（claude-code 和 kimi-cli 均保留原位）

## 目录结构

```
jfox/                                    # 仓库根目录
├── .claude-plugin/                      # 新增：Plugin 清单
│   ├── plugin.json
│   └── marketplace.json
├── commands/                            # 新增：Slash commands
│   ├── jfox-common.md
│   ├── jfox-ingest.md
│   ├── jfox-organize.md
│   ├── jfox-search.md
│   └── jfox-session-summary.md
├── skills-recommend/                    # 不动
│   ├── claude-code/                     # 不动
│   │   ├── jfox-common/SKILL.md
│   │   ├── jfox-ingest/SKILL.md
│   │   ├── jfox-organize/SKILL.md
│   │   ├── jfox-search/SKILL.md
│   │   └── jfox-session-summary/SKILL.md
│   └── kimi-cli/                        # 不动
├── jfox/                                # 不动
├── tests/                               # 不动
└── ...
```

## Plugin 清单

### `.claude-plugin/plugin.json`

```json
{
  "name": "jfox",
  "description": "JFox 知识管理 CLI 的 Claude Code 集成——搜索、导入、整理、会话总结",
  "version": "0.1.0",
  "author": { "name": "zhuxixi" },
  "license": "MIT",
  "keywords": ["zettelkasten", "knowledge-management", "cli"],
  "skills": [
    "./skills-recommend/claude-code/jfox-common",
    "./skills-recommend/claude-code/jfox-ingest",
    "./skills-recommend/claude-code/jfox-organize",
    "./skills-recommend/claude-code/jfox-search",
    "./skills-recommend/claude-code/jfox-session-summary"
  ],
  "commands": [
    "./commands/jfox-common",
    "./commands/jfox-ingest",
    "./commands/jfox-organize",
    "./commands/jfox-search",
    "./commands/jfox-session-summary"
  ]
}
```

### `.claude-plugin/marketplace.json`

```json
{
  "name": "jfox-skills",
  "id": "jfox-skills",
  "owner": { "name": "zhuxixi" },
  "metadata": {
    "description": "JFox Zettelkasten 知识管理工具的 Claude Code 集成",
    "version": "0.1.0"
  },
  "plugins": [
    {
      "name": "jfox",
      "source": "./",
      "description": "JFox 知识管理 CLI 的 Claude Code 集成——搜索、导入、整理、会话总结",
      "version": "0.1.0",
      "author": { "name": "zhuxixi" },
      "keywords": ["zettelkasten", "knowledge-management"],
      "category": "workflow"
    }
  ]
}
```

## Slash Commands

每个 skill 对应一个 slash command，放在 `commands/` 目录。Command 文件是轻量的 `.md` 文件，触发对应的 skill。

| 文件 | 命令 | 说明 |
|------|------|------|
| `jfox-common.md` | `/jfox-common` | 知识库管理、健康检查 |
| `jfox-ingest.md` | `/jfox-ingest` | 从 Git 仓库导入数据 |
| `jfox-organize.md` | `/jfox-organize` | 整理知识库、提炼笔记 |
| `jfox-search.md` | `/jfox-search` | 搜索笔记、图谱查询 |
| `jfox-session-summary.md` | `/jfox-session-summary` | 保存会话总结到知识库 |

Command 文件模板：

```markdown
---
name: <skill-name>
description: <简短描述>
---

请调用 <skill-name> skill 来完成用户的请求。
```

## 安装流程

```bash
# 1. 添加 jfox 仓库为 marketplace 源
/plugin marketplace add https://github.com/zhuxixi/jfox

# 2. 安装 jfox plugin
/plugin marketplace install jfox

# 3. 使用
/jfox-search 笔记关键词
/jfox-common 健康检查
```

**前提条件**：用户需先安装 jfox CLI（`uv tool install jfox-cli`）。

**版本更新**：通过 Claude Code 内置的 `/plugin marketplace update` 拉取最新 git commit，plugin.json 中的 version 仅做展示。

## 不涉及的内容

- 不修改 `skills-recommend/` 下任何现有文件
- 不创建独立仓库
- 不做 kimi-cli 的 plugin 转换
- 不做 CI/CD 自动发布流程
