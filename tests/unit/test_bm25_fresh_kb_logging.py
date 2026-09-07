"""#482: fresh-KB metadata absence is an expected path (INFO), not a failure (WARNING).

_read_disk_write_version 的日志级别语义修正：FileNotFoundError → info（与
_load() 的 "BM25 index not found, will create new index" 先例对齐）；真损坏
（JSON 截断 / 字段畸形 / 其他 OSError）保留 warning 留痕。
"""

import json
import logging

from jfox.bm25_index import BM25Index


class TestFreshKbMissingMetadata:
    """A1: 全新 KB（metadata 不存在）→ INFO，无 WARNING"""

    def test_missing_metadata_logs_info_not_warning(self, tmp_path, caplog):
        idx = BM25Index(index_dir=tmp_path)
        with caplog.at_level(logging.INFO, logger="jfox.bm25_index"):
            version = idx._read_disk_write_version()

        assert version == 0
        infos = [
            r for r in caplog.records if r.levelname == "INFO" and "fresh KB" in r.message
        ]
        assert infos, "expected an INFO record mentioning fresh KB"
        warnings = [r for r in caplog.records if r.levelname == "WARNING"]
        assert not warnings, f"fresh KB must not emit WARNING, got: {warnings}"


class TestCorruptedMetadataKeepsWarning:
    """A2: 真损坏场景 WARNING 保留"""

    def test_truncated_json_keeps_warning(self, tmp_path, caplog):
        (tmp_path / BM25Index.METADATA_FILENAME).write_text('{"write_version": ', encoding="utf-8")
        idx = BM25Index(index_dir=tmp_path)
        with caplog.at_level(logging.INFO, logger="jfox.bm25_index"):
            version = idx._read_disk_write_version()

        assert version == 0
        assert any(
            r.levelname == "WARNING" and "Failed to read" in r.message
            for r in caplog.records
        )

    def test_malformed_write_version_field_keeps_warning(self, tmp_path, caplog):
        (tmp_path / BM25Index.METADATA_FILENAME).write_text(
            json.dumps({"write_version": "abc"}), encoding="utf-8"
        )
        idx = BM25Index(index_dir=tmp_path)
        with caplog.at_level(logging.INFO, logger="jfox.bm25_index"):
            version = idx._read_disk_write_version()

        assert version == 0
        assert any(
            r.levelname == "WARNING" and "Failed to read" in r.message
            for r in caplog.records
        )
