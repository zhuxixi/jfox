"""
BM25Index 并发写防护（#391）单元测试

用两个共享同一索引目录的 BM25Index 实例模拟 CLI 与 daemon 两个进程的交错写。
"""

import json
import pickle
from pathlib import Path
from unittest.mock import patch

from filelock import Timeout

from jfox.bm25_index import BM25Index


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
