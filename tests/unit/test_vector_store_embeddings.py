"""批量读取已存向量及只读快照的测试。"""

import shutil
from unittest.mock import MagicMock, patch

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
    assert metadata[0] is not None
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


def _database_with_wal(tmp_path):
    database = tmp_path / "chroma_db"
    database.mkdir()
    (database / "chroma.sqlite3").write_bytes(b"db-v1")
    (database / "chroma.sqlite3-wal").write_bytes(b"wal-v1")
    segment = database / "segment"
    segment.mkdir()
    (segment / "data.bin").write_bytes(b"segment-v1")
    return database


def _copy_test_tree(source, target):
    target.mkdir(parents=True)
    for source_path in source.rglob("*"):
        relative_path = source_path.relative_to(source)
        target_path = target / relative_path
        if source_path.is_dir():
            target_path.mkdir(parents=True, exist_ok=True)
        else:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source_path, target_path)
    return target


def test_snapshot_retries_when_recursive_manifest_changes(tmp_path):
    database = _database_with_wal(tmp_path)
    copy_attempt = 0

    def copy_then_change_source(source, target):
        nonlocal copy_attempt
        copy_attempt += 1
        result = _copy_test_tree(source, target)
        if copy_attempt == 1:
            (database / "chroma.sqlite3-wal").write_bytes(b"wal-v2-longer")
            (database / "segment" / "data.bin").write_bytes(b"segment-v2-longer")
        return result

    client = MagicMock()
    collection = MagicMock()
    client.get_collection.return_value = collection
    with (
        patch("jfox.vector_store.shutil.copytree", side_effect=copy_then_change_source),
        patch("jfox.vector_store.chromadb.PersistentClient", return_value=client),
    ):
        store = VectorStore(persist_directory=database)
        assert store._get_existing_collection() is collection

    snapshot = getattr(store, "_read_only_snapshot", None)
    assert snapshot is not None
    assert (snapshot / "chroma.sqlite3-wal").read_bytes() == b"wal-v2-longer"
    assert (snapshot / "segment" / "data.bin").read_bytes() == b"segment-v2-longer"


def test_snapshot_retries_after_copy_failure_and_returns_complete_copy(tmp_path):
    database = _database_with_wal(tmp_path)
    copy_attempt = 0

    def fail_once_then_copy(source, target):
        nonlocal copy_attempt
        copy_attempt += 1
        if copy_attempt == 1:
            target.mkdir(parents=True)
            (target / "partial").write_bytes(b"partial")
            raise OSError("temporary Windows file lock")
        return _copy_test_tree(source, target)

    client = MagicMock()
    client.get_collection.return_value = MagicMock()
    with (
        patch("jfox.vector_store.shutil.copytree", side_effect=fail_once_then_copy),
        patch("jfox.vector_store.chromadb.PersistentClient", return_value=client),
    ):
        store = VectorStore(persist_directory=database)
        store._get_existing_collection()

    snapshot = getattr(store, "_read_only_snapshot", None)
    assert snapshot is not None
    assert not (snapshot / "partial").exists()
    assert (snapshot / "chroma.sqlite3").read_bytes() == b"db-v1"
    assert (snapshot / "chroma.sqlite3-wal").read_bytes() == b"wal-v1"


def test_snapshot_final_failure_cleans_up_and_explains_daemon_write(tmp_path):
    database = _database_with_wal(tmp_path)

    with patch(
        "jfox.vector_store.shutil.copytree",
        side_effect=OSError("persistent Windows file lock"),
    ):
        store = VectorStore(persist_directory=database)
        with pytest.raises(VectorStoreReadError) as error:
            store._get_existing_collection()

    message = str(error.value).lower()
    assert "daemon" in message
    assert "稍后重试" in str(error.value)
    assert store.client is None
    assert store.collection is None
    assert store._read_only_tempdir is None
    assert getattr(store, "_read_only_snapshot", None) is None
    assert (database / "chroma.sqlite3").read_bytes() == b"db-v1"
