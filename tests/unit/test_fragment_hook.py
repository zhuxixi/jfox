"""hook 脚本行为单元测试（使用本地 mock daemon，不依赖真实 jfox daemon）。"""

import http.server
import json
import os
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path

import pytest

# hook 是 bash 脚本（fragment-capture.sh），由 hooks.json 通过 `bash` 调起，
# 依赖 bash + curl + python3，仅在 Unix 上运行；Windows 无 /bin/bash，
# 且产品在 Windows（无 git-bash）也不会经 bash 执行该 hook，
# 故这组 hook 行为测试在 Windows 跳过（与 test_daemon_process.py 的 win32 skip 同惯例）。
pytestmark = pytest.mark.skipif(
    sys.platform == "win32",
    reason="fragment-capture.sh 是 bash 脚本，Windows 无 /bin/bash，产品不经 bash 调用该 hook",
)

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


def test_hook_skips_internal_session_entirely(mock_daemon):
    """内部 session（JFOX_INTERNAL_SESSION 命中）hook 直接本地跳过，不 POST。"""
    received, daemon_url = mock_daemon
    payload = json.dumps(
        {"hook_event_name": "UserPromptSubmit", "session_id": "s1", "prompt": "hi"}
    )
    env = {**os.environ, "JFOX_INTERNAL_SESSION": "auto-summary", "JFOX_DAEMON_URL": daemon_url}
    proc = subprocess.run(
        [BASH, str(HOOK)], input=payload, capture_output=True, text=True, timeout=5, env=env
    )
    assert proc.returncode == 0
    assert len(received) == 0  # 本地跳过，无请求


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


def test_hook_skips_internal_session_on_invalid_json(mock_daemon):
    """内部 session 的 payload 不是合法 JSON 时，hook 应直接跳过，不转发无 source 标记的事件。"""
    received, daemon_url = mock_daemon
    payload = "this is not json"
    env = {**os.environ, "JFOX_INTERNAL_SESSION": "auto-summary", "JFOX_DAEMON_URL": daemon_url}
    proc = subprocess.run(
        [BASH, str(HOOK)], input=payload, capture_output=True, text=True, timeout=5, env=env
    )
    assert proc.returncode == 0
    assert len(received) == 0


def test_hook_skips_internal_session_when_python3_missing(mock_daemon, tmp_path):
    """内部 session 且环境缺少 python3 时，hook 应直接跳过，不发送任何请求。"""
    received, daemon_url = mock_daemon
    payload = json.dumps(
        {"hook_event_name": "UserPromptSubmit", "session_id": "s4", "prompt": "hi"}
    )
    # 构造一个只有 curl、没有 python3 的 PATH
    curl_path = shutil.which("curl")
    if not curl_path:
        pytest.skip("当前环境未找到 curl")
    mini_bin = tmp_path / "minibin"
    mini_bin.mkdir()
    shutil.copy(curl_path, mini_bin / "curl")
    env = {
        **os.environ,
        "JFOX_INTERNAL_SESSION": "auto-summary",
        "JFOX_DAEMON_URL": daemon_url,
        "PATH": str(mini_bin),
    }
    proc = subprocess.run(
        [BASH, str(HOOK)], input=payload, capture_output=True, text=True, timeout=5, env=env
    )
    assert proc.returncode == 0
    assert len(received) == 0
