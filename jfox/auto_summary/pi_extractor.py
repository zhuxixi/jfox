"""
pi coding agent session 解析：首行 header + v3 树结构活跃分支 + message 抽取。

关键事实（本机实测 + pi docs/session-format.md）：
- 首行 {"type":"session","id":...} 是唯一可靠的 id 来源，文件名不可用（view_<hash>.jsonl）
- message 的角色与内容嵌套在 entry["message"] 下
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Iterable, Optional, Tuple

from .extractor import DEFAULT_MAX_DIALOG_CHARS, ExtractedDialog, _truncate

logger = logging.getLogger(__name__)


def parse_pi_header(line: str) -> Optional[dict]:
    """解析首行；必须是 type=session 且 id 为非空字符串。"""
    try:
        rec = json.loads(line)
    except json.JSONDecodeError:
        return None
    if not isinstance(rec, dict) or rec.get("type") != "session":
        return None
    sid = rec.get("id")
    if not isinstance(sid, str) or not sid:
        return None
    return rec


def active_branch(entries: list) -> list:
    """从最后一个条目沿 parentId 回溯；断链或成环时回退为文件顺序。"""
    by_id = {e["id"]: e for e in entries if isinstance(e.get("id"), str)}
    if not by_id:
        return entries
    leaf = entries[-1]
    if not isinstance(leaf.get("id"), str):
        return entries
    chain, seen, cur = [], set(), leaf
    while isinstance(cur, dict) and isinstance(cur.get("id"), str):
        cid = cur["id"]
        if cid in seen:
            return entries
        seen.add(cid)
        chain.append(cur)
        parent = cur.get("parentId")
        if parent is None:
            break
        if parent not in by_id:
            return entries
        cur = by_id[parent]
    chain.reverse()
    return chain


def _text_from_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts = []
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    parts.append(text)
        return "\n".join(parts).strip()
    return ""


def dialog_from_branch(
    branch: Iterable[dict], max_chars: int = DEFAULT_MAX_DIALOG_CHARS
) -> Tuple[str, int, int, Optional[str], bool]:
    """返回 (dialog_text, user_turns, assistant_turns, ended_at, truncated)。"""
    turns: list = []
    user_n = assistant_n = 0
    ended_at: Optional[str] = None
    for entry in branch:
        if not isinstance(entry, dict) or entry.get("type") != "message":
            continue
        ts = entry.get("timestamp")
        if isinstance(ts, str):
            ended_at = ts
        msg = entry.get("message")
        if not isinstance(msg, dict):
            continue
        role = msg.get("role")
        if role not in ("user", "assistant"):
            continue
        text = _text_from_content(msg.get("content"))
        if not text:
            continue
        if role == "user":
            user_n += 1
        else:
            assistant_n += 1
        turns.append(f"## {role}\n\n{text}")
    text, truncated = _truncate("\n\n---\n\n".join(turns), max_chars)
    return text, user_n, assistant_n, ended_at, truncated


def model_from_branch(branch: Iterable[dict]) -> Optional[str]:
    """多模型会话取最后一次 model_change。"""
    model: Optional[str] = None
    for entry in branch:
        if not isinstance(entry, dict) or entry.get("type") != "model_change":
            continue
        provider, model_id = entry.get("provider"), entry.get("modelId")
        if isinstance(provider, str) and isinstance(model_id, str) and provider and model_id:
            model = f"{provider}/{model_id}"
    return model


def extract_pi_dialog(path: Path, max_dialog_chars: int = DEFAULT_MAX_DIALOG_CHARS) -> ExtractedDialog:
    result = ExtractedDialog()
    entries: list = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line_no, raw in enumerate(f, start=1):
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    rec = json.loads(raw)
                except json.JSONDecodeError as e:
                    logger.debug("pi session 第 %d 行解析失败: %s", line_no, e)
                    continue
                if isinstance(rec, dict):
                    entries.append(rec)
    except OSError as e:
        logger.warning("读取 pi session 失败 %s: %s", path, e)
        return result

    if not entries:
        return result
    header = entries[0]
    cwd = header.get("cwd")
    if isinstance(cwd, str) and cwd:
        result.cwd = cwd
        result.project_dir_name = Path(cwd).name
    ts = header.get("timestamp")
    if isinstance(ts, str):
        result.started_at = ts

    branch = active_branch(entries)
    (
        result.dialog_text,
        result.user_turn_count,
        result.assistant_turn_count,
        ended_at,
        result.truncated,
    ) = dialog_from_branch(branch, max_dialog_chars)
    if ended_at:
        result.ended_at = ended_at
    # 用全部条目而非活跃分支：model_change 可能没有 id/parentId（真实文件里部分条目如此），
    # 会话级模型以文件顺序的最后一次 model_change 为准。
    result.agent_model = model_from_branch(entries)
    if result.project_dir_name is None:
        result.project_dir_name = path.parent.name
    return result
