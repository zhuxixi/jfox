"""#519: VectorStore 守卫——typed re-raise、warning 记录、替换写入不删既有行。"""

import numpy as np
import pytest

import jfox.vector_store as vs_mod
from jfox.embedding_backend import EmbedDependencyMissingError, format_embed_hint
from jfox.note import create_note
from jfox.vector_store import VectorStore


def _typed_error():
    return EmbedDependencyMissingError(format_embed_hint("写入语义索引"))


@pytest.fixture
def store(tmp_path):
    s = VectorStore(persist_directory=tmp_path / "chroma")
    s.init()
    return s


def _raising_backend(monkeypatch):
    """backend.encode_single 抛 typed error（模拟无组件且无 daemon）。"""
    import jfox.embedding_backend as eb

    class StubBackend:
        def encode_single(self, text):
            raise _typed_error()

    monkeypatch.setattr(eb, "get_backend", lambda: StubBackend())


def _seed_row(store, note_id):
    store.collection.add(
        ids=[note_id],
        embeddings=[[0.1] * 8],
        documents=["既有向量行"],
        metadatas=[{"title": "t", "type": "fleeting", "filepath": "x", "tags": ""}],
    )


class TestAddNote:
    def test_raises_typed_and_records_warning(self, store, monkeypatch):
        _raising_backend(monkeypatch)
        note = create_note("内容", title="标题")
        with pytest.raises(EmbedDependencyMissingError):
            store.add_note(note)
        assert store.last_embed_warning is not None
        assert "UV_TORCH_BACKEND" in store.last_embed_warning


class TestSearch:
    def test_raises_typed_and_records_warning(self, store, monkeypatch):
        _raising_backend(monkeypatch)
        with pytest.raises(EmbedDependencyMissingError):
            store.search("查询")
        assert store.last_embed_warning is not None


class TestAddOrUpdatePreservesRow:
    def test_no_delete_when_service_unavailable(self, store, monkeypatch):
        note = create_note("内容", title="标题")
        _seed_row(store, note.id)
        _raising_backend(monkeypatch)
        # 服务不可用（本地 False 且无 daemon）→ 不删行
        monkeypatch.setattr(vs_mod, "is_embedding_service_available", lambda: False)
        with pytest.raises(EmbedDependencyMissingError):
            store.add_or_update_note(note)
        assert store.collection.get(ids=[note.id])["ids"] == [note.id]  # 行保留

    def test_replaces_when_service_available(self, store, monkeypatch):
        note = create_note("内容", title="标题")
        _seed_row(store, note.id)
        monkeypatch.setattr(vs_mod, "is_embedding_service_available", lambda: True)

        class WorkingBackend:
            def encode_single(self, text):
                return np.zeros(8, dtype=float)  # ndarray：add_note 会调 .tolist()

        import jfox.embedding_backend as eb

        monkeypatch.setattr(eb, "get_backend", lambda: WorkingBackend())
        assert store.add_or_update_note(note) is True  # 删除 + 重写成功
        assert store.collection.get(ids=[note.id])["ids"] == [note.id]
