"""合成记账：哪些锚点碎片已合成过，避免重复。SQLite（WAL）。"""

import sqlite3
import threading
from pathlib import Path
from typing import List, Optional

from .paths import default_synthesis_db_path

_SCHEMA = """
CREATE TABLE IF NOT EXISTS synthesis_log (
    anchor_fragment_id  INTEGER PRIMARY KEY,
    candidate_note_id   TEXT,
    status              TEXT NOT NULL DEFAULT 'success',
    fail_reason         TEXT,
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
        # row_factory=Row 让结果行可用 r["col"] 访问；旧代码用 r[0] 仍兼容
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        # 跨进程写冲突（daemon + CLI 并发）时等待 10s 而非立刻 "database is locked"
        self._conn.execute("PRAGMA busy_timeout=10000")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._maybe_migrate()
        self._closed: bool = False

    def _maybe_migrate(self) -> None:
        """旧表升级：补 status / fail_reason 列（1.2.0 前的表没有）。新表已含，跳过。

        每个 ALTER 都包 try/except：daemon 与 status CLI 可能同时迁移同一库，
        PRAGMA 看到列不存在 → 两进程都尝试 ALTER → 后者拿到 "duplicate column name"。
        该错误视为已迁移完成（幂等），其余异常向上抛。
        """
        # PRAGMA table_info 行：cid, name, type, notnull, dflt_value, pk → name 在第 1 列
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(synthesis_log)")}
        if "status" not in cols:
            try:
                self._conn.execute(
                    "ALTER TABLE synthesis_log ADD COLUMN status TEXT NOT NULL DEFAULT 'success'"
                )
            except Exception as e:
                if "duplicate column" not in str(e).lower():
                    raise
        if "fail_reason" not in cols:
            try:
                self._conn.execute("ALTER TABLE synthesis_log ADD COLUMN fail_reason TEXT")
            except Exception as e:
                if "duplicate column" not in str(e).lower():
                    raise
        if "dup_of" not in cols:
            try:
                self._conn.execute("ALTER TABLE synthesis_log ADD COLUMN dup_of TEXT")
            except Exception as e:
                if "duplicate column" not in str(e).lower():
                    raise
        self._conn.commit()

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
                "(anchor_fragment_id, candidate_note_id, status) VALUES (?, ?, 'success')",
                (anchor_fragment_id, candidate_note_id),
            )
            self._conn.commit()

    def mark_failed(self, anchor_fragment_id: int, fail_reason: str) -> None:
        """失败锚点记账：status='failed' + 原因，candidate_note_id 留空。
        记账后 is_processed 为 True → 不再重试（过夜跑不 thrash）。
        """
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO synthesis_log "
                "(anchor_fragment_id, candidate_note_id, status, fail_reason) "
                "VALUES (?, '', 'failed', ?)",
                (anchor_fragment_id, fail_reason),
            )
            self._conn.commit()

    def mark_duplicate(self, anchor_fragment_id: int, dup_of: str) -> None:
        """重复命中记账：status='duplicate' + dup_of=被重复的 note_id。
        记账后 is_processed=True → 锚点不重试。与 failed 区分，供 status 单独统计。"""
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO synthesis_log "
                "(anchor_fragment_id, candidate_note_id, status, dup_of) "
                "VALUES (?, '', 'duplicate', ?)",
                (anchor_fragment_id, dup_of),
            )
            self._conn.commit()

    def clear_duplicates_of(self, note_id: str) -> None:
        """清除所有 dup_of=note_id 的 duplicate 记账，释放被阻断的锚点。

        candidate 被 reject 后调用：该 candidate 曾触发 dedup 命中，对应锚点标记为
        duplicate（is_processed=True 不重试）。candidate 已丢弃 → 锚点应恢复为未处理，
        允许未来合成周期重新尝试。"""
        with self._lock:
            self._conn.execute(
                "DELETE FROM synthesis_log WHERE status='duplicate' AND dup_of=?",
                (note_id,),
            )
            self._conn.commit()

    def status_counts(self) -> dict:
        """返回 {status: count}，如 {'success': 3, 'failed': 1}。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT status, COUNT(*) AS n FROM synthesis_log GROUP BY status"
            ).fetchall()
        return {r["status"]: int(r["n"]) for r in rows}

    def list_failed(self, limit: int = 100) -> List[dict]:
        """返回失败锚点列表（最新在前），供 status --failed 人工复核。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT anchor_fragment_id, fail_reason, synthesized_at "
                "FROM synthesis_log WHERE status = 'failed' "
                "ORDER BY synthesized_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [
            {
                "anchor_fragment_id": r["anchor_fragment_id"],
                "fail_reason": r["fail_reason"],
                "synthesized_at": r["synthesized_at"],
            }
            for r in rows
        ]

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._conn.close()
            self._closed = True


__all__ = ["SynthesisLog"]
