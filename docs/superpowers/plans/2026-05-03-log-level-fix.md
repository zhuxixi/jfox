# 修复 load_note 空文件日志级别 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 `load_note()` 解析失败时的日志级别从 ERROR 改为 WARNING，避免误导用户。

**Architecture:** 单行改动，`note.py:105` 的 `logger.error` 改为 `logger.warning`。

**Tech Stack:** Python, pytest

---

### Task 1: 修复日志级别

**Files:**
- Modify: `jfox/note.py:105`

- [ ] **Step 1: 修改日志级别**

将 `jfox/note.py:105` 从：

```python
        logger.error(f"Failed to load note from {filepath}: {e}")
```

改为：

```python
        logger.warning(f"Failed to load note from {filepath}: {e}")
```

- [ ] **Step 2: 提交**

```bash
git add jfox/note.py
git commit -m "fix(note): downgrade load_note error log to warning for recoverable parse failures (#186)"
```
