"""
BM25Index.add_documents_batch() 单元测试
"""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from jfox.bm25_index import BM25Index


@pytest.fixture
def bm25(tmp_path):
    """提供干净的 BM25Index 实例，索引目录指向临时目录"""
    with patch.object(BM25Index, '_load', return_value=False):
        idx = BM25Index(index_dir=tmp_path)
    # 阻止自动保存，减少 IO
    idx._save = MagicMock(return_value=True)
    return idx


class TestAddDocumentsBatch:
    """测试 add_documents_batch 方法"""

    def test_adds_multiple_documents(self, bm25):
        """批量添加多个文档后，doc_ids 和 doc_mapping 应包含所有文档"""
        docs = [
            ("id1", "hello world"),
            ("id2", "foo bar baz"),
            ("id3", "测试中文内容"),
        ]
        result = bm25.add_documents_batch(docs)

        assert result is True
        assert len(bm25.doc_ids) == 3
        assert "id1" in bm25.doc_mapping
        assert "id2" in bm25.doc_mapping
        assert "id3" in bm25.doc_mapping

    def test_builds_valid_bm25_index(self, bm25):
        """批量添加后 BM25 索引应可用，搜索能返回结果"""
        docs = [
            ("id1", "machine learning algorithm"),
            ("id2", "deep learning neural network"),
            ("id3", "natural language processing"),
        ]
        bm25.add_documents_batch(docs)

        results = bm25.search("machine learning", top_k=3)
        assert len(results) > 0
        assert results[0]["note_id"] == "id1"

    def test_single_rebuild_per_batch(self, bm25):
        """批量添加应只触发一次 _rebuild_index 和一次 _save"""
        bm25._rebuild_index = MagicMock()
        bm25._save = MagicMock(return_value=True)

        docs = [("id1", "a"), ("id2", "b"), ("id3", "c")]
        bm25.add_documents_batch(docs)

        bm25._rebuild_index.assert_called_once()
        bm25._save.assert_called_once()

    def test_empty_batch_returns_true(self, bm25):
        """空批次不触发 rebuild，直接返回 True"""
        bm25._rebuild_index = MagicMock()
        result = bm25.add_documents_batch([])

        assert result is True
        bm25._rebuild_index.assert_not_called()

    def test_handles_duplicate_ids(self, bm25):
        """重复 ID 应覆盖旧文档（先移除再添加）"""
        bm25.add_documents_batch([("id1", "old content")])
        bm25.add_documents_batch([("id1", "new content")])

        assert len(bm25.doc_ids) == 1
        results = bm25.search("new content", top_k=1)
        assert results[0]["note_id"] == "id1"

    def test_returns_false_on_error(self, bm25):
        """异常时返回 False 并恢复索引状态"""
        bm25.add_documents_batch([("id1", "first doc")])  # add something first
        count_before = len(bm25.doc_ids)
        bm25._tokenize = MagicMock(side_effect=RuntimeError("boom"))
        result = bm25.add_documents_batch([("id2", "test")])
        assert result is False
        # 状态应恢复到错误前
        assert len(bm25.doc_ids) == count_before

    def test_appends_to_existing_index(self, bm25):
        """批量添加应追加到已有索引，不覆盖"""
        bm25.add_documents_batch([("id1", "alpha beta")])
        bm25.add_documents_batch([("id2", "gamma delta")])

        assert len(bm25.doc_ids) == 2
        results_alpha = bm25.search("alpha", top_k=2)
        results_gamma = bm25.search("gamma", top_k=2)
        assert any(r["note_id"] == "id1" for r in results_alpha)
        assert any(r["note_id"] == "id2" for r in results_gamma)
