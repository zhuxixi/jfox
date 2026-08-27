# Issue #436 Organize Archive Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 jfox-organize 提炼流程的源笔记清理从 `delete --force` 硬删改为 `archive` 软删除，并在 jfox-common 中补充 archive 替代说明。

**Architecture:** 纯 skill 文档（Markdown）修改，共 9 处文本替换，涉及 4 个文件。organize 两个版本（pi/kimi-cli）是核心修复，common 两个版本只做补充说明（delete 是合法命令，示例保留）。

**Tech Stack:** Markdown，markdownlint-cli2 校验，rg 验证。

## Global Constraints

- 所有修改在 worktree `issue-436-organize-delete-to-archive` 内完成，禁止碰 main。
- 改动文件按文件 stage：`git add <file>`，禁止 `git add -A`。
- 所有改动后的 md 文件必须通过 markdownlint：`npx --yes markdownlint-cli2 <file>`。
- commit message 用 conventional commits（英文），每个 task 一个 commit。
- `skills-recommend/pi/` 为中文文档，`skills-recommend/kimi-cli/` 为英文文档，措辞与各文件现有语言保持一致。

---

### Task 1: pi/jfox-organize 硬删改归档（核心，中文）

**Files:**

- Modify: `skills-recommend/pi/jfox-organize/SKILL.md`

- [ ] **Step 1: 修改提炼流程第 6 步**

原文：

````markdown
6. **删除源 fleeting**：

   ```bash
   jfox delete <原始-id> --force
   ```
```

改为：

````markdown
6. **归档源 fleeting**：

   ```bash
   jfox archive <原始-id>
   ```

   archive 是软删除（文件保留），`jfox unarchive` 可恢复；误判可回滚，清理源笔记统一用 archive 而非 delete --force。
```

- [ ] **Step 2: 同步错误处理措辞**

原文：

````markdown
- **`jfox delete` 目标 ID 不存在** → 报告错误，跳过继续处理其他笔记
```

改为：

````markdown
- **`jfox archive` 目标 ID 不存在** → 报告错误，跳过继续处理其他笔记
```

- [ ] **Step 3: 验证**

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-436-organize-delete-to-archive
rg -n "delete.*--force" skills-recommend/pi/jfox-organize/SKILL.md || echo "NO-HARD-DELETE-LEFT"
npx --yes markdownlint-cli2 skills-recommend/pi/jfox-organize/SKILL.md
```

Expected: 第一条命令输出 NO-HARD-DELETE-LEFT（无残留硬删）；markdownlint 0 issues。

- [ ] **Step 4: Commit**

```bash
git add skills-recommend/pi/jfox-organize/SKILL.md
git commit -m "fix(skill): jfox-organize pi uses archive instead of delete --force (#436)"
```

---

### Task 2: kimi-cli/jfox-organize 硬删改归档（核心，英文）

**Files:**

- Modify: `skills-recommend/kimi-cli/jfox-organize/SKILL.md`

- [ ] **Step 1: 修改提炼流程第 6 步**

原文：

````markdown
6. **Delete source fleeting**:

   ```bash
   jfox delete <original-id> --force
   ```
```

改为：

````markdown
6. **Archive source fleeting**:

   ```bash
   jfox archive <original-id>
   ```

   Archive is soft delete (file preserved); `jfox unarchive` restores it. Prefer archive over delete --force so a mistaken cleanup can be rolled back.
```

- [ ] **Step 2: 修改 Command Reference**

原文（Command Reference 代码块内）：

```bash
jfox delete <id> --force
```

改为：

```bash
jfox archive <id>
```

- [ ] **Step 3: 同步错误处理措辞**

原文：

````markdown
- **`jfox delete` ID not found**: Report error; continue processing other notes
```

改为：

````markdown
- **`jfox archive` ID not found**: Report error; continue processing other notes
```

- [ ] **Step 4: 验证**

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-436-organize-delete-to-archive
rg -n "delete.*--force" skills-recommend/kimi-cli/jfox-organize/SKILL.md || echo "NO-HARD-DELETE-LEFT"
npx --yes markdownlint-cli2 skills-recommend/kimi-cli/jfox-organize/SKILL.md
```

Expected: 第一条命令输出 NO-HARD-DELETE-LEFT；markdownlint 0 issues。

- [ ] **Step 5: Commit**

```bash
git add skills-recommend/kimi-cli/jfox-organize/SKILL.md
git commit -m "fix(skill): jfox-organize kimi-cli uses archive instead of delete --force (#436)"
```

---

### Task 3: jfox-common 两版本补充 archive 说明（中文 + 英文）

**Files:**

- Modify: `skills-recommend/pi/jfox-common/SKILL.md`
- Modify: `skills-recommend/kimi-cli/jfox-common/SKILL.md`

- [ ] **Step 1: pi/jfox-common §4.4 删除笔记补充 archive 示例**

原文：

````markdown
### 4.4 删除笔记

```bash
jfox delete <note_id>               # 需确认
jfox delete <note_id> --force       # 跳过确认
```
```

改为：

````markdown
### 4.4 删除与归档笔记

```bash
jfox delete <note_id>               # 需确认
jfox delete <note_id> --force       # 跳过确认（硬删，不可恢复）
jfox archive <note_id>              # 归档（软删除）：文件保留，默认列表和搜索中隐藏
jfox unarchive <note_id>            # 恢复归档笔记
```

> 清理已提炼的源笔记优先用 archive（软删除可恢复），delete --force 仅用于确认要永久删除的场景。
```

- [ ] **Step 2: pi/jfox-common 快速参考表补 archive 行**

原文：

```bash
jfox delete <id> --force                                           # 删除笔记
```

改为：

```bash
jfox delete <id> --force                                           # 删除笔记
jfox archive <id>                                                  # 归档（软删除，可 unarchive 恢复）
jfox unarchive <id>                                                # 恢复归档笔记
```

- [ ] **Step 3: kimi-cli/jfox-common Delete Note 补充 archive 示例**

原文：

````markdown
### Delete Note

```bash
jfox delete <note_id>               # Confirm required
jfox delete <note_id> --force       # Skip confirmation
```
```

改为：

````markdown
### Delete & Archive Note

```bash
jfox delete <note_id>               # Confirm required
jfox delete <note_id> --force       # Skip confirmation (hard delete, irreversible)
jfox archive <note_id>              # Archive (soft delete): file kept, hidden from default list/search
jfox unarchive <note_id>            # Restore archived note
```

> Prefer archive (recoverable) for cleaning up source notes after refinement; use delete --force only for permanent removal.
```

- [ ] **Step 4: kimi-cli/jfox-common 快速参考表补 archive 行**

原文：

```bash
jfox delete <id> --force
```

改为：

```bash
jfox delete <id> --force
jfox archive <id>                                     # Archive (soft delete, restorable via unarchive)
jfox unarchive <id>                                   # Restore archived note
```

- [ ] **Step 5: 验证**

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-436-organize-delete-to-archive
rg -n "delete.*--force" skills-recommend/
npx --yes markdownlint-cli2 skills-recommend/pi/jfox-common/SKILL.md skills-recommend/kimi-cli/jfox-common/SKILL.md
```

Expected: rg 结果中 organize 两文件无硬删调用；common 中仅剩 delete 语法示例与快速参考行（合法保留）；markdownlint 0 issues。

- [ ] **Step 6: Commit**

```bash
git add skills-recommend/pi/jfox-common/SKILL.md skills-recommend/kimi-cli/jfox-common/SKILL.md
git commit -m "docs(skill): jfox-common recommend archive over delete --force for cleanup (#436)"
```

---

## Self-Review

- **Spec coverage**: spec 决策表 #1–#9 全部覆盖（Task 1 → #1/#2；Task 2 → #3/#4/#5；Task 3 → #6/#7/#8/#9）。非目标：不改 CLI、不抽象安全协议 skill ✓。
- **Placeholder scan**: 无 TBD/TODO，所有替换给出完整原文与目标文本 ✓。
- **一致性**: pi 版中文、kimi-cli 版英文，与现有文件语言一致 ✓。
