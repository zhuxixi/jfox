"""
从 Claude Code session jsonl 提取出可读对话文本，剔除工具调用、attachment、
system-reminder 等噪音。供 claude -p 总结时阅读。
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

# 单次喂给 claude -p 的最大字符数。超出则保留首尾各一半（开头有上下文，结尾有结论）
DEFAULT_MAX_DIALOG_CHARS = 30000


@dataclass
class ExtractedDialog:
    """extract_dialog 的返回结构"""

    cwd: Optional[str] = None
    git_branch: Optional[str] = None
    started_at: Optional[str] = None
    ended_at: Optional[str] = None
    project_dir_name: Optional[str] = None
    user_turn_count: int = 0
    assistant_turn_count: int = 0
    truncated: bool = False
    dialog_text: str = ""


def _is_system_reminder_text(text: str) -> bool:
    """识别整段 system-reminder（开头/结尾标签都在）"""
    s = text.strip()
    return s.startswith("<system-reminder>") and s.endswith("</system-reminder>")


def _coerce_text(content: Any) -> str:
    """把 Claude Code 的多形态 content 字段拍平成纯文本。

    - str → 直接返回（system-reminder 除外）
    - list → 拼接其中所有 type=text 的 text；逐项剔除 system-reminder；
             丢弃 tool_use/tool_result/image
    - dict → 取 text 字段或递归
    - 其他 → 空串
    """
    if isinstance(content, str):
        return "" if _is_system_reminder_text(content) else content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if not isinstance(item, dict):
                continue
            itype = item.get("type")
            if itype == "text":
                t = item.get("text") or ""
                if isinstance(t, str) and t.strip() and not _is_system_reminder_text(t):
                    parts.append(t)
            # tool_use / tool_result / image / thinking 等一律忽略
        return "\n".join(parts).strip()
    if isinstance(content, dict):
        if isinstance(content.get("text"), str):
            t = content["text"]
            return "" if _is_system_reminder_text(t) else t
        return _coerce_text(content.get("content"))
    return ""


def _extract_role_and_text(record: dict[str, Any]) -> Optional[tuple[str, str]]:
    """从一行 jsonl 记录里抽出 (role, text)；不感兴趣的记录返回 None"""
    rec_type = record.get("type")

    # Claude Code 的两种主要消息形态：
    # 1) {"type": "user"/"assistant", "message": {"role": ..., "content": ...}, ...}
    # 2) {"type": "user"/"assistant", "content": ..., "role": ...}
    if rec_type in ("user", "assistant"):
        message = record.get("message") if isinstance(record.get("message"), dict) else None
        if message is not None:
            text = _coerce_text(message.get("content"))
            role = message.get("role") or rec_type
        else:
            text = _coerce_text(record.get("content"))
            role = record.get("role") or rec_type
        text = text.strip()
        if not text:
            return None
        # _coerce_text 已在 item 级剔除 system-reminder；这里再做一次最终兜底
        if _is_system_reminder_text(text):
            return None
        return role, text

    return None


def _truncate(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    half = max_chars // 2
    head = text[:half]
    tail = text[-half:]
    sep = "\n\n... [省略中间内容以控制长度] ...\n\n"
    return head + sep + tail, True


def extract_dialog(
    jsonl_path: Path,
    max_dialog_chars: int = DEFAULT_MAX_DIALOG_CHARS,
) -> ExtractedDialog:
    """
    读取 jsonl，返回 ExtractedDialog。

    只保留 user/assistant 的纯文本，剔除 tool_use / tool_result / attachment /
    system-reminder。元数据从首条带 cwd/gitBranch 的记录里取。
    """
    result = ExtractedDialog()
    turns: list[str] = []

    try:
        with open(jsonl_path, "r", encoding="utf-8", errors="replace") as f:
            for line_no, raw in enumerate(f, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError as e:
                    logger.debug("第 %d 行 JSON 解析失败: %s", line_no, e)
                    continue
                if not isinstance(rec, dict):
                    continue

                # 元数据收集（首次出现时记录）
                if result.cwd is None and isinstance(rec.get("cwd"), str):
                    result.cwd = rec["cwd"]
                if result.git_branch is None and isinstance(rec.get("gitBranch"), str):
                    result.git_branch = rec["gitBranch"]
                ts = rec.get("timestamp")
                if isinstance(ts, str):
                    if result.started_at is None:
                        result.started_at = ts
                    result.ended_at = ts

                extracted = _extract_role_and_text(rec)
                if extracted is None:
                    continue
                role, text = extracted
                if role == "user":
                    result.user_turn_count += 1
                elif role == "assistant":
                    result.assistant_turn_count += 1
                turns.append(f"## {role}\n\n{text}")
    except OSError as e:
        logger.warning("读取 %s 失败: %s", jsonl_path, e)
        return result

    full = "\n\n---\n\n".join(turns)
    truncated_text, truncated = _truncate(full, max_dialog_chars)
    result.dialog_text = truncated_text
    result.truncated = truncated
    result.project_dir_name = jsonl_path.parent.name
    return result
