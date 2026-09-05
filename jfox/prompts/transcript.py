"""transcript 读取与 context 选择：full / targeted / prompt_only 三种模式。

从 CC transcript JSONL 解析 user/assistant 消息，为目标 prompt 定位 occurrence，
按预算选择完整上下文或目标周围的有界上下文。不发送原始 hook metadata。
"""

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# 默认上下文预算（字符）
DEFAULT_MAX_TRANSCRIPT_CHARS = 4_000_000
DEFAULT_TURNS_BEFORE = 3
DEFAULT_TURNS_AFTER = 3


@dataclass
class TranscriptDocument:
    """解析后的 transcript：有序消息列表 + user 文本/索引。"""

    messages: List[Dict[str, Any]]  # [{"role": "user"/"assistant", "text": str}]
    user_texts: List[str]  # 按出现顺序的 user 消息文本
    user_indices: List[int]  # 与 user_texts 对应的全局消息序号（0-based）

    @property
    def total_messages(self) -> int:
        return len(self.messages)

    @property
    def user_count(self) -> int:
        return len(self.user_texts)


@dataclass
class ContextResult:
    """select_context 的返回：选定的上下文文本 + 模式 + occurrence 定位。"""

    mode: str  # "full" / "targeted" / "prompt_only"
    text: str
    found_occurrences: Dict[int, int] = field(default_factory=dict)
    # key = prompt_id, value = user occurrence 序号（1-based，与 transcript_user_index 一致）


def _iter_jsonl(path: Path):
    """逐行 yield 解析后的 dict；跳过空行/坏行/非 dict 行。"""
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    if isinstance(d, dict):
                        yield d
                except json.JSONDecodeError:
                    continue
    except FileNotFoundError:
        logger.warning("transcript 不存在: %s", path)
        return
    except (OSError, UnicodeDecodeError) as e:
        logger.warning("读 transcript 异常 %s: %s", path, e)
        return


def _block_to_text(block: Any) -> str:
    """content block → 可读文本。"""
    if isinstance(block, str):
        return block
    if isinstance(block, dict):
        btype = block.get("type")
        if btype == "text":
            return block.get("text", "")
        if btype == "thinking":
            return ""
        if btype == "tool_use":
            return f"[工具调用:{block.get('name', '?')}]"
        if btype == "tool_result":
            return "[工具结果]"
    return ""


def _msg_text(raw: Dict[str, Any]) -> str:
    """从 CC transcript 消息提取纯文本。"""
    content = raw.get("message", {}).get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(_block_to_text(b) for b in content if isinstance(b, dict))
    return ""


def read_transcript(path: Path) -> TranscriptDocument:
    """解析 transcript JSONL → TranscriptDocument。只保留 user/assistant 消息。"""
    path = Path(path)
    messages: List[Dict[str, Any]] = []
    user_texts: List[str] = []
    user_indices: List[int] = []

    for raw in _iter_jsonl(path):
        msg_type = raw.get("type")
        if msg_type not in ("user", "assistant"):
            continue
        text = _msg_text(raw)
        role = "user" if msg_type == "user" else "assistant"
        messages.append({"role": role, "text": text})
        if role == "user":
            user_texts.append(text)
            user_indices.append(len(messages) - 1)

    return TranscriptDocument(messages=messages, user_texts=user_texts, user_indices=user_indices)


def read_transcript_safe(path: Path, allowed_roots: List[str]) -> TranscriptDocument:
    """带根目录校验的读取：path 不在允许的根目录内 → 返回空文档。

    校验 resolve 后的路径必须位于某个 allowed root 之下（防 symlink 逃逸）。
    """
    path = Path(path)
    if not allowed_roots:
        return TranscriptDocument(messages=[], user_texts=[], user_indices=[])
    try:
        resolved = path.resolve()
        for root in allowed_roots:
            root_path = Path(root).expanduser().resolve()
            if resolved == root_path or root_path in resolved.parents:
                return read_transcript(path)
    except (OSError, RuntimeError):
        pass
    logger.warning("transcript path 不在允许根目录内，降级 prompt_only: %s", path)
    return TranscriptDocument(messages=[], user_texts=[], user_indices=[])


def _find_occurrence(
    doc: TranscriptDocument,
    prompt_text: str,
    transcript_user_index: Optional[int],
    used_occurrences: set,
) -> Optional[int]:
    """定位 prompt 在 user 消息中的 occurrence（1-based）。

    优先用 transcript_user_index；否则按文本匹配（精确子串→前缀），
    消耗已用 occurrence，不重复命中同一条。
    """
    if transcript_user_index is not None:
        idx = int(transcript_user_index)
        if 1 <= idx <= len(doc.user_texts):
            return idx
        return None

    prompt = (prompt_text or "").strip()
    if not prompt:
        return None

    # 两轮匹配：精确子串 → 前 40 字符前缀
    for match_fn in (
        lambda t: prompt in t,
        lambda t: t.startswith(prompt[:40]),
    ):
        for i, text in enumerate(doc.user_texts, start=1):
            if i in used_occurrences:
                continue
            if match_fn(text):
                return i
    return None


def _render_messages(messages: List[Dict[str, Any]]) -> str:
    """把消息列表转成规范上下文文本。"""
    parts = []
    for msg in messages:
        prefix = "[用户]" if msg["role"] == "user" else "[助手]"
        text = msg["text"].strip()
        if text:
            parts.append(f"{prefix} {text}")
    return "\n\n".join(parts)


def select_context(
    doc: TranscriptDocument,
    target_prompts: List[Dict[str, Any]],
    max_transcript_chars: int = DEFAULT_MAX_TRANSCRIPT_CHARS,
    turns_before: int = DEFAULT_TURNS_BEFORE,
    turns_after: int = DEFAULT_TURNS_AFTER,
) -> ContextResult:
    """为目标 prompt 选择上下文。

    - doc 为空 / 所有 target 都找不到 occurrence → prompt_only
    - 完整 session 在预算内 → full
    - 超预算 → targeted（所有目标周围 ±turns 的有界消息）
    """
    if doc.total_messages == 0:
        return ContextResult(
            mode="prompt_only",
            text="\n\n".join(f"[用户] {t.get('prompt', '')}" for t in target_prompts),
            found_occurrences={},
        )

    # 1) 定位所有 target 的 occurrence
    used: set = set()
    found: Dict[int, int] = {}
    any_found = False
    for target in target_prompts:
        pid = target.get("prompt_id")
        occ = _find_occurrence(
            doc,
            target.get("prompt", ""),
            target.get("transcript_user_index"),
            used,
        )
        if occ is not None:
            found[pid] = occ
            used.add(occ)
            any_found = True

    if not any_found:
        return ContextResult(
            mode="prompt_only",
            text="\n\n".join(f"[用户] {t.get('prompt', '')}" for t in target_prompts),
            found_occurrences={},
        )

    # 2) 完整 session 在预算内 → full
    full_text = _render_messages(doc.messages)
    if len(full_text) <= max_transcript_chars:
        return ContextResult(mode="full", text=full_text, found_occurrences=found)

    # 3) 超预算 → targeted：目标周围的有界消息
    # keep 的 user 范围：[pos - turns_before, pos + max(0, turns_after - 1)]
    # 每个 keep 的 user 后跟其 assistant 回复（到下一个 user 前）
    keep_indices: set = set()
    for occ in found.values():
        if 1 <= occ <= len(doc.user_indices):
            pos = occ - 1  # user 在 user_indices 中的 0-based 位置
            start_user_pos = max(0, pos - turns_before)
            # turns_after=1 → 只保留目标 user+回复；>1 额外扩展后续 user
            end_user_pos = min(len(doc.user_indices) - 1, pos + max(0, turns_after - 1))

            for up in range(start_user_pos, end_user_pos + 1):
                start_msg = doc.user_indices[up]
                # 每个 user 到下一个 user 前（含其 assistant 回复）
                if up + 1 < len(doc.user_indices):
                    end_msg = doc.user_indices[up + 1] - 1
                else:
                    end_msg = len(doc.messages) - 1
                for i in range(start_msg, end_msg + 1):
                    keep_indices.add(i)

    targeted_messages = [doc.messages[i] for i in sorted(keep_indices)]
    targeted_text = _render_messages(targeted_messages)

    return ContextResult(mode="targeted", text=targeted_text, found_occurrences=found)


__all__ = [
    "TranscriptDocument",
    "ContextResult",
    "read_transcript",
    "read_transcript_safe",
    "select_context",
]
