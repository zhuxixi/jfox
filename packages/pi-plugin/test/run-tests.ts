// pi-plugin node 测试入口：纯函数断言 + dynamic import 冒烟 + mock server 流程（Task 3 追加）。
// 运行：node --experimental-strip-types packages/pi-plugin/test/run-tests.ts
import assert from "node:assert/strict";
import http from "node:http";
import { mkdtemp, readdir, readFile, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

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
// ---- A5 冒烟补全：default export 为工厂（本任务加入 factory 后生效）----
assert.equal(typeof ext.default, "function");

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

// ---- A4: spool + POST 流程（mock daemon）----
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

// ---- 汇总 ----
console.log(`\n${passed} passed, ${failures.length} failed`);
if (failures.length > 0) {
  process.exit(1);
}
