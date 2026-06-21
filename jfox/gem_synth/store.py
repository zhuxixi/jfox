"""合成记账：哪些锚点碎片已合成过，避免重复。SQLite（WAL）。"""

import sqlite3
import threading
from pathlib import Path
from typing import List, Optional

from .paths import default_synthesis_db_path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS synthesis_log (
    anchor_fragment_id  INTEGER PRIMARY KEY,
    candidate_note_id   TEXT NOT NULL,
    synthesized_at      TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""


class SynthesisLog:
    """合成记账表。daemon 持有常驻实例；测试传临时路径。"""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path: Path = Path(db_path) if db_path is not None else default_synthesis_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # 同一进程内多线程读写的锁（sqlite3 连接默认 check_same_thread=True）
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._closed: bool = False

    def is_processed(self, anchor_fragment_id: int) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM synthesis_log WHERE anchor_fragment_id = ?",
                (anchor_fragment_id,),
            ).fetchone()
        return row is not None

    def filter_unprocessed(self, fragment_ids: List[int]) -> List[int]:
        if not fragment_ids:
            return []
        placeholders = ",".join("?" * len(fragment_ids))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT anchor_fragment_id FROM synthesis_log "
                f"WHERE anchor_fragment_id IN ({placeholders})",
                fragment_ids,
            ).fetchall()
        done = {r[0] for r in rows}
        return [fid for fid in fragment_ids if fid not in done]

    def mark_processed(self, anchor_fragment_id: int, candidate_note_id: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO synthesis_log "
                "(anchor_fragment_id, candidate_note_id) VALUES (?, ?)",
                (anchor_fragment_id, candidate_note_id),
            )
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._conn.close()
            self._closed = True


__all__ = ["SynthesisLog"]
