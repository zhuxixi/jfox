# chromadb 1.5.x ndarray peek 维度迁移检测修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 `check_dimension_mismatch()` 在 chromadb ≥1.5（peek 返回 numpy.ndarray）下判空抛 ValueError 被吞、导致维度迁移检测静默失效的问题（#475）。

**Architecture:** 单行判空改写使 list/ndarray 双兼容；测试侧通过既有 `_patch_env` seam 注入新增的 ndarray/空值 FakeCollection，复现真实 1.5.x peek 形态。不触碰 Settings、daemon、路径逻辑。

**Tech Stack:** Python 3.10+，pytest（unit 级，无真实 chromadb/daemon/模型），numpy（chromadb 传递依赖）。

**Work from:** `/home/elling/git-repo/github/jfox/.pi/worktrees/issue-475-chromadb-dim-migration-ndarray`（所有命令在此 worktree 内执行）

## Global Constraints

- 生产代码只改 `jfox/embedding_migration.py` 的判空一处；`len()` 写法必须同时兼容 Python list 与 numpy.ndarray（chromadb 约束 `>=0.5.0` 无上限，新旧版本都要安全）
- 不改 `_patch_env` 既有 kb_specs 元组前 5 个槽位的语义；只允许 dim 槽位额外接受预构建 collection 对象（isinstance 分支）
- 测试不加载真实 chromadb/daemon/embedding 模型，只走 monkeypatch seam（文件既有模式）
- 测试文件内注释/docstring 用英文，与 `test_embedding_migration.py` 既有风格一致；commit message 用英文 conventional commits
- spec 验收矩阵：A1（ndarray 检测）、A2（空值跳过）、A3（list 路径回归）、A4（回归四文件）、U1（用户实测，可 pending）

---

### Task 1: ndarray-safe 判空 + ndarray/空值用例

**Files:**

- Modify: `jfox/embedding_migration.py`（check_dimension_mismatch 内 peek 判空块，约 L77-81）
- Modify: `tests/unit/test_embedding_migration.py`（新增 `_NumpyPeekCollection`、`_EmptyPeekCollection`、两个测试；`_patch_env` 一处 isinstance 分支；模块顶部 `import numpy as np`）

**Interfaces:**

- Consumes: 既有 `_patch_env(monkeypatch, tmp_path, health_dim, kb_specs)`、`check_dimension_mismatch() -> Optional[DimensionMismatchReport]`
- Produces: 无新公共接口；`kb_specs` 的 dim 槽位获得"预构建 collection 对象"这一新可传值（仅测试内使用）

- [ ] **Step 1: 写失败测试与回归守卫**

在 `tests/unit/test_embedding_migration.py`：

(a) 模块顶部，`from jfox.embedding_migration import ...` 之后加：

```python
import numpy as np
```

(b) `_FakeCollection` 类定义之后新增两个子类：

```python
class _NumpyPeekCollection(_FakeCollection):
    """peek() returns numpy.ndarray — chromadb >=1.5 behavior (#475)."""

    def peek(self, limit=1):
        if self._dim is None:
            return {"embeddings": None}
        return {"embeddings": np.array([[0.0] * self._dim])}


class _EmptyPeekCollection(_FakeCollection):
    """peek() returns an explicit empty embeddings value (#475)."""

    def __init__(self, value, count=0):
        super().__init__(dim=1, count=count)
        self._value = value

    def peek(self, limit=1):
        return {"embeddings": self._value}
```

(c) `_patch_env` 内 `chroma_roots` 赋值处（原 `chroma_roots[str(chroma_root)] = _FakeCollection(dim=dim, count=count)`）改为：

```python
            if not unregistered:
                collection = (
                    dim
                    if isinstance(dim, _FakeCollection)
                    else _FakeCollection(dim=dim, count=count)
                )
                chroma_roots[str(chroma_root)] = collection
```

并把 `_patch_env` docstring 首行补一句：`dim may also be a prebuilt _FakeCollection subclass instance (injects it directly).`

(d) `TestCheckDimensionMismatch` 类内（`test_mismatch_detected` 之后）新增：

```python
    def test_mismatch_detected_with_ndarray_peek(self, monkeypatch, tmp_path):
        # chromadb >=1.5 peek() returns numpy.ndarray; the old truthiness
        # check raised ValueError inside the broad except and silently
        # skipped the KB (#475)
        _patch_env(
            monkeypatch,
            tmp_path,
            health_dim=512,
            kb_specs=[
                ("default", True, _NumpyPeekCollection(dim=384, count=100), 100),
                ("work", True, 512, 5),
            ],
        )
        report = check_dimension_mismatch()
        assert report is not None
        assert report.model_dimension == 512
        assert report.affected_kbs == ["default"]
        assert report.kb_dimensions == {"default": 384}

    @pytest.mark.parametrize(
        "empty_value",
        [None, np.empty((0, 384)), []],
        ids=["none", "empty-ndarray", "empty-list"],
    )
    def test_empty_embeddings_peek_safe_skip(self, monkeypatch, tmp_path, empty_value):
        # regression guards: empty peek values must skip the KB silently,
        # never raise (covers old-chromadb list and >=1.5 ndarray shapes)
        _patch_env(
            monkeypatch,
            tmp_path,
            health_dim=512,
            kb_specs=[
                ("default", True, _EmptyPeekCollection(value=empty_value, count=3), 3)
            ],
        )
        report = check_dimension_mismatch()
        assert report is None
```

(e) 确认模块已 import pytest；若顶部没有 `import pytest` 则补上。

- [ ] **Step 2: 跑新用例验证失败形态**

Run: `uv run pytest tests/unit/test_embedding_migration.py -q -k "ndarray_peek or empty_embeddings"`
Expected: `test_mismatch_detected_with_ndarray_peek` **FAIL**（report is None——ValueError 被吞后 KB 被 skip）；`test_empty_embeddings_peek_safe_skip` 3 个参数化用例 PASS（零元素数组 bool() 无歧义，本就安全，属回归守卫）。
若 ndarray 用例意外 PASS，停止并回查 chromadb 实际行为（调研已证 1.5.6 必崩，见 issue #475 评论）。

- [ ] **Step 3: 单行修复**

`jfox/embedding_migration.py` `check_dimension_mismatch()` 内：

```python
        # before
            peek = collection.peek(limit=1)
            embeddings = peek.get("embeddings")
            if not embeddings:
                continue
            kb_dim = len(embeddings[0])
        # after
            peek = collection.peek(limit=1)
            embeddings = peek.get("embeddings")
            # ndarray (chromadb >=1.5) raises ValueError under truthiness
            # testing; len() is safe for both list and ndarray (#475)
            if embeddings is None or len(embeddings) == 0:
                continue
            kb_dim = len(embeddings[0])
```

- [ ] **Step 4: 跑全部用例验证通过**

Run: `uv run pytest tests/unit/test_embedding_migration.py -q`
Expected: 全部 PASS（含既有 `test_mismatch_detected` / `test_all_match_returns_none` / `test_empty_kb_skipped` / `test_corrupt_kb_skipped_not_fatal` 等 list 路径，A3 回归）。

- [ ] **Step 5: 回归四文件（A4）**

Run: `uv run pytest tests/unit/test_embedding_migration.py tests/unit/test_default_model_switch.py tests/unit/test_vector_store_dimension_warning.py -q`
Expected: 全绿，无新增 skip/warning。

- [ ] **Step 6: Commit**

```bash
git add jfox/embedding_migration.py tests/unit/test_embedding_migration.py
git commit -m "fix(embedding): make dimension-migration check ndarray-safe for chromadb 1.5.x (#475)"
```

---

### Task 2: U1 用户实测（合并前执行或如实标 pending）

**Files:** 无代码改动（验收记录评论到 issue）

**Interfaces:** 无

- [ ] **Step 1: 真实迁移端到端**

前置：本机存在旧维度（384）索引的 KB + 512 维模型 daemon 在跑。若无此环境，跳到 Step 2 标 pending。
操作：`jfox daemon restart`，观察输出。
通过标准：出现黄色警告（索引维度 384 ≠ 当前模型 512）并询问是否重建。

- [ ] **Step 2: 记录结果**

把 U1 实测结果（或 pending 及原因）评论到 issue #475，与 A1-A4 的自动化证据一起作为验收对账。

---

## Self-Review

- Spec 覆盖：A1→Task1 Step1(d)+Step2-4；A2→Task1 Step1(d) 参数化守卫；A3→Task1 Step4 既有用例；A4→Task1 Step5；U1→Task2。无缺口。
- 占位符扫描：无 TBD/TODO；所有代码块完整可执行。
- 类型一致性：`_NumpyPeekCollection(dim=384, count=100)` / `_EmptyPeekCollection(value=..., count=3)` 构造签名与类定义一致；`kb_specs` 第 4 槽位 count 传值仅为文档一致性（isinstance 分支下不使用）。
