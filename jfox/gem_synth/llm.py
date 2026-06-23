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


def _kill_proc_group(proc: subprocess.Popen, pgid) -> None:
    """SIGTERM 进程组，短暂等待后 SIGKILL 兜底。ProcessLookupError 忽略。

    pgid 为 None（进程已退出/取不到）时退化为 proc.kill()。单一清理点，
    所有异常路径都走这里，避免重复 kill。

    注：killpg / SIGTERM / SIGKILL 为 POSIX 语义；Windows 下 start_new_session/
    killpg 不可用，需用 proc.kill 兜底（项目目前只跑 Linux daemon）。
    """
    killed = False
    if pgid is not None:
        try:
            os.killpg(pgid, signal.SIGTERM)
            killed = True
        except ProcessLookupError:
            pass
    if not killed:
        try:
            proc.kill()
        except Exception:
            pass
    time.sleep(0.3)
    if pgid is not None:
        try:
            os.killpg(pgid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    else:
        try:
            proc.kill()
        except Exception:
            pass


def _invoke_claude(
    prompt: str,
    cfg: GemSynthesisConfig,
    stop_event: Optional[threading.Event] = None,
) -> str:
    """调用 claude -p，返回 stdout。支持 stop_event 中断 + 超时；后台排空 stderr 防死锁。

    stderr 用后台线程持续读取，避免 claude 写满 stderr 管道缓冲（~64KB）后阻塞死锁
    （旧实现仅在 rc!=0 时读 stderr，正常路径 claude 写满缓冲会导致 poll() 永不返回，
    退化成 180s 超时——回归 subprocess.run 的 communicate() 缺陷）。

    start_new_session=True 使 claude 及 node helper 成独立进程组，killpg 一并清理，
    避免孤儿。getpgid 在 try 内执行（进程若已退出则 pgid=None，后续走 proc.kill 兜底）。

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
    # 后台线程持续排空 stderr，防止管道缓冲写满导致 claude 阻塞死锁
    stderr_chunks: list = []

    def _drain_stderr() -> None:
        try:
            for chunk in iter(lambda: proc.stderr.read(4096), ""):
                stderr_chunks.append(chunk)
        except Exception:
            pass

    drainer = threading.Thread(target=_drain_stderr, daemon=True)
    drainer.start()

    pgid = None
    deadline = time.monotonic() + timeout
    try:
        # getpgid 放在 try 内：进程若已退出会抛 ProcessLookupError，此处兜底为 None
        try:
            pgid = os.getpgid(proc.pid)
        except ProcessLookupError:
            pgid = None  # 进程已退出，后续 kill 走 proc.kill() 兜底
        try:
            proc.stdin.write(prompt)
            proc.stdin.close()
        except (BrokenPipeError, OSError) as e:
            # 进程可能已提前退出，继续走 poll 让 returncode 处理
            logger.debug("子进程 stdin 写入失败（进程可能已退出）: %s", e)
        while True:
            rc = proc.poll()
            if rc is not None:
                drainer.join(timeout=2)
                if rc != 0:
                    err = "".join(stderr_chunks)[:300]
                    raise RuntimeError(f"claude 退出码 {rc}: {err}")
                return proc.stdout.read()
            if stop_event is not None and stop_event.is_set():
                raise RuntimeError("claude 调用被中断（stop_event）")
            if time.monotonic() >= deadline:
                raise TimeoutError(f"claude 超时（{timeout}s）")
            time.sleep(0.5)
    except (RuntimeError, TimeoutError):
        # 单一 kill 点：中断/超时路径统一走这里（非零退出码的 RuntimeError 也命中）
        _kill_proc_group(proc, pgid)
        raise
    finally:
        # reap 僵尸 + 关闭所有管道，避免 FD 累积（旧实现未关 stdin/stdout/stderr）
        try:
            proc.wait(timeout=5)
        except Exception:
            pass
        for pipe in (proc.stdin, proc.stdout, proc.stderr):
            try:
                pipe.close()
            except Exception:
                pass


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
