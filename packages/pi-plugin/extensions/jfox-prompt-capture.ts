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

import type { ExtensionAPI } from "@earendil-works/pi-coding-agent";
import { randomUUID } from "node:crypto";
import { mkdir, rename, unlink, writeFile } from "node:fs/promises";
import { homedir } from "node:os";
import { join } from "node:path";

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
