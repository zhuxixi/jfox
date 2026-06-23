"""LLM 调用封装测试（mock subprocess，不真调 claude）。"""

import json
from unittest.mock import MagicMock, patch

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
    """合成 claude 调用必须禁用工具（--allowed-tools ''）防注入"""
    import jfox.gem_synth.llm as llm_mod

    captured_cmd = {}

    def fake_run(cmd, **kw):
        captured_cmd["cmd"] = cmd
        return type("R", (), {"returncode": 0, "stdout": '{"result": "{}"}', "stderr": ""})()

    with patch.object(llm_mod.subprocess, "run", side_effect=fake_run):
        llm_mod._invoke_claude("prompt", MagicMock(claude_timeout_seconds=30, claude_binary=None))
    assert "--allowed-tools" in captured_cmd["cmd"]
    # 紧跟空字符串
    idx = captured_cmd["cmd"].index("--allowed-tools")
    assert captured_cmd["cmd"][idx + 1] == ""
