#!/usr/bin/env bash
# JFox 碎片采集 hook：读 CC stdin JSON，原样 POST 到 JFox daemon。
# 设计：永不阻塞 CC（失败静默 exit 0）；不 spawn Python（curl <10ms，满足 100ms 预算）。
set -u

PAYLOAD="$(cat)"

# POST 原样给 daemon；-m1 限时1秒，-s 静默，失败不报错
RESP="$(printf '%s' "$PAYLOAD" | curl -s -m 1 -X POST \
    http://127.0.0.1:18700/api/fragment \
    -H 'Content-Type: application/json' \
    --data-binary @- 2>/dev/null || true)"

# Stop 事件：打印 daemon 返回的一行采集摘要
# 用 python3 权威解析（CC 的 stdin JSON 冒号后带空格，bash glob 不可靠）；
# 先用粗筛 *Stop* 避免在每个事件上都 spawn python（热路径保持 <10ms）
case "$PAYLOAD" in
  *Stop*)
    MSG="$(python3 -c '
import sys, json
try:
    if json.loads(sys.argv[1]).get("hook_event_name") == "Stop":
        resp = json.loads(sys.argv[2])
        if resp.get("fragment_type") == "session_summary":
            print(resp.get("message", ""))
except Exception:
    pass
' "$PAYLOAD" "$RESP" 2>/dev/null || true)"
    [ -n "$MSG" ] && echo "JFox 碎片采集: $MSG"
    ;;
esac

exit 0
