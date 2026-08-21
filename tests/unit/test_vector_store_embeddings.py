"""Tests for bulk reading stored vector embeddings."""

from unittest.mock import MagicMock

import numpy as np
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.vector_store import VectorStore, VectorStoreReadError


def test_get_all_embeddings_filters_note_type():
    store = VectorStore()
    store.collection = MagicMock()
    store.collection.get.return_value = {
        "ids": ["p1"],
        "metadatas": [{"type": "permanent", "title": "P1"}],
        "embeddings": [[1.0, 0.0]],
    }

    ids, metadata, embeddings = store.get_all_embeddings("permanent")

    store.collection.get.assert_called_once_with(
        include=["embeddings", "metadatas"],
        where={"type": "permanent"},
    )
    assert ids == ["p1"]
    assert metadata[0]["title"] == "P1"
    np.testing.assert_array_equal(embeddings, np.array([[1.0, 0.0]], dtype=np.float32))


def test_get_all_embeddings_does_not_create_missing_database(tmp_path):
    store = VectorStore(persist_directory=tmp_path / "missing")

    with pytest.raises(VectorStoreReadError, match="does not exist"):
        store.get_all_embeddings("permanent")

    assert not (tmp_path / "missing").exists()


def test_get_all_embeddings_opens_existing_collection_without_get_or_create(tmp_path):
    database = tmp_path / "chroma_db"
    database.mkdir()
    (database / "chroma.sqlite3").touch()
    client = MagicMock()
    collection = MagicMock()
    client.get_collection.return_value = collection
    collection.get.return_value = {"ids": [], "metadatas": [], "embeddings": []}
    store = VectorStore(persist_directory=database)
    store.client = client

    store.get_all_embeddings()

    client.get_collection.assert_called_once_with(name="notes")
    client.get_or_create_collection.assert_not_called()


def test_get_all_embeddings_empty_collection():
    store = VectorStore()
    store.collection = MagicMock()
    store.collection.get.return_value = {"ids": [], "metadatas": [], "embeddings": []}

    ids, metadata, embeddings = store.get_all_embeddings()

    assert ids == []
    assert metadata == []
    assert embeddings.shape == (0, 0)
    assert embeddings.dtype == np.float32
