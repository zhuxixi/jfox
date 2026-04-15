# 同步 daemon + show 命令文档，新增 session-summary skill，删除旧 skill 目录

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 #144 (daemon) 和 #146 (show) 两个新功能的文档同步到 README.md、CLAUDE.md、skills-recommend/，新增 jfox-session-summary skill，删除旧 skill/ 目录。

**Architecture:** 纯文档和 skill 文件更新，不涉及 Python 代码改动。按依赖顺序：先更新核心文档（README/CLAUDE.md），再更新 skill 文件，最后清理旧目录。

**Tech Stack:** Markdown, GitHub CLI (`gh`)

---

## File Structure

| Action | File | Responsibility |
|--------|------|----------------|
| Modify | `README.md` | 添加 daemon 架构节点、Module Map 行、show/daemon 命令 |
| Modify | `CLAUDE.md` | 更新 cli.py 行数、添加 show 命令约定 |
| Modify | `skills-recommend/claude-code/jfox-common/SKILL.md` | 补充 show、daemon 命令 |
| Modify | `skills-recommend/claude-code/jfox-ingest/SKILL.md` | 补充 show 命令 |
| Modify | `skills-recommend/claude-code/jfox-organize/SKILL.md` | 补充 show 命令 |
| Modify | `skills-recommend/claude-code/jfox-search/SKILL.md` | 补充 show、daemon 提示 |
| Create | `skills-recommend/claude-code/jfox-session-summary/SKILL.md` | 新 skill：会话总结写入知识库 |
| Modify | `skills-recommend/README.md` | 目录添加 jfox-session-summary |
| Delete | `skill/` | 旧版 skill 目录（zk 前缀） |

---

### Task 1: README.md — 架构图添加 daemon 层

**Files:**
- Modify: `README.md:42-70` (Architecture 架构图)

- [ ] **Step 1: 在架构图 Index Layer 中添加 daemon 节点和连线**

在 `README.md` 第 56 行（`emb[embedding_backend.py...]` 之后）添加 daemon 节点，并在连线部分添加 daemon 关系：

```diff
  subgraph Index ["Index Layer"]
      se[search_engine.py<br/>HybridSearchEngine]
      vs[vector_store.py<br/>ChromaDB]
      bm[bm25_index.py<br/>BM25Okapi]
      emb[embedding_backend.py<br/>all-MiniLM-L6-v2]
+     daemon["daemon/<br/>HTTP Server (可选)"]
  end
```

连线部分（第 65-69 行）添加：

```diff
  cmd --> note & se & gph
  note --> models --> md
  se --> vs & bm
  vs --> emb
+ emb -.->|"fallback"| daemon
  idx --> vs
```

- [ ] **Step 2: 在 Module Map 表格添加 daemon/ 行**

在 `README.md` 第 85 行（`embedding_backend.py` 行之后）插入：

```
| `daemon/` | Embedding HTTP 守护进程，常驻模型避免重复加载 |
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add daemon module to README architecture diagram and module map"
```

---

### Task 2: README.md — Command Reference 添加 show 和 daemon 命令

**Files:**
- Modify: `README.md:257-273` (Notes 章节), `README.md:308-313` (Performance & Debug 章节)

- [ ] **Step 1: 在 Notes 章节表格添加 show 命令**

在 `README.md` 第 273 行（`jfox ingest-log` 行之后，`### Search & Analysis` 之前）插入：

```
| `jfox show NOTE_ID` | View full note content in terminal |
```

- [ ] **Step 2: 在 Performance & Debug 章节之后添加 Daemon 章节**

在 `README.md` 第 313 行（`jfox perf clear-cache` 行之后）添加新的表格章节：

```markdown
### Daemon

| Command | Description |
|---------|-------------|
| `jfox daemon start` | Start embedding daemon (background process) |
| `jfox daemon stop` | Stop embedding daemon |
| `jfox daemon status` | Show daemon PID, port, model info |
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add show and daemon commands to README command reference"
```

---

### Task 3: CLAUDE.md — 更新 cli.py 行数和 show 命令约定

**Files:**
- Modify: `CLAUDE.md:59` (cli.py 行数), `CLAUDE.md:98` (Adding a CLI command)

- [ ] **Step 1: 更新 cli.py 行数**

`CLAUDE.md` 第 59 行：

```diff
- | `cli.py` | All CLI commands (~1800 lines). Commands follow pattern: `@app.command()` → `_xxx_impl()` helper for reuse |
+ | `cli.py` | All CLI commands (~2500 lines). Commands follow pattern: `@app.command()` → `_xxx_impl()` helper for reuse |
```

- [ ] **Step 2: 添加 show 命令约定**

`CLAUDE.md` 第 98 行（`Adding a CLI command` 之后）添加一条约定：

```
- **Viewing note content**: `jfox show <id_or_title>` 复用 `find_note_id_by_title_or_id` 定位笔记，只读输出完整 Markdown
```

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: update CLAUDE.md with current cli.py size and show command convention"
```

---

### Task 4: jfox-common skill — 补充 show 和 daemon 命令

**Files:**
- Modify: `skills-recommend/claude-code/jfox-common/SKILL.md:310-340` (命令参考)

- [ ] **Step 1: 在笔记 CRUD 章节添加 show 命令**

在 `jfox-common/SKILL.md` 的笔记 CRUD 部分（`jfox list` 命令之前）添加：

```bash
jfox show <id_or_title> --format json           # 查看笔记完整内容
```

- [ ] **Step 2: 在健康检查章节之后添加 Daemon 章节**

在 `jfox-common/SKILL.md` 命令参考末尾（健康检查章节之后）添加：

```markdown
### Daemon（可选）

```bash
jfox daemon start                               # 启动 embedding 守护进程
jfox daemon stop                                # 停止守护进程
jfox daemon status                              # 查看 PID、端口、模型信息
```

注意：daemon 依赖（fastapi、uvicorn）已作为必选依赖安装，`jfox daemon start` 可直接使用。
```

- [ ] **Step 3: Commit**

```bash
git add skills-recommend/claude-code/jfox-common/SKILL.md
git commit -m "docs(skill): add show and daemon commands to jfox-common skill"
```

---

### Task 5: jfox-ingest skill — 补充 show 命令

**Files:**
- Modify: `skills-recommend/claude-code/jfox-ingest/SKILL.md:219-242` (命令参考)

- [ ] **Step 1: 在命令参考中添加 show 命令**

在 `jfox-ingest/SKILL.md` 命令参考部分（`jfox add` 手动添加命令之后）添加：

```bash
# 查看导入结果
jfox show <note_id> --format json --kb name
```

- [ ] **Step 2: Commit**

```bash
git add skills-recommend/claude-code/jfox-ingest/SKILL.md
git commit -m "docs(skill): add show command to jfox-ingest skill"
```

---

### Task 6: jfox-organize skill — 补充 show 命令

**Files:**
- Modify: `skills-recommend/claude-code/jfox-organize/SKILL.md:151-164` (命令参考)

- [ ] **Step 1: 在命令参考中添加 show 命令**

在 `jfox-organize/SKILL.md` 命令参考部分（`jfox inbox` 命令之后）添加：

```bash
jfox show <id_or_title> --format json           # 查看笔记完整内容（整理前预览）
```

- [ ] **Step 2: Commit**

```bash
git add skills-recommend/claude-code/jfox-organize/SKILL.md
git commit -m "docs(skill): add show command to jfox-organize skill"
```

---

### Task 7: jfox-search skill — 补充 show 和 daemon 提示

**Files:**
- Modify: `skills-recommend/claude-code/jfox-search/SKILL.md:38-48` (搜索结果展示), `README.md:102-106` (Error Handling)

- [ ] **Step 1: 在搜索结果展示中添加 show 提示**

在 `jfox-search/SKILL.md` 的搜索结果展示模板（第 48 行后）添加提示：

```
提示：使用 `jfox show <note_id>` 查看笔记完整内容。
```

- [ ] **Step 2: 在 Error Handling 中添加 daemon 提示**

在 `jfox-search/SKILL.md` 的 Error Handling 部分（"Slow search" 条目）替换为：

```diff
- - **Slow search**: First search loads embedding model (30-60s). Subsequent searches are fast.
+ - **Slow search**: First search loads embedding model (30-60s). Subsequent searches are fast. 可通过 `jfox daemon start` 启动守护进程避免重复加载。
```

- [ ] **Step 3: Commit**

```bash
git add skills-recommend/claude-code/jfox-search/SKILL.md
git commit -m "docs(skill): add show hint and daemon tip to jfox-search skill"
```

---

### Task 8: 新增 jfox-session-summary skill

**Files:**
- Create: `skills-recommend/claude-code/jfox-session-summary/SKILL.md`
- Modify: `skills-recommend/README.md`

- [ ] **Step 1: 创建 skill 文件**

创建 `skills-recommend/claude-code/jfox-session-summary/SKILL.md`：

```markdown
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

- [ ] **Step 2: 更新 skills-recommend/README.md 目录结构**

在 `skills-recommend/README.md` 第 9 行的目录结构中添加 `jfox-session-summary`：

```diff
  skills-recommend/
  └── claude-code/          # Claude Code 专用 SKILL.md 格式
      ├── jfox-ingest/      # 数据导入（git log / GitHub PR / Issues）
      ├── jfox-organize/    # 知识库整理与提炼（fleeting → permanent）
      ├── jfox-search/      # 知识库搜索与图谱查询
+     ├── jfox-session-summary/  # 会话总结写入知识库
      └── jfox-common/      # 知识库管理 + 健康检查
```

在斜杠命令列表中（第 34 行附近）添加：

```diff
  - `/jfox-organize` — 整理知识库、提炼 permanent 笔记、生成 [[wiki links]]
  - `/jfox-search` — 搜索笔记、图谱查询、链接推荐
+ - `/jfox-session-summary` — 将会话总结写入知识库作为 fleeting 笔记
```

- [ ] **Step 3: Commit**

```bash
git add skills-recommend/claude-code/jfox-session-summary/SKILL.md skills-recommend/README.md
git commit -m "docs(skill): add jfox-session-summary skill for saving session summaries"
```

---

### Task 9: 删除旧 skill/ 目录

**Files:**
- Delete: `skill/evals/evals.json`
- Delete: `skill/knowledge-base-notes/SKILL.md`
- Delete: `skill/knowledge-base-workspace/SKILL.md`
- Delete: `skill/` (整个目录)

- [ ] **Step 1: 删除 skill/ 目录**

```bash
git rm -r skill/
```

- [ ] **Step 2: Commit**

```bash
git commit -m "chore: remove legacy skill/ directory (replaced by skills-recommend/)"
```

---

### Task 10: 最终验证

- [ ] **Step 1: 检查 README.md 中 daemon 和 show 的完整性**

```bash
grep -n "daemon" README.md
grep -n "jfox show" README.md
```

预期：daemon 在架构图（1处）、Module Map（1处）、Command Reference（3条命令）中出现；show 在 Command Reference Notes（1条）中出现。

- [ ] **Step 2: 检查 CLAUDE.md 更新**

```bash
grep -n "~2500" CLAUDE.md
grep -n "jfox show" CLAUDE.md
```

- [ ] **Step 3: 检查 skills-recommend 目录结构**

```bash
ls skills-recommend/claude-code/
```

预期：`jfox-common  jfox-ingest  jfox-organize  jfox-search  jfox-session-summary`

- [ ] **Step 4: 确认旧 skill/ 目录已删除**

```bash
ls skill/ 2>&1
```

预期：`No such file or directory` 或类似错误。

- [ ] **Step 5: 最终 commit（如有 lint/格式修正）**

```bash
git add -A
git status
# 如有未提交的修正：
git commit -m "docs: final cleanup for #147 sync"
```

---

## Self-Review

**1. Spec coverage:**

| Issue #147 要求 | 对应 Task |
|---|---|
| README 架构图添加 daemon | Task 1 |
| README Module Map 添加 daemon/ | Task 1 |
| README Command Reference 添加 show | Task 2 |
| README Command Reference 添加 daemon | Task 2 |
| CLAUDE.md 更新 cli.py 行数 | Task 3 |
| CLAUDE.md 添加 show 约定 | Task 3 |
| jfox-common skill 补充 show/daemon | Task 4 |
| jfox-ingest skill 补充 show | Task 5 |
| jfox-organize skill 补充 show | Task 6 |
| jfox-search skill 补充 show/daemon | Task 7 |
| 新增 jfox-session-summary skill | Task 8 |
| skills-recommend README 更新目录 | Task 8 |
| 删除旧 skill/ 目录 | Task 9 |
| 最终验证 | Task 10 |

**2. Placeholder scan:** No TBD/TODO/placeholders found. All steps contain exact code or commands.

**3. Type consistency:** No code types to verify — this is a documentation-only plan. File paths and command syntax are consistent across all tasks.
