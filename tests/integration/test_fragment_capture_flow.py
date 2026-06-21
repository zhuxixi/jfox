"""端到端：hook 脚本 → daemon → SQLite。

标记 integration：依赖真实运行的 daemon（jfox daemon start）。
用户手动跑：uv run pytest tests/integration/test_fragment_capture_flow.py -v -m integration
"""

import json
import subprocess
import urllib.request
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

DAEMON = "http://127.0.0.1:18700"
REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / "packages" / "cc-plugin" / "hooks" / "fragment-capture.sh"


def _daemon_up() -> bool:
    try:
        with urllib.request.urlopen(f"{DAEMON}/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


@pytest.fixture(scope="module", autouse=True)
def require_daemon():
    if not _daemon_up():
        pytest.skip("JFox daemon 未运行；先 `jfox daemon start`（需用户手动启动，会加载模型）")


def test_post_userprompt_correction():
    payload = json.dumps(
        {
            "hook_event_name": "UserPromptSubmit",
            "session_id": "it-sess-1",
            "prompt": "不对，应该用 patch",
        }
    ).encode()
    req = urllib.request.Request(
        f"{DAEMON}/api/fragment", data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        body = json.loads(r.read())
    assert body["fragment_type"] == "correction"


def test_hook_script_end_to_end():
    """模拟 CC 调用 hook 脚本：POST 经 daemon 落库，再查 daemon 确认。"""
    payload = json.dumps(
        {
            "hook_event_name": "PostToolUse",
            "session_id": "it-sess-2",
            "tool_response": {"stdout": "hi"},
        }
    )
    proc = subprocess.run(
        ["bash", str(HOOK)], input=payload, capture_output=True, text=True, timeout=5
    )
    assert proc.returncode == 0
    with urllib.request.urlopen(f"{DAEMON}/api/fragments?session=it-sess-2", timeout=5) as r:
        body = json.loads(r.read())
    assert body["total"] >= 1
    assert body["fragments"][0]["fragment_type"] == "tool_call"


def test_stop_returns_summary_message():
    payload = json.dumps({"hook_event_name": "Stop", "session_id": "it-sess-2"}).encode()
    req = urllib.request.Request(
        f"{DAEMON}/api/fragment", data=payload, headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        body = json.loads(r.read())
    assert body["fragment_type"] == "session_summary"
    assert "碎片" in body["message"]
