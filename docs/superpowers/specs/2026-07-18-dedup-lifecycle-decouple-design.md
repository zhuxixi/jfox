# gem-synth dedup 生命周期解耦设计（消除核心层反向依赖）

**日期**：2026-07-18
**目标 PR 分支**：`refactor/dedup-lifecycle-decouple`（main 受保护，新分支 + PR）
**关联 Issue**：#310
**前置**：PR #308（dedup 主干，已合 `379dc21`）；本 PR 是 #308 合并前 acknowledge 的 2 个 low 架构债的正解
**KB 依据**：permanent 笔记 `20260712223046-705752`（jfox 分层约束）

## 1. 问题

PR #308 给 gem-synth 加 dedup 时，把"笔记生命周期 → 同步 dedup 表"的钩子塞进核心存储层 `note.py` 的 4 个函数（delete/archive/promote/reject），靠函数体内 `from .gem_synth.dedup import ...` lazy import 调特性层。

违例点（note.py，PR #308 引入）：

| 函数 | 行 | 同步动作 |
|---|---|---|
| `delete_note` | 285 | `delete_dedup` + `release_blocked_anchors`（仅 candidate/permanent）|
| `archive_note` | 331 | 同上 |
| `promote_note` | 447 | `update_dedup_type(..., "permanent")` |
| `reject_note` | 475 | `delete_dedup` + `release_blocked_anchors` |

违反 CLAUDE.md『Core Data Flow』分层约定：依赖应单向（特性层 `gem_synth` → 存储层 `note.py`），不能反向。lazy import 只是绕循环 import 的创可贴。**纯架构债，零运行时 bug。**

调用方高度集中（仅 4 点）：`delete_note→cli.py:1421`、`archive_note→cli.py:1483`、`promote_note→gem_synth/cli.py:172`、`reject_note→gem_synth/cli.py:210`。

## 2. 目标 / 非目标

**目标**
- `note.py` / `global_config.py` 零 `gem_synth.dedup` import（核心层零反向依赖）。
- dedup 生命周期同步行为完全不变（delete/archive/promote/reject 后 dedup 表状态一致）。
- 现有 dedup 测试行为覆盖不回归。

**非目标**
- **不修** `rename_knowledge_base` 的 `dedup_embeddings.kb` 迁移（#310 验收第 3 条 deferred）：依据 KB 笔记 `...705752` 决策——用户不重命名 KB，`jfox gem-synth dedup-backfill` 可兜底。记为已知限制。
- 不改 dedup 算法 / threshold / 配置。
- 不改 `dedup_embeddings` schema。

## 3. 架构：生命周期事件 + 订阅（方案 B）

引入**特性→核心的反向通知机制**：`note.py` 发生命周期事件，`gem_synth` 订阅。`note.py` 保持纯存储，不 import `gem_synth`。

### 3.1 note.py 注册表（新，零 gem_synth 依赖）

`note.py` 加模块级注册表 + 三个 API：
- `register_lifecycle_hook(event: str, callback: Callable) -> None`（幂等：重复注册同一 callback 不叠加）
- `unregister_lifecycle_hook(event: str, callback: Callable) -> None`（取消注册，主要用于测试清理）
- `_dispatch(event: str, **payload) -> None`：遍历该 event 的回调，每个独立 `try/except logger.warning`（保持现有「dedup 同步失败仅 warning 不阻塞」语义）

事件：`post_delete` / `post_archive` / `post_promote` / `post_reject`。payload：`note_id: str` + `note_type: NoteType`（枚举，由 `note.type` 传入）。

`note.py` 4 处 lazy import 块替换为 `_dispatch("post_xxx", note_id=..., note_type=...)`。**无条件触发**（类型守卫下移到订阅器，§3.3）。

### 3.2 gem_synth 订阅器（新 `jfox/gem_synth/lifecycle.py`）

4 个回调，复刻现有同步逻辑（kb 由订阅器内 `_resolve_kb_name(None)` 解析，与现状一致）：

| 回调 | 动作（复刻自现有 note.py 块）|
|---|---|
| `_on_deleted` | `delete_dedup(kb, note_id)` + `release_blocked_anchors(note_id)` |
| `_on_archived` | 同 `_on_deleted` |
| `_on_promoted` | `update_dedup_type(kb, note_id, "permanent")` |
| `_on_rejected` | `delete_dedup(kb, note_id)` + `release_blocked_anchors(note_id)` |

`register()`：把 4 回调注册到 `note.register_lifecycle_hook`。所有 dedup 调用都在 `gem_synth` 内部，合规。

### 3.3 类型守卫下移

订阅器每个回调首行：`if note_type not in (NoteType.CANDIDATE, NoteType.PERMANENT): return` 早返回，不实例化 `DedupStore` → 满足现有注释意图「未启用 gem-synth 用户不创建 synthesis_log.db 污染」。`note.py` 无条件广播，不硬编码「哪些类型有 dedup」。

### 3.4 注册时机（关键设计点）

`gem_synth.lifecycle.register()` 由 **`jfox/__init__.py` 模块级**调用一次（实施期 cc 审查驱动从 cli.py 上移，覆盖库式调用方）。理由：
- `__init__` 是包顶层，任何 `import jfox.*`（CLI、库式 `from jfox.note import ...`、daemon/脚本）都触发包加载 → 订阅就位，无隐式调用顺序耦合。
- `__init__ → gem_synth` 是包顶层依赖，合规（验收只禁 `note.py`/`global_config.py` 反向依赖）。
- daemon 进程（gem-synth loop）入口本就 import `gem_synth`，由其 import 链覆盖（writing-plans 阶段 grep 确认 daemon 入口触发 register，必要时在 daemon 启动显式调）。
- 测试经 `jfox/__init__` 自动 register（`import jfox.*` 即触发），但 `tests/unit/conftest.py` autouse 每测清空 `_LIFECYCLE_HOOKS` 做隔离；`test_note_dedup_sync` 的 `_mock_backend` fixture 显式调 `register()` 确保测试运行时订阅就位。`test_note_lifecycle_hooks` / `test_gem_synth_lifecycle` 各自隔离测注册表与订阅器。

## 4. 文件变动

| 文件 | 变动 |
|---|---|
| `jfox/note.py` | 新增注册表 + `register_lifecycle_hook`/`_dispatch` API；4 处 lazy import → `_dispatch`；删 `gem_synth` import |
| `jfox/gem_synth/lifecycle.py`（新）| 4 回调 + `register()`，复刻 dedup 同步逻辑 |
| `jfox/__init__.py` | 模块级调 `gem_synth.lifecycle.register()`（包顶层接线，CLI + 库式调用方都覆盖；实施期从 cli.py 上移）|
| `jfox/gem_synth/dedup.py` | 无变动（API 不变，仍被 `lifecycle.py` 调）|
| `jfox/global_config.py` | 无变动（本就干净，KB-rename 不修）|

## 5. 测试策略（快速单测，可自主跑）

- `tests/unit/test_note_lifecycle_hooks.py`（新）：注册表纯单测——`register`/`_dispatch`、多回调、异常隔离（一个回调抛不影响其他）、幂等 register。不依赖 `gem_synth`。
- `tests/unit/test_gem_synth_lifecycle.py`（新）：订阅器单测——4 事件回调正确调 dedup API、类型守卫（fleeting/literature 早返回不实例化 store）、kb 解析。
- `tests/unit/test_note_dedup_sync.py`（重构，不删）：**入口不变**（仍调 `note.delete_note/archive_note/promote_note/reject_note`），断言点保持（dedup store 被正确调用）；fixture 确保注册已发生。fleeting-skip 测试语义保留。**行为覆盖不回归。**
- 集成/daemon 路径提供命令让用户手动验证（不自主跑全量）。

## 6. 实施顺序（writing-plans 会细化）

1. `note.py`：注册表 + `register`/`_dispatch` API（先不接旧调用点）
2. `gem_synth/lifecycle.py`：4 回调 + `register()`
3. `jfox/__init__.py`：模块级调 `register()`
4. `note.py`：4 处 lazy import 块替换为 `_dispatch`（一次性切，删 `gem_synth` import）
5. 重构 `test_note_dedup_sync` + 新增 2 个单测文件
6. grep 确认 `note.py`/`global_config.py` 零 `gem_synth` import
7. 单测 `uv run pytest tests/unit/test_note_lifecycle_hooks.py tests/unit/test_gem_synth_lifecycle.py tests/unit/test_note_dedup_sync.py -v`
8. PR（CR 走 zima 双 bot + CI 绿后合）

## 7. 验收映射（Issue #310）

| #310 验收项 | 处置 |
|---|---|
| `note.py`/`global_config.py` 不再 import `gem_synth.dedup` | ✅ §3.1 + §4 |
| dedup 生命周期同步行为不变 | ✅ §3.2 复刻 |
| `rename_knowledge_base` 迁移 `dedup_embeddings.kb` | ⏭️ deferred（§2 非目标，KB 笔记决策；PR 评论 + issue 说明）|
| 现有 dedup 测试不回归 | ✅ §5 行为覆盖不变 |

## 8. 风险 / 回退

- **注册时机遗漏**：某入口调 note 生命周期函数但未触发 `register()` → dedup 不同步。缓解：`jfox/__init__.py` 模块级 register 覆盖任何 `import jfox.*`（CLI + 库式调用方）；daemon 由其 import 链覆盖；测试显式 register。grep 守卫 + 集成验证。
- **行为回归**：复刻逻辑时漏掉守卫/顺序（如 archive 须 `update_note` 成功后才同步）。缓解：`test_note_dedup_sync` 行为断言逐条保留；type guard 下移后 fleeting-skip 语义单测。
- **回退**：纯重构，revert PR 即恢复 lazy import。`dedup_embeddings` 数据不动。
