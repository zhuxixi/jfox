"""conftest 共享 mock 的契约测试。目标: tests/conftest.py MockEmbeddingBackend"""

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_mock_embedding_backend_has_encode_single(mock_embedding_backend):
    """共享 mock 应实现 encode_single（vector_store.add_note 调用；缺了打 AttributeError 日志）"""
    assert hasattr(mock_embedding_backend, "encode_single"), (
        "conftest MockEmbeddingBackend 缺 encode_single，"
        "vector_store.add_note 会打 AttributeError 日志（#392 B1）"
    )
    vec = mock_embedding_backend.encode_single("hello")
    assert vec.shape == (384,)
