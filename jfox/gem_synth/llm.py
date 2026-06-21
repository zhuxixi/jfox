"""独立 LLM 调用：claude -p 合成破损宝石。不耦合 auto_summary。

参考 auto_summary/runner.py _invoke_claude 的 subprocess + env 隔离模式，但独立实现，
避免 auto_summary 的演化影响 L3 合成链路。
"""

import json
import logging
import os
import shutil
import subprocess
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
    """解析 claude 二进制路径：优先 cfg.claude_binary，否则从 PATH 找。"""
    if cfg.claude_binary:
        return cfg.claude_binary
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


def _invoke_claude(prompt: str, cfg: GemSynthesisConfig) -> str:
    """调用 claude -p，返回 stdout。

    env 隔离：清除 JFOX_KB / JFOX_DAEMON_PROCESS 等会干扰子进程的变量，
    避免 claude 子进程意外连到 jfox daemon 或写到错误 KB。
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
    ]
    env = os.environ.copy()
    for noisy in ("JFOX_KB", "JFOX_DAEMON_PROCESS"):
        env.pop(noisy, None)
    proc = subprocess.run(
        cmd,
        input=prompt,
        capture_output=True,
        text=True,
        timeout=cfg.claude_timeout_seconds,
        env=env,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"claude 退出码 {proc.returncode}: {proc.stderr[:300]}")
    return proc.stdout


def synthesize_with_llm(
    turn_context: str, grounding: List[Dict[str, Any]], cfg: GemSynthesisConfig
) -> Optional[Dict[str, Any]]:
    """返回合成 dict（title/content/confidence/knowledge_type/grounded_by），失败返回 None。

    claude --output-format json 返回 {result: "..."} 包装，result 内才是模型 JSON 输出，
    故需两层解析。缺 title 或异常一律返回 None（调用方据此跳过/重试）。
    """
    try:
        prompt = _build_prompt(turn_context, grounding)
        raw = _invoke_claude(prompt, cfg)
        wrapper = json.loads(raw)
        inner = wrapper.get("result", raw) if isinstance(wrapper, dict) else raw
        parsed = json.loads(inner) if isinstance(inner, str) else inner
        if not isinstance(parsed, dict) or "title" not in parsed:
            logger.warning("LLM 输出缺 title: %r", parsed)
            return None
        return parsed
    except Exception as e:
        logger.exception("LLM 合成失败: %s", e)
        return None


__all__ = ["synthesize_with_llm", "_build_prompt"]
