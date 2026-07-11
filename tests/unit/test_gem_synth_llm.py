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


def test_invoke_claude_uses_isolated_cwd(monkeypatch, tmp_path):
    """_invoke_claude 调 Popen 必须传 cwd=~/.jfox-gem-synth-runs 隔离目录，使 session
    transcript 落到被 auto-summary blocklist 排除的 project 目录（#297 同类反馈循环的
    session 选择链路补漏；fragment 链路已由 #297 修）。"""
    import io as _io

    from jfox.gem_synth import llm as llm_mod

    # 隔离 _gem_synth_runs_dir 的目录创建，不污染真实 HOME
    monkeypatch.setenv("HOME", str(tmp_path))

    captured = {}

    class FakeProc:
        def __init__(self):
            self.stdin = MagicMock()
            self.stdout = _io.StringIO('{"result":"ok"}')
            self.stderr = _io.StringIO("")
            self.pid = 12345

        def poll(self):
            return 0

    def fake_popen(*args, **kwargs):
        captured.update(kwargs)
        return FakeProc()

    monkeypatch.setattr(llm_mod.subprocess, "Popen", fake_popen)
    monkeypatch.setattr(llm_mod.os, "getpgid", lambda pid: 12345)

    cfg = MagicMock()
    cfg.claude_timeout_seconds = 30
    result = llm_mod._invoke_claude("prompt", cfg)
    assert result == '{"result":"ok"}'
    assert captured.get("cwd", "").endswith(
        ".jfox-gem-synth-runs"
    ), "Popen 必须用 ~/.jfox-gem-synth-runs 隔离 cwd"


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


def test_synthesize_strips_fence_with_preamble():
    """模型在围栏前加解释文本时（如"这是 JSON:"），也要正确提取围栏内 JSON。"""
    inner_json = json.dumps({"title": "带前导文本", "content": "x", "confidence": 0.7})
    fenced = f"这是合成的 JSON：\n```json\n{inner_json}\n```\n（如上）"
    fake_output = json.dumps({"type": "result", "result": fenced})
    with patch("jfox.gem_synth.llm._invoke_claude", return_value=fake_output):
        result = synthesize_with_llm(turn_context="x", grounding=[], cfg=MagicMock())
    assert result is not None
    assert result["title"] == "带前导文本"


def test_synthesize_prefers_json_fenced_block_over_earlier_code_fence():
    """模型在 JSON 围栏前还输出别的代码围栏时，应优先取 ```json 块（不误取前面的）。"""
    inner_json = json.dumps({"title": "正确的 JSON", "content": "x", "confidence": 0.6})
    fenced = f"```python\nprint('hi')\n```\n```json\n{inner_json}\n```"
    fake_output = json.dumps({"type": "result", "result": fenced})
    with patch("jfox.gem_synth.llm._invoke_claude", return_value=fake_output):
        result = synthesize_with_llm(turn_context="x", grounding=[], cfg=MagicMock())
    assert result is not None
    assert result["title"] == "正确的 JSON"


def test_synthesize_preserves_clean_json_with_code_fence_in_content():
    """模型返回裸 JSON（无外层围栏），但其 content 字段含 ``` 代码示例时，
    不能误把内部代码块当外层围栏提取（会截断 JSON 致 json.loads 失败）。

    回归 kimi R3 issue-4：regex 全文搜索会把 content 内的 ```python...``` 误当外层围栏。
    修法：首字符 { 的裸 JSON 原样返回，绝不 regex。
    """
    content_with_code = "示例：\n```python\nprint('hi')\n```\n如上"
    inner_json = json.dumps(
        {
            "title": "含代码的知识",
            "content": content_with_code,
            "confidence": 0.8,
            "knowledge_type": "procedural",
            "grounded_by": [],
        }
    )
    # 裸 JSON（无外层围栏），envelope.result 直接是它
    fake_output = json.dumps({"type": "result", "result": inner_json})
    with patch("jfox.gem_synth.llm._invoke_claude", return_value=fake_output):
        result = synthesize_with_llm(turn_context="x", grounding=[], cfg=MagicMock())
    assert result is not None
    assert result["title"] == "含代码的知识"
    assert "print('hi')" in result["content"]


def test_synthesize_fenced_json_with_code_fence_in_content():
    """模型把 JSON 包在 ```json 围栏里，且 content 字段内又含 ```python 代码示例时，
    不能把内部代码块当外层围栏终点、截断 JSON（kimi R4 issue-5）。

    这是代码宝石的高频场景（content 常含代码示例）。正则 fence-strip 在此必崩；
    解析式（raw_decode）尊重字符串字面量，content 内的 ``` 不干扰。
    """
    content_with_code = "示例：\n```python\nprint('hi')\n```\n如上"
    inner_json = json.dumps(
        {
            "title": "含代码的宝石",
            "content": content_with_code,
            "confidence": 0.8,
            "knowledge_type": "procedural",
            "grounded_by": [],
        }
    )
    # 外层 ```json 围栏包裹，content 内又嵌 ```python
    fenced = f"```json\n{inner_json}\n```"
    fake_output = json.dumps({"type": "result", "result": fenced})
    with patch("jfox.gem_synth.llm._invoke_claude", return_value=fake_output):
        result = synthesize_with_llm(turn_context="x", grounding=[], cfg=MagicMock())
    assert result is not None
    assert result["title"] == "含代码的宝石"
    assert "print('hi')" in result["content"]


def test_synthesize_picks_largest_json_object_over_earlier_brace_code():
    """模型在目标 JSON 前还输出含 { 的代码块（如 python 字典示例）时，
    应取跨度最大的 JSON 对象（gem），不误取前面的小 {...}（kimi R5 issue-6）。

    单 { 版本会取到前面的小字典就停；扫描所有 { 取最大者才对。
    """
    inner_json = json.dumps(
        {
            "title": "目标宝石",
            "content": "x",
            "confidence": 0.7,
            "knowledge_type": "procedural",
            "grounded_by": [],
        }
    )
    # 前面有个含 { 的 python 字典示例（恰好是合法 JSON 语法的小对象），后面才是 gem
    fenced = f'```python\nd = {{"a": 1, "b": 2}}\n```\n```json\n{inner_json}\n```'
    fake_output = json.dumps({"type": "result", "result": fenced})
    with patch("jfox.gem_synth.llm._invoke_claude", return_value=fake_output):
        result = synthesize_with_llm(turn_context="x", grounding=[], cfg=MagicMock())
    assert result is not None
    assert result["title"] == "目标宝石"


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
