"""dedup-backfill：扫 candidate(非 archived)+permanent 灌 dedup 表。"""

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from jfox.models import Note, NoteType

pytestmark = [pytest.mark.unit, pytest.mark.fast]


@pytest.fixture(autouse=True)
def _mock_backend(monkeypatch, mock_embedding_backend, temp_kb):
    """save_note → vector_store 会调 get_backend().encode；mock_embedding_backend
    fixture 只返回实例不接管 get_backend，这里补上 patch，避免 backfill 路径
    触发真实 sentence-transformers 加载。

    mock_embedding_backend 只有 encode/encode_batch，没有 encode_single（dedup 的
    _embed 走 encode_single），这里补上一个确定性实现。

    同时把全局 config 单例钉到 temp_kb 路径——temp_kb fixture 只 yield 路径不改
    config.notes_dir，否则 save_note/load_note_by_id 会落到共享 default KB。"""
    import hashlib

    import numpy as np

    from jfox import embedding_backend
    from jfox.config import config

    def _encode_single(text):
        h = hashlib.sha1(text.encode("utf-8")).digest()
        vec = np.frombuffer((h * 8)[: 384 * 4], dtype=np.uint8)
        return (vec.astype(np.float32) % 16) / 16.0

    monkeypatch.setattr(mock_embedding_backend, "encode_single", _encode_single, raising=False)
    monkeypatch.setattr(embedding_backend, "get_backend", lambda: mock_embedding_backend)

    original = (config.base_dir, config.notes_dir, config.zk_dir, config.chroma_dir)
    config.base_dir = temp_kb
    config.notes_dir = temp_kb / "notes"
    config.zk_dir = temp_kb / ".zk"
    config.chroma_dir = config.zk_dir / "chroma_db"
    try:
        yield
    finally:
        config.base_dir, config.notes_dir, config.zk_dir, config.chroma_dir = original


def _now():
    return datetime(2026, 7, 12, 13, 0, 0)


def test_backfill_populates_store(temp_kb, mock_embedding_backend):
    from jfox.note import save_note

    # 造 2 candidate + 1 permanent
    save_note(
        Note(
            id="20260712130000-1",
            title="a",
            content="内容A",
            type=NoteType.CANDIDATE,
            created=_now(),
            updated=_now(),
        )
    )
    save_note(
        Note(
            id="20260712130001-2",
            title="b",
            content="内容B",
            type=NoteType.CANDIDATE,
            created=_now(),
            updated=_now(),
        )
    )
    save_note(
        Note(
            id="20260712130002-3",
            title="p",
            content="永久",
            type=NoteType.PERMANENT,
            created=_now(),
            updated=_now(),
        )
    )

    store = MagicMock()
    store.get_hash.return_value = None  # 全是新内容
    with patch("jfox.gem_synth.dedup._get_store", return_value=store):
        from jfox.gem_synth.cli import _dedup_backfill_impl

        n_cand, n_perm = _dedup_backfill_impl(kb=None)
    assert n_cand == 2
    assert n_perm == 1
    assert n_cand + n_perm == 3
    assert store.upsert.call_count == 3


def test_backfill_skips_archived(temp_kb, mock_embedding_backend):
    """archived candidate 不应被灌入 dedup 表（已归档相当于丢弃）。"""
    from jfox.note import save_note

    # 1 个普通 candidate + 1 个 archived candidate
    save_note(
        Note(
            id="20260712130010-1",
            title="live",
            content="活的",
            type=NoteType.CANDIDATE,
            created=_now(),
            updated=_now(),
        )
    )
    save_note(
        Note(
            id="20260712130011-2",
            title="dead",
            content="废的",
            type=NoteType.CANDIDATE,
            archived=True,
            created=_now(),
            updated=_now(),
        )
    )

    store = MagicMock()
    store.get_hash.return_value = None
    with patch("jfox.gem_synth.dedup._get_store", return_value=store):
        from jfox.gem_synth.cli import _dedup_backfill_impl

        n_cand, n_perm = _dedup_backfill_impl(kb=None)
    assert n_cand == 1  # 只算非 archived
    assert n_perm == 0
    assert store.upsert.call_count == 1


def test_backfill_idempotent_via_content_hash(temp_kb, mock_embedding_backend):
    """store.get_hash 命中（内容没变）时 upsert 不被调用，省 daemon embedding 计算。"""
    from jfox.gem_synth.dedup import _clean_candidate_content, _content_hash
    from jfox.note import save_note

    save_note(
        Note(
            id="20260712130020-1",
            title="a",
            content="稳定内容",
            type=NoteType.CANDIDATE,
            created=_now(),
            updated=_now(),
        )
    )

    # 用真实 _content_hash 算期望值，让 upsert_dedup 的 hash 比较命中
    expected_hash = _content_hash(_clean_candidate_content("稳定内容"))
    store = MagicMock()
    store.get_hash.return_value = expected_hash
    with patch("jfox.gem_synth.dedup._get_store", return_value=store):
        from jfox.gem_synth.cli import _dedup_backfill_impl

        n_cand, n_perm = _dedup_backfill_impl(kb=None)
    # hash 命中 → upsert_dedup 返回 False → n_cand 不计入；store.upsert 也没被调用
    assert n_cand == 0
    assert store.upsert.call_count == 0
