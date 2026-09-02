#!/usr/bin/env bash
# JFox prompt 记录 hook：读 CC stdin JSON，先原子写本地 spool，再尽力 POST daemon。
# 设计原则：
#   1. spool 原子写入成功 = prompt 已可靠保存（fsync + rename）；
#   2. POST 成功且 daemon 确认落盘 → 删除 spool；
#   3. POST 失败/超时/daemon 不可用 → 保留 spool（jfox prompts drain 恢复）；
#   4. 永不阻塞 CC（失败静默 exit 0），不在日志输出 prompt 正文。
set -u

PAYLOAD="$(cat)"

# ---------------------------------------------------------------------------
# 内部 session 过滤：auto-summary / gem-synth / prompt-judge
# 必须与服务端 jfox/prompts/service.py 的 INTERNAL_SOURCES 保持一致。
# ---------------------------------------------------------------------------
case "${JFOX_INTERNAL_SESSION:-}" in
    auto-summary|gem-synth|prompt-judge)
        exit 0
        ;;
esac

# ---------------------------------------------------------------------------
# spool 目录：默认 ~/.zettelkasten/prompt-spool/，可用 JFOX_PROMPT_SPOOL_DIR 覆盖
# ---------------------------------------------------------------------------
SPOOL_DIR="${JFOX_PROMPT_SPOOL_DIR:-$HOME/.zettelkasten/prompt-spool}"
mkdir -p "$SPOOL_DIR" 2>/dev/null || exit 0
chmod 700 "$SPOOL_DIR" 2>/dev/null || true

# ---------------------------------------------------------------------------
# 生成 capture UUID 并注入 payload
# ---------------------------------------------------------------------------
if command -v uuidgen >/dev/null 2>&1; then
    CAPTURE_ID="$(uuidgen)"
elif command -v python3 >/dev/null 2>&1; then
    CAPTURE_ID="$(python3 -c 'import uuid; print(uuid.uuid4())' 2>/dev/null)" || exit 0
else
    exit 0
fi
[ -n "$CAPTURE_ID" ] || exit 0

# 注入 jfox_capture_id（python3 权威解析，失败跳过避免坏 payload）
if command -v python3 >/dev/null 2>&1; then
    PAYLOAD="$(printf '%s' "$PAYLOAD" | python3 -c '
import sys, json
try:
    event = json.loads(sys.stdin.read())
    event["jfox_capture_id"] = sys.argv[1]
    sys.stdout.write(json.dumps(event, ensure_ascii=False, separators=(",", ":")))
except Exception:
    sys.exit(1)
' "$CAPTURE_ID")" || exit 0
else
    exit 0
fi
[ -n "$PAYLOAD" ] || exit 0

# ---------------------------------------------------------------------------
# 原子写 spool：.tmp → fsync → rename → fsync dir
# ---------------------------------------------------------------------------
SPOOL_FILE="$SPOOL_DIR/$CAPTURE_ID.json"
SPOOL_TMP="$SPOOL_FILE.tmp"

if printf '%s' "$PAYLOAD" > "$SPOOL_TMP" 2>/dev/null; then
    # fsync 文件内容
    if command -v python3 >/dev/null 2>&1; then
        python3 -c "
import os, sys
try:
    fd = os.open(sys.argv[1], os.O_RDONLY)
    os.fsync(fd)
    os.close(fd)
except Exception:
    pass
" "$SPOOL_TMP" 2>/dev/null || true
    fi
    chmod 600 "$SPOOL_TMP" 2>/dev/null || true
    mv "$SPOOL_TMP" "$SPOOL_FILE" 2>/dev/null || {
        rm -f "$SPOOL_TMP" 2>/dev/null || true
        exit 0
    }
else
    # spool 写失败：不伪造成功，不输出 prompt 正文，静默退出
    rm -f "$SPOOL_TMP" 2>/dev/null || true
    exit 0
fi

# ---------------------------------------------------------------------------
# 尽力 POST /api/prompt：只有 daemon 确认 stored/duplicate 才删除 spool
# ---------------------------------------------------------------------------
JFOX_DAEMON_URL="${JFOX_DAEMON_URL:-http://127.0.0.1:18700}"
RESP="$(printf '%s' "$PAYLOAD" | curl -s -m 2 -X POST \
    "${JFOX_DAEMON_URL}/api/prompt" \
    -H 'Content-Type: application/json' \
    --data-binary @- 2>/dev/null || true)"

# 权威解析响应：stored/duplicate → 删除 spool；其他（超时/错误/daemon 不可用）→ 保留
if command -v python3 >/dev/null 2>&1; then
    python3 -c '
import sys, json
try:
    resp = json.loads(sys.argv[1])
    if resp.get("status") in ("stored", "duplicate"):
        sys.exit(0)
    else:
        sys.exit(1)
except Exception:
    sys.exit(1)
' "$RESP" 2>/dev/null && rm -f "$SPOOL_FILE" 2>/dev/null || true
fi

exit 0
