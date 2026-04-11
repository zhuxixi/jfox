#!/usr/bin/env python
"""
测试混合搜索功能

Issue #17: Hybrid Search: BM25 + Semantic Search
"""

import tempfile
from pathlib import Path

import pytest

from jfox.bm25_index import BM25Index
from jfox.search_engine import HybridSearchEngine, SearchMode


class TestBM25Index:
    """测试 BM25 索引功能"""

    def test_tokenize_chinese(self):
        """测试中文分词"""
        index = BM25Index()
        tokens = index._tokenize("今天学习了 Python 的 async/await 机制")

        assert isinstance(tokens, list)
        assert len(tokens) > 0
        # 应该包含中文字符和英文单词
        assert any(t in ["今天", "学", "习", "了"] for t in tokens)
        assert any("python" in t for t in tokens)

    def test_tokenize_english(self):
        """测试英文分词"""
        index = BM25Index()
        tokens = index._tokenize("Python async await function")

        assert isinstance(tokens, list)
        assert "python" in tokens
        assert "async" in tokens
        assert "await" in tokens
        assert "function" in tokens

    def test_tokenize_empty(self):
        """测试空内容分词"""
        index = BM25Index()
        tokens = index._tokenize("")
        assert tokens == []

    def test_add_and_search_document(self):
        """测试添加和搜索文档"""
        with tempfile.TemporaryDirectory() as tmpdir:
            index = BM25Index(index_dir=Path(tmpdir))

            # 添加文档
            success = index.add_document("note1", "Python programming guide")
            assert success

            # 搜索
            results = index.search("Python", top_k=5)
            assert isinstance(results, list)
            assert len(results) > 0
            assert results[0]["note_id"] == "note1"

    def test_remove_document(self):
        """测试移除文档"""
        with tempfile.TemporaryDirectory() as tmpdir:
            index = BM25Index(index_dir=Path(tmpdir))

            # 添加文档
            index.add_document("note1", "Python programming")
            index.add_document("note2", "JavaScript programming")

            # 移除
            success = index.remove_document("note1")
            assert success

            # 搜索
            results = index.search("Python", top_k=5)
            note_ids = [r["note_id"] for r in results]
            assert "note1" not in note_ids

    def test_search_ranking(self):
        """测试搜索结果排序"""
        with tempfile.TemporaryDirectory() as tmpdir:
            index = BM25Index(index_dir=Path(tmpdir))

            # 添加多个文档
            index.add_document("note1", "Python Python Python programming")
            index.add_document("note2", "Python programming guide")
            index.add_document("note3", "Java programming")

            # 搜索
            results = index.search("Python", top_k=5)

            # 分数应该递减
            for i in range(len(results) - 1):
                assert results[i]["score"] >= results[i + 1]["score"]

    def test_get_stats(self):
        """测试获取统计信息"""
        with tempfile.TemporaryDirectory() as tmpdir:
            index = BM25Index(index_dir=Path(tmpdir))

            # 添加文档
            index.add_document("note1", "Python programming")

            stats = index.get_stats()
            assert "indexed" in stats
            assert "version" in stats
            assert stats["indexed"] >= 0


class TestHybridSearchEngine:
    """测试混合搜索引擎"""

    def test_search_modes(self):
        """测试不同搜索模式"""
        HybridSearchEngine()

        # 测试模式转换
        assert SearchMode.HYBRID.value == "hybrid"
        assert SearchMode.SEMANTIC.value == "semantic"
        assert SearchMode.KEYWORD.value == "keyword"

    def test_rrf_fusion_with_mock_data(self):
        """测试 RRF 融合逻辑：两个搜索源都有结果时，正确融合排序"""
        from unittest.mock import MagicMock

        vs = MagicMock()
        vs.search.return_value = [
            {"id": "n1", "document": "doc1", "score": 0.9},
            {"id": "n2", "document": "doc2", "score": 0.7},
        ]
        bm25 = MagicMock()
        bm25.search.return_value = [
            {"note_id": "n2", "score": 5.0},
            {"note_id": "n3", "score": 3.0},
        ]

        # n3 只在 BM25 中，需要 mock load_note_by_id
        import jfox.note as note_module

        original_load = note_module.load_note_by_id
        mock_note = MagicMock()
        mock_note.content = "n3 content"
        mock_note.title = "N3 Note"
        mock_note.type.value = "permanent"
        note_module.load_note_by_id = lambda nid: mock_note if nid == "n3" else None

        try:
            engine = HybridSearchEngine(vector_store=vs, bm25_index=bm25, rrf_k=60)
            results = engine.search("test", top_k=5, mode=SearchMode.HYBRID)

            # 应该融合来自两个源的结果
            ids = [r.get("id") or r.get("note_id") for r in results]
            assert "n2" in ids  # n2 同时出现在两个源中，RRF 分数最高
            assert "n1" in ids
            assert "n3" in ids
            # 所有结果都应标记为 hybrid
            for r in results:
                assert r["search_mode"] == "hybrid"
        finally:
            note_module.load_note_by_id = original_load

    def test_fallback_to_semantic(self):
        """测试 BM25 无结果时回退到语义搜索"""
        from unittest.mock import MagicMock

        vs = MagicMock()
        vs.search.return_value = [
            {"id": "n1", "document": "doc1", "score": 0.9},
        ]
        bm25 = MagicMock()
        bm25.search.return_value = []  # BM25 无结果

        engine = HybridSearchEngine(vector_store=vs, bm25_index=bm25)
        results = engine.search("test", top_k=5, mode=SearchMode.HYBRID)

        assert len(results) == 1
        assert results[0]["id"] == "n1"
        assert results[0]["search_mode"] == "semantic"

    def test_fallback_to_keyword(self):
        """测试语义搜索无结果时回退到关键词搜索"""
        from unittest.mock import MagicMock

        vs = MagicMock()
        vs.search.return_value = []  # 语义搜索无结果
        bm25 = MagicMock()
        bm25.search.return_value = [
            {"note_id": "n1", "score": 5.0},
        ]

        # _keyword_search 会调用 note_module.load_note_by_id，需要 mock
        import jfox.note as note_module

        original_load = note_module.load_note_by_id

        mock_note = MagicMock()
        mock_note.content = "test content"
        mock_note.title = "Test Note"
        mock_note.type.value = "permanent"
        note_module.load_note_by_id = lambda nid: mock_note if nid == "n1" else None

        try:
            engine = HybridSearchEngine(vector_store=vs, bm25_index=bm25)
            results = engine.search("test", top_k=5, mode=SearchMode.HYBRID)

            assert len(results) == 1
            assert results[0]["id"] == "n1"
            assert results[0]["search_mode"] == "keyword"
        finally:
            note_module.load_note_by_id = original_load


class TestSearchIntegration:
    """测试搜索集成"""

    def test_search_notes_with_mode(self):
        """测试 note.search_notes 的 mode 参数"""
        from jfox.note import search_notes

        # 空查询应返回空列表
        results = search_notes("nonexistent_query_xyz", top_k=5, mode="hybrid")
        assert isinstance(results, list)

    def test_search_notes_semantic_mode(self):
        """测试语义搜索模式"""
        from jfox.note import search_notes

        results = search_notes("test", top_k=5, mode="semantic")
        assert isinstance(results, list)

    def test_search_notes_keyword_mode(self):
        """测试关键词搜索模式"""
        from jfox.note import search_notes

        results = search_notes("test", top_k=5, mode="keyword")
        assert isinstance(results, list)


class TestBM25Persistence:
    """测试 BM25 索引持久化"""

    def test_save_and_load(self):
        """测试保存和加载索引"""
        with tempfile.TemporaryDirectory() as tmpdir:
            index_dir = Path(tmpdir)

            # 创建索引并添加文档
            index1 = BM25Index(index_dir=index_dir)
            index1.add_document("note1", "Python programming guide")

            # 创建新实例，应该能加载已有索引
            index2 = BM25Index(index_dir=index_dir)
            results = index2.search("Python", top_k=5)

            assert len(results) > 0
            assert results[0]["note_id"] == "note1"

    def test_clear_index(self):
        """测试清空索引"""
        with tempfile.TemporaryDirectory() as tmpdir:
            index = BM25Index(index_dir=Path(tmpdir))
            index.add_document("note1", "Python programming")

            # 清空
            success = index.clear()
            assert success

            # 搜索应该返回空
            results = index.search("Python", top_k=5)
            assert len(results) == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
