"""读 CC transcript.jsonl，提取锚点那一"一轮"的完整上下文。

一轮 = 锚点 user 消息 + 其后的 assistant 回复（thinking/text/tool_use），
到下一条 user 消息为止。
"""

import json
import logging
from pathlib import Path
from typing import Iterator, List

logger = logging.getLogger(__name__)


def _iter_messages(transcript_path: Path) -> Iterator[dict]:
    """逐行 yield user/assistant 消息（跳过 ai-title/agent-name 等元数据行）。"""
    try:
        with open(transcript_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get("type") in ("user", "assistant"):
                    yield d
    except FileNotFoundError:
        logger.warning("transcript 不存在: %s", transcript_path)
        return
    except Exception as e:
        logger.exception("读 transcript 异常 %s: %s", transcript_path, e)
        return


def _block_to_text(block: dict) -> str:
    """把 assistant content block 转成可读文本。"""
    btype = block.get("type")
    if btype == "text":
        return block.get("text", "")
    if btype == "thinking":
        return f"[思考] {block.get('thinking', '')}"
    if btype == "tool_use":
        return (
            f"[工具调用: {block.get('name')}] "
            f"{json.dumps(block.get('input', {}), ensure_ascii=False)[:300]}"
        )
    if btype == "tool_result":
        c = block.get("content")
        if isinstance(c, list):
            c = " ".join(b.get("text", "") for b in c if isinstance(b, dict))
        return f"[工具结果] {str(c)[:300]}"
    return ""


def _user_text(msg: dict) -> str:
    content = msg.get("message", {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(_block_to_text(b) for b in content if isinstance(b, dict))
    return ""


def _assistant_text(msg: dict) -> str:
    content = msg.get("message", {}).get("content")
    if isinstance(content, list):
        return "\n".join(_block_to_text(b) for b in content if isinstance(b, dict))
    return str(content or "")


def extract_turn_around(transcript_path: Path, anchor_user_text: str) -> str:
    """返回锚点那一轮文本：锚点 user 消息 + 后续 assistant 回复（到下一条 user）。

    锚点 content 可能被碎片截断过，故用子串匹配（transcript 完整文本包含锚点文本，
    或 transcript 文本以锚点文本前 40 字符开头）。
    """
    transcript_path = Path(transcript_path)
    if not transcript_path.exists():
        return ""
    anchor = (anchor_user_text or "").strip()
    if not anchor:
        return ""

    msgs = list(_iter_messages(transcript_path))
    anchor_idx = None
    for i, m in enumerate(msgs):
        if m.get("type") != "user":
            continue
        full = _user_text(m)
        if anchor in full or full.startswith(anchor[:40]):
            anchor_idx = i
            break
    if anchor_idx is None:
        return ""

    parts: List[str] = [f"[用户] {_user_text(msgs[anchor_idx])}"]
    for m in msgs[anchor_idx + 1 :]:
        if m.get("type") == "user":
            break
        parts.append(f"[助手] {_assistant_text(m)}")
    return "\n\n".join(parts).strip()


__all__ = ["extract_turn_around", "_iter_messages"]
