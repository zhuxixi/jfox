# Spec: index status 只显示真实持久化状态（issue #539）

- 日期：2026-10-09
- 状态：**draft，待用户确认**
- 根因报告：`research/01-root-cause-and-contract.md`、`research/02-fix-surface.md`
- 类型：bug（CLI 显示层）· systematic-debugging Phase 1-2 完成（根因在 issue 正文
  - 当前 main 复核成立，无需复现实验——静态死路径：CLI 一次性进程不可能触发
  `Indexer.start()`）

## 1. 背景、根因、修什么（一段话版）

`jfox index status` 的 `Total Indexed` / `Last Indexed` / `Pending Changes` 三个字段
读的是 watchdog 监听器的**进程内存计数器**（`indexer.py:204-208` 的 `IndexStats`），
唯一会更新它的 `Indexer.start()` 只有长驻 embedding daemon 调用，CLI 一次性进程
结构性读到全默认值（0 / Never / 0），无论索引健康与否。同根的还有 table 模式
"Recent Errors" 段（`stats.errors` 恒空）。**修的是 status 命令的显示层：删掉三个
死的 watcher 字段，补上真实持久化数据（BM25 计数 + rebuild 时间戳），不动
indexer.py 的数据结构与 daemon 行为。**

## 2. 目标 / 非目标

目标：

1. `index status` 每个字段都对应真实持久化状态（ChromaDB 计数 + BM25 计数 +
   最近 rebuild 时间），误导性的恒零字段消失；
2. 一屏看全两套索引（issue 方案 1 括号建议）；
3. JSON 字段契约与 `docs/json-schemas.md` 同步更新，静态测试防漂移。

非目标：

- 不动 `jfox/indexer.py` 的 `IndexStats` / `NoteEventHandler` / daemon 内 Indexer
  行为（进程内计数器是否保留给 daemon 自用不在本 issue 范围）；
- 不给 daemon 加 stats/rebuild RPC 端点（方案 3 已否决）；
- 不改 `index verify`（其 `total_indexed` 是真实字段，语义不同）；
- 不做状态文件的历史回填（首次 rebuild 前显示 Never/null）。

## 3. 设计决策

| ID | 决策 | 依据 |
|----|------|------|
| D1 | status 删除三个 watcher 字段与 errors 段：JSON 去掉 `total_indexed` / `last_indexed` / `pending_changes`，table 去掉对应三行与 "Recent Errors" | CLI 场景信息量为零且误导（本 issue 核心）；三个字段零外部消费方（轮 1 事实 3） |
| D2 | status 补两个真实字段：`bm25_indexed`（复用 `bm25_index.get_stats()["indexed"]`，bm25-status 先例）与 `last_rebuild`（新状态文件，见 D4）；`vector_store` 保持原样 | 一屏看全两套索引；详情（version/path）归 bm25-status，status 保持精简 |
| D3 | 字段命名避开 `total_indexed`（`index verify` 同名真实字段的语义冲突） | 轮 1 事实 4 |
| D4 | 新模块 `jfox/index_state.py`：`load_index_state(cfg) -> dict\|None`（无文件/损坏 JSON 容错返回 None）、`save_index_state(state, cfg) -> bool`（temp+rename 原子写）；文件 `.zk/index_state.json`（与 chroma_db / bm25_index.pkl 同目录、路径推导方式与两者一致，per-KB）；内容 `{"last_rebuild": ISO8601, "semantic": bool, "notes": int}` | 最小可复用持久层；原子写防半文件 |
| D5 | 写入点：`index rebuild`（含 `--backlinks` 变体）与 `rebuild-bm25` 的成功路径（失败不写）；`semantic` 记录本次是否重建语义索引，`notes` 记 BM25 侧笔记数 | 覆盖所有"索引被重建"的真实时刻 |
| D6 | CLI 组装抽成模块级纯函数 `_index_status_payload(vs_stats, bm25_stats, state) -> dict`（cli.py），table/JSON 两态都从它取数 | 可测性拆分：组装逻辑 unit 可测，不依赖真子进程 |
| D7 | `docs/json-schemas.md:57` status 字段清单同步为 `success, vector_store, bm25_indexed, last_rebuild`，同 PR 更新 | #502 契约文档；#456 防漂移体系 |
| D8 | 新静态测试断言 schema 文档与实现不漂移（文档行含新字段组合、不含死字段组合） | 同 #559 的静态契约先例（test_nightly_script_env.py 模式） |

## 4. 改动形态（before → after 概览）

```python
# before（cli.py status 分支）
stats = indexer.get_stats()          # watcher 内存计数器，CLI 恒默认值
result = {"total_indexed": ..., "last_indexed": ..., "pending_changes": ...,
          "vector_store": vs_stats}
# table: Total Indexed / Last Indexed / Pending Changes / Vector Store Notes (+errors)

# after
vs_stats  = get_vector_store().get_stats()
bm25      = get_bm25_index().get_stats()
state     = load_index_state(config)
result    = _index_status_payload(vs_stats, bm25, state)
# {"vector_store": {...}, "bm25_indexed": int, "last_rebuild": ISO|None}
# table: Vector Store Notes / BM25 Indexed / Last Rebuild("Never" when None)
```

## 5. 本地调试与验证（分层）

- **L1 单测（秒级）**：`uv run --extra dev --extra embed pytest tests/unit/test_index_state.py tests/unit/<payload 测试文件> -q`——状态文件三分支（无文件/损坏/正常）与 payload 组装字段集；
- **L2 集成（分钟级）**：临时 KB 上真子进程跑 `index status --json`（字段断言）→ `index rebuild` → 再 status（`last_rebuild` 出现且为刚写入时间）→ `rebuild-bm25` → 时间再更新；
- **L3 本机实测（U1）**：实现完成后在你的默认库（3528 条）跑 `jfox index status`——应显示真实条数；先 `jfox index rebuild` 一次让状态文件落地，或首次显示 "Never"（不回填，D 非目标）；
- **L4 契约回归**：`uv run --extra dev --extra embed pytest tests/test_json_schema_contract.py -q` + `npx --yes markdownlint-cli2`（schema 文档改动过 lint 门禁）。

## 6. 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|----|--------|----------|----------|----------|
| A1 | 状态文件读写与容错 | 自动化验证（unit） | `uv run --extra dev --extra embed pytest tests/unit/test_index_state.py -q` | 无文件→None；损坏 JSON→None 不抛；save 后 load 回读一致；写入为原子 rename |
| A2 | payload 组装 | 自动化验证（unit） | payload 测试文件 | 字段集合 = {vector_store, bm25_indexed, last_rebuild}；无死字段；state=None → last_rebuild=None；bm25 计数取自传入 stats |
| A3 | status CLI 输出 | 自动化验证（integration） | 临时 KB 真子进程 `index status --json` + table 模式 | JSON 严格、顶层 success、字段同 A2；table 三行渲染无异常；旧三字段不再出现 |
| A4 | rebuild 落盘 | 自动化验证（integration） | `index rebuild` → status；`rebuild-bm25` → status | last_rebuild 从 null 变为时间且随后一次 rebuild 递增；semantic/notes 记录正确 |
| A5 | schema 文档同步 | 自动化验证（static） | 静态测试断言 docs/json-schemas.md | status 行含 `bm25_indexed`、`last_rebuild`；不再含 `total_indexed, last_indexed, pending_changes` 组合 |
| A6 | 契约与回归 | 自动化验证（unit+integration） | 契约测试 + 既有 index 相关单测（test_index_kb_param.py 等，更新其中钉旧字段的断言） | 全绿 |
| U1 | 本机真实库显示 | 用户实测 | 默认库 `jfox index status`（可先 rebuild 一次） | 显示真实条数（~3528）与 rebuild 时间；无恒零字段 |
| U2 | 稳定性 | 用户实测 | daemon 运行中重复执行 status ×3 | 字段值稳定，不随进程状态漂移 |

## 7. 可测性拆分设计（自动化项的硬约束）

| 函数/边界 | 签名 | 纯度 | 测试方式 |
|-----------|------|------|----------|
| `load_index_state` | `(cfg) -> dict\|None` | 读副作用隔离（只读单文件） | tmp_path 造三种文件态断言返回 |
| `save_index_state` | `(state, cfg) -> bool` | 写副作用隔离（temp+rename） | 写后回读 + 断言无残留 temp 文件 |
| `_index_status_payload` | `(vs_stats, bm25_stats, state) -> dict` | 纯 | 传入合成 dict 断言字段集与取值映射 |

实现不得把组装逻辑内联进命令分支（那样只能走 integration 级测试）；也不得在
payload 函数内做任何 IO。

## 8. 风险与缓解

| 风险 | 评估 | 缓解 |
|------|------|------|
| 既有测试钉住旧字段（test_index_kb_param.py 等） | 中——必须同 PR 更新这些断言（属行为变更的正当测试更新，非"不动现有测试"） | A6 明确纳入；实现时全仓 grep `total_indexed` 定位测试 |
| `.zk` 路径推导与 chroma/bm25 不一致导致状态文件落错位置 | 低 | D4 规定与两者同源推导；A1 用真 ZKConfig 断言路径 |
| schema 文档表格行过长影响 lint/可读性 | 低 | 行宽规则已禁用；lint 预跑 |
| 用户习惯旧字段名（肌肉记忆） | 低 | 死字段从未有过真实值，无实际信息损失；U1 验收 |

## 9. 变更文件清单（实现预估）

| 文件 | 改动 |
|------|------|
| `jfox/index_state.py` | 新建（load/save 纯函数对，~60 行） |
| `jfox/cli.py` | status 分支重写（payload 纯函数 + 新字段）；rebuild / rebuild-bm25 成功路径加 save_index_state（~50 行） |
| `docs/json-schemas.md` | :57 行 status 字段清单同步 |
| `tests/unit/test_index_state.py` | 新建（A1，~70 行） |
| `tests/unit/test_index_status_payload.py` | 新建（A2，~50 行） |
| `tests/integration/test_index_status_persist.py` | 新建（A3/A4，~90 行） |
| `tests/unit/test_json_schema_contract_doc.py` | 新建或并入既有静态测试（A5，~30 行） |
| 既有钉旧字段的测试（如 test_index_kb_param.py） | 更新断言（A6） |

## 10. 开放问题（需用户拍板）

1. BM25 字段粒度：status 只放 `bm25_indexed` 计数（推荐，version/path 详情归
   bm25-status），还是嵌套完整 `bm25_index{...}`？
2. `last_rebuild` 无状态文件时的显示：table "Never" + JSON `null`（推荐）？
3. `rebuild-bm25` 也更新 `last_rebuild`（推荐，它确实重建了索引的一半）？
4. 状态文件不做历史回填、首次 rebuild 前显示 Never（推荐，最简）？
