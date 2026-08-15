"""
BM25Index 并发写防护（#391）单元测试

用两个共享同一索引目录的 BM25Index 实例模拟 CLI 与 daemon 两个进程的交错写。
"""

import json
import pickle
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from filelock import Timeout

from jfox.bm25_index import BM25Index
from jfox.models import Note, NoteType


def _note(nid: str, ntype: NoteType = NoteType.PERMANENT) -> Note:
    return Note(
        id=nid,
        title=f"title {nid}",
        type=ntype,
        content=f"content {nid}",
        created=datetime.now(),
        updated=datetime.now(),
    )


def _load_disk_ids(index_dir: Path) -> list:
    with open(index_dir / BM25Index.INDEX_FILENAME, "rb") as f:
        return pickle.load(f)["doc_ids"]


def _disk_version(index_dir: Path) -> int:
    with open(index_dir / BM25Index.METADATA_FILENAME, "r", encoding="utf-8") as f:
        return json.load(f).get("write_version", 0)


class TestWriteVersionAndLock:
    """write_version 元数据、原子写、文件锁"""

    def test_write_version_increments(self, tmp_path):
        idx = BM25Index(index_dir=tmp_path)
        assert idx.add_document("a", "hello world", "session")
        assert idx.add_document("b", "foo bar", "session")
        assert _disk_version(tmp_path) == 2
        meta = json.loads((tmp_path / BM25Index.METADATA_FILENAME).read_text(encoding="utf-8"))
        assert meta["doc_count"] == 2
        assert meta["write_version"] == 2

    def test_legacy_metadata_without_version(self, tmp_path):
        idx = BM25Index(index_dir=tmp_path)
        assert idx.add_document("a", "hello world", "session")
        # 抹掉 write_version 模拟旧格式文件
        meta_path = tmp_path / BM25Index.METADATA_FILENAME
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta.pop("write_version", None)
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        idx2 = BM25Index(index_dir=tmp_path)
        assert idx2._loaded_write_version == 0
        assert "a" in idx2.doc_mapping
        assert idx2.add_document("b", "foo bar", "session")
        assert _disk_version(tmp_path) >= 1

    def test_lock_timeout_aborts_save_without_writing(self, tmp_path):
        idx = BM25Index(index_dir=tmp_path)
        with patch("jfox.bm25_index.FileLock") as mock_lock_cls:
            mock_lock_cls.return_value.__enter__.side_effect = Timeout("bm25_index.lock")
            ok = idx._save()
        assert ok is False
        assert not (tmp_path / BM25Index.INDEX_FILENAME).exists()


class TestOptimisticMerge:
    """双实例模拟双进程：磁盘较新时 reload + 重放本地增量"""

    def test_concurrent_add_replay(self, tmp_path):
        a = BM25Index(index_dir=tmp_path)  # 模拟 daemon：先 load 旧状态
        b = BM25Index(index_dir=tmp_path)  # 模拟 CLI
        assert b.add_document("note-cli", "cli 写入 hello", "session")  # v1
        assert a.add_document("note-daemon", "daemon 写入 world", "session")  # merge → v2
        ids = _load_disk_ids(tmp_path)
        assert "note-cli" in ids
        assert "note-daemon" in ids
        assert _disk_version(tmp_path) == 2

    def test_concurrent_remove_replay(self, tmp_path):
        a = BM25Index(index_dir=tmp_path)
        assert a.add_document("x", "hello x", "permanent")  # v1
        b = BM25Index(index_dir=tmp_path)  # b load v1（含 x）
        assert b.add_document("y", "hello y", "permanent")  # v2
        assert a.remove_document("x")  # a：reload v2 + 重放 remove x → v3
        ids = _load_disk_ids(tmp_path)
        assert "y" in ids
        assert "x" not in ids
        assert _disk_version(tmp_path) == 3

    def test_conflict_last_writer_wins(self, tmp_path):
        a = BM25Index(index_dir=tmp_path)
        assert a.add_document("x", "from a", "session")  # v1
        b = BM25Index(index_dir=tmp_path)
        assert b.add_document("x", "from b", "session")  # v2
        assert a.remove_document("x")  # v3：重放 remove 覆盖 b 的 add
        assert "x" not in _load_disk_ids(tmp_path)

    def test_reload_failure_aborts_save_without_writing(self, tmp_path):
        a = BM25Index(index_dir=tmp_path)
        b = BM25Index(index_dir=tmp_path)
        assert b.add_document("x", "hello x", "session")  # v1
        # a 内存里产生未落盘的增量，然后破坏磁盘 pkl 使 reload 失败
        a._add_document_local("y", "local change", "session")
        a._pending_ops.append(("add", "y", "local change", "session"))
        corrupted = b"corrupted-pkl"
        (tmp_path / BM25Index.INDEX_FILENAME).write_bytes(corrupted)
        assert a._save() is False
        assert (tmp_path / BM25Index.INDEX_FILENAME).read_bytes() == corrupted


class TestRebuildSemantics:
    def test_rebuild_overwrites_stale_disk(self, tmp_path):
        a = BM25Index(index_dir=tmp_path)
        b = BM25Index(index_dir=tmp_path)
        assert b.add_document("old", "old note", "session")  # v1
        # a 内存是旧状态，但 rebuild 语义=以我的快照为准：直接覆盖，不 merge
        assert a.rebuild_from_notes([_note("n1"), _note("n2")])
        assert set(_load_disk_ids(tmp_path)) == {"n1", "n2"}


class TestStaleDetection:
    def test_check_stale_and_reload(self, tmp_path):
        a = BM25Index(index_dir=tmp_path)
        b = BM25Index(index_dir=tmp_path)
        assert b.add_document("x", "hello x", "session")  # v1
        assert "x" not in a.doc_mapping  # a 仍是旧内存
        a.check_stale_and_reload()
        assert "x" in a.doc_mapping

    def test_check_stale_and_reload_noop_when_fresh(self, tmp_path):
        a = BM25Index(index_dir=tmp_path)
        assert a.add_document("x", "hello x", "session")
        docs_before = list(a.documents)
        a.check_stale_and_reload()
        assert a.documents == docs_before  # 未发生 reload


import logging


class TestFailureRecovery:
    """B1：reload 失败不得毒化实例；N1：rebuild 覆盖须记 warning"""

    def test_failed_reload_does_not_poison_instance(self, tmp_path):
        a = BM25Index(index_dir=tmp_path)
        b = BM25Index(index_dir=tmp_path)
        assert b.add_document("x", "hello x", "session")  # v1
        pkl_path = tmp_path / BM25Index.INDEX_FILENAME
        good_bytes = pkl_path.read_bytes()
        # 磁盘 pkl 损坏 → a 的 save 失败且不写盘，实例不得被毒化
        pkl_path.write_bytes(b"corrupted")
        assert a.add_document("y", "local y", "session") is False
        assert pkl_path.read_bytes() == b"corrupted"
        # 磁盘恢复后，下一次 save 必须 reload + 重放 pending，而不是用旧/空内存覆盖
        pkl_path.write_bytes(good_bytes)
        assert a.add_document("z", "local z", "session") is True
        ids = _load_disk_ids(tmp_path)
        assert "x" in ids
        assert "y" in ids
        assert "z" in ids

    def test_rebuild_overwrite_logs_warning(self, tmp_path, caplog):
        a = BM25Index(index_dir=tmp_path)
        b = BM25Index(index_dir=tmp_path)
        assert b.add_document("old", "old note", "session")  # v1
        with caplog.at_level(logging.WARNING, logger="jfox.bm25_index"):
            assert a.rebuild_from_notes([_note("n1")])
        assert any("覆盖" in r.message for r in caplog.records)
