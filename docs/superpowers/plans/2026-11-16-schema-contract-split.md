# Schema Contract Test Split Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `tests/unit/test_json_schema_contract_doc.py`（5 条静态防漂移断言）按命令拆分为 `tests/unit/schema_contract/` 包下 3 个文件，消除 PR 并行时的结构性合并冲突（issue #601）。

**Architecture:** 纯测试文件重组：一命令一文件（index/status/edit），每文件自带 `REPO_ROOT`/`DOC` 常量与 `pytestmark`，测试函数逐字搬运（唯一例外：`REPO_ROOT` 的 `parents[2]`→`parents[3]`），旧文件删除。零生产行为变化。

**Tech Stack:** pytest（marker 由 `tests/conftest.py` 动态注册 `unit`/`fast`）、uv。

**Spec:** `docs/superpowers/specs/2026-11-16-schema-contract-split-design.md`（v2，两轮异构复核收敛）

## Global Constraints

- 所有路径相对 worktree 根（`/home/elling/work/git-repo/jfox/.pi/worktrees/issue-601-schema-contract-split`）；**禁止碰主 checkout**。
- 测试函数体**逐字搬运**：函数名、docstring、断言字符串一律不改；唯一例外是模块头 `REPO_ROOT = Path(__file__).resolve().parents[3]`（原文件为 `parents[2]`，目录深了一层）。
- **禁止**在 `tests/unit/schema_contract/` 下创建 `conftest.py` 或任何共享 DOC 的 helper（spec 已决：复制而非共享）。
- 不改 `docs/json-schemas.md`；不动 `tests/test_json_schema_contract.py`（运行时契约测试）；不新增/修改任何断言。
- `git add` 按文件逐一 stage，禁止 `git add -A`。
- commit message 用 conventional commits。

## Review Focus

1. `REPO_ROOT` 的 parents 索引抄错（残留 `parents[2]`）→ `DOC` 指向不存在的 `tests/docs/`，A2 首跑 5 条全 FileNotFoundError；reviewer 须核对新目录层级下 `parents[3]` = 仓根。
2. 断言字符串在搬运中被改动（尤其中文标点、反引号、`[]`）→ A4 的 `git diff` 逐行核对函数体。
3. `pytestmark` 值拼错（如漏 `fast`）→ A5 精确串匹配拦截。
4. 旧文件残留 → 断言重复收集；A1（文件不存在）+ A3（收集总数不变）双保险。
5. `__init__.py` 漏建（与 `tests/unit/test_edit.py` 模块名冲突）或越权加 conftest 共享 DOC → A2 收集报错 / CR 对照 spec 禁令检查。

## 验收追溯（spec ↔ plan 双向）

| spec 验收 ID | 归属 Task/Step |
|---|---|
| A1 旧文件移除、新结构就位（static） | Task 1 · Step 6 |
| A2 5 条测试全保留且通过（unit） | Task 1 · Step 7 |
| A3 全仓收集数不变（unit） | Task 1 · Step 1（基线）+ Step 9 |
| A4 函数与断言逐字保留（static） | Task 1 · Step 8 + CR `git diff` 复核 |
| A5 marker 补齐（static） | Task 1 · Step 8 |

Task 1 覆盖全部 A1–A5；无超出验收矩阵的实现步骤。

---

### Task 1: 拆分 schema 契约静态测试为按命令的包

**Files:**
- Create: `tests/unit/schema_contract/__init__.py`
- Create: `tests/unit/schema_contract/test_index.py`
- Create: `tests/unit/schema_contract/test_status.py`
- Create: `tests/unit/schema_contract/test_edit.py`
- Delete: `tests/unit/test_json_schema_contract_doc.py`

**Interfaces:**
- Consumes: `docs/json-schemas.md`（只读，被测对象，不动）
- Produces: 无代码接口；产出物是 3 个可独立运行的 pytest 文件（后续 PR 新增契约断言时新建文件即可）

- [ ] **Step 1: 捕获 A3 基线（改动前）**

Run: `uv run pytest tests/ --collect-only -q | tail -1`
Expected: `2193 tests collected`（编排者 2026-11-16 在本 worktree 实测；若数字不同，以你现场捕获值为基线并在完成报告中注明）

- [ ] **Step 2: 创建包标记**

Create `tests/unit/schema_contract/__init__.py`，内容为空文件（0 字节）。

- [ ] **Step 3: 创建 `test_index.py`**

```python
"""#539 schema 文档与 index status 实现的静态防漂移测试（#601 自 test_json_schema_contract_doc.py 拆分）。"""

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC = REPO_ROOT / "docs" / "json-schemas.md"


def test_index_status_fields_documented():
    text = DOC.read_text(encoding="utf-8")
    assert "`status`：`success, vector_store, bm25_indexed, last_rebuild`" in text


def test_index_status_dead_fields_removed_from_doc():
    text = DOC.read_text(encoding="utf-8")
    assert "success, total_indexed, last_indexed, pending_changes, vector_store" not in text
```

- [ ] **Step 4: 创建 `test_status.py`**

```python
"""#363 status backend 契约文档静态防漂移测试（#601 自 test_json_schema_contract_doc.py 拆分）。"""

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC = REPO_ROOT / "docs" / "json-schemas.md"


def test_status_backend_documents_source_field():
    """#363：status 的 backend 块新增 source 字段，文档必须跟上。"""
    text = DOC.read_text(encoding="utf-8")
    assert "backend{type,model,dimension,source}" in text


def test_status_dimension_nullability_in_breaking_changes():
    """#363：dimension 从 int 变 int|null，属破坏性变更，必须在表里登记。"""
    text = DOC.read_text(encoding="utf-8")
    assert "`backend.dimension` 可为 `null`" in text
```

- [ ] **Step 5: 创建 `test_edit.py`**

```python
"""#577 edit --json 链接字段契约文档静态防漂移测试（#601 自 test_json_schema_contract_doc.py 拆分）。"""

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[3]
DOC = REPO_ROOT / "docs" / "json-schemas.md"


def test_edit_link_fields_documented():
    text = DOC.read_text(encoding="utf-8")
    assert "note{id,title,type,filepath,links,backlinks}" in text
    assert "`links_added[], links_removed[]`（恒有，可为空数组）" in text
```

- [ ] **Step 6: 删除旧文件并执行 A1 检查**

Run: `git rm tests/unit/test_json_schema_contract_doc.py && test ! -f tests/unit/test_json_schema_contract_doc.py && ls tests/unit/schema_contract/`
Expected: 输出恰好 `__init__.py  test_edit.py  test_index.py  test_status.py`（及可能的 `__pycache__`），且 `test` 返回 0

- [ ] **Step 7: 运行 A2**

Run: `uv run pytest tests/unit/schema_contract/ -q`
Expected: `5 passed`（收集数恰为 5，无 error）

- [ ] **Step 8: 执行 A4 + A5 静态检查**

Run:
```bash
rg -c "^def test_" tests/unit/schema_contract/*.py
rg -lF "pytestmark = [pytest.mark.unit, pytest.mark.fast]" tests/unit/schema_contract/ | wc -l
git diff HEAD --stat
```
Expected: `test_edit.py:1`、`test_index.py:2`、`test_status.py:2`；第二命令输出 `3`；diff --stat 只涉及上述 5 个文件

- [ ] **Step 9: 执行 A3 复核**

Run: `uv run pytest tests/ --collect-only -q | tail -1`
Expected: 与 Step 1 基线一致（`2193 tests collected`；净变化 0）

- [ ] **Step 10: 提交**

```bash
git add tests/unit/schema_contract/__init__.py tests/unit/schema_contract/test_index.py tests/unit/schema_contract/test_status.py tests/unit/schema_contract/test_edit.py
git commit -m "refactor(test): split json schema contract doc tests per command (#601)"
```

（`git rm` 已在 Step 6 stage 删除；commit 前用 `git status --short` 确认无多余暂存）
