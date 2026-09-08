# Spec: pi-coding-agent 侧 user prompt 采集（#462）

- **issue**: <https://github.com/zhuxixi/jfox/issues/462>
- **日期**: 2026-09-07
- **状态**: draft（等用户确认）
- **上游**: #399 记录层（8 PR 已落地：#491-#508），本 spec 是其 pi 覆盖补全
- **调研**: `~/.claude/github-issue-driven/zhuxixi/jfox/issue-462/research/`（3 篇）

## 1. 背景与目标

Issue #399 把 gem-synth 重构为「记录 + 按需判断」，记录层全量记录 user prompt 到
`user_prompts` 表。现状采集只覆盖 Claude Code（cc-plugin hooks.json），pi 会话 0 条。

**目标**：pi 扩展把 pi 会话的 user prompt 送入既有记录层（daemon `/api/prompt` + spool 兜底），
与 CC 侧语义对齐，下游（drain、judge、处置闭环）零改动复用。

## 2. 设计决策表

| ID | 决策 | 理由 |
|----|------|------|
| D1 | 采集事件用 `pi.on("input")` 而非 issue 评论原案的 `message_end` | `event.source` 区分真人/程序注入；`event.text` 是 skill/template 展开**前**的原句；返回 `{action:"continue"}` 无侵入。一次解决原案注意点「user 消息含非真人输入」 |
| D2 | 采集 `source === "interactive"` 与 `"rpc"`，跳过 `"extension"` | interactive=真人；rpc=API 驱动（agent-board 等，用户主动发起有记录价值）；extension=sendUserMessage 程序注入，纯噪音 |
| D3 | 扩展合成 CC 兼容 event（`hook_event_name: "UserPromptSubmit"` 等字段） | `PromptStore.insert_prompt` 硬校验该字段（store.py:207），合成即复用，store 零改动 |
| D4 | daemon `ingest_prompt` 透传 event 顶层 `source` 为 DB source 列 | 现状硬默认 `"claude-code"` 会误标 pi 记录。透传条件：非空字符串（internal 来源已在前面被 skip 挡住）。CC event 无此字段 → 默认值不变零回归；`backfill_from_fragments` 直调 `insert_prompt(source="backfill")` 不经此路径不受影响 |
| D5 | pi 侧 source 值定 `"pi-coding-agent"` | 与 CC `"claude-code"`、backfill `"backfill"` 命名风格一致 |
| D6 | 先原子写 spool 再 POST daemon，失败保留 | 继承 #399 D12「零信息损失」：spool 原子写成功 = prompt 不丢 |
| D7 | `transcript_path = getSessionFile() ?? null` | in-memory 会话（--no-session）返回 undefined；session 文件惰性落盘，早期 input 也可能 undefined。反查层按 session UUID + cwd-slug 定位文件是后续工作，MVP 接受 null |
| D8 | 哨兵过滤：`JFOX_INTERNAL_SESSION ∈ {auto-summary, gem-synth, prompt-judge}` 直接 return | 镜像 CC hook（fragment-capture.sh 同语义）；防反馈循环第二层（第一层 judge runner argv 写死 `--no-extensions`，机制封死）。单一事实源 `jfox/fragment/internal_sources.py` |
| D9 | 单文件扩展 + README 手动安装（拷贝或符号链接到 `~/.pi/agent/extensions/`） | 不 npm 化、不进 Python 发版链；`~/.pi/agent/extensions` 本身是 git 仓库（pi-personal-extensions），用户既有部署习惯兼容 |
| D10 | 空文本输入跳过（纯图片输入无 prompt 可记） | store 硬校验非空 `prompt`，空文本必然 error |
| D11 | 不做跨进程去重 | prompt_hash 语义是「合法重复保留」（#399 决策），双 pi 进程同 session 双采（agent-board attach）交由 judge 层处理 |
| D12 | POST 超时 2s；spool 删除条件 `status ∈ {stored, duplicate, skipped}` | 与 CC hook `curl -m 2` 及删除条件逐字对齐；`skipped` 是 daemon 明确表态（禁用/内部来源），保留会无限累积 |
| D13 | 环境变量 `JFOX_DAEMON_URL`（默认 `http://127.0.0.1:18700`）、`JFOX_PROMPT_SPOOL_DIR`（默认 `~/.zettelkasten/prompt-spool`） | 与 CC hook 同名同默认，运维心智一致 |
| D14 | 扩展运行时零依赖（node 内置 fetch/fs/crypto/path）；类型仅 `import type` | `--experimental-strip-types` 剥离 type import，jfox 仓无需安装 pi 包即可直跑测试 |
| D15 | spool 写法：tmp 文件 → rename（原子），权限 600，目录 700 | 与 CC hook 对齐；node 侧用 `fs.rename`（同文件系统原子） |

## 3. 数据流

```
用户输入 → pi input 事件 {text, source, images}
  ├─ shouldCapture()：D8 哨兵 ∨ D2 source 过滤 ∨ D10 空文本 → 不满足直接 return {action:"continue"}
  ├─ buildCaptureEvent()：
  │    { hook_event_name: "UserPromptSubmit",
  │      source: "pi-coding-agent",                  # D4/D5：daemon 透传为 DB source
  │      session_id: ctx.sessionManager.getSessionId(),
  │      prompt: event.text,                          # 展开前原句
  │      transcript_path: ctx.sessionManager.getSessionFile() ?? null,   # D7
  │      cwd: ctx.sessionManager.getCwd(),
  │      jfox_capture_id: crypto.randomUUID() }
  ├─ writeSpoolAtomic()：~/.zettelkasten/prompt-spool/<capture_id>.json  # D6/D15
  ├─ postToDaemon()：POST {JFOX_DAEMON_URL}/api/prompt，AbortSignal.timeout(2000)  # D12/D13
  └─ status ∈ {stored, duplicate, skipped} → unlink spool；否则保留（jfox prompts drain 恢复）
  全程异常吞掉（debug log 到 stderr 可选），永远 return {action:"continue"}，永不阻塞 pi
```

## 4. 组件契约

### 4.1 `packages/pi-plugin/extensions/jfox-prompt-capture.ts`（新，单文件）

```typescript
// 纯函数（可测性拆分的核心，无副作用）
shouldCapture(input: {source: string; text: string},
              env: Record<string, string | undefined>): boolean
buildCaptureEvent(input: {text: string},
                  session: {id: string; file: string | null; cwd: string},
                  captureId: string): Record<string, unknown>

// 副作用薄封装（依赖可注入）
writeSpoolAtomic(spoolDir: string, captureId: string, payload: string): Promise<boolean>
postToDaemon(url: string, payload: string): Promise<{status: string} | null>  // 失败/超时 → null

// 编排（handler 只做组合）
capturePrompt(input, sessionInfo, deps?): Promise<void>   // deps 可注入 write/post，测试用

export default (pi: ExtensionAPI) => {
  pi.on("input", async (event, ctx) => {
    await capturePrompt(event, {/* id/file/cwd from ctx.sessionManager */})
    return { action: "continue" }
  })
}
```

- 顶层单文件、`export default` 工厂（pi loader 要求）；无 `lib/` 需求（无独立工具模块）
- `capturePrompt` 的错误边界：内部 try/catch 全吞，绝不向 pi 抛异常

### 4.2 `jfox/prompts/service.py`（小改）

```python
# ingest_prompt 内，现有 source 变量（_get_event_source 已解析）：
# internal 已在上方被 skip 挡住；此处只需 非空→透传，空→默认
db_source = source if source else "claude-code"
return store.insert_prompt(event, source_key=source_key, capture_id=cid, source=db_source)
```

`store.insert_prompt` 的 `source` 参数已存在（store.py:195），store 零改动。

### 4.3 `packages/pi-plugin/README.md`（新）

- 功能简介 + 前置条件（jfox ≥ 记录层版本、daemon 运行）
- 安装：`cp packages/pi-plugin/extensions/jfox-prompt-capture.ts ~/.pi/agent/extensions/`
  （或 `ln -s <repo>/packages/pi-plugin/extensions/jfox-prompt-capture.ts ~/.pi/agent/extensions/`），
  重启 pi 或 `/reload`
- 环境变量表（D13 两个 + `JFOX_INTERNAL_SESSION` 哨兵说明）
- 验证方法：发一条消息 → `jfox prompts list --json | head` 看最新记录

### 4.4 `.github/workflows/integration-test.yml`（+1 step）

Fast job 增加一步：`node --experimental-strip-types packages/pi-plugin/test/run-tests.ts`，
把 A1/A2/A4 纳入 CI 门禁（GitHub runner 自带 node ≥22.6）。

## 5. 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|----|--------|----------|----------|----------|
| A1 | `shouldCapture` 过滤：internal 哨兵 3 值 / extension 来源 / 空文本 / 空白文本 → false；哨兵未设置且 interactive、rpc → true | 自动化验证（unit，node 直跑） | `node --experimental-strip-types packages/pi-plugin/test/run-tests.ts`（内含 A1/A2/A4） | 全部断言通过 |
| A2 | `buildCaptureEvent` 合成：7 字段完整、`source: "pi-coding-agent"`、`transcript_path` null fallback、`prompt` 传原句、`hook_event_name: "UserPromptSubmit"` | 自动化验证（unit，node 直跑） | 同 A1 命令 | 全部断言通过 |
| A3 | daemon source 透传：pi event（source=pi-coding-agent）→ DB source 透传；无 source 的 CC 形 event → 默认 claude-code；internal source → skipped 不入库 | 自动化验证（unit，pytest） | `uv run pytest tests/unit/test_prompt_capture.py -v`（新增 3 个 case） | 新增测试通过，既有测试零回归 |
| A4 | spool→POST 流程：成功路径 spool 创建→POST 收到完整 payload→status stored → spool 删除；daemon 不可达 → spool 保留 | 自动化验证（integration，node 脚本：node:http 起 mock server + 临时 spool 目录 + 注入 deps 跑 `capturePrompt`） | 同 A1 命令（同一 runner 内） | 断言 spool 生命周期与 POST payload 正确 |
| A5 | 扩展模块可加载（import type 剥离后 node 无报错，default export 为函数） | 自动化验证（build/static） | 同 A1 命令（runner 首步 dynamic import 冒烟） | 加载无异常且 typeof factory === "function" |
| A6 | README 通过 markdownlint | 自动化验证（static） | `npx --yes markdownlint-cli2` | 0 error |
| A7 | CI Fast job 包含 node 测试 step | 自动化验证（build） | workflow YAML 语法 + push 后 Fast run 绿 | Fast run 通过 |
| U1 | 真实 pi 会话端到端 | 用户实测 | ① `cp` 扩展到 `~/.pi/agent/extensions/` + 重启 pi ② `jfox daemon start`（或确认运行中）③ pi 里发一条消息 ④ `jfox prompts list --json` 看 | 最新记录 `source=pi-coding-agent`、`prompt` 为输入原句、session_id 为 pi 会话 UUID |
| U2 | daemon 停机兜底 | 用户实测 | ① `jfox daemon stop` ② pi 里发消息 ③ `ls ~/.zettelkasten/prompt-spool/` 有新 `<uuid>.json` ④ `jfox daemon start && jfox prompts drain` ⑤ `jfox prompts list --json` | spool 文件出现且 drain 后记录入库（source=pi-coding-agent），prompt 原文不丢 |

## 6. 可测性拆分设计（自动化项的实现约束）

- **纯函数优先**：`shouldCapture` / `buildCaptureEvent` 无任何 I/O，输入输出全显式参数
  ——A1/A2 直接断言输入输出，测试边界即函数签名。
- **副作用隔离 + 依赖注入**：`writeSpoolAtomic` / `postToDaemon` 是仅有的 I/O 单元；
  `capturePrompt` 接受可选 `deps`（默认真实实现），A4 注入临时 spool 目录 + 指向
  mock server 的 URL。**实现不得把过滤/合成逻辑内联进 handler 或 I/O 函数**（保持可独测）。
- **测试边界**：
  - node 侧：run-tests.ts 一个入口三类测试（纯函数断言 / dynamic import 冒烟 / mock server 流程），
    无需外部进程；mock server 用 `node:http` 监听 127.0.0.1 随机端口。
  - pytest 侧：`test_prompt_capture.py` 既有 tmp_path + 内存 store 模式，新增 source 透传 3 case，
    不依赖 daemon 进程。
- **CI 层级**：unit（纯函数）+ integration（mock 流程）合并在一个 node runner 内跑，
  不引入 vitest/jest 等测试基建（YAGNI，KB 既有 node 直跑方法验证可行）。

## 7. 非目标

- 反查层对 pi session JSONL 格式的适配（`transcript.py` 目前只认 CC 格式）——后续 issue
- pi-plugin npm 化 / `pi install` 分发
- capture 时间戳精度改造（store `captured_at` 用摄入时间；pi 原始时间已随全量 event 进 `metadata_json`）
- 跨进程/跨会话去重（D11）
- kimi-plugin 侧采集

## 8. 风险与降级

| 风险 | 缓解 |
|------|------|
| pi 扩展异常拖慢/阻塞输入 | handler 全异步 + 内部 try/catch 全吞 + POST 有 2s 超时；spool 写失败静默 return（不伪装成功，prompt 丢一条但会话不受影响） |
| daemon 旧版本（无 source 透传）收到 pi event | 旧 daemon 把它当普通 event 存 source=claude-code，功能不破坏（来源标错但不丢数据）；README 注明建议升级 |
| spool 无限累积（daemon 长期停机） | 既有 `max_spool_bytes` 保护（drain 时超限停止并报错交人工） |
| 双 pi 进程双采（agent-board attach） | D11：不去重，judge 层处理；UNIQUE(source, session_id, session_seq) 保证 seq 连续不冲突 |
| `input` 事件在未来 pi 版本变更 | 扩展零外部依赖、单文件可整体替换；pi 升级破坏时删除该文件即完全回退 |
