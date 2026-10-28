# Spec: `jfox status` 的 backend 三字段改从 daemon 取真实值（issue #363）

Drafted: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-27T08:12:07+08:00
Revised: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-27T08:24:00+08:00 · 第 1 轮复核（3 真缺口 + 3 细化）全部接受
Revised: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-27T08:32:00+08:00 · 第 2 轮复核（0 真缺口 + 3 细化）全部接受 → 收敛
Decided: user — 采纳 D3（`unloaded` 时 `dimension: null`），否决 D3-alt @ 2026-10-27T08:38:11+08:00

- 日期：2026-10-27
- 状态：**approved（用户已确认 D3 + auto 授权）**
- 基线：main @ `5920398`（v1.16.3）
- 调研与两轮交叉复核留档在仓外：`~/.github-issue-driven/zhuxixi/jfox/issue-363/`（`research/01-symptom-and-code-path.md`、`research/02-precedent-and-contract.md`、`research/spec-review-round-1.md`、`research/spec-review-round-2.md`）
- 类型：bug（CLI 显示层 + JSON 契约）· systematic-debugging Phase 1-2 已完成

## 1. 根因（一段话）

`jfox status` 的 `backend{type,model,dimension}` 来自进程内 `EmbeddingBackend` 惰性单例：`get_backend()` 只构造实例，而真正解析设备（`_resolve_device()`）和探测 daemon（`_check_daemon()`）**只在 `load()` 内发生**，`_status_impl` 从不调用 `load()`。于是三个属性各自落到兜底分支——`resolved_device` → `"unknown"`、`model_name` → `None` → 字面量 `"auto (未加载)"`、`dimension` → `return 512`。daemon 的真实状态在另一个函数的另一条路径上（`get_daemon_status()` → HTTP `/health`），两者没有交汇点。**修的是取数源：daemon 在跑时用 daemon 自报值覆盖，并把「这个值从哪来」显式暴露出来，而不是继续猜。**

## 2. 目标 / 非目标

目标：

1. daemon 运行中时，`jfox status` 的 `backend.type/model/dimension` 与 `jfox daemon status` **完全一致**（同一次检查、同源数据）；
2. 无法确知维度时不再伪造数字（不再出现 `512` 这种"默认值冒充事实"，包括经 `get_daemon_status()` 缺键兜底复发的路径）；
3. 新增 `backend.source` 让"值从哪来"可读：`daemon` / `local` / `unloaded`；
4. json / yaml / table **三种输出格式**共用同一 payload，不再出现格式间矛盾；
5. JSON schema 文档同步，并加静态防漂移测试（沿用 #539 范式）。

非目标（明确不做，避免范围蔓延）：

- **不给 `jfox daemon` 加 `--json`**——独立缺口，另开 issue；
- **不改 `backend.type` 字段名**（它装的是设备名，命名确有权衡），改名是破坏性契约变更，另开 issue；
- **不改 `embedding{local_package,daemon_running,service_available}` 块**（#519 语义）；
- **不把 `model` 的 `"auto (未加载)"` 字面量改成 `null`**——属同类契约清理，单独评估；
- **不改 `/health` 丢弃 `status`（`degraded`）字段的行为**；degraded daemon 在 `jfox status` 里表现与 `jfox daemon status` 一致即可（两者都不特别标注）；
- 不做 daemon 状态缓存 / 不做后台轮询。

## 3. 设计决策

| ID | 决策 | 依据 |
|----|------|------|
| D1 | `_status_impl` 在渲染前调用一次 `get_daemon_status()`；返回非 None 即视为 daemon 可用 | 与 `jfox daemon status` 同源，避免"两套真理"。复用而非新写 HTTP 逻辑 |
| D2 | 新增 `backend.source`，取值 `daemon` / `local` / `unloaded`：daemon 非 None → `daemon`；否则 `backend.model` 已加载 → `local`；否则 `unloaded` | issue 期望行为第二句（"至少明确标注视角"）；可测性上把三态变成一个纯函数输入 |
| D3 | `dimension` 只在可信时给整数：`daemon` → daemon 上报值；`local` → 已加载模型的真实维度；`unloaded` → **`null`**（不伪造 512/384） | issue 核心抱怨就是"维度对不上"。留有伪造值等于把 bug 修一半。**契约影响**：`dimension` 类型从 `int` 变 `int\|null`，需登记进 `docs/json-schemas.md` 的破坏性变更表 |
| D3-alt | （备选，已否决）保留整数默认值、仅靠 `source: "unloaded"` 提示不可信 | 用户 2026-10-27 选定 D3，此路作废（保留记录供追溯） |
| D4 | 组件抽成模块级纯函数 `_status_backend_payload(local, daemon_info) -> dict`，**json / yaml / table 三态共用**（`_status_impl` 实际有三条输出分支：`cli.py:1268` json、`cli.py:1270-1271` yaml、`cli.py:1272` table） | #539 先例：`_index_status_payload` 同形；组装逻辑 unit 可测、不依赖真子进程或真 daemon。三态共用一个 payload 才不会再出现格式间矛盾 |
| D5 | table 增一行 `Backend Source`（值 `daemon` / `local` / `unloaded`），`Dimension` 在 `null` 时显示 `unknown` | 表格逐行可读；不把来源塞进 `Backend` 单元格（避免 `cuda (daemon)` 这种混读） |
| D6 | 复用 `get_daemon_status()` 即接受其副作用：健康检查失败时 `_remove_pid_file()` 清理陈旧 pid 文件 | 该清理是幂等自愈且语义正确（"健康检查失败 ⇒ pid 文件失效"）；换用 `_http_health_check` 会引入第二处 `/health` 解析逻辑。**副作用本身由 A7 钉住**（清理发生且仅发生一次） |
| D7 | `docs/json-schemas.md:45` 的 `status` 行同步为 `backend{type,model,dimension,source}`（含 `dimension` 可为 `null` 的说明），并在破坏性变更表登记 `dimension: int → int\|null` | #502 契约文档是权威参考；#539 已建立"同 PR 更新 + 静态测试"纪律 |
| D8 | 新增静态测试断言 schema 文档不漂移（`tests/unit/test_json_schema_contract_doc.py` 追加两条，模式照抄 #539） | 防未来实现漂移；零运行成本 |
| D9 | 修复后回写 permanent note `202610140844473542`（补"已修复 + 正确读法"） | 知识库该笔记当前仍是"未修复"事实，留着会误导下次排障。**写 KB 属用户数据变更，须用户显式授权后执行**（见 U3） |
| D10 | `get_daemon_status()` 的 `dimension` 兜底从 `health.get("dimension", 512)` 改为 `health.get("dimension")`（缺键即 `None`）；两处消费点（`cli.py:3699-3703` 的 `_print_daemon_status`、`cli.py:3817-3822` 的 `daemon status` 分支）改用**显式判空** `"unknown" if v is None else str(v)` 显示，**不得用 `or`**（degraded daemon 上报 `dimension: 0`，`0 or "unknown"` 会把 `0` 误显示为 `unknown`，与 A8 透传断言冲突） | 512 兜底会经新路径把"伪造维度"重新引入（复核 R1-G3）。改后 `jfox daemon status` 在真 daemon 下行为不变（`/health` 恒带 `dimension`），只在异常缺键时变诚实 |

## 4. 数据流（before → after）

```
before:
  _status_impl → get_backend() → 直接读 backend.resolved_device / model_name / dimension
                                 ↑ 永不 load()，三个值恒为兜底
  jfox status ─┐
  jfox daemon status ─┘ 两条独立路径，无关联

after:
  _status_impl
    ├─ local = {"type": backend.resolved_device,      # "unknown" 可能是真话
    │            "model": backend.model_name,          # None 或 pinned 名
    │            "dimension": backend.dimension}
    └─ daemon_info = get_daemon_status()               # /health 或 None
         ↓
      _status_backend_payload(local, daemon_info) → {"type","model","dimension","source"}
         ↓
      json / yaml / table 三态共用同一 payload
```

`_status_backend_payload` 规则（纯函数，无 I/O）：

| daemon_info | backend.model | 输出 |
|---|---|---|
| 非 None | — | `type=info["device"]`, `model=info["model"]`, `dimension=info["dimension"]`, `source="daemon"` |
| None | 非 None | `type=local["type"]`, `model=local["model"]`, `dimension=local["dimension"]`, `source="local"` |
| None | None | `type=local["type"]`（通常 `"unknown"`）, `model=local["model"] or "auto (未加载)"`, `dimension=None`, `source="unloaded"` |

**保证边界**：`source="local"` 只在同进程已 `load()` 时可达（库用法 / 单测直接构造）；`jfox status` 是 CLI 一次性进程，`embedding` 块（#519）明确不触发模型加载，所以**CLI 实跑只可能出现 `daemon` 与 `unloaded` 两态**。`local` 分支保留是为了让纯函数对库调用方语义完整，不承诺 CLI 可观测。

## 5. 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|----|--------|----------|----------|----------|
| A1 | 纯函数三态组装 | 自动化验证（unit） | `uv run pytest tests/unit/test_status_backend_payload.py -q` | daemon / local / unloaded 三例各返回预期 dict；`unloaded` 的 `dimension is None`；键集合恰为 `{type,model,dimension,source}`；`daemon_info` 缺键时按 `.get` 兜底不抛 |
| A2 | daemon 在跑时三格式输出一致 | 自动化验证（unit，CliRunner + 边界 patch） | `uv run pytest tests/unit/test_status_daemon_source.py -q`（`patch("jfox.daemon.process.get_daemon_status")` 返回固定 dict，分别跑 `jfox status --json` / `--format yaml` / 默认 table） | 三态 `backend` 段一致：`{type:"cuda", model:"BAAI/bge-m3", dimension:1024, source:"daemon"}`；table 含 `Backend Source` 行且值为 `daemon` |
| A3 | 无 daemon 时不伪造维度 | 自动化验证（unit，CliRunner + patch 返回 None） | 同上文件 | `backend.source == "unloaded"`；`backend.dimension is None`；table `Dimension` 行为 `unknown`（若采纳 D3-alt 则改断言 `512`） |
| A4 | daemon 值不被本地兜底遮蔽 | 自动化验证（unit） | A2 用例内同时断言本地 `backend.model_name` 为 None 时输出 model 仍是 daemon 值 | 输出 `model != "auto (未加载)"` |
| A5 | schema 文档防漂移 | 自动化验证（static） | `uv run pytest tests/unit/test_json_schema_contract_doc.py -q` | 文档含 `backend{type,model,dimension,source}`；破坏性变更表含 `dimension` 类型变更行 |
| A6 | 无回归 | 自动化验证（unit + integration 子集） | `uv run pytest tests/unit/test_embed_availability.py tests/unit/test_daemon_cli.py tests/unit/test_daemon_process.py tests/test_json_schema_contract.py -q` | 全绿（不跑全量：全量 ~50min，按 AGENTS.md 由用户手动执行） |
| A7 | `get_daemon_status()` 本体行为（新增覆盖，原为零） | 自动化验证（unit） | `uv run pytest tests/unit/test_daemon_process.py::TestGetDaemonStatus -q`。**patch 三件套**：`_http_health_check` / `_remove_pid_file` / `_read_pid_file`（后者返回 None 或固定 dict），host/port 断言用固定值——否则开发机真跑 daemon 时 `PID_FILE`（`process.py:38`，无 env 覆盖）会让 host/port 随环境漂移 | 三例：① 健康检查返回完整 dict → 组装出 `pid/host/port/model/dimension/device`（host/port 等于 patch 注入的固定值）；② 健康检查返回 None → 函数返回 None 且 `_remove_pid_file()` 被调用一次；③ `/health` 缺 `dimension` 键 → 返回 `dimension is None`（不出现 512） |
| A8 | degraded daemon 透传行为 | 自动化验证（unit） | `uv run pytest tests/unit/test_status_backend_payload.py -q`（degraded 用例） | `daemon_info={"model":"unavailable","dimension":0,"device":"none"}` → 原样透传（`source="daemon"`、`dimension==0`）；与 `jfox daemon status` 显示一致，不额外改写 |
| A9 | `daemon status` 维度显示：None→`unknown`、0→`0` | 自动化验证（unit，CliRunner） | `uv run pytest tests/unit/test_daemon_cli.py -q`（新增两例） | ① `get_daemon_status` 返回 `dimension=None` → table 显示 `unknown`，不出现字面量 `None`；② 返回 `dimension=0`（degraded）→ table 显示 `0`，**不显示 `unknown`** |
| U1 | 真实 daemon 下两命令一致 | 用户实测 | 前置：在合入修复的分支上以 `uv run jfox …` 执行（或升级 PATH 安装版本至含修复的 release）；daemon **无需重启**——修复在 status 客户端取数，daemon 侧 `/health` 本就正确。步骤：① `jfox daemon start`（已有 daemon 则 `jfox daemon status` 确认运行中）；② `jfox status`；③ `jfox daemon status`；④ `jfox status --json \| jq .backend` | 三字段与 ③ 完全一致；`source == "daemon"`；table `Backend Source` 行显示 `daemon` |
| U2 | 停 daemon 后退化可读 | 用户实测 | 前置同 U1。步骤：① `jfox daemon stop`；② `jfox status` | `Backend Source` 显示 `unloaded`、`Dimension` 显示 `unknown`；不出现任何数字维度 |
| U3 | KB 笔记回写（D9） | 用户实测（须用户显式授权写 KB） | 授权后执行 `jfox edit 202610140844473542` 补"已修复 + 正确读法"，再 `jfox show 202610140844473542` 复核 | 笔记正文含"已修复（#363 / PR）"与"daemon 运行时应看 `jfox daemon status` 或 `jfox status --json` 的 `backend.source`"；**未获授权时标记 `pending`，不算验收完成** |

## 6. 可测性拆分设计（实现硬约束）

| 单元 | 形态 | 副作用 | 怎么测 |
|---|---|---|---|
| `_status_backend_payload(local, daemon_info)` | 纯函数，`dict` 进 `dict` 出，无 import 副作用 | 无 | 直接单测三态 + 边界（`daemon_info` 缺键用 `.get` 兜底、`local["model"]` 为空串、degraded 值）——A1 + A8 |
| `get_daemon_status()` 调用点 | 薄包装，仅做 I/O | 有（HTTP + 可能的 pid 文件清理） | 不单测内部；A2/A3 用 `patch("jfox.daemon.process.get_daemon_status")` 隔离。**该函数本体原为零测试覆盖，本 PR 新增 A7 补上（三个用例）** |
| table 渲染 | 读 payload 的展示层；`Dimension` 的 `None → "unknown"` 转换抽小函数 `_display_dimension(value)`（**显式 `is None` 判空，禁止 `or`**，否则 `0` 会被吞成 `unknown`） | 无 | `_display_dimension` 随 A1 顺带覆盖（含 `0 → "0"` 与 `None → "unknown"` 两例）；A2/A3 断言落盘文本 |
| `daemon status` 显示层 | `"unknown" if info.get("dimension") is None else str(...)` | 无 | A9（CliRunner，两例） |

**测试边界**：`_status_impl` 里只保留"取 local 快照 → 取 daemon_info → 调纯函数 → 渲染"四步直线，不允许把分支塞回 `_status_impl`；任何分支判断只存在于纯函数内，否则 A1 覆盖不到。

**导入形态硬约束**：`_status_impl` 对 `get_daemon_status` 必须在**函数内** `from .daemon.process import get_daemon_status`（照抄 `cli.py:3682-3688` 现有写法）。若改成模块顶层 import 或 `from .daemon import get_daemon_status`，A2/A3 的 patch 目标 `jfox.daemon.process.get_daemon_status` 将失效（`daemon/__init__.py:8` 已再绑定该名，patch process 属性不影响包级名），A2/A3 会在 CI 上必红。

## 7. 风险

| 风险 | 处置 |
|---|---|
| `dimension` 类型变 `int\|null` 破坏脚本 | 已登记破坏性变更表；调研确认仓内无消费方；随 minor 发布 |
| `get_daemon_status()` 在 daemon 未运行时删 pid 文件（只读命令写盘） | D6 已列，A7 ② 钉住"失败路径清理且只清一次"；若复核否决则改 `_http_health_check` |
| daemon 处于 `degraded` 时 model=`unavailable`、dimension=`0` 被原样透出 | A8 钉住"透传不改写"，与 `jfox daemon status` 一致；如需标注另开 issue |
| D10 改 `daemon status` 显示层 | 真 daemon 的 `/health` 恒带 `dimension`，非 degraded 行为不变；degraded（`dimension: 0`）靠 A9 ② 钉住仍显示 `0`，不因 `or` 判空被吞成 `unknown` |
| status 每次多一次 HTTP（timeout 2s） | daemon 未运行时多等最多 2s；`is_daemon_running()` 已在该命令里跑过（经 `embedding` 块），量级相同 |
| 修复后旧 KB 笔记仍写"未修复" | D9 + U3（须用户授权写 KB） |
