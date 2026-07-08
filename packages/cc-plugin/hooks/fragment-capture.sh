#!/usr/bin/env bash
# JFox 碎片采集 hook：读 CC stdin JSON，原样 POST 到 JFox daemon。
# 设计：永不阻塞 CC（失败静默 exit 0）。
# 热路径（UserPromptSubmit/PostToolUse）仅 curl，<10ms；仅 Stop 分支 spawn python3 解析摘要。
set -u

PAYLOAD="$(cat)"

# 若这是 JFox 内部系统产生的 session，将来源标记注入 payload，让 daemon 统一过滤。
# 这样 daemon（长驻进程）无需读取进程环境变量，避免环境变量污染导致普通用户事件被误跳过。
# 值列表必须与服务端 INTERNAL_SOURCES 保持一致。
case "${JFOX_INTERNAL_SESSION:-}" in
    auto-summary|gem-synth)
        PAYLOAD="$(printf '%s' "$PAYLOAD" | python3 -c '
import sys, json
try:
    event = json.load(sys.stdin)
    event["source"] = sys.argv[1]
    json.dump(event, sys.stdout, ensure_ascii=False, separators=(",", ":"))
except Exception:
    sys.stdout.write(sys.stdin.read())
' "$JFOX_INTERNAL_SESSION")"
        ;;
esac

# POST 原样给 daemon；-m1 限时1秒，-s 静默，失败不报错
RESP="$(printf '%s' "$PAYLOAD" | curl -s -m 1 -X POST \
    http://127.0.0.1:18700/api/fragment \
    -H 'Content-Type: application/json' \
    --data-binary @- 2>/dev/null || true)"

# Stop 事件：打印 daemon 返回的一行采集摘要。
# 用 python3 权威解析（CC 的 stdin JSON 冒号后带空格，bash glob 不可靠）；
# 粗筛 *Stop* 避免每个事件都 spawn python（热路径保持 <10ms）；
# 大 payload 走 stdin 而非 argv，避免触碰 ARG_MAX（~2MB）；小 resp 走 argv 安全。
case "$PAYLOAD" in
  *Stop*)
    MSG="$(printf '%s' "$PAYLOAD" | python3 -c '
import sys, json
try:
    event = json.loads(sys.stdin.read())
    if event.get("hook_event_name") == "Stop":
        resp = json.loads(sys.argv[1])
        if resp.get("fragment_type") == "session_summary":
            print(resp.get("message", ""))
except Exception:
    pass
' "$RESP" 2>/dev/null || true)"
    [ -n "$MSG" ] && echo "JFox 碎片采集: $MSG"
    ;;
esac

exit 0
