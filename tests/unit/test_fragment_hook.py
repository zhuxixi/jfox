"""hook 脚本行为单元测试（使用本地 mock daemon，不依赖真实 jfox daemon）。"""

import http.server
import json
import os
import socket
import subprocess
import threading
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / "packages" / "cc-plugin" / "hooks" / "fragment-capture.sh"
BASH = "/bin/bash"


def _free_port() -> int:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.bind(("127.0.0.1", 0))
    port = int(sock.getsockname()[1])
    sock.close()
    return port


@pytest.fixture
def mock_daemon():
    """在随机端口启动临时 HTTP server，返回 (收到的请求列表, daemon_url)。"""
    port = _free_port()
    received: list = []

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_POST(self):
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length)
            try:
                received.append(json.loads(body))
            except Exception:
                received.append(body.decode("utf-8", errors="replace"))
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(b'{"fragment_type":"user_input"}')

        def log_message(self, *args):
            pass

    server = http.server.HTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield received, f"http://127.0.0.1:{port}"
    finally:
        server.shutdown()


def test_hook_injects_source_for_internal_session(mock_daemon):
    """JFOX_INTERNAL_SESSION 为内部来源时，hook 脚本应在 payload 中注入 source 字段。"""
    received, daemon_url = mock_daemon
    payload = json.dumps(
        {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "hi"}
    )
    env = {**os.environ, "JFOX_INTERNAL_SESSION": "auto-summary", "JFOX_DAEMON_URL": daemon_url}
    proc = subprocess.run(
        [BASH, str(HOOK)], input=payload, capture_output=True, text=True, timeout=5, env=env
    )
    assert proc.returncode == 0
    assert len(received) == 1
    assert received[0].get("source") == "auto-summary"
    # 原事件字段保留
    assert received[0].get("hook_event_name") == "UserPromptSubmit"


def test_hook_no_source_for_normal_session(mock_daemon):
    """普通用户 session 不设置 JFOX_INTERNAL_SESSION，payload 不应被注入 source。"""
    received, daemon_url = mock_daemon
    payload = json.dumps(
        {"hook_event_name": "UserPromptSubmit", "session_id": "s3", "prompt": "hi"}
    )
    env = {
        **{k: v for k, v in os.environ.items() if k != "JFOX_INTERNAL_SESSION"},
        "JFOX_DAEMON_URL": daemon_url,
    }
    proc = subprocess.run(
        [BASH, str(HOOK)], input=payload, capture_output=True, text=True, timeout=5, env=env
    )
    assert proc.returncode == 0
    assert len(received) == 1
    assert "source" not in received[0]
