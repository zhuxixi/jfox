# Spec: #502 `--json` 输出轻量统一（success 分流 + 错误必 JSON + 文档化）

> 状态：draft（待用户审阅）
> Issue: zhuxixi/jfox#502
> 调研依据：`~/.claude/github-issue-driven/zhuxixi/jfox/issue-502/research/schema-inventory.md`（全命令 schema 盘点）
> 路线：中间路线（用户 2026-09-10 确认）；裸数组包装成对象（用户确认）

## 1. 背景

jfox CLI 27 个顶层命令 + 9 个 typer 子应用、50+ JSON 输出点，成功 schema 分裂为 8 种形状：约 40 个输出点（全部查询/读类命令）成功输出**无 `success` 字段**，agent 无法用统一逻辑分流成败；部分错误分支在 JSON 模式下只 console 打印不输出 JSON（stdout 为空）。`jfox add --json` 的 `id` 嵌套在 `note` 里导致顶层解析静默得 null → 误判失败 → 重跑产生重复笔记（issue 正文实例）。

关联层已修复：#383/#483（防重 + JSON 纯净输出，v1.12.1）、#482/#522（bm25 日志降级）。本 issue 只剩 schema 层。

## 2. 目标与非目标

**目标**：

1. agent/脚本一条规则分流所有命令：顶层 `d["success"]` 布尔判断成败。
2. 错误信息永远可从 stdout JSON 拿到：`{success: false, error: "..."}` + 退出码 1。
3. schema 有文档（`docs/json-schemas.md`）。

**非目标**：

- 不动实体字段位置（`note` 嵌套 / `show` 平铺 / `results`/`notes` 列表键保持现状——留给未来 2.0 纯 envelope）。
- 不引入 `schema_version` / `command` / `data` 字段。
- 不改 `--format` 非 json 值静默走默认输出（KB 确认 wontfix-by-design）。
- 不统一 4 套序列化通道（`output_json` / `OutputFormatter.to_json` / 裸 `json.dumps` / `_json_console`）——只统一**形状**，不动**通道**。

## 3. 设计决策表

| # | 决策 | 依据 |
|---|------|------|
| D1 | 键名用 `success` 不用 `ok` | 对齐现有 40+ 错误输出点；KB 笔记「CLI JSON 响应须保持成功/错误 schema 对称」（20260713011331-845663）推荐 |
| D2 | 各命令显式在 result 构造处加 `"success": True`，不做 `output_json` 自动注入 | 透传 dict（`index verify` 的 `healthy` dict 已有 `error` 键）会撞键；显式优于隐式，review 清楚 |
| D3 | 裸数组包装为 `{success:true, items:[...]}` | 用户确认；规则零例外优于零破坏（低频管理命令，破坏面小，CHANGELOG 标注） |
| D4 | `auto-summary run` 的 `success` 计数重命名 `succeeded` | int 语义与全库布尔语义冲突必须消除；对齐 `prompts judge` 的 `succeeded` |
| D5 | schema 文档手工维护（docs/json-schemas.md），不挂 generate_docs.py | 生成脚本只提取 click.Parameter 参数表，输出 schema 无来源可提取 |
| D6 | 版本 1.14.0（minor） | 纯增量为主；2 个小 breaking（D3/D4）低频且 CHANGELOG 标注 |
| D7 | #483 固化形状零改动 | 防重输出 `{success:false, skipped:"duplicate", duplicate{...}}` 原样；`test_add_dedup_cli.py` 不动 |

## 4. 变更内容

### C1 全命令成功输出顶层补 `success: true`

**范围**（盘点确认当前无 `success` 的成功输出点，约 40 处）：

主 CLI：`search`、`status`、`list`、`show`、`refs`（3 分支）、`query`、`graph`（3 分支）、`daily`、`inbox`、`suggest-links`、`index`（`status`/`bm25-status`/`verify` 三个 action）、`kb`（`list`/`current`/`info`）、`bulk-import`、`check`。

子应用：`template list/show`、`fragments list/show`、`prompts list/show/status/drain/backfill/judge/config`、`candidates show/list`、`bookshelf list/show/remove`、`auto-summary status/scan/run`、`backup status/list/verify`。

（`init/add/edit/delete/archive/unarchive/ingest-log/update/redirect/model download`、`moc` 全部、`template create/remove`、`kb create/switch/use/remove/delete/rename`、`auto-summary enable/disable/forget/prune`、`bookshelf add`、`candidates promote/reject` 已带 `success`，不动。）

实现：各命令 result dict 构造处显式加 `"success": True`（D2）。

### C2 修复「JSON 模式下错误不输出 JSON」分支

统一规则：JSON 输出模式下任何错误路径输出 `{"success": false, "error": "<message>"}` + `raise typer.Exit(1)`。

修复清单（盘点确认；调研复查修正：`delete` 入链守卫的 JSON 分支**已合规**——已有 `{success:false, error, references}` + Exit(1)，console.print 只是 table 分支，不修）：

1. `kb`：缺 name / KB 不存在 / 无默认 KB / 路径越界分支仅 console
2. `status`：generic except 仅 console（L1109-1112）
3. `template`：全部错误分支仅 console
4. `fragments`：全部错误分支仅 console
5. `prompts`：动作命令（promote/unresolved/resolve-unresolved/ignore/retry）部分错误仅 console
6. `model download`：无 try/except 兜底，意外异常无 JSON → 加 except 输出 JSON；且 json 模式下 console.print("准备下载") 污染 stdout、output_json 走 console.print 有 Rich 折行风险 → 改 print() 并把提示信息挪进非 json 分支

注意（KB 陷阱 202608292119524400）：所有新增 try/except 处 `except typer.Exit: raise` 必须在 `except Exception` 之前，防止退出码信号被吞（PR #449 实证）。

### C3 `add` 顶层冗余 `id`/`title`

```python
result = {
    "success": True,
    "id": new_note.id,        # 冗余快捷字段
    "title": new_note.title,  # 冗余快捷字段
    "note": {...},            # 原样保留
}
```

### C4 `auto-summary run` 字段重命名

顶层 `success`（int 计数）→ `succeeded`；顶层新增 `"success": True`（布尔）。其余字段（`scanned/processed/skipped/failed/items`）不动。

### C5 裸数组包装

- `backup list`：`[...]` → `{"success": true, "items": [...]}`
- `prompts list`：同上

### C6 新文档 `docs/json-schemas.md`

结构：

1. 分流规则：顶层 `success` 布尔判断成败；失败时 `error` 字符串 + 退出码 1；成功时实体字段位置见各命令条目
2. 每命令条目表：命令 | 成功顶层字段 | 实体字段位置 | 失败形状 | 示例 JSON
3. 覆盖全部 27 顶层命令 + 9 子应用命令
4. 版本标注（1.14.0 起 `success` 全量覆盖；D3/D4 breaking 说明）

需通过 markdownlint（AGENTS.md CI 门禁）。

## 5. 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|----|--------|----------|----------|----------|
| A1 | 全命令成功输出顶层 `success:true` | 自动化（integration） | 新增 `tests/test_json_schema_contract.py`：参数化命令清单跑真实子进程 `--json`（复用 TestJsonPurity 模式：stderr 合流 + json.loads 严格解析），断言顶层 `success is True` | 清单内全部命令通过 |
| A2 | 错误场景输出 `{success:false, error}` + 退出码 1 | 自动化（integration） | 对 C2 清单每个修复分支构造触发场景（kb 缺 name、template show 不存在、delete 无 force 守卫、fragments show 不存在、model download 失败路径等），断言 stdout JSON 可解析且形状正确 | 全部触发场景通过 |
| A3 | `add` 顶层冗余 `id`/`title` 与 `note` 内同值 | 自动化（unit/integration） | CLI 测试断言 `d["id"] == d["note"]["id"]` 且 `d["title"] == d["note"]["title"]` | 通过 |
| A4 | `auto-summary run` 重命名后形状 | 自动化（unit/integration） | 更新/新增 auto-summary run 测试：断言 `success` 为布尔、`succeeded` 为计数 | 通过 |
| A5 | 裸数组包装后形状 | 自动化（unit/integration） | 更新 backup list / prompts list 测试：断言顶层为对象、`items` 为列表 | 通过 |
| U1 | 文档准确性 | 用户实测 | 抽 3-5 个命令人工比对 `docs/json-schemas.md` 条目与实际 `--json` 输出 | 一致 |

## 6. 可测性拆分设计

- **命令契约清单独立**：A1 的命令清单硬编码为 `tests/test_json_schema_contract.py` 模块级常量（`EXPECTED_SUCCESS_COMMANDS`），每项含命令模板与最小参数。新增命令时补清单，跑测试即暴露漏网——测试边界=清单即契约。
- **触发场景独立函数**：A2 每个错误触发场景一个测试函数，不共享 fixture 状态（各用独立临时 KB 或无 KB 场景）——测试边界=每分支一个用例。
- **形状断言 helper**：`assert_json_shape(stdout, success_expected: bool)` 小函数做「可解析 + success 类型正确 + 失败时 error 非空」三段断言，供 A1/A2 复用——测试边界=helper 不依赖具体命令。
- **真实子进程边界**：A1/A2 用真实子进程（`subprocess` + `stderr=STDOUT` 合流 + `json.loads` 严格解析），不用 CliRunner——防 Rich console 污染 stdout 的通道问题被子进程边界暴露。

## 7. 兼容性与风险

| 风险 | 缓解 |
|------|------|
| `tests/utils/jfox_cli.py` 全局 `--json` 解析（含括号配对兜底）受形状变化影响 | 纯增量字段不影响 `json.loads`；D3/D4 改动点跑全量受影响测试确认 |
| Rich console 折行破坏 JSON（子应用曾用 `_json_console`/`typer.echo` 规避） | C1 各命令沿用**现有输出通道**只改 dict 内容，不换通道 |
| 2 个小 breaking 的存量调用方 | 低频管理命令（backup/prompts/auto-summary），CHANGELOG breaking 标注；jfox 自身 skills（jfox-common 等）引用处排查 |
| 改动面大（~50 输出点）导致漏改 | A1 契约清单测试兜底；实现按「主 CLI → 子应用」分批 |

## 8. 关联

- #502（本 issue）、#383/#483（防重，形状保持约束）、#482/#522（日志，已关闭）
- KB：20260713011331-845663（schema 对称）、202609030740572260（三层静默不回退）、202608292119524400（typer.Exit 陷阱）
