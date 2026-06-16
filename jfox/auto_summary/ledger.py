"""
auto-summary 状态文件：~/.zk_auto_summary_state.json

记录每个 session 的处理状态（成功 / 跳过 / 永久失败），防止重复处理；
失败超过 max_retries 后转为 failed_permanent，永久跳过。
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

DEFAULT_LEDGER_PATH = Path.home() / ".zk_auto_summary_state.json"
SCHEMA_VERSION = 1
DEFAULT_MAX_RETRIES = 3


class SessionStatus(str, Enum):
    SUCCESS = "success"
    SKIPPED = "skipped"
    FAILED_TRANSIENT = "failed_transient"  # 可重试
    FAILED_PERMANENT = "failed_permanent"  # 不再重试


_TERMINAL_STATUSES = {
    SessionStatus.SUCCESS,
    SessionStatus.SKIPPED,
    SessionStatus.FAILED_PERMANENT,
}


@dataclass
class LedgerEntry:
    project: str
    processed_at: str
    status: str  # SessionStatus.value
    note_id: Optional[str] = None
    retry_count: int = 0
    last_error: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "LedgerEntry":
        return cls(
            project=str(data.get("project", "")),
            processed_at=str(data.get("processed_at", "")),
            status=str(data.get("status", SessionStatus.FAILED_TRANSIENT.value)),
            note_id=data.get("note_id"),
            retry_count=int(data.get("retry_count", 0)),
            last_error=data.get("last_error"),
        )


@dataclass
class _LedgerData:
    version: int = SCHEMA_VERSION
    sessions: dict[str, LedgerEntry] = field(default_factory=dict)


class Ledger:
    """
    并发安全性说明：写方法使用 CAS（compare-and-swap）保护，daemon 后台循环
    和 CLI 手动 run 并发写入同一份 ledger 时，会自动重试（最多 3 次）。
    不适用于高频并发场景（每秒多次写入）。
    """

    def __init__(self, path: Optional[Path] = None, max_retries: int = DEFAULT_MAX_RETRIES):
        self.path = path or DEFAULT_LEDGER_PATH
        self.max_retries = max_retries
        self._last_mtime: Optional[float] = None
        self._data = self._load()

    def _load(self) -> _LedgerData:
        if not self.path.exists():
            self._last_mtime = None
            return _LedgerData()
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                raw = json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            backup_path = self._backup_corrupted_file()
            logger.error(
                "Ledger 文件解析失败 (%s)，已备份至 %s，将以空状态启动",
                e,
                backup_path or "(备份失败)",
            )
            self._last_mtime = None
            return _LedgerData()

        # 合法 JSON 但非 dict → 视为损坏，同样备份
        if not isinstance(raw, dict):
            backup_path = self._backup_corrupted_file()
            logger.error(
                "Ledger 文件期望 dict 但得到 %s，已备份至 %s，将以空状态启动",
                type(raw).__name__,
                backup_path or "(备份失败)",
            )
            self._last_mtime = None
            return _LedgerData()

        version = raw.get("version", SCHEMA_VERSION)
        if version != SCHEMA_VERSION:
            logger.warning(
                "Ledger schema version=%s 与本程序期望 %s 不一致，仍按当前 schema 解析",
                version,
                SCHEMA_VERSION,
            )
        sessions_raw = raw.get("sessions", {})
        sessions = {
            sid: LedgerEntry.from_dict(d) for sid, d in sessions_raw.items() if isinstance(d, dict)
        }
        # 迁移：旧版裸 session_id（不含 ':')视为 claude 来源，加前缀
        sessions = {
            (sid if ":" in sid else f"claude:{sid}"): entry for sid, entry in sessions.items()
        }
        try:
            self._last_mtime = os.path.getmtime(self.path)
        except OSError:
            self._last_mtime = None
        return _LedgerData(version=SCHEMA_VERSION, sessions=sessions)

    def _backup_corrupted_file(self) -> Optional[Path]:
        """把损坏的 ledger 文件改名为 *.corrupted-<ts>.json，返回新路径。失败返回 None。"""
        if not self.path.exists():
            return None
        try:
            ts = datetime.now().strftime("%Y%m%dT%H%M%S")
            backup = self.path.with_suffix(f".corrupted-{ts}.json")
            self.path.rename(backup)
            return backup
        except OSError as e:
            logger.error("备份损坏的 ledger 文件失败: %s", e)
            return None

    def _save(self) -> bool:
        try:
            from ..utils import atomic_write_json

            payload = {
                "version": self._data.version,
                "sessions": {sid: e.to_dict() for sid, e in self._data.sessions.items()},
            }
            atomic_write_json(self.path, payload)
            return True
        except OSError as e:
            logger.error("保存 ledger 失败: %s", e)
            return False

    def _save_cas(self, data: _LedgerData) -> bool:
        """CAS 写入：mtime 变化则返回 False（调用方应重新 load 再试）。"""
        try:
            current_mtime = None
            if self.path.exists():
                current_mtime = os.path.getmtime(self.path)
        except OSError:
            current_mtime = None

        if current_mtime != self._last_mtime:
            return False

        from ..utils import atomic_write_json

        payload = {
            "version": data.version,
            "sessions": {sid: e.to_dict() for sid, e in data.sessions.items()},
        }
        atomic_write_json(self.path, payload)
        try:
            self._last_mtime = os.path.getmtime(self.path)
        except OSError:
            self._last_mtime = None
        return True

    def _retry_count_from(self, data: _LedgerData, session_id: str) -> int:
        prev = data.sessions.get(session_id)
        return prev.retry_count if prev else 0

    # 查询 -----------------------------------------------------------------

    def get(self, session_id: str) -> Optional[LedgerEntry]:
        return self._data.sessions.get(session_id)

    def is_done(self, session_id: str) -> bool:
        """该 session 是否已经"了结"（成功 / 跳过 / 永久失败）"""
        entry = self.get(session_id)
        if entry is None:
            return False
        try:
            return SessionStatus(entry.status) in _TERMINAL_STATUSES
        except ValueError:
            return False

    def all_entries(self) -> dict[str, LedgerEntry]:
        return dict(self._data.sessions)

    def stats(self) -> dict[str, int]:
        counts = {s.value: 0 for s in SessionStatus}
        for e in self._data.sessions.values():
            counts[e.status] = counts.get(e.status, 0) + 1
        return counts

    # 写入 -----------------------------------------------------------------

    def record_success(self, session_id: str, project: str, note_id: str) -> bool:
        for attempt in range(self.max_retries):
            data = self._load()
            data.sessions[session_id] = LedgerEntry(
                project=project,
                processed_at=datetime.now().isoformat(),
                status=SessionStatus.SUCCESS.value,
                note_id=note_id,
                retry_count=self._retry_count_from(data, session_id),
                last_error=None,
            )
            if self._save_cas(data):
                self._data = data
                return True
            logger.debug(
                "CAS conflict on record_success, retry %d/%d", attempt + 1, self.max_retries
            )
        raise RuntimeError(f"Ledger CAS conflict after {self.max_retries} retries: {session_id}")

    def record_skip(self, session_id: str, project: str, reason: str) -> bool:
        for attempt in range(self.max_retries):
            data = self._load()
            data.sessions[session_id] = LedgerEntry(
                project=project,
                processed_at=datetime.now().isoformat(),
                status=SessionStatus.SKIPPED.value,
                note_id=None,
                retry_count=self._retry_count_from(data, session_id),
                last_error=reason,
            )
            if self._save_cas(data):
                self._data = data
                return True
            logger.debug("CAS conflict on record_skip, retry %d/%d", attempt + 1, self.max_retries)
        raise RuntimeError(f"Ledger CAS conflict after {self.max_retries} retries: {session_id}")

    def record_failure(self, session_id: str, project: str, error: str) -> bool:
        for attempt in range(self.max_retries):
            data = self._load()
            prev = data.sessions.get(session_id)
            retries = (prev.retry_count if prev else 0) + 1
            permanent = retries >= self.max_retries
            status = SessionStatus.FAILED_PERMANENT if permanent else SessionStatus.FAILED_TRANSIENT
            data.sessions[session_id] = LedgerEntry(
                project=project,
                processed_at=datetime.now().isoformat(),
                status=status.value,
                note_id=prev.note_id if prev else None,
                retry_count=retries,
                last_error=error[:500],
            )
            if self._save_cas(data):
                self._data = data
                return True
            logger.debug(
                "CAS conflict on record_failure, retry %d/%d", attempt + 1, self.max_retries
            )
        raise RuntimeError(f"Ledger CAS conflict after {self.max_retries} retries: {session_id}")

    def forget(self, session_id: str) -> bool:
        """从 ledger 中移除某条，使其下次扫描时被重新处理"""
        for attempt in range(self.max_retries):
            data = self._load()
            if session_id not in data.sessions:
                return False
            del data.sessions[session_id]
            if self._save_cas(data):
                self._data = data
                return True
            logger.debug("CAS conflict on forget, retry %d/%d", attempt + 1, self.max_retries)
        raise RuntimeError(f"Ledger CAS conflict after {self.max_retries} retries: {session_id}")

    def prune_older_than(self, days: int) -> int:
        """删除 processed_at 早于 N 天的条目，返回删除数量"""
        if days <= 0:
            return 0
        cutoff = datetime.now().timestamp() - days * 86400
        for attempt in range(self.max_retries):
            data = self._load()
            to_delete = []
            for sid, entry in data.sessions.items():
                try:
                    ts = datetime.fromisoformat(entry.processed_at).timestamp()
                except ValueError:
                    continue
                if ts < cutoff:
                    to_delete.append(sid)
            for sid in to_delete:
                del data.sessions[sid]
            if not to_delete:
                return 0
            if self._save_cas(data):
                self._data = data
                return len(to_delete)
            logger.debug("CAS conflict on prune, retry %d/%d", attempt + 1, self.max_retries)
        raise RuntimeError(f"Ledger CAS conflict after {self.max_retries} retries during prune")
