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
