"""LLM 调用封装测试（mock subprocess，不真调 claude）。"""

import io
import json
import threading
from unittest.mock import MagicMock, patch

import pytest

from jfox.gem_synth.llm import _build_prompt, synthesize_with_llm


@pytest.fixture(autouse=True)
def _mock_resolve_claude_binary():
    """CI 无 claude CLI；默认 mock _resolve_claude_binary，使 _invoke_claude 测试
    不依赖 PATH 上有 claude 二进制（本地有、CI 没有会导致同一测试本地过 CI 红）。"""
    with patch("jfox.gem_synth.llm._resolve_claude_binary", return_value="claude"):
        yield


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


def test_synthesize_strips_json_code_fence():
    """claude 把 JSON 包在 ```json ... ``` 围栏里时，必须剥围栏后解析。

    真实 claude --output-format json 返回 envelope，其 result 字段常被模型包在
    markdown 代码围栏里（即使 SYSTEM_PROMPT 要求裸 JSON）。不剥围栏会让 json.loads
    碰到首字符反引号直接崩（JSONDecodeError: Expecting value char 0）→ 合成全失败。
    """
    inner_json = json.dumps(
        {
            "title": "应优先用 patch",
            "content": "修改文件优先用 patch",
            "confidence": 0.8,
            "knowledge_type": "procedural",
            "grounded_by": [],
        }
    )
    fenced = f"```json\n{inner_json}\n```"
    # 模拟真实 claude 返回：envelope.result 是带围栏的字符串
    fake_output = json.dumps({"type": "result", "subtype": "success", "result": fenced})
    with patch("jfox.gem_synth.llm._invoke_claude", return_value=fake_output):
        result = synthesize_with_llm(turn_context="x", grounding=[], cfg=MagicMock())
    assert result is not None
    assert result["title"] == "应优先用 patch"
    assert result["confidence"] == 0.8


def test_synthesize_strips_bare_code_fence():
    """围栏无语言标签（``` ... ```）时也要正确剥。"""
    inner_json = json.dumps({"title": "裸围栏", "content": "x", "confidence": 0.5})
    fenced = f"```\n{inner_json}\n```"
    fake_output = json.dumps({"type": "result", "result": fenced})
    with patch("jfox.gem_synth.llm._invoke_claude", return_value=fake_output):
        result = synthesize_with_llm(turn_context="x", grounding=[], cfg=MagicMock())
    assert result is not None
    assert result["title"] == "裸围栏"


def test_synthesize_returns_none_on_invalid_json():
    with patch("jfox.gem_synth.llm._invoke_claude", return_value="not json"):
        assert synthesize_with_llm(turn_context="x", grounding=[], cfg=MagicMock()) is None


def test_synthesize_returns_none_on_exception():
    with patch("jfox.gem_synth.llm._invoke_claude", side_effect=RuntimeError("boom")):
        assert synthesize_with_llm(turn_context="x", grounding=[], cfg=MagicMock()) is None


def test_invoke_claude_cmd_restricts_tools():
    """合成 claude 调用必须禁用工具（--allowed-tools ''）防注入。

    _invoke_claude 用 Popen + poll + 后台 stderr 排空线程，故 mock subprocess.Popen。
    FakePopen.poll() 先返回 None（模拟进程在跑），下一次返回 0（结束）。
    stdin/stdout/stderr 用 io.StringIO，兼容 .read() 与 .read(4096)（drainer 调用）。
    """
    import jfox.gem_synth.llm as llm_mod

    captured_cmd = {}

    class FakePopen:
        def __init__(self, cmd, **kw):
            captured_cmd["cmd"] = cmd
            self.stdin = io.StringIO()
            self.stdout = io.StringIO('{"result": "{}"}')
            self.stderr = io.StringIO("")
            self.pid = 12345
            self._polled = False

        def poll(self):
            if not self._polled:
                self._polled = True
                return None
            return 0

        def wait(self, timeout=None):
            return 0

    with (
        patch.object(llm_mod.subprocess, "Popen", side_effect=FakePopen),
        patch.object(llm_mod.os, "getpgid", return_value=12345, create=True),
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
    应抛 RuntimeError 含"中断"，并调用 killpg 清理（_kill_proc_group 单一 kill 点）。
    """
    import jfox.gem_synth.llm as llm_mod

    class HangingPopen:
        def __init__(self, cmd, **kw):
            self.stdin = io.StringIO()
            self.stdout = io.StringIO("")
            self.stderr = io.StringIO("")
            self.pid = 12345

        def poll(self):
            return None  # claude 永不结束

        def wait(self, timeout=None):
            return 0

    ev = threading.Event()
    ev.set()
    with (
        patch.object(llm_mod.subprocess, "Popen", side_effect=HangingPopen),
        patch.object(llm_mod.os, "getpgid", return_value=12345, create=True),
        patch.object(llm_mod.os, "killpg", create=True) as mock_killpg,
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


def test_invoke_claude_drains_stderr_no_deadlock():
    """stderr 后台排空：进程正常退出且写了 stderr 时，不阻塞、能返回 stdout。

    TDD：模拟 claude 写若干 stderr（如警告日志）后正常退出（rc=0）。
    drainer 线程读光 stderr，poll 返回 0 → 返回 stdout。若未排空 stderr，且 stderr
    数据 > 64KB，真实场景会死锁；此处验证排空路径被触发且函数正常完成。
    """
    import jfox.gem_synth.llm as llm_mod

    class StderrPopen:
        def __init__(self, cmd, **kw):
            self.stdin = io.StringIO()
            self.stdout = io.StringIO('{"result": "{}"}')
            # 模拟 claude 写入若干 stderr 后关闭
            self.stderr = io.StringIO("warn: something\nwarn: more\n")
            self.pid = 12345
            self._polled = False

        def poll(self):
            if not self._polled:
                self._polled = True
                return None
            return 0

        def wait(self, timeout=None):
            return 0

    with (
        patch.object(llm_mod.subprocess, "Popen", side_effect=StderrPopen),
        patch.object(llm_mod.os, "getpgid", return_value=12345, create=True),
        patch.object(llm_mod.time, "sleep"),
    ):
        # 应正常返回 stdout，不挂起
        out = llm_mod._invoke_claude(
            "prompt", MagicMock(claude_timeout_seconds=30, claude_binary=None)
        )
    assert "result" in out


def test_invoke_claude_drains_stdout_no_deadlock():
    """stdout 后台排空：输出 > 64KB 时不阻塞、能完整返回。

    TDD（cc#4）：R2 只排空 stderr，大 JSON 输出写满 stdout 管道缓冲会让 claude
    阻塞在 write，poll() 永不返回 → 退化成超时。drainer 线程对称排空 stdout，
    poll 返回 0 → 从累积块拼接返回完整内容。
    """
    import jfox.gem_synth.llm as llm_mod

    # > 64KB 的 stdout 内容，验证排空路径不挂起
    big_payload = '{"result": "' + "x" * (70 * 1024) + '"}'

    class BigStdoutPopen:
        def __init__(self, cmd, **kw):
            self.stdin = io.StringIO()
            self.stdout = io.StringIO(big_payload)
            self.stderr = io.StringIO("")
            self.pid = 12345
            self._polled = False

        def poll(self):
            if not self._polled:
                self._polled = True
                return None
            return 0

        def wait(self, timeout=None):
            return 0

    with (
        patch.object(llm_mod.subprocess, "Popen", side_effect=BigStdoutPopen),
        patch.object(llm_mod.os, "getpgid", return_value=12345, create=True),
        patch.object(llm_mod.time, "sleep"),
    ):
        out = llm_mod._invoke_claude(
            "prompt", MagicMock(claude_timeout_seconds=30, claude_binary=None)
        )
    # 完整内容被 drainer 排空后拼接返回，无截断、无挂起
    assert out == big_payload


def test_invoke_claude_finally_kills_on_unexpected_exception():
    """finally 兜底 kill：非 RuntimeError/TimeoutError 的意外异常（如 OSError）也必须杀进程组。

    TDD（kimi#1/cc#3）：R2 的 except (RuntimeError, TimeoutError) 只覆盖两类异常，
    其它异常路径（OSError 等）跳过 kill → 孤儿进程。新实现 finally 为单一 kill 权威点：
    只要 poll() is None 就 kill，覆盖任意异常路径。
    """
    import jfox.gem_synth.llm as llm_mod

    class HangingPopen:
        def __init__(self, cmd, **kw):
            self.stdin = io.StringIO()
            self.stdout = io.StringIO("")
            self.stderr = io.StringIO("")
            self.pid = 12345

        def poll(self):
            return None  # 进程始终未退出 → finally 必杀

        def wait(self, timeout=None):
            return 0

    # monotonic 第一次调用算 deadline（正常返回），第二次（while 循环内）抛 OSError
    monotonic_state = {"first": True}

    def fake_monotonic():
        if monotonic_state["first"]:
            monotonic_state["first"] = False
            return 1000.0
        raise OSError("unexpected")

    with (
        patch.object(llm_mod.subprocess, "Popen", side_effect=HangingPopen),
        patch.object(llm_mod.os, "getpgid", return_value=12345, create=True),
        patch.object(llm_mod.os, "killpg", create=True) as mock_killpg,
        patch.object(llm_mod.time, "sleep"),
        patch.object(llm_mod.time, "monotonic", side_effect=fake_monotonic),
    ):
        with pytest.raises(OSError, match="unexpected"):
            llm_mod._invoke_claude(
                "prompt", MagicMock(claude_timeout_seconds=30, claude_binary=None)
            )
    # OSError 路径也触发 kill（finally 兜底，非仅 RuntimeError/TimeoutError）
    assert mock_killpg.called
