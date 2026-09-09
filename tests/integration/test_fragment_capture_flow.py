"""端到端：hook 脚本 → spool / daemon API → user_prompts（#399 新链路）。

标记 integration：依赖真实运行的 daemon（jfox daemon start）。
用户手动跑：uv run pytest tests/integration/test_fragment_capture_flow.py -v -m integration

历史：#399/#493 退役旧分类采集（PostToolUse/Stop → retired），
#462/#521 hook 改版为 spool + POST /api/prompt 静默模式。本文件
按新契约重写（原用例见 git 历史），session id 一律随机，避免真实
daemon 持久库的固定 session 残留污染（#523 根因之一）。
"""

import json
import os
import subprocess
import sys
import urllib.request
import uuid
from pathlib import Path
from typing import Dict, Optional

import pytest

pytestmark = pytest.mark.integration

DAEMON = "http://127.0.0.1:18700"
REPO_ROOT = Path(__file__).resolve().parents[2]
HOOK = REPO_ROOT / "packages" / "cc-plugin" / "hooks" / "fragment-capture.sh"
# 硬路径调用，不依赖 PATH（Windows 上 PATH 的 bash 会解析到 WSL launcher）
BASH = "/bin/bash"

# hook 是 bash 脚本，仅在 Unix 上运行；Windows 无 /bin/bash 且产品不经 bash
# 调用该 hook——与 test_fragment_hook.py 的 win32 skip 同惯例
posix_only = pytest.mark.skipif(
    sys.platform == "win32",
    reason="fragment-capture.sh 是 bash 脚本，Windows 无 /bin/bash，产品不经 bash 调用该 hook",
)


def _daemon_up() -> bool:
    try:
        with urllib.request.urlopen(f"{DAEMON}/health", timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _sess() -> str:
    """随机 session id：杜绝固定 id 在真实库累积/污染。"""
    return f"it-{uuid.uuid4().hex[:8]}"


def _post_api(event: dict) -> dict:
    req = urllib.request.Request(
        f"{DAEMON}/api/prompt",
        data=json.dumps(event).encode(),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def _run_hook(
    payload: str, spool_dir: Path, extra_env: Optional[Dict[str, str]] = None
) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "JFOX_PROMPT_SPOOL_DIR": str(spool_dir),
        **(extra_env or {}),
    }
    return subprocess.run(
        [BASH, str(HOOK)], input=payload, capture_output=True, text=True, timeout=10, env=env
    )


@pytest.fixture(scope="module")
def require_daemon():
    if not _daemon_up():
        pytest.skip("JFox daemon 未运行；先 `jfox daemon start`（需用户手动启动，会加载模型）")


@pytest.mark.usefixtures("require_daemon")
def test_prompt_api_stores_full_prompt():
    """POST /api/prompt（UserPromptSubmit）→ stored + prompt 原文完整回显。
    隐含前提：真实 daemon 的 prompt_capture.enabled 为 true（默认）。
    若返回 skipped，检查 ~/.zk_config.json 是否禁用了采集。"""
    sess, text = _sess(), "不对，应该用 patch 而不是 put（集成测试随机注入）"
    body = _post_api({"hook_event_name": "UserPromptSubmit", "session_id": sess, "prompt": text})
    assert body["status"] == "stored"
    assert body["prompt"] == text


@pytest.mark.usefixtures("require_daemon")
def test_prompt_api_idempotent():
    """同 capture_id 重复 POST → duplicate（幂等键 source_key=capture:<id>）"""
    cid = str(uuid.uuid4())
    event = {
        "hook_event_name": "UserPromptSubmit",
        "session_id": _sess(),
        "prompt": "幂等探针（集成测试随机注入）",
        "jfox_capture_id": cid,
    }
    first = _post_api(event)
    second = _post_api(event)
    assert first["status"] == "stored"  # 随机新 uuid 必为新行
    assert second["status"] == "duplicate"
    assert second["prompt_id"] == first["prompt_id"]


@pytest.mark.usefixtures("require_daemon")
@posix_only
def test_hook_post_success_clears_spool(tmp_path):
    """daemon 可用：hook 完成后 spool 为空（stored 确认后删除）、静默 exit 0"""
    payload = json.dumps(
        {"hook_event_name": "UserPromptSubmit", "session_id": _sess(), "prompt": "hook 链路探针"}
    )
    # 显式 pin daemon 地址：防止继承的外部 JFOX_DAEMON_URL 把 hook 引向别处
    proc = _run_hook(payload, tmp_path, extra_env={"JFOX_DAEMON_URL": DAEMON})
    assert proc.returncode == 0
    assert proc.stdout == ""  # hook 静默契约：不打印摘要（#462 改版）
    assert list(tmp_path.glob("*.json")) == []  # POST 成功 → spool 已删


@posix_only
def test_hook_post_failure_keeps_spool(tmp_path):
    """daemon 不可达：spool 保留（durable 降级不丢数据）、仍静默 exit 0。
    本用例不依赖真实 daemon（JFOX_DAEMON_URL 指向黑洞端口）。"""
    payload = json.dumps(
        {"hook_event_name": "UserPromptSubmit", "session_id": _sess(), "prompt": "降级探针"}
    )
    proc = _run_hook(payload, tmp_path, extra_env={"JFOX_DAEMON_URL": "http://127.0.0.1:1"})
    assert proc.returncode == 0
    assert proc.stdout == ""
    spool_files = list(tmp_path.glob("*.json"))
    assert len(spool_files) == 1  # POST 失败 → spool 留存待 drain
    kept = json.loads(spool_files[0].read_text(encoding="utf-8"))
    assert kept["jfox_capture_id"]  # capture id 已注入
    assert kept["prompt"] == "降级探针"


@posix_only
def test_hook_handles_real_cc_format_payload(tmp_path):
    """回归 guard：CC stdin JSON 冒号后带空格，hook 必须仍能解析处理。
    历史上 bash glob 空格敏感 bug 曾致验收#5 静默失败（见 git 历史
    test_hook_prints_stop_summary_with_real_cc_format）。新 hook 用 python3
    权威解析，本用例守住该行为不回退；用黑洞端口隔离 daemon 依赖。"""
    payload = (
        '{ "hook_event_name": "UserPromptSubmit", '
        f'"session_id": "{_sess()}", "prompt": "空格格式探针" }}'
    )
    proc = _run_hook(payload, tmp_path, extra_env={"JFOX_DAEMON_URL": "http://127.0.0.1:1"})
    assert proc.returncode == 0
    assert proc.stdout == ""
    kept = json.loads(next(tmp_path.glob("*.json")).read_text(encoding="utf-8"))
    assert kept["hook_event_name"] == "UserPromptSubmit"
    assert kept["prompt"] == "空格格式探针"


@posix_only
@pytest.mark.parametrize("source", ["auto-summary", "gem-synth", "prompt-judge"])
def test_hook_internal_session_skipped(source, tmp_path):
    """JFOX_INTERNAL_SESSION 命中内部来源 → hook 直接 exit 0，不产生 spool 文件"""
    payload = json.dumps(
        {"hook_event_name": "UserPromptSubmit", "session_id": _sess(), "prompt": "内部来源探针"}
    )
    proc = _run_hook(payload, tmp_path, extra_env={"JFOX_INTERNAL_SESSION": source})
    assert proc.returncode == 0
    assert list(tmp_path.glob("*.json")) == []


@pytest.mark.usefixtures("require_daemon")
def test_legacy_fragment_endpoint_retired():
    """旧 /api/fragment 端点：PostToolUse/Stop → retired（#399 退役契约）"""
    for event_name in ("PostToolUse", "Stop"):
        req = urllib.request.Request(
            f"{DAEMON}/api/fragment",
            data=json.dumps({"hook_event_name": event_name, "session_id": _sess()}).encode(),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=5) as r:
            body = json.loads(r.read())
        assert body["status"] == "retired"
        assert event_name in body["reason"]
