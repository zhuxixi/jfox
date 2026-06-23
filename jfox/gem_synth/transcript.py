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
    except (OSError, UnicodeDecodeError) as e:
        # 文件读取层预期失败（权限/编码等），用 warning 而非 exception 标记
        logger.warning("读 transcript 异常 %s: %s", transcript_path, e)
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

    匹配策略：两轮——先尝试精确子串匹配（anchor in full），命中即止；找不到再退而
    求其次用前缀匹配。单轮 + or 短路会因前缀相似而误取早先消息，两轮可降低误匹配。
    """
    transcript_path = Path(transcript_path)
    if not transcript_path.exists():
        return ""
    anchor = (anchor_user_text or "").strip()
    if not anchor:
        return ""

    msgs = list(_iter_messages(transcript_path))
    user_indices = [i for i, m in enumerate(msgs) if m.get("type") == "user"]

    def _full_text(i):
        return _user_text(msgs[i])

    # 优先精确子串匹配（锚点文本完整出现在某条 user 消息里）
    anchor_idx = next((i for i in user_indices if anchor in _full_text(i)), None)
    # 退而求其次：前缀匹配（锚点被截断时）
    if anchor_idx is None:
        prefix = anchor[:40]
        anchor_idx = next((i for i in user_indices if _full_text(i).startswith(prefix)), None)
    if anchor_idx is None:
        return ""

    parts: List[str] = [f"[用户] {_user_text(msgs[anchor_idx])}"]
    for m in msgs[anchor_idx + 1 :]:
        if m.get("type") == "user":
            break
        parts.append(f"[助手] {_assistant_text(m)}")
    return "\n\n".join(parts).strip()


__all__ = ["extract_turn_around", "_iter_messages"]
