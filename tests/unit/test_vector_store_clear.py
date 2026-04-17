"""
测试 VectorStore.clear() 方法

验证 rebuild 前清除旧数据的逻辑
"""

from unittest.mock import MagicMock

import chromadb


class TestVectorStoreClear:
    """VectorStore.clear() 单元测试"""

    def test_clear_removes_all_documents(self):
        """clear() 应删除 collection 中所有文档"""
        from jfox.vector_store import VectorStore

        store = VectorStore()
        # 使用 EphemeralClient 避免文件锁，手动设置 client 和 collection
        client = chromadb.EphemeralClient()
        store.client = client
        store.collection = client.create_collection(
            name="test_clear", metadata={"hnsw:space": "cosine"}
        )

        # 插入 mock 数据（跳过 embedding，直接操作 collection）
        store.collection.add(
            ids=["note_001", "note_002", "note_003"],
            documents=["doc1", "doc2", "doc3"],
            embeddings=[[0.1] * 384, [0.2] * 384, [0.3] * 384],
            metadatas=[
                {"title": "t1", "type": "permanent", "filepath": "/a", "tags": ""},
                {"title": "t2", "type": "permanent", "filepath": "/b", "tags": ""},
                {"title": "t3", "type": "permanent", "filepath": "/c", "tags": ""},
            ],
        )

        assert store.collection.count() == 3

        # 清除
        result = store.clear()

        assert result is True
        assert store.collection.count() == 0

    def test_clear_on_empty_collection(self):
        """clear() 在空 collection 上应正常返回 True"""
        from jfox.vector_store import VectorStore

        store = VectorStore()
        client = chromadb.EphemeralClient()
        store.client = client
        store.collection = client.create_collection(
            name="test_empty", metadata={"hnsw:space": "cosine"}
        )

        assert store.collection.count() == 0

        result = store.clear()

        assert result is True
        assert store.collection.count() == 0

    def test_clear_returns_false_on_failure(self):
        """clear() 在异常时应返回 False 而非抛出"""
        from jfox.vector_store import VectorStore

        store = VectorStore()
        # mock 一个会抛异常的 collection
        store.collection = MagicMock()
        store.collection.get.side_effect = Exception("DB error")

        result = store.clear()

        assert result is False


class TestVectorStoreResetCollection:
    """VectorStore.reset_collection() 单元测试"""

    def test_reset_collection_recreates_collection(self):
        """reset_collection() 应删除旧 collection 并创建新的（维度重置）"""
        from jfox.vector_store import VectorStore

        store = VectorStore()
        client = chromadb.EphemeralClient()
        store.client = client
        store.collection = client.create_collection(
            name="notes", metadata={"hnsw:space": "cosine"}
        )

        # 插入 384 维数据
        store.collection.add(
            ids=["note_001"],
            documents=["doc1"],
            embeddings=[[0.1] * 384],
            metadatas=[{"title": "t1", "type": "permanent", "filepath": "/a", "tags": ""}],
        )
        assert store.collection.count() == 1

        # reset 后 collection 应为空
        result = store.reset_collection()

        assert result is True
        assert store.collection.count() == 0

    def test_reset_collection_on_nonexistent_collection(self):
        """reset_collection() 在 collection 不存在时应正常创建新的"""
        from jfox.vector_store import VectorStore

        store = VectorStore()
        client = chromadb.EphemeralClient()
        store.client = client
        # 不创建 collection，client 上没有 "notes" collection

        result = store.reset_collection()

        assert result is True
        assert store.collection is not None
        assert store.collection.count() == 0

    def test_reset_collection_returns_false_on_failure(self):
        """reset_collection() 在 init 失败时返回 False"""
        from jfox.vector_store import VectorStore

        store = VectorStore()
        store.client = MagicMock()
        # Mock get_or_create_collection 抛异常
        store.client.delete_collection.return_value = None  # 模拟删除成功（可能不存在）
        store.client.get_or_create_collection.side_effect = Exception("DB error")

        result = store.reset_collection()

        assert result is False
