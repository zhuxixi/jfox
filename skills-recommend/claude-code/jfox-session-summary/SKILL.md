---
name: jfox-session-summary
description: |
  Use when user wants to save the current conversation/session summary into their Zettelkasten. Triggers on "保存会话", "总结到知识库", "记录这次对话", "写入知识库", "save session", "summarize to knowledge base", "log this conversation".
---

# JFox Session Summary

将当前 Claude Code 会话的总结写入 jfox 知识库（支持用户确认和笔记类型选择）。

## 前置条件

- 知识库已初始化（`jfox init`）
- 确认目标知识库（通过 `--kb` 或当前默认）

## 工作流程

### Step 1: 生成会话总结

回顾当前会话内容，生成结构化总结：

```
## 会话总结

### 主题
[一句话描述会话主要话题]

### 完成的工作
- [具体完成的任务 1]
- [具体完成的任务 2]
- ...

### 关键决策
- [决策 1 及其理由]
- [决策 2 及其理由]

### 待办 / 后续
- [未完成的事项]
- [后续步骤]
```

### Step 2: 用户确认

将生成的总结用普通文本输出，供用户阅读。然后使用 `AskUserQuestion` 询问：

- 问题：`笔记内容是否 OK？`
- 选项：
  - `内容没问题` → 继续 Step 3
  - `需要修改` → 用户在 "Other" 中输入修改意见，根据意见调整总结后回到 Step 2 重新展示和确认

循环直到用户满意为止。

### Step 3: 选择笔记类型

用户确认内容后，使用 `AskUserQuestion` 询问笔记类型：

- 问题：`选择笔记类型`
- 选项：
  - `fleeting`（推荐）— 会话记录是临时性笔记，后续可提炼为 permanent
  - `literature` — 如果会话有明确的参考资料来源
  - `permanent` — 如果总结已经是成熟的知识

### Step 4: 写入知识库

使用 Step 3 选定的笔记类型执行写入：

```bash
jfox add "<markdown-escaped-summary>" \
  --title "Session: <topic>" \
  --type <Step 3 选定的类型> \
  --tag session \
  --kb <kb-name> \
  --format json
```

**注意**：
- 标题格式统一为 `Session: <简短主题>`
- 类型使用 Step 3 的选择结果，不再硬编码 `fleeting`
- 标签统一使用 `session`
- 内容中的双引号需要转义，或使用 `--content-file` 从临时文件读取

### Step 5: 处理长内容

如果总结超过 500 字或包含特殊字符，优先使用 `--content-file`：

```bash
# 写入临时文件
cat > /tmp/session-summary.md << 'EOF'
<总结内容>
EOF

# 从文件导入
jfox add --content-file /tmp/session-summary.md \
  --title "Session: <topic>" \
  --type <Step 3 选定的类型> \
  --tag session \
  --kb <kb-name> \
  --format json
```

## 命令参考

```bash
# 直接添加（短内容）
jfox add "<summary>" --title "Session: <topic>" --type <type> --tag session --kb <name>

# 从文件添加（长内容或含特殊字符）
jfox add --content-file <path> --title "Session: <topic>" --type <type> --tag session --kb <name>

# 验证写入
jfox show <note_id> --format json
```

## 错误处理

- **"Knowledge base not found"**: 提示用户先运行 `/jfox-common` 创建知识库
- **内容过长导致 shell 解析失败**: 切换到 `--content-file` 方式
- **特殊字符转义问题**: 使用单引号包裹内容，或写入临时文件
```