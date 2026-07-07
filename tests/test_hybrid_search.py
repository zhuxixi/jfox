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

    def test_search_with_note_type_filter(self):
        """测试按笔记类型过滤 BM25 搜索结果"""
        with tempfile.TemporaryDirectory() as tmpdir:
            index = BM25Index(index_dir=Path(tmpdir))

            index.add_document("note1", "Python programming guide", note_type="permanent")
            index.add_document("note2", "Python programming session", note_type="session")
            index.add_document("note3", "Python quick tips", note_type="permanent")

            results = index.search("Python", top_k=5, note_type="permanent")

            assert len(results) == 2
            note_ids = [r["note_id"] for r in results]
            assert "note1" in note_ids
            assert "note3" in note_ids
            assert "note2" not in note_ids

    def test_search_with_note_type_no_match(self):
        """测试按笔记类型过滤无匹配时返回空列表"""
        with tempfile.TemporaryDirectory() as tmpdir:
            index = BM25Index(index_dir=Path(tmpdir))

            index.add_document("note1", "Python programming", note_type="session")
            index.add_document("note2", "Python session log", note_type="session")

            results = index.search("Python", top_k=5, note_type="permanent")
            assert results == []

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

        # BM25 结果会经过 tags / 归档过滤，需要 mock load_note_by_id
        import jfox.note as note_module

        original_load = note_module.load_note_by_id
        mock_note = MagicMock()
        mock_note.content = "note content"
        mock_note.title = "Note"
        mock_note.type.value = "permanent"
        mock_note.archived = False
        mock_note.tags = []
        note_module.load_note_by_id = lambda nid: mock_note

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

    def test_keyword_search_respects_top_k(self):
        """测试 keyword 模式返回结果数量不超过 top_k"""
        from unittest.mock import MagicMock

        import jfox.note as note_module

        bm25 = MagicMock()
        bm25.search.return_value = [{"note_id": f"n{i}", "score": float(10 - i)} for i in range(10)]

        original_load = note_module.load_note_by_id
        mock_note = MagicMock()
        mock_note.content = "content"
        mock_note.title = "Note"
        mock_note.tags = []
        mock_note.type.value = "permanent"
        mock_note.archived = False
        note_module.load_note_by_id = lambda nid: mock_note

        try:
            engine = HybridSearchEngine(vector_store=MagicMock(), bm25_index=bm25)
            results = engine.search("test", top_k=3, mode=SearchMode.KEYWORD)

            assert len(results) == 3
        finally:
            note_module.load_note_by_id = original_load

    def test_keyword_search_with_tags_expands_search_k(self):
        """测试 keyword 模式有 tags / 归档过滤时扩展 search_k"""
        from unittest.mock import MagicMock

        import jfox.note as note_module

        bm25 = MagicMock()
        bm25.search.return_value = [{"note_id": f"n{i}", "score": float(10 - i)} for i in range(25)]

        original_load = note_module.load_note_by_id
        mock_note = MagicMock()
        mock_note.content = "content"
        mock_note.title = "Note"
        mock_note.tags = ["python"]
        mock_note.type.value = "permanent"
        mock_note.archived = False
        note_module.load_note_by_id = lambda nid: mock_note

        try:
            engine = HybridSearchEngine(vector_store=MagicMock(), bm25_index=bm25)
            engine.search("test", top_k=5, mode=SearchMode.KEYWORD, tags=["python"])

            bm25.search.assert_called_once_with("test", top_k=25, note_type=None)
        finally:
            note_module.load_note_by_id = original_load

    def test_keyword_search_with_note_type_filter(self):
        """测试 keyword 模式按笔记类型过滤"""
        from unittest.mock import MagicMock

        import jfox.note as note_module

        def _bm25_search(query, top_k, note_type=None):
            # 模拟 BM25 已按 note_type 过滤
            all_results = [
                {"note_id": "n1", "score": 5.0},
                {"note_id": "n2", "score": 3.0},
            ]
            if note_type == "permanent":
                return [r for r in all_results if r["note_id"] == "n1"]
            return all_results

        bm25 = MagicMock()
        bm25.search.side_effect = _bm25_search

        original_load = note_module.load_note_by_id

        def _make_note(note_id):
            note = MagicMock()
            note.content = f"{note_id} content"
            note.title = f"Note {note_id}"
            note.tags = []
            note.archived = False
            note.type.value = "permanent" if note_id == "n1" else "session"
            return note

        note_module.load_note_by_id = lambda nid: _make_note(nid)

        try:
            engine = HybridSearchEngine(vector_store=MagicMock(), bm25_index=bm25)
            results = engine.search(
                "test",
                top_k=5,
                mode=SearchMode.KEYWORD,
                note_type="permanent",
                include_archived=True,
            )

            assert len(results) == 1
            assert results[0]["id"] == "n1"
            assert results[0]["metadata"]["type"] == "permanent"
            # 验证 BM25 搜索时传入了 note_type；仅 note_type 过滤时不应扩展 search_k
            bm25.search.assert_called_once_with("test", top_k=5, note_type="permanent")
        finally:
            note_module.load_note_by_id = original_load

    def test_hybrid_search_with_note_type_filter(self):
        """测试 hybrid 模式按笔记类型过滤 BM25 分支"""
        from unittest.mock import MagicMock

        import jfox.note as note_module

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

        # BM25 结果会经过 tags / 归档过滤，需要 mock load_note_by_id
        original_load = note_module.load_note_by_id
        mock_note = MagicMock()
        mock_note.content = "note content"
        mock_note.title = "Note"
        mock_note.type.value = "permanent"
        mock_note.archived = False
        mock_note.tags = []
        note_module.load_note_by_id = lambda nid: mock_note

        try:
            engine = HybridSearchEngine(vector_store=vs, bm25_index=bm25, rrf_k=60)
            results = engine.search(
                "test",
                top_k=5,
                mode=SearchMode.HYBRID,
                note_type="permanent",
                include_archived=True,
            )

            # 语义分支和 BM25 分支都应传入 note_type
            vs.search.assert_called_once_with("test", top_k=10, note_type="permanent", tags=None)
            bm25.search.assert_called_once_with("test", top_k=10, note_type="permanent")

            # 结果只包含目标类型（语义结果 n1/n2 假设已过滤；BM25 n2/n3 由 mock 模拟已过滤）
            ids = [r.get("id") or r.get("note_id") for r in results]
            assert "n1" in ids
            assert "n2" in ids
            assert "n3" in ids
        finally:
            note_module.load_note_by_id = original_load

    def test_auto_rebuild_on_v1_index_migration(self):
        """测试 search_engine 检测到 v1 索引时自动触发重建回填 doc_types"""
        from unittest.mock import MagicMock, patch

        bm25 = MagicMock()
        bm25.needs_rebuild = True
        bm25.rebuild_from_notes.return_value = True

        with patch.object(
            HybridSearchEngine, "rebuild_bm25_index", return_value=True
        ) as mock_rebuild:
            HybridSearchEngine(vector_store=MagicMock(), bm25_index=bm25)

            mock_rebuild.assert_called_once()
            assert not bm25.needs_rebuild

    def test_auto_rebuild_failure_keeps_flag(self):
        """测试 v1 索引自动重建失败时保留 needs_rebuild 标志"""
        from unittest.mock import MagicMock, patch

        bm25 = MagicMock()
        bm25.needs_rebuild = True

        with patch.object(
            HybridSearchEngine, "rebuild_bm25_index", return_value=False
        ) as mock_rebuild:
            HybridSearchEngine(vector_store=MagicMock(), bm25_index=bm25)

            mock_rebuild.assert_called_once()
            assert bm25.needs_rebuild

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
        mock_note.archived = False
        mock_note.tags = []
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

    def test_load_v1_index_migrates_doc_types(self):
        """测试加载 v1 索引时自动补齐 doc_types 并可正常搜索"""
        import pickle

        from jfox.bm25_index import BM25Index

        with tempfile.TemporaryDirectory() as tmpdir:
            index_dir = Path(tmpdir)

            # 构造一个 v1 索引（没有 doc_types）
            index1 = BM25Index(index_dir=index_dir)
            index1.add_document("note1", "Python programming guide")

            # 手动把索引存成 v1 格式
            index_data = {
                "bm25": index1.bm25,
                "documents": index1.documents,
                "doc_ids": index1.doc_ids,
                "doc_mapping": index1.doc_mapping,
                # 故意不存 doc_types
            }
            with open(index_dir / "bm25_index.pkl", "wb") as f:
                pickle.dump(index_data, f)
            with open(index_dir / "bm25_metadata.json", "w", encoding="utf-8") as f:
                import json

                json.dump({"version": 1, "doc_count": 1}, f)

            # 新实例应能加载 v1 索引
            index2 = BM25Index(index_dir=index_dir)
            results = index2.search("Python", top_k=5)
            assert len(results) > 0
            assert results[0]["note_id"] == "note1"
            # doc_types 被补齐为 None，并标记需要重建
            assert index2.doc_types == [None]
            assert index2.needs_rebuild

    def test_load_v2_missing_doc_types_triggers_rebuild(self):
        """测试 v2 索引缺失 doc_types 时同样触发 needs_rebuild"""
        import pickle

        from jfox.bm25_index import BM25Index

        with tempfile.TemporaryDirectory() as tmpdir:
            index_dir = Path(tmpdir)

            index1 = BM25Index(index_dir=index_dir)
            index1.add_document("note1", "Python programming guide")

            index_data = {
                "bm25": index1.bm25,
                "documents": index1.documents,
                "doc_ids": index1.doc_ids,
                "doc_mapping": index1.doc_mapping,
            }
            with open(index_dir / "bm25_index.pkl", "wb") as f:
                pickle.dump(index_data, f)
            with open(index_dir / "bm25_metadata.json", "w", encoding="utf-8") as f:
                import json

                json.dump({"version": 2, "doc_count": 1}, f)

            index2 = BM25Index(index_dir=index_dir)
            assert index2.doc_types == [None]
            assert index2.needs_rebuild

    def test_load_corrupted_index_resets_state(self):
        """测试持久化文件长度不一致时安全重置"""
        import pickle

        from jfox.bm25_index import BM25Index

        with tempfile.TemporaryDirectory() as tmpdir:
            index_dir = Path(tmpdir)

            # 构造长度不一致的损坏索引
            index_data = {
                "bm25": None,
                "documents": [["python"]],
                "doc_ids": ["note1", "note2"],
                "doc_types": [None],
                "doc_mapping": {"note1": 0, "note2": 1},
            }
            with open(index_dir / "bm25_index.pkl", "wb") as f:
                pickle.dump(index_data, f)
            with open(index_dir / "bm25_metadata.json", "w", encoding="utf-8") as f:
                import json

                json.dump({"version": 2, "doc_count": 2}, f)

            index = BM25Index(index_dir=index_dir)
            # 损坏索引应被重置
            assert index.doc_ids == []
            assert index.documents == []
            assert index.doc_types == []
            assert index.doc_mapping == {}
            assert index.search("Python", top_k=5) == []

    def test_load_corrupted_mapping_resets_state(self):
        """测试 doc_mapping 与 doc_ids 不对应时安全重置"""
        import pickle

        from jfox.bm25_index import BM25Index

        with tempfile.TemporaryDirectory() as tmpdir:
            index_dir = Path(tmpdir)

            # doc_mapping 与 doc_ids 顺序不一致
            index_data = {
                "bm25": None,
                "documents": [["python"]],
                "doc_ids": ["note1"],
                "doc_types": [None],
                "doc_mapping": {"note1": 1},  # 越界
            }
            with open(index_dir / "bm25_index.pkl", "wb") as f:
                pickle.dump(index_data, f)
            with open(index_dir / "bm25_metadata.json", "w", encoding="utf-8") as f:
                import json

                json.dump({"version": 2, "doc_count": 1}, f)

            index = BM25Index(index_dir=index_dir)
            assert index.doc_ids == []
            assert index.search("Python", top_k=5) == []

    def test_load_invalid_doc_types_resets_state(self):
        """测试 doc_types 元素类型非法时安全重置"""
        import pickle

        from jfox.bm25_index import BM25Index

        with tempfile.TemporaryDirectory() as tmpdir:
            index_dir = Path(tmpdir)

            index_data = {
                "bm25": None,
                "documents": [["python"]],
                "doc_ids": ["note1"],
                "doc_types": [123],  # 非法类型
                "doc_mapping": {"note1": 0},
            }
            with open(index_dir / "bm25_index.pkl", "wb") as f:
                pickle.dump(index_data, f)
            with open(index_dir / "bm25_metadata.json", "w", encoding="utf-8") as f:
                import json

                json.dump({"version": 2, "doc_count": 1}, f)

            index = BM25Index(index_dir=index_dir)
            assert index.doc_ids == []
            assert index.search("Python", top_k=5) == []

    def test_load_bm25_none_resets_state(self):
        """测试 bm25 为 None 但其他字段有效时安全重置"""
        import pickle

        from jfox.bm25_index import BM25Index

        with tempfile.TemporaryDirectory() as tmpdir:
            index_dir = Path(tmpdir)

            index_data = {
                "bm25": None,
                "documents": [["python"]],
                "doc_ids": ["note1"],
                "doc_types": [None],
                "doc_mapping": {"note1": 0},
            }
            with open(index_dir / "bm25_index.pkl", "wb") as f:
                pickle.dump(index_data, f)
            with open(index_dir / "bm25_metadata.json", "w", encoding="utf-8") as f:
                import json

                json.dump({"version": 2, "doc_count": 1}, f)

            index = BM25Index(index_dir=index_dir)
            assert index.doc_ids == []
            assert index.bm25 is None
            assert index.search("Python", top_k=5) == []

    def test_add_document_with_enum_note_type(self):
        """测试 add_document 接受 NoteType 枚举并取 .value"""
        from enum import Enum

        with tempfile.TemporaryDirectory() as tmpdir:
            index = BM25Index(index_dir=Path(tmpdir))

            class DummyType(Enum):
                PERMANENT = "permanent"

            index.add_document("note1", "Python programming", note_type=DummyType.PERMANENT)
            assert index.doc_types == ["permanent"]

            index.add_document("note2", "Java programming", note_type=123)
            assert index.doc_types[1] == "123"

    def test_rebuild_from_notes_is_atomic_on_save_failure(self):
        """测试 rebuild_from_notes 在保存失败时回滚到之前状态并恢复 needs_rebuild"""
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            index = BM25Index(index_dir=Path(tmpdir))
            index.add_document("note1", "Python programming", note_type="permanent")

            original_doc_ids = list(index.doc_ids)
            original_bm25 = index.bm25
            index.needs_rebuild = True

            with patch.object(index, "_save", return_value=False):
                result = index.rebuild_from_notes([])

            assert result is False
            assert index.doc_ids == original_doc_ids
            assert index.bm25 is original_bm25
            assert index.needs_rebuild is True

    def test_rebuild_from_notes_is_atomic_on_exception(self):
        """测试 rebuild_from_notes 在异常时回滚到之前状态"""
        from unittest.mock import patch

        with tempfile.TemporaryDirectory() as tmpdir:
            index = BM25Index(index_dir=Path(tmpdir))
            index.add_document("note1", "Python programming", note_type="permanent")

            original_doc_ids = list(index.doc_ids)
            original_bm25 = index.bm25

            with patch.object(index, "_tokenize", side_effect=RuntimeError("tokenize error")):
                result = index.rebuild_from_notes(
                    [type("N", (), {"id": "n", "title": "t", "content": "c", "type": None})()]
                )

            assert result is False
            assert index.doc_ids == original_doc_ids
            assert index.bm25 is original_bm25

    def test_load_doc_types_not_list_resets_state(self):
        """测试 doc_types 不是 list 时安全重置"""
        import pickle

        from jfox.bm25_index import BM25Index

        with tempfile.TemporaryDirectory() as tmpdir:
            index_dir = Path(tmpdir)

            # doc_types 是长度匹配的字符串，元素类型校验会通过但 append 会失败
            index_data = {
                "bm25": None,
                "documents": [],
                "doc_ids": [],
                "doc_types": "",  # 空字符串长度为 0
                "doc_mapping": {},
            }
            with open(index_dir / "bm25_index.pkl", "wb") as f:
                pickle.dump(index_data, f)
            with open(index_dir / "bm25_metadata.json", "w", encoding="utf-8") as f:
                import json

                json.dump({"version": 2, "doc_count": 0}, f)

            index = BM25Index(index_dir=index_dir)
            assert index.doc_types == []
            # 验证后续 add_document 不会崩溃
            index.add_document("note1", "Python programming", note_type="permanent")
            assert index.doc_types == ["permanent"]

    def test_rebuild_from_notes_clears_needs_rebuild(self):
        """测试 rebuild_from_notes 成功后清除 needs_rebuild"""
        from jfox.bm25_index import BM25Index

        with tempfile.TemporaryDirectory() as tmpdir:
            index = BM25Index(index_dir=Path(tmpdir))
            index.needs_rebuild = True

            class DummyNote:
                def __init__(self):
                    self.id = "note1"
                    self.title = "Title"
                    self.content = "Python programming"
                    self.type = None

            assert index.rebuild_from_notes([DummyNote()])
            assert index.needs_rebuild is False

    def test_rebuild_from_notes_normalizes_enum_type(self):
        """测试 rebuild_from_notes 对枚举类型取 .value"""
        from enum import Enum

        from jfox.bm25_index import BM25Index

        class DummyType(Enum):
            PERMANENT = "permanent"

        class DummyNote:
            def __init__(self, note_id, title, content, note_type):
                self.id = note_id
                self.title = title
                self.content = content
                self.type = note_type

        with tempfile.TemporaryDirectory() as tmpdir:
            index = BM25Index(index_dir=Path(tmpdir))
            note = DummyNote("note1", "Title", "Python programming", DummyType.PERMANENT)
            assert index.rebuild_from_notes([note])
            assert index.doc_types == ["permanent"]

    def test_needs_rebuild_persisted_to_metadata(self):
        """测试 needs_rebuild 标志持久化到 metadata"""
        import json

        from jfox.bm25_index import BM25Index

        with tempfile.TemporaryDirectory() as tmpdir:
            index_dir = Path(tmpdir)
            index = BM25Index(index_dir=index_dir)
            index.add_document("note1", "Python programming", note_type="permanent")
            index.needs_rebuild = True
            index._save()

            with open(index_dir / "bm25_metadata.json", "r", encoding="utf-8") as f:
                metadata = json.load(f)
            assert metadata.get("needs_rebuild") is True

            # 新实例加载时应读取到 needs_rebuild
            index2 = BM25Index(index_dir=index_dir)
            assert index2.needs_rebuild is True

    def test_clear_resets_needs_rebuild(self):
        """测试 clear() 后 needs_rebuild 被重置"""
        from jfox.bm25_index import BM25Index

        with tempfile.TemporaryDirectory() as tmpdir:
            index = BM25Index(index_dir=Path(tmpdir))
            index.add_document("note1", "Python programming")
            index.needs_rebuild = True

            index.clear()
            assert index.needs_rebuild is False

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
