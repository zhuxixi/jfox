"""detector.classify 纯逻辑测试（无 I/O）。"""

from jfox.fragment.detector import classify
from jfox.global_config import FragmentCaptureConfig


def test_userprompt_correction():
    cfg = FragmentCaptureConfig()
    ftype, content = classify({"hook_event_name": "UserPromptSubmit", "prompt": "不对，应该用 patch"}, cfg)
    assert ftype == "correction"
    assert content == "不对，应该用 patch"


def test_userprompt_decision():
    cfg = FragmentCaptureConfig()
    ftype, _ = classify({"hook_event_name": "UserPromptSubmit", "prompt": "我决定用方案 A"}, cfg)
    assert ftype == "decision"


def test_correction_takes_priority_over_decision():
    """同时命中时纠正优先（被纠正的信号更强）"""
    cfg = FragmentCaptureConfig()
    ftype, _ = classify({"hook_event_name": "UserPromptSubmit", "prompt": "不对，我决定换一种"}, cfg)
    assert ftype == "correction"


def test_userprompt_plain_input():
    cfg = FragmentCaptureConfig()
    ftype, content = classify({"hook_event_name": "UserPromptSubmit", "prompt": "帮我写个函数"}, cfg)
    assert ftype == "user_input"
    assert content == "帮我写个函数"


def test_posttooluse_tool_call():
    cfg = FragmentCaptureConfig()
    event = {
        "hook_event_name": "PostToolUse",
        "tool_name": "Bash",
        "tool_response": {"stdout": "done", "exit_code": 0},
    }
    ftype, content = classify(event, cfg)
    assert ftype == "tool_call"
    assert "done" in content


def test_content_truncated_to_max():
    cfg = FragmentCaptureConfig(max_content_chars=10)
    long_prompt = "x" * 100
    _, content = classify({"hook_event_name": "UserPromptSubmit", "prompt": long_prompt}, cfg)
    assert len(content) == 10


def test_stop_returns_summary_type():
    cfg = FragmentCaptureConfig()
    ftype, content = classify({"hook_event_name": "Stop"}, cfg)
    assert ftype == "session_summary"
    assert content is None


def test_unknown_event_fallback():
    cfg = FragmentCaptureConfig()
    ftype, _ = classify({"hook_event_name": "Whatever"}, cfg)
    assert ftype == "user_input"
