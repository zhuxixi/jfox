---
name: jfox-session-summary
description: |
  Use when user wants to save the current conversation/session summary into their Zettelkasten as a fleeting note. Triggers on "保存会话", "总结到知识库", "记录这次对话", "写入知识库", "save session", "summarize to knowledge base", "log this conversation".
---

# JFox Session Summary

将当前 Claude Code 会话的总结写入 jfox 知识库作为 fleeting 笔记。

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

### Step 2: 写入知识库

```bash
jfox add "<markdown-escaped-summary>" \
  --title "Session: <topic>" \
  --type fleeting \
  --tag session \
  --kb <kb-name> \
  --format json
```

**注意**：
- 标题格式统一为 `Session: <简短主题>`
- 类型使用 `fleeting`（会话记录是临时性笔记，后续可提炼为 permanent）
- 标签统一使用 `session`
- 内容中的双引号需要转义，或使用 `--content-file` 从临时文件读取

### Step 3: 处理长内容

如果总结超过 500 字或包含特殊字符，优先使用 `--content-file`：

```bash
# 写入临时文件
cat > /tmp/session-summary.md << 'EOF'
<总结内容>
EOF

# 从文件导入
jfox add --content-file /tmp/session-summary.md \
  --title "Session: <topic>" \
  --type fleeting \
  --tag session \
  --kb <kb-name> \
  --format json
```

## 命令参考

```bash
# 直接添加（短内容）
jfox add "<summary>" --title "Session: <topic>" --type fleeting --tag session --kb <name>

# 从文件添加（长内容或含特殊字符）
jfox add --content-file <path> --title "Session: <topic>" --type fleeting --tag session --kb <name>

# 验证写入
jfox show <note_id> --format json
```

## 错误处理

- **"Knowledge base not found"**: 提示用户先运行 `/jfox-common` 创建知识库
- **内容过长导致 shell 解析失败**: 切换到 `--content-file` 方式
- **特殊字符转义问题**: 使用单引号包裹内容，或写入临时文件
```