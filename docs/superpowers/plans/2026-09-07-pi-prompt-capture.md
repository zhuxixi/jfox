# pi Prompt Capture Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** pi 会话的 user prompt 通过 `input` 事件扩展采集进 jfox 记录层（spool + POST `/api/prompt`），daemon 透传 `source=pi-coding-agent`。

**Architecture:** 单文件零依赖 pi 扩展（纯函数过滤/合成 + 可注入 I/O 薄封装 + fire-and-forget 编排），外加 daemon `ingest_prompt` 的 source 透传小改。下游（drain/judge）零改动复用。

**Tech Stack:** TypeScript（node ≥22.6 `--experimental-strip-types` 直跑，无构建无 npm 依赖）、Python（pytest，沿用既有 `tests/unit/test_prompt_capture.py` 模式）。

**Spec:** `docs/superpowers/specs/2026-09-07-pi-prompt-capture-design.md`（决策 D1-D15，验收 A1-A7/U1-U2）

## Global Constraints

- **Work from:** `/home/elling/git-repo/github/jfox/.pi/worktrees/issue-462-pi-prompt-capture`（所有路径相对此根；**禁碰主 checkout**）
- 主分支 main 是保护分支，一切改动只在 `issue-462-pi-prompt-capture` 分支
- 扩展运行时零依赖：只用 node 内置模块（`node:crypto/fs/promises/path/os/http/assert`）与全局 `fetch`；`import type` 仅限 `@earendil-works/pi-coding-agent`（strip-types 会剥离，仓库不安装该包）
- 本地只跑快速单元测试：`uv run pytest tests/unit/test_prompt_capture.py -v`（不自主跑全量/集成测试）
- commit message：conventional commits，issue 号放尾部（`feat(...): xxx (#462)`）；commit-lint 会拒绝 `(#462)` 作 scope
- `git add <file>` 按文件 stage，禁止 `git add -A`
- 新增 `.md` 文件必须过 markdownlint（`npx --yes markdownlint-cli2 <file>`，0 error）
- 验收 ID 对应：Task 1 → A3；Task 2 → A1/A2（部分 A5）；Task 3 → A4 + A5 完成；Task 4 → A6；Task 5 → A7；Task 6 → U1/U2

---

### Task 1: daemon source 透传（A3）

**Files:**

- Modify: `jfox/prompts/service.py:102`（`ingest_prompt` 的 return 行）
- Test: `tests/unit/test_prompt_capture.py`（文件末尾追加）

**Interfaces:**

- Consumes: 既有 `_get_event_source(event)`（service.py:29，返回顶层 `source` 或 `metadata.source` 的非空 str 或 None）；既有 `store.insert_prompt(event, source_key, capture_id, source=...)` 的 `source` 参数（store.py:195，默认 `"claude-code"`）
- Produces: `ingest_prompt` 行为变化——event 顶层非空 `source`（非内部来源，内部来源已在上方被 skip 挡住）透传为 DB `user_prompts.source`。签名不变。

- [ ] **Step 1: Write the failing test**

在 `tests/unit/test_prompt_capture.py` 末尾（`test_ingest_prompt_skips_internal_sources` 之后）追加：

```python
# ---------------------------------------------------------------------------
# source 透传（#462 D4：pi 扩展 event 的来源标记进 DB source 列）
# ---------------------------------------------------------------------------


def test_ingest_prompt_passes_through_pi_source(tmp_path):
    """event 顶层 source=pi-coding-agent 透传为 DB source（#462）。"""
    store = _store(tmp_path)
    result = ingest_prompt(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "s1",
            "prompt": "pi 侧输入",
            "source": "pi-coding-agent",
        },
        store=store,
        capture_id="cap-pi-1",
    )
    assert result["status"] == "stored"
    row = store.get_prompt(result["prompt_id"])
    assert row["source"] == "pi-coding-agent"


def test_ingest_prompt_defaults_source_without_field(tmp_path):
    """无 source 字段的 CC 形 event 保持默认 claude-code（零回归）。"""
    store = _store(tmp_path)
    result = ingest_prompt(
        {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "cc 输入"},
        store=store,
        capture_id="cap-cc-1",
    )
    assert result["status"] == "stored"
    row = store.get_prompt(result["prompt_id"])
    assert row["source"] == "claude-code"
```

（A3 第三项「internal source → skipped 不入库」已由既有 `test_ingest_prompt_skips_internal_sources` 覆盖，无需新增。）

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_prompt_capture.py -v -k "passes_through_pi_source or defaults_source_without_field"`
Expected: 2 FAIL（`row["source"]` 均为 `"claude-code"`，第一个用例断言失败）

- [ ] **Step 3: Write minimal implementation**

`jfox/prompts/service.py`，把第 102 行：

```python
    return store.insert_prompt(event, source_key=source_key, capture_id=cid)
```

改为（`source` 变量是上文 `_get_event_source` 的返回值；internal 来源已在上方 return skipped，到这里必非 internal）：

```python
    # 顶层 source 透传为 DB 来源（#462 D4）：pi 扩展放 "pi-coding-agent"；
    # CC event 无此字段 → 保持默认 "claude-code"。backfill 直调 insert_prompt 不受影响。
    db_source = source if source else "claude-code"
    return store.insert_prompt(
        event, source_key=source_key, capture_id=cid, source=db_source
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_prompt_capture.py -v`
Expected: 全部 PASS（新增 2 个 + 既有全量零回归）

- [ ] **Step 5: Commit**

```bash
git add jfox/prompts/service.py tests/unit/test_prompt_capture.py
git commit -m "feat(prompts): pass through event source into user_prompts (#462)"
```

---

### Task 2: 扩展纯函数 + node 测试骨架（A1、A2、A5 部分）

**Files:**

- Create: `packages/pi-plugin/extensions/jfox-prompt-capture.ts`
- Create: `packages/pi-plugin/test/run-tests.ts`

**Interfaces:**

- Produces（Task 3 依赖的精确签名）:
  - `shouldCapture(input: {source: string; text: string}, env: Record<string, string | undefined>): boolean`
  - `buildCaptureEvent(input: {source: string; text: string}, session: {id: string; file: string | null; cwd: string}, captureId: string): Record<string, unknown>`
  - interface `CaptureInput { source: string; text: string }`、`SessionInfo { id: string; file: string | null; cwd: string }`
- 测试入口：`node --experimental-strip-types packages/pi-plugin/test/run-tests.ts`，退出码 0=全过

- [ ] **Step 1: Write the failing test**

创建 `packages/pi-plugin/test/run-tests.ts`：

```typescript
// pi-plugin node 测试入口：纯函数断言 + dynamic import 冒烟 + mock server 流程（Task 3 追加）。
// 运行：node --experimental-strip-types packages/pi-plugin/test/run-tests.ts
import assert from "node:assert/strict";

const ext = await import("../extensions/jfox-prompt-capture.ts");

let passed = 0;
const failures: string[] = [];
async function test(name: string, fn: () => Promise<void> | void): Promise<void> {
  try {
    await fn();
    passed++;
    console.log(`ok - ${name}`);
  } catch (e) {
    failures.push(name);
    console.error(`FAIL - ${name}: ${e instanceof Error ? e.message : String(e)}`);
  }
}

// ---- A5 冒烟：模块可加载，导出为函数 ----
assert.equal(typeof ext.shouldCapture, "function");
assert.equal(typeof ext.buildCaptureEvent, "function");

// ---- A1: shouldCapture ----
await test("A1 internal sentinel values are rejected", () => {
  for (const s of ["auto-summary", "gem-synth", "prompt-judge"]) {
    assert.equal(ext.shouldCapture({ source: "interactive", text: "hi" }, { JFOX_INTERNAL_SESSION: s }), false, s);
  }
});

await test("A1 extension-source input is rejected", () => {
  assert.equal(ext.shouldCapture({ source: "extension", text: "injected" }, {}), false);
});

await test("A1 empty and whitespace-only text are rejected", () => {
  assert.equal(ext.shouldCapture({ source: "interactive", text: "" }, {}), false);
  assert.equal(ext.shouldCapture({ source: "interactive", text: "   \n " }, {}), false);
});

await test("A1 interactive and rpc with no sentinel are captured", () => {
  assert.equal(ext.shouldCapture({ source: "interactive", text: "真人输入" }, {}), true);
  assert.equal(ext.shouldCapture({ source: "rpc", text: "API 输入" }, {}), true);
});

await test("A1 unrelated sentinel value does not block", () => {
  assert.equal(ext.shouldCapture({ source: "interactive", text: "hi" }, { JFOX_INTERNAL_SESSION: "other" }), true);
});

// ---- A2: buildCaptureEvent ----
await test("A2 builds full CC-compatible event", () => {
  const ev = ext.buildCaptureEvent(
    { source: "interactive", text: "/skill:foo 展开前的原句" },
    { id: "uuid-1", file: "/home/u/.pi/agent/sessions/x.jsonl", cwd: "/repo" },
    "cap-1",
  );
  assert.deepEqual(ev, {
    hook_event_name: "UserPromptSubmit",
    source: "pi-coding-agent",
    session_id: "uuid-1",
    prompt: "/skill:foo 展开前的原句",
    transcript_path: "/home/u/.pi/agent/sessions/x.jsonl",
    cwd: "/repo",
    jfox_capture_id: "cap-1",
  });
});

await test("A2 null transcript fallback for in-memory session", () => {
  const ev = ext.buildCaptureEvent(
    { source: "rpc", text: "x" },
    { id: "uuid-2", file: null, cwd: "/repo" },
    "cap-2",
  );
  assert.equal(ev.transcript_path, null);
});

// ---- 汇总 ----
console.log(`\n${passed} passed, ${failures.length} failed`);
if (failures.length > 0) {
  process.exit(1);
}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `node --experimental-strip-types packages/pi-plugin/test/run-tests.ts`
Expected: 模块加载失败（`Cannot find module '../extensions/jfox-prompt-capture.ts'`），退出码非 0

- [ ] **Step 3: Write minimal implementation**

创建 `packages/pi-plugin/extensions/jfox-prompt-capture.ts`（本任务只写纯函数部分；I/O 与 factory 是 Task 3，追加到同一文件）：

```typescript
/**
 * JFox prompt capture extension for pi (#462).
 *
 * Records every real user prompt from pi sessions into the jfox prompt
 * recording layer (#399): atomic local spool first, then best-effort POST
 * to the jfox daemon /api/prompt. Never blocks or breaks the pi session.
 *
 * Install: copy or symlink this file into ~/.pi/agent/extensions/ and
 * restart pi (or /reload). Runtime deps: none (node builtins only).
 */

const INTERNAL_SOURCES = new Set(["auto-summary", "gem-synth", "prompt-judge"]);

export interface CaptureInput {
  source: string;
  text: string;
}

export interface SessionInfo {
  id: string;
  file: string | null;
  cwd: string;
}

/** Filter: internal-session sentinel, programmatic injections, empty text. */
export function shouldCapture(
  input: CaptureInput,
  env: Record<string, string | undefined>,
): boolean {
  const sentinel = env.JFOX_INTERNAL_SESSION;
  if (sentinel !== undefined && INTERNAL_SOURCES.has(sentinel)) return false;
  if (input.source === "extension") return false;
  if (typeof input.text !== "string" || input.text.trim() === "") return false;
  return true;
}

/** Build a CC-compatible UserPromptSubmit event for the jfox daemon. */
export function buildCaptureEvent(
  input: CaptureInput,
  session: SessionInfo,
  captureId: string,
): Record<string, unknown> {
  return {
    hook_event_name: "UserPromptSubmit",
    source: "pi-coding-agent",
    session_id: session.id,
    prompt: input.text,
    transcript_path: session.file,
    cwd: session.cwd,
    jfox_capture_id: captureId,
  };
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --experimental-strip-types packages/pi-plugin/test/run-tests.ts`
Expected: `8 passed, 0 failed`，退出码 0

- [ ] **Step 5: Commit**

```bash
git add packages/pi-plugin/extensions/jfox-prompt-capture.ts packages/pi-plugin/test/run-tests.ts
git commit -m "feat(pi-plugin): prompt capture pure functions and node test runner (#462)"
```

---

### Task 3: I/O + 编排 + factory + mock server 集成测试（A4，A5 完成）

**Files:**

- Modify: `packages/pi-plugin/extensions/jfox-prompt-capture.ts`（文件末尾追加）
- Modify: `packages/pi-plugin/test/run-tests.ts`（汇总前追加测试）

**Interfaces:**

- Consumes: Task 2 的 `shouldCapture`/`buildCaptureEvent`/`CaptureInput`/`SessionInfo`
- Produces: `writeSpoolAtomic(spoolDir, captureId, payload): Promise<boolean>`、`postToDaemon(url, payload): Promise<{status: string} | null>`、`capturePrompt(input, session, env?, deps?): Promise<void>`、`export default (pi: ExtensionAPI) => void`
- 实现约束（spec §6）：过滤/合成逻辑**不得**内联进 handler 或 I/O 函数；I/O 只经 `deps` 注入点替换

- [ ] **Step 1: Write the failing test**

在 `packages/pi-plugin/test/run-tests.ts` 的 `// ---- 汇总 ----` 之前追加（并更新冒烟断言）：

```typescript
// ---- A5 冒烟补全：default export 为工厂（本任务加入 factory 后生效）----
assert.equal(typeof ext.default, "function");
```

```typescript
// ---- A4: spool + POST 流程（mock daemon）----
import http from "node:http";
import { mkdtemp, readdir, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

await test("A4 success flow: spool written, POST payload correct, spool deleted", async () => {
  let receivedBody = "";
  const server = http.createServer((req, res) => {
    let body = "";
    req.on("data", (c: string) => (body += c));
    req.on("end", () => {
      receivedBody = body;
      res.writeHead(200, { "Content-Type": "application/json" });
      res.end(JSON.stringify({ status: "stored" }));
    });
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = (server.address() as { port: number }).port;
  const dir = await mkdtemp(join(tmpdir(), "jfox-prompt-"));
  try {
    await ext.capturePrompt(
      { source: "interactive", text: "hello from test" },
      { id: "sess-1", file: "/tmp/x.jsonl", cwd: "/repo" },
      { JFOX_DAEMON_URL: `http://127.0.0.1:${port}`, JFOX_PROMPT_SPOOL_DIR: dir },
    );
    const files = await readdir(dir);
    assert.deepEqual(files, [], "spool must be deleted after stored");
    const ev = JSON.parse(receivedBody);
    assert.equal(ev.hook_event_name, "UserPromptSubmit");
    assert.equal(ev.source, "pi-coding-agent");
    assert.equal(ev.prompt, "hello from test");
    assert.equal(ev.session_id, "sess-1");
    assert.equal(ev.transcript_path, "/tmp/x.jsonl");
    assert.ok(ev.jfox_capture_id);
  } finally {
    await rm(dir, { recursive: true, force: true });
    server.close();
  }
});

await test("A4 failure flow: daemon unreachable keeps spool with payload", async () => {
  const dir = await mkdtemp(join(tmpdir(), "jfox-prompt-"));
  try {
    // 127.0.0.1:1 无监听 → 立即 connection refused，不受 2s 超时拖慢
    await ext.capturePrompt(
      { source: "interactive", text: "offline prompt" },
      { id: "sess-2", file: null, cwd: "/repo" },
      { JFOX_DAEMON_URL: "http://127.0.0.1:1", JFOX_PROMPT_SPOOL_DIR: dir },
    );
    const files = await readdir(dir);
    assert.equal(files.length, 1, "spool file must survive daemon outage");
    assert.match(files[0], /\.json$/);
    const payload = JSON.parse(await readFile(join(dir, files[0]), "utf8"));
    assert.equal(payload.prompt, "offline prompt");
    assert.equal(payload.transcript_path, null);
    assert.ok(payload.jfox_capture_id);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

await test("A4 filtered input writes nothing", async () => {
  const dir = await mkdtemp(join(tmpdir(), "jfox-prompt-"));
  try {
    await ext.capturePrompt(
      { source: "extension", text: "injected" },
      { id: "sess-3", file: null, cwd: "/repo" },
      { JFOX_PROMPT_SPOOL_DIR: dir },
    );
    assert.deepEqual(await readdir(dir), []);
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

await test("A4 duplicate status also deletes spool", async () => {
  const server = http.createServer((_req, res) => {
    res.writeHead(200, { "Content-Type": "application/json" });
    res.end(JSON.stringify({ status: "duplicate" }));
  });
  await new Promise<void>((resolve) => server.listen(0, "127.0.0.1", resolve));
  const port = (server.address() as { port: number }).port;
  const dir = await mkdtemp(join(tmpdir(), "jfox-prompt-"));
  try {
    await ext.capturePrompt(
      { source: "rpc", text: "dup" },
      { id: "sess-4", file: null, cwd: "/repo" },
      { JFOX_DAEMON_URL: `http://127.0.0.1:${port}`, JFOX_PROMPT_SPOOL_DIR: dir },
    );
    assert.deepEqual(await readdir(dir), []);
  } finally {
    await rm(dir, { recursive: true, force: true });
    server.close();
  }
});
```

注意：`import` 语句放文件顶部（与既有 import 合并），上面代码块中的 import 行仅为标注来源，追加时合并到顶部。

- [ ] **Step 2: Run test to verify it fails**

Run: `node --experimental-strip-types packages/pi-plugin/test/run-tests.ts`
Expected: 冒烟断言 `typeof ext.default === "function"` 直接抛错（无 default export），退出码非 0

- [ ] **Step 3: Write minimal implementation**

在 `packages/pi-plugin/extensions/jfox-prompt-capture.ts` 顶部补 import：

```typescript
import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { randomUUID } from "node:crypto";
import { mkdir, rename, unlink, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";
```

文件末尾追加：

```typescript
const DEFAULT_DAEMON_URL = "http://127.0.0.1:18700";
const DEFAULT_SPOOL_DIR = join(homedir(), ".zettelkasten", "prompt-spool");
const SETTLED_STATUSES = new Set(["stored", "duplicate", "skipped"]);

/** Atomic spool write: tmp file -> rename. Returns false on any failure. */
export async function writeSpoolAtomic(
  spoolDir: string,
  captureId: string,
  payload: string,
): Promise<boolean> {
  try {
    await mkdir(spoolDir, { recursive: true, mode: 0o700 });
    const finalPath = join(spoolDir, `${captureId}.json`);
    const tmpPath = `${finalPath}.tmp`;
    await writeFile(tmpPath, payload, { mode: 0o600 });
    await rename(tmpPath, finalPath);
    return true;
  } catch {
    return false;
  }
}

/** Best-effort POST to daemon /api/prompt. Returns null on failure/timeout. */
export async function postToDaemon(
  baseUrl: string,
  payload: string,
): Promise<{ status: string } | null> {
  try {
    const res = await fetch(`${baseUrl.replace(/\/+$/, "")}/api/prompt`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: payload,
      signal: AbortSignal.timeout(2000),
    });
    const data = (await res.json()) as { status?: unknown };
    if (typeof data.status === "string") return { status: data.status };
    return null;
  } catch {
    return null;
  }
}

export interface CaptureDeps {
  writeSpool: (dir: string, id: string, payload: string) => Promise<boolean>;
  postToDaemon: (url: string, payload: string) => Promise<{ status: string } | null>;
}

/**
 * Orchestration: filter -> build event -> atomic spool -> best-effort POST ->
 * delete spool only on settled status. Swallows all errors (never breaks pi).
 */
export async function capturePrompt(
  input: CaptureInput,
  session: SessionInfo,
  env: Record<string, string | undefined> = process.env,
  deps: CaptureDeps = { writeSpool: writeSpoolAtomic, postToDaemon: postToDaemon },
): Promise<void> {
  try {
    if (!shouldCapture(input, env)) return;
    const captureId = randomUUID();
    const payload = JSON.stringify(buildCaptureEvent(input, session, captureId));
    const spoolDir = env.JFOX_PROMPT_SPOOL_DIR || DEFAULT_SPOOL_DIR;
    const daemonUrl = env.JFOX_DAEMON_URL || DEFAULT_DAEMON_URL;
    const spooled = await deps.writeSpool(spoolDir, captureId, payload);
    if (!spooled) return; // spool write failed: give up silently, never fake success
    const resp = await deps.postToDaemon(daemonUrl, payload);
    if (resp && SETTLED_STATUSES.has(resp.status)) {
      await unlink(join(spoolDir, `${captureId}.json`)).catch(() => undefined);
    }
  } catch {
    // capture must never break the pi session
  }
}

export default function jfoxPromptCapture(pi: ExtensionAPI): void {
  pi.on("input", async (event, ctx) => {
    // fire-and-forget: the POST has a 2s timeout, must not delay agent start
    void capturePrompt(
      { source: event.source ?? "", text: event.text ?? "" },
      {
        id: ctx.sessionManager.getSessionId(),
        file: ctx.sessionManager.getSessionFile() ?? null,
        cwd: ctx.sessionManager.getCwd(),
      },
    );
    return { action: "continue" };
  });
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `node --experimental-strip-types packages/pi-plugin/test/run-tests.ts`
Expected: `12 passed, 0 failed`（8 纯函数 + 4 流程），退出码 0
再跑一次 Python 回归：`uv run pytest tests/unit/test_prompt_capture.py -v` → 全 PASS

- [ ] **Step 5: Commit**

```bash
git add packages/pi-plugin/extensions/jfox-prompt-capture.ts packages/pi-plugin/test/run-tests.ts
git commit -m "feat(pi-plugin): spool/post orchestration, extension factory, mock flow tests (#462)"
```

---

### Task 4: README 安装文档（A6）

**Files:**

- Create: `packages/pi-plugin/README.md`

**Interfaces:**

- Consumes: Task 2/3 的扩展文件路径与行为、spec D13 环境变量
- Produces: 无代码接口；用户安装/排障入口

- [ ] **Step 1: Write the README**

```markdown
# jfox pi-plugin

pi-coding-agent 侧 user prompt 采集扩展（issue #462）：把 pi 会话中真人输入的
prompt 记录进 jfox 记录层（#399），与 Claude Code 侧对齐。

## 工作原理

监听 pi 的 `input` 事件，过滤程序注入（`source === "extension"`）与 JFox 内部
session，把用户输入合成为 CC 兼容事件后：先原子写本地 spool，再尽力 POST
jfox daemon 的 `/api/prompt`。daemon 确认落盘（stored/duplicate/skipped）后删除
spool；daemon 不可用时 spool 保留，`jfox prompts drain` 恢复。全程不阻塞 pi。

## 前置条件

- jfox ≥ 0.15.0（记录层：`/api/prompt` 端点 + source 透传）
- jfox daemon 运行中（`jfox daemon start`）；停机也能采（spool 兜底）

## 安装

拷贝或符号链接单文件到 pi 扩展目录，重启 pi 或执行 `/reload`：

```bash
cp packages/pi-plugin/extensions/jfox-prompt-capture.ts ~/.pi/agent/extensions/
```

符号链接方式（仓库更新后 `git pull` 即生效）：

```bash
ln -s "$(pwd)/packages/pi-plugin/extensions/jfox-prompt-capture.ts" ~/.pi/agent/extensions/
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `JFOX_DAEMON_URL` | `http://127.0.0.1:18700` | jfox daemon 地址 |
| `JFOX_PROMPT_SPOOL_DIR` | `~/.zettelkasten/prompt-spool` | 本地 spool 目录 |
| `JFOX_INTERNAL_SESSION` | （未设置） | 命中 `auto-summary`/`gem-synth`/`prompt-judge` 时跳过采集（防反馈循环，由 jfox 内部 runner 设置） |

## 验证

在 pi 里发一条消息，然后：

```bash
jfox prompts list --json | head -40
```

最新记录应含 `"source": "pi-coding-agent"`，`prompt` 为输入原句。

## 开发测试

无 npm 依赖，node ≥ 22.6 直跑：

```bash
node --experimental-strip-types packages/pi-plugin/test/run-tests.ts
```

```

- [ ] **Step 2: Run markdownlint**

Run: `npx --yes markdownlint-cli2 packages/pi-plugin/README.md`
Expected: 0 issues。若有（如嵌套 fence），按提示修正后重跑至 0。

- [ ] **Step 3: Commit**

```bash
git add packages/pi-plugin/README.md
git commit -m "docs(pi-plugin): install and usage guide (#462)"
```

---

### Task 5: CI Fast job 增加 node 测试 step（A7）

**Files:**

- Modify: `.github/workflows/integration-test.yml`（`test-fast` job，pytest step 之后）

**Interfaces:**

- Consumes: Task 2/3 的 `packages/pi-plugin/test/run-tests.ts`
- Produces: CI 门禁覆盖 node 测试；lint job 已有 markdownlint（A6 在 CI 侧自动覆盖）

- [ ] **Step 1: Edit workflow**

在 `test-fast` job 的「Run fast tests (no embedding)」step 之后追加两个 step：

```yaml
    - name: Set up Node
      uses: actions/setup-node@v4
      with:
        node-version: '22'

    - name: Run pi-plugin node tests
      run: node --experimental-strip-types packages/pi-plugin/test/run-tests.ts
```

注意：matrix 含 `windows-latest`，该命令跨平台（node 内置模块 + 正斜杠路径）。`lint` job 已有同款 setup-node，无需改。

- [ ] **Step 2: Verify YAML locally**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/integration-test.yml'))" && git diff --stat`
Expected: YAML 解析无异常；diff 只含上述两个 step

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/integration-test.yml
git commit -m "ci: run pi-plugin node tests in fast job (#462)"
```

（A7 的最终验证是 push 后 Fast run 绿，属 PR 阶段对账。）

---

### Task 6: 用户实测（U1、U2）——post-implementation manual verification

**Files:** 无代码改动；结果记录进 PR 描述/最终汇报。

- [ ] **U1 端到端**

1. `cp <WT>/packages/pi-plugin/extensions/jfox-prompt-capture.ts ~/.pi/agent/extensions/`，重启 pi（或 `/reload`）
2. `jfox daemon status` 确认运行（未运行则 `jfox daemon start`）
3. 在 pi 里发一条消息（如「测试采集」）
4. `jfox prompts list --json | head -40`
5. **通过标准**：最新记录 `source=pi-coding-agent`、`prompt` 为输入原句、`session_id` 为该 pi 会话 UUID
6. 完成后删除部署文件：`rm ~/.pi/agent/extensions/jfox-prompt-capture.ts`（避免本 session 后续输入持续入库造成噪音）或保留（用户决定）

- [ ] **U2 daemon 停机兜底**

1. `jfox daemon stop`
2. pi 里发一条消息
3. `ls ~/.zettelkasten/prompt-spool/` → 有新 `<uuid>.json`
4. `jfox daemon start && jfox prompts drain`
5. `jfox prompts list --json | head -40`
6. **通过标准**：spool 文件出现，drain 后记录入库（source=pi-coding-agent）且 prompt 原文不丢
7. 同 U1 第 6 步清理

**注意**：U1/U2 未经执行或未达通过标准时，最终汇报必须如实标 `pending`/失败，不得宣称验收完成。

---

## Self-Review 记录

- **Spec 覆盖**：D1-D15 全部落在 Task 1-5（D4→T1，D1/D2/D8/D10→T2/T3，D3/D5/D6/D7/D12/D13/D14/D15→T3，D9→T4，A7→T5）；A1-A7 与 U1-U2 全部有 task 对应，双向可追溯 ✓
- **占位符扫描**：无 TBD/TODO，所有代码步骤含完整代码 ✓
- **类型一致性**：`CaptureInput`/`SessionInfo`/`CaptureDeps` 签名在 T2 定义、T3 消费一致；`shouldCapture(input, env)` 参数顺序两任务一致 ✓
