"""Dimension mismatch warnings must surface to users, not stay in logs (#442)."""

import numpy as np

from jfox.vector_store import VectorStore


def _dimension_error():
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
