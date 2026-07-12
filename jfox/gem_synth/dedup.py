"""合成去重：存盘前用正文 embedding 余弦查 candidate/permanent 重复。

自包含子系统：dedup_embeddings 表存全局 synthesis_log.db（带 kb 列做 KB 作用域
隔离），numpy 暴力余弦（<1k 向量微秒级）。daemon 不可用时降级跳过 dedup，不阻塞合成。
"""

import hashlib
import logging
import sqlite3
import threading
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np

from .paths import default_synthesis_db_path

logger = logging.getLogger(__name__)

_MAX_CONTENT_CHARS = 2000
_CANDIDATE_META_MARKERS = ["\n## 来源\n", "\n## 参考的永久笔记\n", "\n## 置信度\n"]

_SCHEMA = """
CREATE TABLE IF NOT EXISTS dedup_embeddings (
    note_id      TEXT NOT NULL,
    kb           TEXT NOT NULL,
    note_type    TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    emb          BLOB NOT NULL,
    PRIMARY KEY (kb, note_id)
);
"""


class DedupStore:
    """dedup embedding 表的 sqlite 访问器。daemon 持单例；测试注入临时 db_path。"""

    def __init__(self, db_path: Optional[Path] = None) -> None:
        self.db_path: Path = Path(db_path) if db_path is not None else default_synthesis_db_path()
        self.db_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        # 跨进程写冲突（daemon + CLI 并发）时等待 10s 而非立刻 "database is locked"
        self._conn.execute("PRAGMA busy_timeout=10000")
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def upsert(self, kb: str, note_id: str, note_type: str, content_hash: str, emb: bytes) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO dedup_embeddings "
                "(note_id, kb, note_type, content_hash, emb) VALUES (?,?,?,?,?)",
                (note_id, kb, note_type, content_hash, emb),
            )
            self._conn.commit()

    def get_hash(self, kb: str, note_id: str) -> Optional[str]:
        with self._lock:
            r = self._conn.execute(
                "SELECT content_hash FROM dedup_embeddings WHERE kb=? AND note_id=?",
                (kb, note_id),
            ).fetchone()
        return r["content_hash"] if r else None

    def all_embeddings(self, kb: str, note_types: Tuple[str, ...]) -> List[Tuple[str, np.ndarray]]:
        if not note_types:
            return []
        placeholders = ",".join("?" * len(note_types))
        with self._lock:
            rows = self._conn.execute(
                f"SELECT note_id, emb FROM dedup_embeddings "
                f"WHERE kb=? AND note_type IN ({placeholders})",
                (kb, *note_types),
            ).fetchall()
        return [(r["note_id"], np.frombuffer(r["emb"], dtype=np.float32)) for r in rows]

    def update_type(self, kb: str, note_id: str, new_type: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE dedup_embeddings SET note_type=? WHERE kb=? AND note_id=?",
                (new_type, kb, note_id),
            )
            self._conn.commit()

    def delete(self, kb: str, note_id: str) -> None:
        """删除指定 KB 下的 dedup 行。PK 是 (kb, note_id)，必须带 kb 作用域，
        否则跨 KB 的 note_id 碰撞会误删。"""
        with self._lock:
            self._conn.execute(
                "DELETE FROM dedup_embeddings WHERE kb=? AND note_id=?", (kb, note_id)
            )
            self._conn.commit()

    def count(self, kb: Optional[str] = None) -> int:
        with self._lock:
            if kb:
                r = self._conn.execute(
                    "SELECT COUNT(*) FROM dedup_embeddings WHERE kb=?", (kb,)
                ).fetchone()
            else:
                r = self._conn.execute("SELECT COUNT(*) FROM dedup_embeddings").fetchone()
        return int(r[0]) if r else 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()


# 模块级单例（daemon 进程；测试用 set_store 注入临时实例）
_store_lock = threading.Lock()
_store: Optional[DedupStore] = None


def _get_store() -> DedupStore:
    global _store
    with _store_lock:
        if _store is None:
            _store = DedupStore()
        return _store


def set_store(store: Optional[DedupStore]) -> None:
    """测试注入临时 store（用 temp db_path）。传 None 重置回默认单例。"""
    global _store
    with _store_lock:
        _store = store


def _resolve_kb_name(kb: Optional[str]) -> str:
    """target_kb=None 表示用 default；在 use_kb 上下文内取 config.base_dir.name 作具体名。

    dedup_embeddings.kb 是 TEXT NOT NULL，且 dedup_check 的 SQL WHERE kb=? 绑 None
    会匹配 0 行（永远检不到重复）。target_kb=None 时（默认 KB），use_kb 不会换
    base_dir，但 config.base_dir 在模块加载时已指向默认 KB 路径，其 .name 即 KB 名。
    """
    if kb:
        return kb
    from ..config import config as _zk_config

    return _zk_config.base_dir.name


def _clean_candidate_content(content: str) -> str:
    """剥掉 _save_candidate_note 追加的元段落（## 来源/参考的永久笔记/置信度），
    截断到 _MAX_CONTENT_CHARS。保证新 candidate（无元段落）与 backfill 旧 candidate
    （有元段落）口径一致，余弦比较的是知识本身。"""
    for marker in _CANDIDATE_META_MARKERS:
        idx = content.find(marker)
        if idx >= 0:
            content = content[:idx]
    return content.strip()[:_MAX_CONTENT_CHARS]


def _content_hash(content: str) -> str:
    return hashlib.sha1(content.encode("utf-8")).hexdigest()


def _embed(text: str) -> Optional[np.ndarray]:
    """经 embedding daemon 取向量。daemon 不可用返回 None（调用方降级）。"""
    from ..embedding_backend import get_backend

    vec = get_backend().encode_single(text)
    return np.asarray(vec, dtype=np.float32)


def dedup_check(kb: str, content: str, threshold: float = 0.88) -> Optional[str]:
    """返回与已有 candidate/permanent 重复的 note_id；无重复或降级时返回 None。

    daemon 不可用 / 空内容 / 表空 → 返回 None（降级放行，不阻塞合成）。
    """
    try:
        cleaned = _clean_candidate_content(content)
        if not cleaned:
            return None
        emb = _embed(cleaned)
        if emb is None:
            return None
        rows = _get_store().all_embeddings(kb, ("candidate", "permanent"))
        if not rows:
            return None
        mat = np.vstack([r[1] for r in rows])  # (N, D)
        # 两侧范数都加 epsilon 防零行/零向量除零 → NaN 毒化 argmax
        norms = (np.linalg.norm(mat, axis=1) + 1e-12) * (np.linalg.norm(emb) + 1e-12)
        sims = (mat @ emb) / norms
        # 腐败零行产 NaN 时替换为 -1，防 argmax 选到 NaN 导致误判重复
        np.nan_to_num(sims, nan=-1.0, copy=False)
        best = int(np.argmax(sims))
        if sims[best] >= threshold:
            return rows[best][0]
    except Exception as e:
        logger.warning("dedup_check 失败，降级跳过: %s", e)
        return None
    return None


def upsert_dedup(kb: str, note_id: str, note_type: str, content: str) -> bool:
    """算 embedding 入表。content_hash 命中（内容没变）则跳过省 daemon 调用。失败仅 warning。

    返回 True 表示实际写入了 dedup_embeddings；False 表示跳过（内容空/hash 命中/embed 失败/异常）。
    调用方（如 backfill）据此精确计数，避免把跳过的行也算作"已灌入"。"""
    try:
        # 仅 candidate 需剥元段落（## 来源/参考/置信度）；permanent 嵌完整正文（无元段落，
        # 若误剥会截断真实知识）。按 spec：permanent embed FULL content。
        if note_type == "candidate":
            cleaned = _clean_candidate_content(content)
        else:
            cleaned = (content or "").strip()[:_MAX_CONTENT_CHARS]
        if not cleaned:
            return False
        store = _get_store()
        ch = _content_hash(cleaned)
        if store.get_hash(kb, note_id) == ch:
            return False
        emb = _embed(cleaned)
        if emb is None:
            return False
        store.upsert(kb, note_id, note_type, ch, emb.tobytes())
        return True
    except Exception as e:
        logger.warning("upsert_dedup 失败 note=%s: %s", note_id, e)
        return False


def update_dedup_type(kb: str, note_id: str, new_type: str) -> None:
    try:
        _get_store().update_type(kb, note_id, new_type)
    except Exception as e:
        logger.warning("update_dedup_type 失败 note=%s: %s", note_id, e)


def delete_dedup(kb: str, note_id: str) -> None:
    """删除 dedup 行（KB 作用域隔离，防跨 KB note_id 碰撞误删）。失败仅 warning。"""
    try:
        _get_store().delete(kb, note_id)
    except Exception as e:
        logger.warning("delete_dedup 失败 note=%s: %s", note_id, e)


def release_blocked_anchors(note_id: str) -> None:
    """释放因"重复于 note_id"而被阻断的锚点（清除 synthesis_log 中的 duplicate 记账）。

    candidate 被 reject 后调用：该 candidate 曾触发 dedup 命中，对应锚点被标记
    duplicate（不重试）。candidate 已丢弃 → 锚点应恢复为未处理，允许未来重新合成。
    失败仅 warning，不阻塞 reject 流程。"""
    try:
        from .store import SynthesisLog

        log = SynthesisLog()
        try:
            log.clear_duplicates_of(note_id)
        finally:
            log.close()
    except Exception as e:
        logger.warning("release_blocked_anchors 失败 note=%s: %s", note_id, e)


__all__ = [
    "DedupStore",
    "dedup_check",
    "upsert_dedup",
    "update_dedup_type",
    "delete_dedup",
    "release_blocked_anchors",
    "set_store",
    "_clean_candidate_content",
    "_resolve_kb_name",
]
