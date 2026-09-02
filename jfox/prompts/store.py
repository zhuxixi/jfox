"""Prompt 存储层：user_prompts / prompt_judgments / unresolved_items（SQLite WAL）。

与旧 session_fragments 共用 fragments.db（JFOX_FRAGMENTS_DB），但语义独立：
prompt 不截断、不分类；judgment 按 (kb_name, prompt_id) 作用域隔离。
"""

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS user_prompts (
    prompt_id            INTEGER PRIMARY KEY AUTOINCREMENT,
    source_key           TEXT NOT NULL UNIQUE,
    capture_id           TEXT UNIQUE,
    source               TEXT NOT NULL DEFAULT 'claude-code',
    source_fragment_id   INTEGER UNIQUE,
    source_message_uuid  TEXT,
    session_id           TEXT NOT NULL,
    session_seq          INTEGER NOT NULL,
    captured_at          TEXT NOT NULL,
    prompt               TEXT NOT NULL,
    prompt_hash          TEXT NOT NULL,
    transcript_path      TEXT,
    transcript_user_index INTEGER,
    session_title        TEXT,
    cwd                  TEXT,
    metadata_json        TEXT,
    UNIQUE(source, session_id, session_seq)
);
CREATE INDEX IF NOT EXISTS idx_prompts_session
    ON user_prompts(source, session_id, captured_at, prompt_id);
CREATE INDEX IF NOT EXISTS idx_prompts_hash
    ON user_prompts(prompt_hash, captured_at);
CREATE INDEX IF NOT EXISTS idx_prompts_transcript
    ON user_prompts(transcript_path, transcript_user_index);
CREATE UNIQUE INDEX IF NOT EXISTS uq_prompts_transcript_occurrence
    ON user_prompts(transcript_path, transcript_user_index)
    WHERE transcript_path IS NOT NULL AND transcript_user_index IS NOT NULL;

CREATE TABLE IF NOT EXISTS prompt_judgments (
    kb_name                       TEXT NOT NULL,
    prompt_id                     INTEGER NOT NULL,
    judgment_state                TEXT NOT NULL,
    classification                TEXT,
    disposition                   TEXT,
    candidate_note_id             TEXT,
    reason                        TEXT,
    confidence                    REAL,
    matched_note_ids              TEXT,
    matched_prompt_ids            TEXT,
    matched_unresolved_prompt_ids TEXT,
    context_mode                  TEXT,
    runner_id                     TEXT,
    model_id                      TEXT,
    attempt_count                 INTEGER NOT NULL DEFAULT 0,
    claim_token                   TEXT,
    claimed_at                    TEXT,
    last_error                    TEXT,
    judged_at                     TEXT,
    handled_at                    TEXT,
    manual_override               INTEGER NOT NULL DEFAULT 0,
    manual_reason                 TEXT,
    PRIMARY KEY (kb_name, prompt_id)
);
CREATE INDEX IF NOT EXISTS idx_judgments_state
    ON prompt_judgments(kb_name, judgment_state, disposition);
CREATE INDEX IF NOT EXISTS idx_judgments_candidate
    ON prompt_judgments(kb_name, candidate_note_id);

CREATE TABLE IF NOT EXISTS unresolved_items (
    kb_name           TEXT NOT NULL,
    prompt_id         INTEGER NOT NULL,
    note_id           TEXT NOT NULL,
    state             TEXT NOT NULL DEFAULT 'active',
    first_seen        TEXT NOT NULL,
    last_seen         TEXT NOT NULL,
    resolved_at       TEXT,
    resolution_reason TEXT,
    PRIMARY KEY (kb_name, prompt_id)
);
CREATE INDEX IF NOT EXISTS idx_unresolved_active
    ON unresolved_items(kb_name, state, last_seen);
"""

# claim lease 默认值（秒）；claim_timeout_seconds 必须大于 runner timeout + 60
DEFAULT_CLAIM_TIMEOUT_SECONDS = 420

_VALID_CLASSIFICATIONS = {"new", "repeated", "recorded", "needs_review"}
_VALID_DISPOSITIONS = {"pending", "promoted", "unresolved", "ignored", "rejected", "resolved"}

# 空白折叠：连续空白（含换行）合并为单个空格
_WHITESPACE_RE = re.compile(r"\s+")


def default_prompt_db_path() -> Path:
    """与 fragments.db 同库；JFOX_FRAGMENTS_DB 可覆盖（测试/自定义用）。"""
    env = os.environ.get("JFOX_FRAGMENTS_DB")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".zettelkasten" / "fragments.db"


def _utc_now() -> str:
    """UTC ISO-8601（带 Z 后缀），供 captured_at / claimed_at / judged_at。"""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_ts(ts: str) -> datetime:
    """容忍 Z 后缀的 ISO 解析（Python 3.10 fromisoformat 不认 Z）。"""
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def _normalize_prompt_text(text: str) -> str:
    """prompt 规范化：NFKC + 首尾空白 + 连续空白折叠；用于 hash，不改原文。"""
    text = unicodedata.normalize("NFKC", text)
    text = text.strip()
    return _WHITESPACE_RE.sub(" ", text)


def _prompt_hash(text: str) -> str:
    return hashlib.sha256(_normalize_prompt_text(text).encode("utf-8")).hexdigest()


def _clamp_confidence(value: Any) -> Optional[float]:
    """confidence 必须是有限 [0,1] 数值；非法返回 None。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    if f != f or f < 0.0 or f > 1.0:  # NaN / 越界
        return None
    return f


def _to_json_array(value: Any) -> str:
    """列表 → JSON 数组字符串；None/非列表 → 空数组。"""
    if isinstance(value, (list, tuple)):
        return json.dumps(list(value), ensure_ascii=False)
    return "[]"


def _from_json_array(raw: Optional[str]) -> List[Any]:
    if not raw:
        return []
    try:
        val = json.loads(raw)
        return val if isinstance(val, list) else []
    except (json.JSONDecodeError, TypeError):
        return []


class PromptStore:
    """prompt 记录 + judgment 状态机 + unresolved 索引。

    daemon 持有常驻实例（热连接）；CLI / 测试传入临时路径。
    同一进程内多线程访问用 threading.Lock 保护（与 FragmentStore 一致）。
    """

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path: Path = Path(db_path) if db_path is not None else default_prompt_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.execute("PRAGMA synchronous=NORMAL")
        self._conn.execute("PRAGMA busy_timeout=10000")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()
        self._closed = False

    # ------------------------------------------------------------------
    # user_prompts：插入与查询
    # ------------------------------------------------------------------

    def insert_prompt(
        self,
        event: Dict[str, Any],
        source_key: str,
        capture_id: Optional[str] = None,
        source: str = "claude-code",
        source_fragment_id: Optional[int] = None,
        transcript_path: Optional[str] = None,
        transcript_user_index: Optional[int] = None,
    ) -> Dict[str, Any]:
        """校验并插入一条 prompt record。返回 {status, prompt_id, prompt}。

        status: stored（新行）/ duplicate（幂等命中，返回已有行）/ error（校验失败）。
        幂等优先级：source_key > capture_id > transcript occurrence。
        """
        if not isinstance(event, dict):
            return {"status": "error", "error": "event must be a JSON object"}
        if event.get("hook_event_name") != "UserPromptSubmit":
            return {"status": "error", "error": "only UserPromptSubmit is captured"}
        session_id = event.get("session_id")
        prompt = event.get("prompt")
        if not isinstance(session_id, str) or not session_id.strip():
            return {"status": "error", "error": "missing session_id"}
        if not isinstance(prompt, str) or not prompt.strip():
            return {"status": "error", "error": "missing prompt"}
        if not source_key or not isinstance(source_key, str):
            return {"status": "error", "error": "missing source_key"}

        # transcript 定位信息：优先显式参数，其次 event 字段
        tp = transcript_path or event.get("transcript_path")
        tui = (
            transcript_user_index
            if transcript_user_index is not None
            else event.get("transcript_user_index")
        )

        now = _utc_now()
        # 事件内可验证时间优先（CC event 无标准时间字段，MVP 用摄入时间）
        captured_at = now
        ph = _prompt_hash(prompt)

        try:
            with self._lock:
                return self._insert_prompt_locked(
                    event=event,
                    source_key=source_key,
                    capture_id=capture_id,
                    source=source,
                    source_fragment_id=source_fragment_id,
                    session_id=session_id,
                    prompt=prompt,
                    prompt_hash=ph,
                    transcript_path=tp,
                    transcript_user_index=tui,
                    captured_at=captured_at,
                )
        except sqlite3.IntegrityError as e:
            # 并发下唯一键竞态：重查已有行（异常退出 with self._lock 后须重新持锁，
            # _find_by_idempotency 内部自带 self._lock）
            logger.debug("insert_prompt IntegrityError（并发竞态）: %s", e)
            # with 块因异常退出已释放锁；_find_by_idempotency 约定调用方持锁，重新获取
            with self._lock:
                existing = self._find_by_idempotency(source_key, capture_id, tp, tui)
            if existing is not None:
                return {"status": "duplicate", "prompt_id": existing, "prompt": prompt}
            return {"status": "error", "error": f"integrity error: {e}"}
        except sqlite3.Error as e:
            logger.exception("insert_prompt 数据库错误: %s", e)
            return {"status": "error", "error": f"database error: {e}"}

    def _insert_prompt_locked(
        self,
        event: Dict[str, Any],
        source_key: str,
        capture_id: Optional[str],
        source: str,
        source_fragment_id: Optional[int],
        session_id: str,
        prompt: str,
        prompt_hash: str,
        transcript_path: Optional[str],
        transcript_user_index: Optional[int],
        captured_at: str,
    ) -> Dict[str, Any]:
        # 1) source_key 幂等
        existing_id = self._find_by_idempotency(
            source_key, capture_id, transcript_path, transcript_user_index
        )
        if existing_id is not None:
            return {"status": "duplicate", "prompt_id": existing_id, "prompt": prompt}

        # 2) session_seq：BEGIN IMMEDIATE 保证并发下不撞 UNIQUE(source, session_id, session_seq)
        self._conn.execute("BEGIN IMMEDIATE")
        try:
            row = self._conn.execute(
                "SELECT COALESCE(MAX(session_seq), 0) + 1 AS next_seq "
                "FROM user_prompts WHERE source = ? AND session_id = ?",
                (source, session_id),
            ).fetchone()
            session_seq = int(row["next_seq"])

            metadata_json = json.dumps(event, ensure_ascii=False, default=str)

            cur = self._conn.execute(
                "INSERT INTO user_prompts "
                "(source_key, capture_id, source, source_fragment_id, source_message_uuid, "
                " session_id, session_seq, captured_at, prompt, prompt_hash, "
                " transcript_path, transcript_user_index, session_title, cwd, metadata_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    source_key,
                    capture_id,
                    source,
                    source_fragment_id,
                    event.get("message_uuid"),
                    session_id,
                    session_seq,
                    captured_at,
                    prompt,
                    prompt_hash,
                    transcript_path,
                    transcript_user_index,
                    event.get("session_title"),
                    event.get("cwd"),
                    metadata_json,
                ),
            )
            self._conn.commit()
            return {"status": "stored", "prompt_id": int(cur.lastrowid), "prompt": prompt}
        except BaseException:
            self._conn.rollback()
            raise

    def _find_by_idempotency(
        self,
        source_key: str,
        capture_id: Optional[str],
        transcript_path: Optional[str],
        transcript_user_index: Optional[int],
    ) -> Optional[int]:
        """按优先级查已有行：source_key > capture_id > transcript occurrence。"""
        row = self._conn.execute(
            "SELECT prompt_id FROM user_prompts WHERE source_key = ?", (source_key,)
        ).fetchone()
        if row is not None:
            return int(row["prompt_id"])
        if capture_id:
            row = self._conn.execute(
                "SELECT prompt_id FROM user_prompts WHERE capture_id = ?", (capture_id,)
            ).fetchone()
            if row is not None:
                return int(row["prompt_id"])
        if transcript_path and transcript_user_index is not None:
            row = self._conn.execute(
                "SELECT prompt_id FROM user_prompts "
                "WHERE transcript_path = ? AND transcript_user_index = ?",
                (transcript_path, transcript_user_index),
            ).fetchone()
            if row is not None:
                return int(row["prompt_id"])
        return None

    def get_prompt(self, prompt_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM user_prompts WHERE prompt_id = ?", (prompt_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_prompts(
        self,
        session_id: Optional[str] = None,
        limit: int = 50,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """按摄入顺序列出 prompt（旧→新），支持 session 过滤与分页。"""
        sql = "SELECT * FROM user_prompts"
        params: List[Any] = []
        if session_id is not None:
            sql += " WHERE session_id = ?"
            params.append(session_id)
        sql += " ORDER BY prompt_id LIMIT ? OFFSET ?"
        params.extend([limit, offset])
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def count_prompts(self, session_id: Optional[str] = None) -> int:
        sql = "SELECT COUNT(*) FROM user_prompts"
        params: List[Any] = []
        if session_id is not None:
            sql += " WHERE session_id = ?"
            params.append(session_id)
        with self._lock:
            row = self._conn.execute(sql, params).fetchone()
        return int(row[0]) if row else 0

    # ------------------------------------------------------------------
    # prompt_judgments：claim 状态机
    # ------------------------------------------------------------------

    def claim_prompts(
        self,
        kb_name: str,
        prompt_ids: List[int],
        claim_token: str,
        now: str,
        claim_timeout_seconds: int = DEFAULT_CLAIM_TIMEOUT_SECONDS,
        allow_needs_review_reclaim: bool = False,
    ) -> List[int]:
        """尝试 claim 一批 prompt。返回成功 claim 的 prompt_id 列表。

        claim 规则：
        - 无 judgment 行 → 创建 processing 行并 claim
        - 有活跃 claim（token 非空且未过期）→ skip
        - claim 过期 → 回收（attempt+1，换 token）
        - failed 且无活跃 claim → 可 claim（retry-failed 场景）
        - succeeded → 普通claim 不碰（防重复判断）
        - processing 且 claim 为空 → 异常中断残留，可回收
        """
        claimed: List[int] = []
        now_dt = _parse_ts(now)
        try:
            with self._lock:
                self._conn.execute("BEGIN IMMEDIATE")
                try:
                    for pid in prompt_ids:
                        row = self._conn.execute(
                            "SELECT * FROM prompt_judgments " "WHERE kb_name = ? AND prompt_id = ?",
                            (kb_name, pid),
                        ).fetchone()
                        if row is None:
                            self._conn.execute(
                                "INSERT INTO prompt_judgments "
                                "(kb_name, prompt_id, judgment_state, attempt_count, "
                                " claim_token, claimed_at) "
                                "VALUES (?, ?, 'processing', 1, ?, ?)",
                                (kb_name, pid, claim_token, now),
                            )
                            claimed.append(pid)
                            continue

                        state = row["judgment_state"]
                        token = row["claim_token"]
                        claimed_at = row["claimed_at"]

                        if token:
                            # 活跃 claim 检查
                            if claimed_at:
                                try:
                                    elapsed = (now_dt - _parse_ts(claimed_at)).total_seconds()
                                except (ValueError, TypeError):
                                    elapsed = claim_timeout_seconds + 1  # 坏时间戳视为过期
                                if elapsed < claim_timeout_seconds:
                                    continue  # lease 未过期，skip
                            # 过期 → 回收
                        elif state == "succeeded":
                            # 成功的不重判——唯一例外：needs_review + 待处置 +
                            # 显式重判请求（judge --retry-needs-review 入口）
                            if not (
                                allow_needs_review_reclaim
                                and row["classification"] == "needs_review"
                                and row["disposition"] == "pending"
                            ):
                                continue
                        # failed / processing+空claim → 可 claim

                        self._conn.execute(
                            "UPDATE prompt_judgments SET "
                            "judgment_state = 'processing', "
                            "attempt_count = attempt_count + 1, "
                            "claim_token = ?, claimed_at = ? "
                            "WHERE kb_name = ? AND prompt_id = ?",
                            (claim_token, now, kb_name, pid),
                        )
                        claimed.append(pid)
                    self._conn.commit()
                except BaseException:
                    self._conn.rollback()
                    raise
        except sqlite3.Error as e:
            # 事务已整体 rollback，claimed 里的部分行并未落库——返回空列表防幻影 claim
            logger.exception("claim_prompts 数据库错误: %s", e)
            return []
        return claimed

    def finish_judgment(
        self,
        kb_name: str,
        prompt_id: int,
        classification: str,
        reason: str,
        confidence: Any,
        matched_note_ids: Any,
        matched_prompt_ids: Any,
        matched_unresolved_prompt_ids: Any,
        context_mode: str,
        runner_id: str,
        model_id: str,
        candidate_note_id: Optional[str] = None,
    ) -> bool:
        """写入成功 judgment（succeeded + pending），清空 claim。"""
        if classification not in _VALID_CLASSIFICATIONS:
            logger.warning("finish_judgment 非法 classification: %r", classification)
            return False
        conf = _clamp_confidence(confidence)
        now = _utc_now()
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO prompt_judgments "
                    "(kb_name, prompt_id, judgment_state, classification, disposition, "
                    " candidate_note_id, reason, confidence, matched_note_ids, "
                    " matched_prompt_ids, matched_unresolved_prompt_ids, context_mode, "
                    " runner_id, model_id, attempt_count, claim_token, claimed_at, judged_at) "
                    "VALUES (?, ?, 'succeeded', ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, "
                    " COALESCE((SELECT attempt_count FROM prompt_judgments "
                    "  WHERE kb_name = ? AND prompt_id = ?), 1), NULL, NULL, ?) "
                    "ON CONFLICT(kb_name, prompt_id) DO UPDATE SET "
                    "judgment_state = 'succeeded', classification = excluded.classification, "
                    "disposition = 'pending', candidate_note_id = excluded.candidate_note_id, "
                    "reason = excluded.reason, confidence = excluded.confidence, "
                    "matched_note_ids = excluded.matched_note_ids, "
                    "matched_prompt_ids = excluded.matched_prompt_ids, "
                    "matched_unresolved_prompt_ids = excluded.matched_unresolved_prompt_ids, "
                    "context_mode = excluded.context_mode, "
                    "runner_id = excluded.runner_id, model_id = excluded.model_id, "
                    "claim_token = NULL, claimed_at = NULL, judged_at = excluded.judged_at",
                    (
                        kb_name,
                        prompt_id,
                        classification,
                        candidate_note_id,
                        reason,
                        conf,
                        _to_json_array(matched_note_ids),
                        _to_json_array(matched_prompt_ids),
                        _to_json_array(matched_unresolved_prompt_ids),
                        context_mode,
                        runner_id,
                        model_id,
                        kb_name,
                        prompt_id,
                        now,
                    ),
                )
                self._conn.commit()
            return True
        except sqlite3.Error as e:
            logger.exception("finish_judgment 数据库错误: %s", e)
            return False

    def fail_judgment(self, kb_name: str, prompt_id: int, error: str) -> bool:
        """写入失败 judgment（failed），清空 claim；classification/disposition 置空。"""
        now = _utc_now()
        try:
            with self._lock:
                self._conn.execute(
                    "INSERT INTO prompt_judgments "
                    "(kb_name, prompt_id, judgment_state, classification, disposition, "
                    " attempt_count, claim_token, claimed_at, last_error, judged_at) "
                    "VALUES (?, ?, 'failed', NULL, NULL, "
                    " COALESCE((SELECT attempt_count FROM prompt_judgments "
                    "  WHERE kb_name = ? AND prompt_id = ?), 1), NULL, NULL, ?, ?) "
                    "ON CONFLICT(kb_name, prompt_id) DO UPDATE SET "
                    "judgment_state = 'failed', classification = NULL, disposition = NULL, "
                    "claim_token = NULL, claimed_at = NULL, "
                    "last_error = excluded.last_error, judged_at = excluded.judged_at",
                    (kb_name, prompt_id, kb_name, prompt_id, error, now),
                )
                self._conn.commit()
            return True
        except sqlite3.Error as e:
            logger.exception("fail_judgment 数据库错误: %s", e)
            return False

    def get_judgment(self, kb_name: str, prompt_id: int) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM prompt_judgments WHERE kb_name = ? AND prompt_id = ?",
                (kb_name, prompt_id),
            ).fetchone()
        if row is None:
            return None
        d = dict(row)
        d["matched_note_ids"] = _from_json_array(d.get("matched_note_ids"))
        d["matched_prompt_ids"] = _from_json_array(d.get("matched_prompt_ids"))
        d["matched_unresolved_prompt_ids"] = _from_json_array(
            d.get("matched_unresolved_prompt_ids")
        )
        return d

    def update_disposition(
        self,
        kb_name: str,
        prompt_id: int,
        disposition: str,
        manual_override: bool = False,
        manual_reason: Optional[str] = None,
    ) -> bool:
        """用户动作后更新 disposition（promoted/unresolved/ignored/rejected/resolved）。"""
        if disposition not in _VALID_DISPOSITIONS:
            return False
        now = _utc_now()
        try:
            with self._lock:
                cur = self._conn.execute(
                    "UPDATE prompt_judgments SET disposition = ?, handled_at = ?, "
                    "manual_override = ?, manual_reason = ? "
                    "WHERE kb_name = ? AND prompt_id = ? AND judgment_state = 'succeeded'",
                    (
                        disposition,
                        now,
                        1 if manual_override else 0,
                        manual_reason,
                        kb_name,
                        prompt_id,
                    ),
                )
                self._conn.commit()
            return cur.rowcount > 0
        except sqlite3.Error as e:
            logger.exception("update_disposition 数据库错误: %s", e)
            return False

    def reset_judgment(self, kb_name: str, prompt_id: int) -> bool:
        """删除 judgment 行，让下次 judge 重新选择（retry 用）。"""
        try:
            with self._lock:
                cur = self._conn.execute(
                    "DELETE FROM prompt_judgments WHERE kb_name = ? AND prompt_id = ?",
                    (kb_name, prompt_id),
                )
                self._conn.commit()
            return cur.rowcount > 0
        except sqlite3.Error as e:
            logger.exception("reset_judgment 数据库错误: %s", e)
            return False

    def list_judgments(
        self,
        kb_name: str,
        judgment_state: Optional[str] = None,
        disposition: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """按条件列出 judgment（judge 命令选择 prompt 用）。"""
        sql = "SELECT * FROM prompt_judgments WHERE kb_name = ?"
        params: List[Any] = [kb_name]
        if judgment_state is not None:
            sql += " AND judgment_state = ?"
            params.append(judgment_state)
        if disposition is not None:
            sql += " AND disposition = ?"
            params.append(disposition)
        sql += " ORDER BY prompt_id LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["matched_note_ids"] = _from_json_array(d.get("matched_note_ids"))
            d["matched_prompt_ids"] = _from_json_array(d.get("matched_prompt_ids"))
            d["matched_unresolved_prompt_ids"] = _from_json_array(
                d.get("matched_unresolved_prompt_ids")
            )
            result.append(d)
        return result

    def count_judgments_by_state(self, kb_name: str) -> Dict[str, int]:
        """{state: count}，status 命令用。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT judgment_state, COUNT(*) AS n FROM prompt_judgments "
                "WHERE kb_name = ? GROUP BY judgment_state",
                (kb_name,),
            ).fetchall()
        return {r["judgment_state"]: int(r["n"]) for r in rows}

    # ------------------------------------------------------------------
    # unresolved_items 索引
    # ------------------------------------------------------------------

    def record_candidate_note(self, kb_name: str, prompt_id: int, note_id: str) -> bool:
        """两阶段记账：candidate 落盘后立即记录 note_id（不改变 judgment 状态）。

        崩溃恢复：save_note 成功但 finish_judgment 未执行时，重试方靠本字段
        复用已有 candidate，不重复创建（D17 幂等）。
        """
        try:
            with self._lock:
                cur = self._conn.execute(
                    "UPDATE prompt_judgments SET candidate_note_id = ? "
                    "WHERE kb_name = ? AND prompt_id = ?",
                    (note_id, kb_name, prompt_id),
                )
                self._conn.commit()
            return cur.rowcount > 0
        except sqlite3.Error as e:
            logger.exception("record_candidate_note 数据库错误: %s", e)
            return False

    def upsert_unresolved(
        self, kb_name: str, prompt_id: int, note_id: str, now: Optional[str] = None
    ) -> Dict[str, Any]:
        """幂等写入 active unresolved 条目；重复调用只刷新 last_seen。"""
        ts = now or _utc_now()
        try:
            with self._lock:
                existing = self._conn.execute(
                    "SELECT * FROM unresolved_items WHERE kb_name = ? AND prompt_id = ?",
                    (kb_name, prompt_id),
                ).fetchone()
                if existing is None:
                    self._conn.execute(
                        "INSERT INTO unresolved_items "
                        "(kb_name, prompt_id, note_id, state, first_seen, last_seen) "
                        "VALUES (?, ?, ?, 'active', ?, ?)",
                        (kb_name, prompt_id, note_id, ts, ts),
                    )
                else:
                    self._conn.execute(
                        "UPDATE unresolved_items SET state = 'active', last_seen = ?, "
                        "resolved_at = NULL, resolution_reason = NULL "
                        "WHERE kb_name = ? AND prompt_id = ?",
                        (ts, kb_name, prompt_id),
                    )
                self._conn.commit()
                row = self._conn.execute(
                    "SELECT * FROM unresolved_items WHERE kb_name = ? AND prompt_id = ?",
                    (kb_name, prompt_id),
                ).fetchone()
            return dict(row)
        except sqlite3.Error as e:
            logger.exception("upsert_unresolved 数据库错误: %s", e)
            raise

    def resolve_unresolved(
        self,
        kb_name: str,
        prompt_id: int,
        reason: Optional[str] = None,
        now: Optional[str] = None,
    ) -> bool:
        """把 active 条目标记为 resolved；非 active 条目返回 False。"""
        ts = now or _utc_now()
        try:
            with self._lock:
                cur = self._conn.execute(
                    "UPDATE unresolved_items SET state = 'resolved', "
                    "resolved_at = ?, resolution_reason = ? "
                    "WHERE kb_name = ? AND prompt_id = ? AND state = 'active'",
                    (ts, reason, kb_name, prompt_id),
                )
                self._conn.commit()
            return cur.rowcount > 0
        except sqlite3.Error as e:
            logger.exception("resolve_unresolved 数据库错误: %s", e)
            return False

    def list_unresolved(
        self, kb_name: str, state: str = "active", limit: int = 100
    ) -> List[Dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM unresolved_items "
                "WHERE kb_name = ? AND state = ? ORDER BY last_seen DESC LIMIT ?",
                (kb_name, state, limit),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # 关闭
    # ------------------------------------------------------------------

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._conn.close()
            self._closed = True


__all__ = ["PromptStore", "default_prompt_db_path", "DEFAULT_CLAIM_TIMEOUT_SECONDS"]
