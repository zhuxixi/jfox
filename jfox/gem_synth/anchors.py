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
        # AskUserQuestion 走 PostToolUse；用 json_extract 精确匹配 tool_name
        # （SQL 层精确 → count_anchors 与 find_anchors 过滤一致；find_anchors 的
        # Python 二次确认保留为无害冗余检查）
        clauses.append(
            "(source_event = 'PostToolUse' AND json_extract(metadata_json, '$.tool_name') = 'AskUserQuestion')"
        )
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


def count_anchors(fragments_db: Path, anchor_types: List[str]) -> int:
    """高信号锚点总数（不区分是否已处理）—— status 命令算 pending 用。

    复用 _anchor_where 构造 WHERE 子句；空 anchor_types 直接返回 0，
    避免空 WHERE 拉全表（find_anchors 同样的早退约定）。
    """
    where = _anchor_where(anchor_types)
    if not where:
        return 0
    conn = sqlite3.connect(str(fragments_db))
    try:
        row = conn.execute(f"SELECT COUNT(*) FROM session_fragments WHERE {where}").fetchone()
    finally:
        conn.close()
    return int(row[0]) if row else 0


__all__ = ["find_anchors", "count_anchors"]
