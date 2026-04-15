# Session Summary Confirmation Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add user confirmation and note type selection steps to the jfox-session-summary skill before writing to the knowledge base.

**Architecture:** Insert two new steps (confirm content + select type) between summary generation and `jfox add`. The modification is purely in the skill Markdown document — no Python code changes.

**Tech Stack:** Skill document (Markdown), AskUserQuestion tool

**Spec:** `docs/superpowers/specs/2026-04-15-session-summary-confirmation-design.md`

---

### Task 1: Rewrite SKILL.md workflow section

**Files:**
- Modify: `skills-recommend/claude-code/jfox-session-summary/SKILL.md`

This is the only task. The file is a single skill document — no decomposition needed.

- [ ] **Step 1: Read current SKILL.md**

Read `skills-recommend/claude-code/jfox-session-summary/SKILL.md` to confirm current content matches expectations (3-step workflow, Step 2 hardcodes `--type fleeting`).

- [ ] **Step 2: Replace Step 2 and add new Steps 2–3**

Replace the entire `### Step 2: 写入知识库` section and everything after it (through end of file) with the new 5-step workflow. The exact replacement content:

Replace the old `### Step 2` and `### Step 3` sections (lines 42–96) with:

```markdown
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

- [ ] **Step 3: Verify the file reads correctly**

Read the full updated `SKILL.md` and confirm:
1. Step 1 (生成会话总结) is unchanged
2. Step 2 (用户确认) has AskUserQuestion with "内容没问题" and "需要修改" options, plus loop description
3. Step 3 (选择笔记类型) has AskUserQuestion with fleeting/literature/permanent options
4. Step 4 (写入知识库) uses `<Step 3 选定的类型>` not hardcoded `fleeting`
5. Step 5 (处理长内容) also uses `<Step 3 选定的类型>`
6. 命令参考 section shows `--type <type>` not `--type fleeting`
7. No leftover hardcoded `fleeting` in any `jfox add` example (except the Step 3 option description)

- [ ] **Step 4: Commit**

```bash
git add skills-recommend/claude-code/jfox-session-summary/SKILL.md
git commit -m "feat(skill): add user confirmation and note type selection to session-summary

Inserts Step 2 (content confirmation via AskUserQuestion) and Step 3
(note type selection) before writing to knowledge base. Users can now
review the generated summary, request modifications, and choose between
fleeting/literature/permanent note types.

Closes #154"
```
