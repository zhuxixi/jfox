"""
BM25Index.add_documents_batch() 单元测试
"""

from unittest.mock import MagicMock, patch

import pytest

from jfox.bm25_index import BM25Index


@pytest.fixture
def bm25(tmp_path):
    """提供干净的 BM25Index 实例，索引目录指向临时目录"""
    with patch.object(BM25Index, "_load", return_value=False):
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
        """异常时返回 False 并恢复索引状态（包括 bm25 对象）"""
        bm25.add_documents_batch([("id1", "first doc")])  # add something first
        count_before = len(bm25.doc_ids)
        original_tokenize = bm25._tokenize
        bm25._tokenize = MagicMock(side_effect=RuntimeError("boom"))
        result = bm25.add_documents_batch([("id2", "test")])
        assert result is False
        # 恢复原始 _tokenize 以便搜索正常工作
        bm25._tokenize = original_tokenize
        # 状态应恢复到错误前
        assert len(bm25.doc_ids) == count_before
        # bm25 对象也应恢复，搜索仍能正常工作
        results = bm25.search("first doc", top_k=1)
        assert len(results) == 1
        assert results[0]["note_id"] == "id1"

    def test_save_failure_rolls_back(self, bm25):
        """_save 失败时，应回滚所有状态（包括 bm25 对象）"""
        bm25.add_documents_batch([("id1", "alpha beta")])

        # 让 _save 失败
        bm25._save = MagicMock(return_value=False)
        result = bm25.add_documents_batch([("id2", "gamma delta")])
        assert result is False

        # 索引应回滚到只有 id1 的状态
        assert len(bm25.doc_ids) == 1
        assert bm25.doc_ids == ["id1"]
        # bm25 对象也应恢复，搜索仍能找到 id1
        results = bm25.search("alpha", top_k=1)
        assert len(results) == 1
        assert results[0]["note_id"] == "id1"

    def test_appends_to_existing_index(self, bm25):
        """批量添加应追加到已有索引，不覆盖"""
        bm25.add_documents_batch([("id1", "alpha beta")])
        bm25.add_documents_batch([("id2", "gamma delta")])

        assert len(bm25.doc_ids) == 2
        results_alpha = bm25.search("alpha", top_k=2)
        results_gamma = bm25.search("gamma", top_k=2)
        assert any(r["note_id"] == "id1" for r in results_alpha)
        assert any(r["note_id"] == "id2" for r in results_gamma)


class TestBulkImportBM25Integration:
    """测试 bulk_import_notes 是否正确调用 BM25 索引"""

    @patch("jfox.bm25_index.get_bm25_index")
    @patch("jfox.vector_store.get_vector_store")
    @patch("jfox.embedding_backend.get_backend")
    @patch("jfox.note.create_note")
    def test_bulk_import_calls_bm25_batch(
        self, mock_create_note, mock_get_backend, mock_get_vs, mock_get_bm25, tmp_path
    ):
        """bulk_import_notes 应调用 add_documents_batch 更新 BM25 索引"""
        import numpy as np

        from jfox.models import Note, NoteType
        from jfox.performance import bulk_import_notes

        # 准备 mock note
        mock_note = MagicMock(spec=Note)
        mock_note.id = "20260411120000"
        mock_note.title = "测试笔记"
        mock_note.content = "这是测试内容"
        mock_note.type = NoteType.PERMANENT
        mock_note.tags = []
        mock_note.filepath = tmp_path / "notes" / "permanent" / "test.md"
        mock_note.to_markdown.return_value = "# 测试笔记\n这是测试内容"
        mock_create_note.return_value = mock_note

        # mock embedding backend
        mock_backend = MagicMock()
        mock_backend.model = MagicMock()
        mock_backend.encode.return_value = np.array([[0.1] * 384])
        mock_get_backend.return_value = mock_backend

        # mock vector store
        mock_vs = MagicMock()
        mock_vs.collection = MagicMock()
        mock_get_vs.return_value = mock_vs

        # mock BM25
        mock_bm25 = MagicMock()
        mock_bm25.add_documents_batch.return_value = True
        mock_get_bm25.return_value = mock_bm25

        notes_data = [{"title": "测试笔记", "content": "这是测试内容"}]
        bulk_import_notes(notes_data, show_progress=False)

        # 验证 BM25 batch 被调用
        mock_bm25.add_documents_batch.assert_called_once()
        call_args = mock_bm25.add_documents_batch.call_args[0][0]
        assert len(call_args) == 1
        assert call_args[0] == ("20260411120000", "测试笔记 这是测试内容")

    @patch("jfox.bm25_index.get_bm25_index")
    @patch("jfox.vector_store.get_vector_store")
    @patch("jfox.embedding_backend.get_backend")
    @patch("jfox.note.create_note")
    def test_bulk_import_bm25_failure_does_not_fail_import(
        self, mock_create_note, mock_get_backend, mock_get_vs, mock_get_bm25, tmp_path
    ):
        """BM25 更新失败不应导致整个导入失败"""
        import numpy as np

        from jfox.models import Note, NoteType
        from jfox.performance import bulk_import_notes

        mock_note = MagicMock(spec=Note)
        mock_note.id = "20260411120001"
        mock_note.title = "测试"
        mock_note.content = "内容"
        mock_note.type = NoteType.PERMANENT
        mock_note.tags = []
        mock_note.filepath = tmp_path / "notes" / "permanent" / "test.md"
        mock_note.to_markdown.return_value = "# 测试\n内容"
        mock_create_note.return_value = mock_note

        mock_backend = MagicMock()
        mock_backend.model = MagicMock()
        mock_backend.encode.return_value = np.array([[0.1] * 384])
        mock_get_backend.return_value = mock_backend

        mock_vs = MagicMock()
        mock_vs.collection = MagicMock()
        mock_get_vs.return_value = mock_vs

        # BM25 抛异常
        mock_bm25 = MagicMock()
        mock_bm25.add_documents_batch.side_effect = Exception("BM25 error")
        mock_get_bm25.return_value = mock_bm25

        notes_data = [{"title": "测试", "content": "内容"}]
        result = bulk_import_notes(notes_data, show_progress=False)

        # 导入仍然成功（BM25 错误被 try/except 包裹）
        assert result["imported"] == 1

    @patch("jfox.bm25_index.get_bm25_index")
    @patch("jfox.vector_store.get_vector_store")
    @patch("jfox.embedding_backend.get_backend")
    @patch("jfox.note.create_note")
    def test_bulk_import_multi_batch_calls_bm25_per_batch(
        self, mock_create_note, mock_get_backend, mock_get_vs, mock_get_bm25, tmp_path
    ):
        """多批次导入时，每批都应调用 BM25 batch 更新"""
        import numpy as np

        from jfox.models import Note, NoteType
        from jfox.performance import bulk_import_notes

        notes = []
        for i in range(5):
            n = MagicMock(spec=Note)
            n.id = f"2026041112000{i}"
            n.title = f"笔记{i}"
            n.content = f"内容{i}"
            n.type = NoteType.PERMANENT
            n.tags = []
            n.filepath = tmp_path / "notes" / "permanent" / f"test{i}.md"
            n.to_markdown.return_value = f"# 笔记{i}\n内容{i}"
            notes.append(n)

        mock_create_note.side_effect = notes

        mock_backend = MagicMock()
        mock_backend.model = MagicMock()
        mock_backend.encode.return_value = np.array([[0.1] * 384] * 3)
        mock_get_backend.return_value = mock_backend

        mock_vs = MagicMock()
        mock_vs.collection = MagicMock()
        mock_get_vs.return_value = mock_vs

        mock_bm25 = MagicMock()
        mock_bm25.add_documents_batch.return_value = True
        mock_get_bm25.return_value = mock_bm25

        notes_data = [{"title": f"笔记{i}", "content": f"内容{i}"} for i in range(5)]
        result = bulk_import_notes(notes_data, batch_size=3, show_progress=False)

        # batch_size=3, 5 notes = 2 batches
        assert result["imported"] == 5
        assert mock_bm25.add_documents_batch.call_count == 2

    @patch("jfox.bm25_index.get_bm25_index")
    @patch("jfox.embedding_backend.get_backend")
    @patch("jfox.note.create_note")
    def test_bulk_import_with_uninitialized_vectorstore(
        self, mock_create_note, mock_get_backend, mock_get_bm25, tmp_path
    ):
        """bulk_import_notes 应在 collection.add() 前自动初始化 VectorStore"""
        import numpy as np

        from jfox.models import Note, NoteType
        from jfox.performance import bulk_import_notes

        # 准备 mock note
        mock_note = MagicMock(spec=Note)
        mock_note.id = "20260413120000"
        mock_note.title = "测试初始化"
        mock_note.content = "内容"
        mock_note.type = NoteType.PERMANENT
        mock_note.tags = []
        mock_note.filepath = tmp_path / "notes" / "permanent" / "test.md"
        mock_note.to_markdown.return_value = "# 测试初始化\n内容"
        mock_create_note.return_value = mock_note

        # mock embedding backend
        mock_backend = MagicMock()
        mock_backend.model = MagicMock()
        mock_backend.encode.return_value = np.array([[0.1] * 384])
        mock_get_backend.return_value = mock_backend

        # mock BM25
        mock_bm25 = MagicMock()
        mock_bm25.add_documents_batch.return_value = True
        mock_get_bm25.return_value = mock_bm25

        # 不 mock get_vector_store，让真实的 VectorStore 被创建
        # 但 patch 掉 VectorStore.init 来验证它被调用了
        with patch("jfox.vector_store.get_vector_store") as mock_get_vs:
            mock_vs = MagicMock()
            # 关键：collection 初始为 None，模拟真实场景
            mock_vs.collection = None

            # init() 会设置 collection
            def fake_init():
                mock_vs.collection = MagicMock()

            mock_vs.init.side_effect = fake_init
            mock_get_vs.return_value = mock_vs

            notes_data = [{"title": "测试初始化", "content": "内容"}]
            result = bulk_import_notes(notes_data, show_progress=False)

            # 验证 init 被调用了
            mock_vs.init.assert_called()
            # 导入成功
            assert result["imported"] == 1
