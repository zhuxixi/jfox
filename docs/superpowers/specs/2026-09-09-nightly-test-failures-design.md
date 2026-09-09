# Spec: nightly-test 失败修复（#523）

- 日期: 2026-09-09
- Issue: #523（nightly-test 失败 2026-09-08，sig d54f65c16af6，6 个失败）
- 状态: 待用户确认

## 1. 背景与根因

9-08 nightly 首次跑新代码（#399/#493 退役旧分类采集、#462/#521 hook 改版为 prompt 记录），6 个失败分 3 组，均为「代码演进、测试未同步」，非产品功能 bug：

| 组 | 失败测试 | 根因 |
|----|---------|------|
| A | test_fragment_capture_flow.py 4 个 | 旧采集链路退役（PostToolUse/Stop → retired，UserPromptSubmit → /api/prompt），hook 改版为 spool+POST 静默模式；plan（2026-08-30-gem-synth-prompt-judgment.md Task 2）明确计划 Modify 该文件但 #493 未执行 → **plan 执行遗漏** |
| B | test_multiple_notes_with_links_batch | NoteGenerator.generate() 有放回抽样（15 模板选 15 次）→ 重复标题；#483 防重闸门后拒绝 → flaky |
| C | test_add_note_dimension_mismatch_friendly_message | #442 把 rebuild 提示从 logger.error 移到 last_dimension_warning 属性，旧断言未更新 |

## 2. 修复方案

### 2.1 组 A：重写 `tests/integration/test_fragment_capture_flow.py`（适配新链路）

新链路契约（来自 #399 spec §5、#462 spec）：

- hook 脚本：读 stdin JSON → 注入 jfox_capture_id → 原子写 spool（`JFOX_PROMPT_SPOOL_DIR` 可覆盖）→ 尽力 POST `/api/prompt` → daemon 确认 stored/duplicate/skipped 才删 spool；`JFOX_INTERNAL_SESSION` 命中内部来源直接 exit 0
- daemon `/api/prompt`：`ingest_prompt` 返回 `{status: stored, prompt_id, prompt}` / `{status: duplicate}` / `{status: skipped}` / `{status: error}`
- daemon `/api/fragment`：UserPromptSubmit 转发 /api/prompt；PostToolUse/Stop 返回 `{status: retired}`

测试用例设计（保留 require_daemon fixture，依赖真实 daemon）：

| 用例 | 验证点 | 说明 |
|------|--------|------|
| test_prompt_api_stores_full_prompt | POST /api/prompt（UserPromptSubmit）→ stored + prompt 原文完整回显 | 替代 test_post_userprompt_correction；session id 随机化 |
| test_prompt_api_idempotent | 同 capture_id 重复 POST → duplicate | 新增，验证幂等键（store.py `_find_by_idempotency`） |
| test_hook_post_success_clears_spool | daemon 可用时跑 hook（UserPromptSubmit）→ 完成后 spool 临时目录**为空**（POST stored 后删除）+ stdout 为空 + exit 0 | 替代 test_hook_script_end_to_end；JFOX_PROMPT_SPOOL_DIR 指向临时目录 |
| test_hook_post_failure_keeps_spool | JFOX_DAEMON_URL 指向 `127.0.0.1:1`（不可达）跑 hook → spool 文件**保留** + exit 0 | 新增，验证 durable spool 降级路径（POST 失败不丢数据、永不阻塞 CC）；不依赖真实 daemon |
| test_hook_internal_session_skipped | JFOX_INTERNAL_SESSION=auto-summary/gem-synth → hook exit 0、spool 目录无新文件 | 保留原用例意图，改为验证 spool 不产生文件 |
| test_legacy_fragment_endpoint_retired | POST /api/fragment（PostToolUse/Stop）→ {status: retired} | 替代 test_stop_returns_summary_message / test_hook_prints_stop_summary_with_real_cc_format（Stop 摘要功能已退役，验证 retired 契约） |

删除：test_stop_returns_summary_message、test_hook_prints_stop_summary_with_real_cc_format（功能已退役）。

**session id 随机化**：所有用例 session id 用 uuid 前缀（如 `it-<uuid8>`），避免真实 daemon 持久库残留污染（本次失败的直接诱因之一）。

**spool 断言稳定性**：已确认 daemon 无后台 spool drain 循环（drain 仅手动 CLI `jfox prompts drain`），临时 spool 目录（JFOX_PROMPT_SPOOL_DIR 覆盖）不被 daemon 感知，断言无竞态。

**时序断言取舍**：hook 是 subprocess 同步执行，进程结束后才能检查文件系统，故不断言「spool 先出现」的中途时序，只断言终态（可用→空 / 不可达→保留）。

### 2.2 组 B：`NoteGenerator.generate()` 改无放回抽样

- 模板列表洗牌（`random.shuffle`）后按序轮转取用；一轮取完再洗牌进入下一轮
- 保留现有「count > len(templates) 时标题加 `(i+1)` 后缀」逻辑（轮转后一轮内标题天然不重复，后缀逻辑仅跨轮生效）
- 影响面：generate() 被多个测试使用，测试只断言标题存在/数量，不依赖具体标题 → 行为变更安全
- 新增单元测试：`generate(15)` 一轮内标题无重复（固定 seed 可复现）

### 2.3 组 C：更新 `tests/unit/test_vector_store_clear.py::TestVectorStoreDimensionMismatch`

- `test_add_note_dimension_mismatch_friendly_message`：断言从 logger.error 改为 `store.last_dimension_warning` 包含 `jfox index rebuild`（#442 新行为）；保留「384/1024 数字出现在提示中」断言
- `test_add_note_non_dimension_exception_unchanged`：保留不动（已通过）
- 与 `tests/unit/test_vector_store_dimension_warning.py`（#442 新增）互补：前者测 add_note 路径，后者测 search/add 双路径

## 3. 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|----|--------|----------|----------|----------|
| A1 | 集成测试重写 | 自动化验证（integration） | `uv run pytest tests/integration/test_fragment_capture_flow.py -v -m integration`（前提：daemon 运行且版本 ≥ 含 #493——集成测试测的是环境里 daemon 的 API 契约，非 worktree 代码） | 全部用例通过；无 KeyError/残留污染 |
| A2 | 生成器无放回 | 自动化验证（unit） | `uv run pytest tests/unit/test_note_generator.py -q`（新增用例） | generate(15) 一轮内标题无重复 |
| A3 | 维度提示断言更新 | 自动化验证（unit） | `uv run pytest tests/unit/test_vector_store_clear.py -q` | friendly_message 用例断言 last_dimension_warning 通过 |
| A4 | 回归：核心工作流 | 自动化验证（unit/integration） | `uv run pytest tests/test_core_workflow.py::TestCompleteWorkflow::test_multiple_notes_with_links_batch -q` | 连续 3 次运行通过（flaky 根治验证） |
| A5 | 全量快速回归 | 自动化验证（unit） | `uv run pytest tests/ -m "not embedding and not slow" -q` | 无新增失败（注：组 A 为 integration 标记，本项不覆盖；组 A 由 A1 在 daemon 环境/nightly 验证） |

## 4. 可测性拆分设计

- 组 A：测试全部走真实 daemon HTTP 契约（黑盒），不引入新生产代码；spool 目录通过 `JFOX_PROMPT_SPOOL_DIR` 环境变量注入临时目录（hook 已支持），测试边界 = hook 脚本行为 + daemon API 响应
- 组 B：`generate()` 抽样逻辑是纯函数（输入 count/category/seed → 输出 notes 列表），单测直接断言标题唯一性；不触碰 CLI/存储层
- 组 C：`_dimension_warning_text()` 已是静态纯函数（#442 拆分），断言 `last_dimension_warning` 属性即可，无需 mock 链

## 5. 非目标

- 不改动生产代码（daemon/hook/service 均不动）——本次失败全部是测试侧问题
- 不新增 daemon GET /api/prompts 查询端点（集成测试通过 API 响应 + spool 行为验证，不查库）
- 不清理真实 daemon 库的历史残留数据（it-sess-* 行，属测试数据，随机化后不再产生新冲突）
- 不处理「hook 层不区分事件类型」——daemon 端已校验兜底（`store.py:207` 非 UserPromptSubmit 返回 error，`hooks.json` 只挂 UserPromptSubmit），hook 冗余但无害，无需改动

## 6. 风险与已知副作用

- 集成测试依赖真实 daemon：daemon 未运行时跳过（现有 fixture 行为），nightly 环境 daemon 常驻 → 可测
- **测试数据写入真实库**：POST /api/prompt 会写入真实 daemon 的 `user_prompts` 表（随机 session id 前缀 `it-` 避免冲突，但每次 nightly 累积垃圾行）。与现有测试同模式，可接受；如需清理，另行开 issue 评估 daemon 清理端点或测试专用库
- 生成器行为变更可能影响依赖标题分布的既有断言：已排查 generate() 调用点（tests/utils/note_generator.py 自测 + 各测试仅断言存在性），风险低
