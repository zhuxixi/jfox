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
