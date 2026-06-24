"""锚点查询：从 fragments.db 取高信号、未处理的锚点碎片。

锚点类型（配置项 anchor_types）：
- correction / decision：fragment_type 命中
- ask_user_question：PostToolUse 且 metadata.tool_name == 'AskUserQuestion'
"""

import json
import sqlite3
from pathlib import Path
from typing import Dict, List, Optional


def _anchor_where(anchor_types: List[str]) -> str:
    """构造 WHERE 子句中的锚点条件（不含 WHERE 关键字，空则返回空串）。"""
    clauses = []
    if "correction" in anchor_types:
        clauses.append("fragment_type = 'correction'")
    if "decision" in anchor_types:
        clauses.append("fragment_type = 'decision'")
    if "ask_user_question" in anchor_types:
        # AskUserQuestion 走 PostToolUse；用 metadata_json LIKE 粗筛，Python 里二次确认
        clauses.append("(source_event = 'PostToolUse' AND metadata_json LIKE '%AskUserQuestion%')")
    return "(" + " OR ".join(clauses) + ")" if clauses else ""


def find_anchors(
    fragments_db: Path,
    log,
    anchor_types: List[str],
    session_id: Optional[str] = None,
    limit: int = 100,
) -> List[Dict]:
    """返回未处理的高信号锚点 dict 列表。

    每条 dict 含 fragment_id / session_id / timestamp / content / transcript_path / metadata。
    """
    where = _anchor_where(anchor_types)
    if not where:
        return []
    sql = (
        f"SELECT fragment_id, session_id, fragment_type, timestamp, content, metadata_json "
        f"FROM session_fragments WHERE {where}"
    )
    params: List = []
    if session_id:
        sql += " AND session_id = ?"
        params.append(session_id)
    sql += " ORDER BY fragment_id LIMIT ?"
    params.append(limit * 3)  # 多取再在 Python 侧按精确条件过滤

    conn = sqlite3.connect(str(fragments_db))
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(sql, params).fetchall()
    finally:
        conn.close()

    unprocessed = set(log.filter_unprocessed([r["fragment_id"] for r in rows]))

    result: List[Dict] = []
    for r in rows:
        if r["fragment_id"] not in unprocessed:
            continue
        md = json.loads(r["metadata_json"] or "{}")
        # ask_user_question 精确二次确认（避免 LIKE 误命中正文）
        is_ask = md.get("tool_name") == "AskUserQuestion"
        if r["fragment_type"] not in ("correction", "decision") and not is_ask:
            continue
        result.append(
            {
                "fragment_id": r["fragment_id"],
                "session_id": r["session_id"],
                "timestamp": r["timestamp"],
                "content": r["content"],
                "transcript_path": md.get("transcript_path"),
                "metadata": md,
            }
        )
        if len(result) >= limit:
            break
    return result


__all__ = ["find_anchors"]
