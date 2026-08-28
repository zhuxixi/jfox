"""Dimension mismatch warnings must surface to users, not stay in logs (#442)."""

import numpy as np

from jfox.vector_store import VectorStore


def _dimension_error():
    """Real chromadb (>=0.5) dimension-mismatch message.

    Embedding dim (model, 512) comes first; collection dim (index, 384) second.
    """
    return ValueError("Embedding dimension 512 does not match collection dimensionality 384")


def _legacy_dimension_error():
    """Legacy/wrapper message shape kept as a fallback path."""
    return ValueError(
        "InvalidDimensionalityException: Collection expecting embedding with "
        "dimension of 384, got 512"
    )


class _FakeCollectionRaises:
    """Collection whose query/add always raise a dimension mismatch error."""

    def query(self, **kwargs):
        raise _dimension_error()

    def add(self, **kwargs):
        raise _dimension_error()


class _FakeType:
    value = "fleeting"


class _FakeNote:
    id = "20260828"
    title = "t"
    content = "c"
    type = _FakeType()
    tags = []
    filepath = "/tmp/fake.md"


class _FakeBackend:
    """Backend returning 512-dim numpy vectors (real ones carry .tolist())."""

    def encode_single(self, text):
        return np.zeros(512, dtype="float32")


def _make_store(tmp_path, monkeypatch):
    vs = VectorStore(persist_directory=tmp_path / "chroma")
    monkeypatch.setattr(vs, "init", lambda: None)
    vs.collection = _FakeCollectionRaises()
    monkeypatch.setattr("jfox.embedding_backend.get_backend", lambda: _FakeBackend())
    return vs


class TestDimensionWarning:
    def test_init_has_none_warning(self, tmp_path):
        vs = VectorStore(persist_directory=tmp_path / "chroma")
        assert vs.last_dimension_warning is None

    def test_search_sets_warning(self, tmp_path, monkeypatch):
        vs = _make_store(tmp_path, monkeypatch)

        results = vs.search("任何查询")

        assert results == []
        assert vs.last_dimension_warning is not None
        assert "384" in vs.last_dimension_warning and "512" in vs.last_dimension_warning
        # Real chromadb format: model dim first, collection dim second —
        # warning must label index dim 384 and model dim 512 in that order.
        assert "索引维度(384)" in vs.last_dimension_warning
        assert "模型维度(512)" in vs.last_dimension_warning
        assert "daemon restart" in vs.last_dimension_warning

    def test_add_sets_warning(self, tmp_path, monkeypatch):
        vs = _make_store(tmp_path, monkeypatch)

        ok = vs.add_note(_FakeNote())

        assert ok is False
        assert vs.last_dimension_warning is not None
        assert "index rebuild" in vs.last_dimension_warning
        assert "384" in vs.last_dimension_warning and "512" in vs.last_dimension_warning

    def test_non_dimension_errors_do_not_set_warning(self, tmp_path, monkeypatch):
        vs = VectorStore(persist_directory=tmp_path / "chroma")
        monkeypatch.setattr(vs, "init", lambda: None)

        class _OtherError:
            def query(self, **kwargs):
                raise RuntimeError("connection refused")

        vs.collection = _OtherError()
        monkeypatch.setattr("jfox.embedding_backend.get_backend", lambda: _FakeBackend())

        results = vs.search("任何查询")

        assert results == []
        assert vs.last_dimension_warning is None

    def test_dimension_warning_text_without_numbers(self):
        text = VectorStore._dimension_warning_text(
            "InvalidDimensionalityException: expecting embedding with wrong dimension"
        )
        assert text is not None
        assert "daemon restart" in text
        assert VectorStore._dimension_warning_text("some other error") is None

    def test_warning_text_legacy_format(self):
        """Legacy 'dimension of X, got Y' messages keep working (X=index dim)."""
        text = VectorStore._dimension_warning_text(str(_legacy_dimension_error()))
        assert text is not None
        assert "索引维度(384)" in text
        assert "模型维度(512)" in text

    def test_warning_text_real_format_dim_order(self):
        """Real chromadb message: model dim first, collection dim second."""
        text = VectorStore._dimension_warning_text(str(_dimension_error()))
        assert text is not None
        assert "索引维度(384)" in text
        assert "模型维度(512)" in text
        # The two dims must not be swapped: index(384) precedes model(512)
        assert text.index("索引维度(384)") < text.index("模型维度(512)")
