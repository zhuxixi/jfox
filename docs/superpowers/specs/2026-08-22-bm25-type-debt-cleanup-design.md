# Spec: bm25_index.py 存量类型债清理（issue #405）

日期：2026-08-22
类型：chore（纯注解/结构修正，无行为变化）

## 目标

消除 `jfox/bm25_index.py` 的类型类 blocking 诊断（18 → ≤9，实测修后仅剩 2 条 import 环境误报）。

## 决策表

| 决策点 | 选择 | 理由 |
|--------|------|------|
| `self.documents` 注解 | `List[List[str]]` | 实际存 token 列表；pkl 格式不变，纯注解修正 |
| `new_documents` 局部注解（L803） | `List[List[str]]` | 同款债，issue 未单列但 L815 append 报点根因 |
| possibly-unbound 修法 | 快照前置（移到 try 之前） | 与 `rebuild_from_notes` 现有模式一致，结构性消除，不加 ignore |
| pickle 加载边界 | 不加 type: ignore | `index_data["documents"]` 是 Any 赋值，无告警 |
| import 无法解析（filelock/rank_bm25） | 不修 | LSP/venv 环境问题，运行时验证 OK（issue 甄别结论） |
| pickle 反序列化告警 | 不修 | 固定误报模式，数据源为自写文件 |

## 改动清单（jfox/bm25_index.py）

1. L51：`self.documents: List[str] = []` → `List[List[str]]`，注释同步改为「分词后的文档列表（每个文档为 token 列表）」
2. L803：`new_documents: List[str] = []` → `List[List[str]]`
3. `add_documents_batch`：8 个 saved_* 快照从 try 内（L648-655）移到 try 之前（仍在 `with self._mem_lock:` 内，锁语义不变）

## 非目标

- 不改 pkl 持久化格式
- 不改任何运行时行为（快照赋值 list()/dict() 本身不会抛异常，移动位置无行为差异）
- 不修 import 环境问题、pickle 反序列化告警
- 不动其他文件的类型债

## 验证

1. `npx pyright jfox/bm25_index.py`：error 从 13 → 2（仅剩 import 环境误报），0 新增
2. `uv run pytest tests/unit/test_bm25_concurrency.py tests/unit/test_bm25_batch.py -v`：全绿
3. `uv run ruff check jfox/bm25_index.py` + `uv run black --check jfox/bm25_index.py`：通过
