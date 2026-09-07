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
