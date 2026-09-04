# Spec: #475 — chromadb 1.5.x 下维度迁移检测 ndarray 判空崩溃

> draft，待用户确认后落 worktree：`docs/superpowers/specs/2026-09-04-chromadb-dim-migration-ndarray-design.md`
> 分支名：`issue-475-chromadb-dim-migration-ndarray`
>
> 范围决议：#478（test_vector_store_clear.py 测试漂移）与本 issue 根因不同，按用户要求拆分独立 PR，本 spec 已剔除相关条目。

## 1. 问题与根因（调研已完成，见 research/root-cause.md）

chromadb ≥1.5 的 `Collection.peek()` 返回 `embeddings` 为 `numpy.ndarray`（旧版为 Python list）。
`jfox/embedding_migration.py::check_dimension_mismatch()` L79 `if not embeddings:` 对多元素 ndarray 布尔求值抛 `ValueError: The truth value of an array with more than one element is ambiguous`，被外层宽泛 `except Exception` 捕获后 `continue` → `affected_kbs` 恒空 → `return None` → `jfox daemon restart` 后零迁移提示，语义搜索静默失效。

已在 uv.lock 锁定的 chromadb 1.5.6 上最小复现（EphemeralClient + peek → ndarray + bool() 抛错）。

现有测试盲区：`tests/unit/test_embedding_migration.py::_FakeCollection.peek()` 返回 Python list，ndarray 路径零覆盖。

## 2. 修复设计

### Fix 1（生产代码，仅 1 处）

`jfox/embedding_migration.py` `check_dimension_mismatch()`：

```python
# before
if not embeddings:
    continue
# after
if embeddings is None or len(embeddings) == 0:
    continue
```

- `len()` 对 list / ndarray 及其元素均安全，新旧 chromadb 双兼容
- 其余逻辑零改动（Settings 对齐、daemon seam 检查、per-KB 隔离均已正确）

### Fix 2（测试，仅 tests/unit/test_embedding_migration.py）

- `_FakeCollection` 支持 peek 返回 `numpy.ndarray`（真实 1.5.x 形态；可用构造参数控制或子类）
- 新用例 A1：peek → `np.array([[0.0]*384])`，daemon health 512 维 → report 正确产出（affected_kbs 含该 KB，kb_dimensions=384）
- 新用例 A2：peek → None / 空 ndarray / 空 list → 安全跳过，不抛异常
- 保留现有 list 用例（旧 chromadb 兼容路径不回归）

## 3. 可测性拆分设计（硬约束）

| 被测单元 | 形态 | 测试边界 |
|---|---|---|
| `check_dimension_mismatch()` | 编排函数；模块级 seam（`_is_daemon_running` / `_DaemonClient` / `_GlobalConfigManager` / `chromadb`）全部可 monkeypatch | 纯 fake 注入，无真实 chromadb / daemon / 模型加载；边界 = peek 返回类型（list/ndarray/None/空）× 维度关系（等/不等）→ report 产出与否 |

现有 `_patch_env` helper 已覆盖 seam 注入，新用例复用，不新建测试基建。

## 4. 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|----|--------|----------|----------|----------|
| A1 | peek 返回 ndarray 时正确检测维度不匹配 | 自动化验证（unit） | 新用例：FakeCollection peek → `np.array([[0.0]*384])`，health_dim=512，走 `_patch_env` 注入 | report 非 None；affected_kbs 含该 KB；kb_dimensions[KB]==384 |
| A2 | peek 空值（None / 空 ndarray / 空 list）安全跳过 | 自动化验证（unit） | 三种空形态参数化用例 | 不抛异常；该 KB 不进 affected；report 为 None（无其他不匹配 KB 时） |
| A3 | 旧 chromadb list 路径不回归 | 自动化验证（unit） | 现有 `test_mismatch_detected` 等用例不改语义照跑 | 全绿 |
| A4 | 回归：相关测试文件全绿 | 自动化验证（unit） | `uv run pytest tests/unit/test_embedding_migration.py tests/unit/test_default_model_switch.py tests/unit/test_vector_store_dimension_warning.py` | 全部通过，无新增 skip/warning |
| U1 | 真实环境迁移提示端到端 | 用户实测 | 本机旧 384 维索引 KB + 512 维模型 daemon 在跑 → `jfox daemon restart` | 出现黄色警告并询问是否重建；执行时机：本机存在旧维度索引时，若无则标记 pending 不阻塞合并 |

## 5. 非目标

- #478 的 test_vector_store_clear.py 测试对齐（独立 PR）
- conftest 按 nodeid 关键词自动打 marker 的误伤面治理（另开 issue 跟踪）
- `chromadb.errors.InvalidDimensionException` 类型化捕获重构（独立评估）
- `_load()` / per-KB 宽泛 except 收窄（#481 范畴；本处 debug 日志已够定位）

## 6. 风险

- Fix 1 单行、list/ndarray 双类型安全，风险极低；不触碰 Settings / 路径 / daemon 逻辑
- Fix 2 纯测试新增，无生产风险
- U1 依赖本机存在旧维度索引，无法保证可执行 → 允许 pending
