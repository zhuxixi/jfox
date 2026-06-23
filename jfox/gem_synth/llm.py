"""独立 LLM 调用：claude -p 合成破损宝石。不耦合 auto_summary。

参考 auto_summary/runner.py _invoke_claude 的 subprocess + env 隔离模式，但独立实现，
避免 auto_summary 的演化影响 L3 合成链路。
"""

import json
import logging
import os
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..global_config import GemSynthesisConfig

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """你是知识合成器。给定一段对话上下文和若干已有永久笔记（事实基准），
从中合成出一条可复用的知识宝石（破损级）。严格输出 JSON：
{
  "title": "简洁标题",
  "content": "Markdown 正文，结构化知识",
  "confidence": 0.0-1.0 的浮点（与基准一致性、信号强度、上下文完整度），
  "knowledge_type": "factual|procedural|preference|constraint",
  "grounded_by": ["引用的永久笔记标题列表"]
}
若上下文不足以合成有效知识，confidence 给低分（<0.3）并简述原因。不要编造基准里没有的事实。"""


def _resolve_claude_binary(cfg: GemSynthesisConfig) -> str:
    """解析 claude 二进制路径：优先 cfg.claude_binary，否则从 PATH 找。

    返回 normalize 后的绝对路径（expanduser + resolve），避免相对路径/符号链接
    导致的解析歧义。
    """
    if cfg.claude_binary:
        return str(Path(cfg.claude_binary).expanduser().resolve())
    found = shutil.which("claude")
    if not found:
        raise RuntimeError("找不到 claude 二进制（PATH 无 claude，且 cfg.claude_binary 未设）")
    return found


def _build_prompt(turn_context: str, grounding: List[Dict[str, Any]]) -> str:
    """组装用户 prompt：对话上下文 + 永久笔记基准。"""
    grounding_md = (
        "\n".join(f"- ### {g['title']}\n{g['content']}" for g in grounding)
        if grounding
        else "（无相关永久笔记）"
    )
    return f"""## 对话上下文（待合成的锚点一轮）
{turn_context}

## 已有永久笔记（事实基准，防幻觉）
{grounding_md}

请合成一条知识宝石。只输出 JSON。"""


def _kill_pgroup(pgid: int) -> None:
    """SIGTERM 进程组，短暂等待后 SIGKILL 兜底。ProcessLookupError 忽略。

    daemon 跑在 Linux 上；Windows 下 start_new_session/killpg/signal 语义不同，
    Windows 兜底未实现（项目目前只跑 Linux daemon）。
    """
    try:
        os.killpg(pgid, signal.SIGTERM)
    except ProcessLookupError:
        return
    time.sleep(0.3)
    try:
        os.killpg(pgid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def _invoke_claude(
    prompt: str,
    cfg: GemSynthesisConfig,
    stop_event: Optional[threading.Event] = None,
) -> str:
    """调用 claude -p，返回 stdout。支持 stop_event 中断 + 超时 kill 整个进程组。

    用 Popen + 周期 poll，使 daemon shutdown / stop_event 能在 claude 运行中中断
    （subprocess.run 无法中断，task.cancel 对已在 executor 中的 run 无效，会阻塞到
    timeout，默认 180s）。start_new_session=True 让 claude 及其 node helper 成独立
    进程组，killpg 一并清理，避免孤儿（subprocess.run 的 timeout 只杀直接子进程）。

    env 隔离：清除 JFOX_KB / JFOX_DAEMON_PROCESS 等会干扰子进程的变量，避免 claude
    子进程意外连到 jfox daemon 或写到错误 KB（沿用既有安全修复）。
    """
    binary = _resolve_claude_binary(cfg)
    cmd = [
        binary,
        "-p",
        "--output-format",
        "json",
        "--append-system-prompt",
        SYSTEM_PROMPT,
        "--permission-mode",
        "bypassPermissions",
        # 合成只需文本生成，禁用所有工具（防注入执行；synthesis 输入含不可信 transcript/笔记）
        "--allowed-tools",
        "",
    ]
    env = os.environ.copy()
    for noisy in ("JFOX_KB", "JFOX_DAEMON_PROCESS"):
        env.pop(noisy, None)

    timeout = max(30, cfg.claude_timeout_seconds)
    proc = subprocess.Popen(
        cmd,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
        start_new_session=True,
    )
    pgid = os.getpgid(proc.pid)
    deadline = time.monotonic() + timeout
    try:
        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
        except (BrokenPipeError, OSError) as e:
            # 进程可能已提前退出，继续走 poll 让 returncode 处理
            logger.debug("子进程 stdin 写入失败（进程可能已退出）: %s", e)
        while True:
            rc = proc.poll()
            if rc is not None:
                if rc != 0:
                    err = (proc.stderr.read() or "")[:300]
                    raise RuntimeError(f"claude 退出码 {rc}: {err}")
                return proc.stdout.read()
            if stop_event is not None and stop_event.is_set():
                _kill_pgroup(pgid)
                raise RuntimeError("claude 调用被中断（stop_event）")
            if time.monotonic() >= deadline:
                _kill_pgroup(pgid)
                raise TimeoutError(f"claude 超时（{timeout}s）")
            time.sleep(0.5)
    except Exception:
        # 任何异常路径（中断/超时/非零退出码）兜底杀进程组，避免孤儿
        _kill_pgroup(pgid)
        raise


def synthesize_with_llm(
    turn_context: str,
    grounding: List[Dict[str, Any]],
    cfg: GemSynthesisConfig,
    stop_event: Optional[threading.Event] = None,
) -> Optional[Dict[str, Any]]:
    """返回合成 dict（title/content/confidence/knowledge_type/grounded_by），失败返回 None。

    claude --output-format json 返回 {result: "..."} 包装，result 内才是模型 JSON 输出，
    故需两层解析。缺 title 或异常一律返回 None（调用方据此跳过/重试）。

    stop_event 透传给 _invoke_claude，使 daemon shutdown / 任务中断能在 claude 调用
    进行中触发（而非等满 timeout）。
    """
    try:
        prompt = _build_prompt(turn_context, grounding)
        raw = _invoke_claude(prompt, cfg, stop_event)
        wrapper = json.loads(raw)
        inner = wrapper.get("result", raw) if isinstance(wrapper, dict) else raw
        parsed = json.loads(inner) if isinstance(inner, str) else inner
        if not isinstance(parsed, dict) or "title" not in parsed:
            logger.warning("LLM 输出缺 title: %r", parsed)
            logger.debug("LLM raw output: %r", raw)
            return None
        return parsed
    except Exception as e:
        logger.exception("LLM 合成失败: %s", e)
        logger.debug("LLM raw output on exception: %r", locals().get("raw"))
        return None


__all__ = ["synthesize_with_llm", "_build_prompt"]
