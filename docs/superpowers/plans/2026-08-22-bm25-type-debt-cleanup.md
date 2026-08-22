# BM25 存量类型债清理 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除 `jfox/bm25_index.py` 的类型类静态诊断（pyright error 13 → 2），纯注解/结构修正，无运行时行为变化。

**Architecture:** 两处注解修正（`self.documents` 与 `new_documents` 从 `List[str]` 改为 `List[List[str]]`）+ 一处结构修正（`add_documents_batch` 的 8 个 saved_* 快照从 try 内移到 try 前，与 `rebuild_from_notes` 现有模式对齐）。pkl 持久化格式不变。

**Tech Stack:** Python 3.10+、pyright 1.1.413（静态验收）、pytest（回归验收）、ruff/black（风格门禁）。

## Global Constraints

- 改动范围仅 `jfox/bm25_index.py` 一个文件，不碰其他模块
- 不改 pkl 持久化格式、不改任何运行时行为
- 不加 `# type: ignore` / `# pyright: ignore`（结构性消除，不掩盖）
- 不修 import 无法解析（filelock/rank_bm25，环境问题）与 pickle 反序列化告警（固定误报）
- 验收：`npx pyright jfox/bm25_index.py` error 13 → 2（仅剩 L17/L18 import 环境误报，0 新增）
- 回归：`uv run pytest tests/unit/test_bm25_batch.py tests/unit/test_bm25_concurrency.py -v` 48 用例全绿
- 风格：`uv run ruff check jfox/bm25_index.py` 与 `uv run black --check jfox/bm25_index.py` 通过
- commit message 用 conventional commits 格式，按文件 stage（不用 `git add -A`）

---

### Task 1: documents 注解修正（L51 + L803）

**Files:**

- Modify: `jfox/bm25_index.py:51`（`self.documents` 实例注解）
- Modify: `jfox/bm25_index.py:803`（`new_documents` 局部注解）

**Interfaces:**

- Consumes: 无（首个任务）
- Produces: `self.documents: List[List[str]]`（Task 2 的快照 `list(self.documents)` 类型随之正确）

- [ ] **Step 1: 记录基线扫描**

Run: `npx pyright jfox/bm25_index.py`
Expected: 13 errors，其中 3 条 `reportArgumentType` 位于 L516/L683/L815（`append(tokens)` 报 `List[str]` 不能赋给 `str` 参数）

- [ ] **Step 2: 修改 L51 注解**

`jfox/bm25_index.py` L51，原文：

```python
        self.documents: List[str] = []  # 分词后的文档列表
```

改为：

```python
        self.documents: List[List[str]] = []  # 分词后的文档列表（每个文档为 token 列表）
```

- [ ] **Step 3: 修改 L803 注解**

`jfox/bm25_index.py` L803，原文：

```python
                new_documents: List[str] = []
```

改为：

```python
                new_documents: List[List[str]] = []
```

- [ ] **Step 4: 扫描验证注解错误清零**

Run: `npx pyright jfox/bm25_index.py`
Expected: 3 条 `reportArgumentType` 消失，error 13 → 10（剩 8 条 `reportPossiblyUnboundVariable` + 2 条 import 环境误报），0 新增

- [ ] **Step 5: 回归测试**

Run: `uv run pytest tests/unit/test_bm25_batch.py tests/unit/test_bm25_concurrency.py -v`
Expected: 48 passed（注解在运行时被擦除，行为不变）

- [ ] **Step 6: Commit**

```bash
git add jfox/bm25_index.py
git commit -m "fix(bm25): documents 注解修正为 List[List[str]]（#405）"
```

---

### Task 2: add_documents_batch 快照前置（消除 possibly-unbound）

**Files:**

- Modify: `jfox/bm25_index.py:644-655`（快照从 try 内移到 try 前）

**Interfaces:**

- Consumes: Task 1 的 `self.documents: List[List[str]]`（快照 `list(self.documents)` 类型正确）
- Produces: `add_documents_batch` 的 except 回滚分支引用 8 个 saved_* 变量，全部在 try 前定义（与 `rebuild_from_notes` L791-799 模式一致）

- [ ] **Step 1: 移动快照到 try 之前**

`jfox/bm25_index.py` L644-655，原文：

```python
        with self._mem_lock:
            try:
                # 快照当前状态，失败时恢复（回滚必须在锁内执行，防半回滚状态被并发读）
                saved_docs = list(self.documents)
                saved_ids = list(self.doc_ids)
                saved_types = list(self.doc_types)
                saved_mapping = dict(self.doc_mapping)
                saved_bm25 = self.bm25
                saved_pending_len = len(self._pending_ops)
                saved_needs_rebuild = self.needs_rebuild
                saved_loaded_version = self._loaded_write_version
```

改为（快照移到 `try:` 之前，仍在锁内，执行顺序不变）：

```python
        with self._mem_lock:
            # 快照当前状态，失败时恢复（回滚必须在锁内执行，防半回滚状态被并发读）
            saved_docs = list(self.documents)
            saved_ids = list(self.doc_ids)
            saved_types = list(self.doc_types)
            saved_mapping = dict(self.doc_mapping)
            saved_bm25 = self.bm25
            saved_pending_len = len(self._pending_ops)
            saved_needs_rebuild = self.needs_rebuild
            saved_loaded_version = self._loaded_write_version

            try:
```

- [ ] **Step 2: 扫描验证 possibly-unbound 清零**

Run: `npx pyright jfox/bm25_index.py`
Expected: 8 条 `reportPossiblyUnboundVariable` 消失，error 10 → 2（仅剩 L17/L18 import 环境误报），0 新增

- [ ] **Step 3: 回归测试**

Run: `uv run pytest tests/unit/test_bm25_batch.py tests/unit/test_bm25_concurrency.py -v`
Expected: 48 passed（快照赋值 `list()`/`dict()`/`len()` 不会抛异常，移动位置无行为差异；`test_save_failure_rolls_back` 验证回滚语义不变）

- [ ] **Step 4: 风格门禁**

Run: `uv run ruff check jfox/bm25_index.py && uv run black --check jfox/bm25_index.py`
Expected: 两者通过，无输出错误

- [ ] **Step 5: Commit**

```bash
git add jfox/bm25_index.py
git commit -m "refactor(bm25): add_documents_batch 快照前置，消除 possibly-unbound 模式（#405）"
```

---

## Self-Review

**1. Spec coverage:** spec 的 3 项改动清单全部覆盖——L51 注解（Task 1 Step 2）、L803 注解（Task 1 Step 3）、快照前置（Task 2 Step 1）。非目标项（import/pickle 告警）未引入任务，符合 spec。

**2. Placeholder scan:** 无 TBD/TODO，所有步骤含实际代码与命令。

**3. Type consistency:** `List[List[str]]` 在 Task 1 两处与 Task 2 的 `list(self.documents)` 消费处一致；saved_* 变量名与现有 except 分支（L702-711）引用一致。
