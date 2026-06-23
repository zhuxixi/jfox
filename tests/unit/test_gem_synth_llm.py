"""LLM 调用封装测试（mock subprocess，不真调 claude）。"""

import json
import threading
from unittest.mock import MagicMock, patch

import pytest

from jfox.gem_synth.llm import _build_prompt, synthesize_with_llm


def test_build_prompt_contains_context_and_grounding():
    prompt = _build_prompt(
        turn_context="用户说：不对，应该用 patch",
        grounding=[{"title": "补丁规范", "content": "优先用 patch"}],
    )
    assert "不对，应该用 patch" in prompt
    assert "补丁规范" in prompt
    assert "优先用 patch" in prompt


def test_synthesize_returns_parsed_dict():
    fake_output = json.dumps(
        {
            "title": "应优先用 patch 而非 sed",
            "content": "## 知识\n修改文件优先用 patch...",
            "confidence": 0.85,
            "knowledge_type": "procedural",
            "grounded_by": ["补丁规范"],
        }
    )
    with patch("jfox.gem_synth.llm._invoke_claude", return_value=fake_output):
        result = synthesize_with_llm(
            turn_context="x",
            grounding=[{"title": "补丁规范", "content": "y"}],
            cfg=MagicMock(),
        )
    assert result["title"] == "应优先用 patch 而非 sed"
    assert result["confidence"] == 0.85
    assert result["knowledge_type"] == "procedural"


def test_synthesize_returns_none_on_invalid_json():
    with patch("jfox.gem_synth.llm._invoke_claude", return_value="not json"):
        assert synthesize_with_llm(turn_context="x", grounding=[], cfg=MagicMock()) is None


def test_synthesize_returns_none_on_exception():
    with patch("jfox.gem_synth.llm._invoke_claude", side_effect=RuntimeError("boom")):
        assert synthesize_with_llm(turn_context="x", grounding=[], cfg=MagicMock()) is None


def test_invoke_claude_cmd_restricts_tools():
    """合成 claude 调用必须禁用工具（--allowed-tools ''）防注入。

    _invoke_claude 用 Popen + poll，故 mock subprocess.Popen。FakePopen.poll() 先返回
    None（模拟进程在跑），下一次返回 0（结束），stdout.read() 给 JSON 包装。
    """
    import jfox.gem_synth.llm as llm_mod

    captured_cmd = {}

    class FakePopen:
        def __init__(self, cmd, **kw):
            captured_cmd["cmd"] = cmd
            self.stdin = self
            self.stdout = self
            self.stderr = self
            self.pid = 12345
            self._polled = False

        def write(self, s):
            pass

        def close(self):
            pass

        def poll(self):
            if not self._polled:
                self._polled = True
                return None
            return 0

        def read(self):
            return '{"result": "{}"}'

    with (
        patch.object(llm_mod.subprocess, "Popen", side_effect=FakePopen),
        patch.object(llm_mod.os, "getpgid", return_value=12345),
        patch.object(llm_mod.time, "sleep"),
    ):
        llm_mod._invoke_claude("prompt", MagicMock(claude_timeout_seconds=30, claude_binary=None))
    assert "--allowed-tools" in captured_cmd["cmd"]
    # 紧跟空字符串
    idx = captured_cmd["cmd"].index("--allowed-tools")
    assert captured_cmd["cmd"][idx + 1] == ""


def test_invoke_claude_interruptible_by_stop_event():
    """stop_event 置位时，_invoke_claude 必须中断挂起的 claude 调用并杀进程组。

    TDD：FakePopen.poll() 永远返回 None（claude 一直没退出），stop_event 预先 set，
    应抛 RuntimeError 含"中断"，并调用 killpg 清理。
    """
    import jfox.gem_synth.llm as llm_mod

    class HangingPopen:
        def __init__(self, cmd, **kw):
            self.stdin = self
            self.stdout = self
            self.stderr = self
            self.pid = 12345

        def write(self, s):
            pass

        def close(self):
            pass

        def poll(self):
            return None  # claude 永不结束

        def read(self):
            return ""

    ev = threading.Event()
    ev.set()
    with (
        patch.object(llm_mod.subprocess, "Popen", side_effect=HangingPopen),
        patch.object(llm_mod.os, "getpgid", return_value=12345),
        patch.object(llm_mod.os, "killpg") as mock_killpg,
        patch.object(llm_mod.time, "sleep"),
    ):
        with pytest.raises(RuntimeError, match="中断"):
            llm_mod._invoke_claude(
                "prompt",
                MagicMock(claude_timeout_seconds=300, claude_binary=None),
                stop_event=ev,
            )
    # killpg 被调（中断路径必杀进程组）
    assert mock_killpg.called
