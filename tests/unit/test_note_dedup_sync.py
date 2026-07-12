"""promote/reject/archive 同步 dedup 表。用 temp_kb + mock backend。"""

from datetime import datetime
from unittest.mock import patch

import pytest

from jfox.models import Note, NoteType

pytestmark = [pytest.mark.unit, pytest.mark.fast]


@pytest.fixture(autouse=True)
def _mock_backend(monkeypatch, mock_embedding_backend, temp_kb):
    """save_note/update_note → vector_store 会调 get_backend().encode；
    mock_embedding_backend fixture 只返回实例不接管 get_backend，这里补上 patch，
    避免 promote/archive/reject 路径触发真实 sentence-transformers 加载。

    同时把全局 config 单例钉到 temp_kb 路径——temp_kb fixture 只 yield 路径不改
    config.notes_dir，否则 save_note/load_note_by_id 会落到共享 default KB，
    promote 后残留在 permanent/ 的文件会让重跑时 load 先命中旧 permanent 副本。"""
    from jfox import embedding_backend
    from jfox.config import config

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
    return datetime(2026, 7, 12, 12, 0, 0)


def test_archive_deletes_from_dedup(temp_kb, mock_embedding_backend):
    from jfox.note import archive_note, save_note

    n = Note(
        id="20260712120000-000001",
        title="t",
        content="c",
        type=NoteType.FLEETING,
        created=_now(),
        updated=_now(),
    )
    save_note(n)
    with patch("jfox.gem_synth.dedup._get_store") as ms:
        store = ms.return_value
        archive_note(n.id)
        store.delete.assert_called_once_with(n.id)


def test_reject_deletes_from_dedup(temp_kb, mock_embedding_backend):
    from jfox.note import reject_note, save_note

    n = Note(
        id="20260712120001-000002",
        title="t",
        content="c",
        type=NoteType.CANDIDATE,
        created=_now(),
        updated=_now(),
    )
    save_note(n)
    with patch("jfox.gem_synth.dedup._get_store") as ms:
        store = ms.return_value
        reject_note(n.id, reason="x")
        store.delete.assert_called_once_with(n.id)


def test_promote_updates_dedup_type(temp_kb, mock_embedding_backend):
    from jfox.note import promote_note, save_note

    n = Note(
        id="20260712120002-000003",
        title="t",
        content="c",
        type=NoteType.CANDIDATE,
        created=_now(),
        updated=_now(),
    )
    save_note(n)
    with patch("jfox.gem_synth.dedup._get_store") as ms:
        store = ms.return_value
        promote_note(n.id)
        # promote 把 candidate→permanent：dedup 表里 note_type 改 permanent
        store.update_type.assert_called_once()
        args = store.update_type.call_args[0]
        assert args[2] == "permanent"
