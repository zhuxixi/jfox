"""碎片存储层：SQLite（WAL 模式，daemon 单一写者，CLI 多读者并发安全）。

落盘默认 ~/.zettelkasten/fragments.db；可用 JFOX_FRAGMENTS_DB 环境变量覆盖（测试/自定义用）。
"""

import json
import os
import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

_SCHEMA = """
CREATE TABLE IF NOT EXISTS session_fragments (
    fragment_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    fragment_type   TEXT NOT NULL,
    source_event    TEXT NOT NULL,
    timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    content         TEXT,
    metadata_json   TEXT
);
CREATE INDEX IF NOT EXISTS idx_frag_session ON session_fragments(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_frag_type    ON session_fragments(fragment_type, timestamp);
"""


def default_db_path() -> Path:
    """默认碎片库路径，可被 JFOX_FRAGMENTS_DB 覆盖。"""
    env = os.environ.get("JFOX_FRAGMENTS_DB")
    if env:
        return Path(env).expanduser()
    return Path.home() / ".zettelkasten" / "fragments.db"


class FragmentStore:
    """SQLite 碎片存储。daemon 持有一个常驻实例（热连接）；测试传入临时路径。"""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path: Path = Path(db_path) if db_path is not None else default_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        # 同一进程内多线程读写的锁（sqlite3 连接默认 check_same_thread=True）
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def insert(
        self,
        session_id: str,
        fragment_type: str,
        source_event: str,
        content: Optional[str],
        metadata: Optional[Dict[str, Any]] = None,
    ) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO session_fragments "
                "(session_id, fragment_type, source_event, content, metadata_json) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    session_id,
                    fragment_type,
                    source_event,
                    content,
                    json.dumps(metadata, ensure_ascii=False) if metadata is not None else None,
                ),
            )
            self._conn.commit()
            return int(cur.lastrowid)

    def get(self, fragment_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM session_fragments WHERE fragment_id = ?", (fragment_id,)
            ).fetchone()
        return dict(row) if row else None

    def query(
        self,
        session_id: Optional[str] = None,
        fragment_type: Optional[str] = None,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        sql = "SELECT * FROM session_fragments WHERE 1=1"
        params: List[Any] = []
        if session_id is not None:
            sql += " AND session_id = ?"
            params.append(session_id)
        if fragment_type is not None:
            sql += " AND fragment_type = ?"
            params.append(fragment_type)
        sql += " ORDER BY timestamp DESC, fragment_id DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def counts_by_type(self, session_id: str) -> Dict[str, int]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT fragment_type, COUNT(*) AS n FROM session_fragments "
                "WHERE session_id = ? GROUP BY fragment_type",
                (session_id,),
            ).fetchall()
        return {r["fragment_type"]: int(r["n"]) for r in rows}

    def close(self) -> None:
        with self._lock:
            self._conn.close()


__all__ = ["FragmentStore", "default_db_path"]
