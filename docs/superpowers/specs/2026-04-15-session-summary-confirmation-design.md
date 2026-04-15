# jfox-session-summary 用户确认流程设计

**Date**: 2026-04-15
**Issue**: #154
**Status**: Draft

## 背景

当前 `jfox-session-summary` skill 生成总结后直接写入知识库，硬编码 `--type fleeting`。用户无法审查内容或选择笔记类型。

## 改动范围

仅修改 `skills-recommend/claude-code/jfox-session-summary/SKILL.md`。不涉及 CLI 命令或 Python 代码变更。

## 新流程

当前 3 步扩展为 5 步：

| Step | 内容 | 状态 |
|------|------|------|
| Step 1 | 生成会话总结 | 不变 |
| Step 2 | 展示总结 + 用户确认 | **新增** |
| Step 3 | 选择笔记类型 | **新增** |
| Step 4 | `jfox add --type <选择>` | 原 Step 2 |
| Step 5 | 处理长内容 | 原 Step 3，不变 |

### Step 2：展示总结 + 用户确认

1. 用普通文本输出完整总结内容，供用户阅读
2. 使用 `AskUserQuestion` 询问「笔记内容是否 OK？」
   - **内容没问题** → 继续 Step 3
   - **需要修改** → 用户在 Other 中输入修改意见 → 根据意见调整总结 → 回到 Step 2 重新展示和确认
3. 循环直到用户满意为止

### Step 3：选择笔记类型

使用 `AskUserQuestion` 询问「选择笔记类型」：

- **fleeting**（推荐）— 会话记录是临时性笔记，后续可提炼为 permanent
- **literature** — 会话有明确的参考资料来源
- **permanent** — 总结已经是成熟的知识

### Step 4：写入知识库

`jfox add` 的 `--type` 参数使用 Step 3 的选择结果，不再硬编码 `fleeting`。其余参数（`--title`、`--tag session`、`--kb`）不变。

## 不在范围内

- 不修改 `jfox add` CLI 命令本身
- 不增加新的笔记类型
- 不改变总结模板格式（Step 1 不变）
- 不做自动检测笔记类型的智能逻辑
