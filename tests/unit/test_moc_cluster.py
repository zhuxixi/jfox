"""纯语义聚类辅助函数的测试。"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from jfox.bm25_index import BM25Index
from jfox.config import ZKConfig
from jfox.moc.cluster import (
    MAX_DENSE_CLUSTER_NOTES,
    MocDiagnoseError,
    build_threshold_summary,
    compute_similarity,
    diagnose_moc_density,
    find_clusters_at_threshold,
    semantic_orphan_indices,
)
from jfox.models import NoteType
from jfox.note_index import NoteMeta

assert MAX_DENSE_CLUSTER_NOTES == 5000


VECTORS = np.array(
    [
        [1.0, 0.0, 0.0],
        [0.99, 0.01, 0.0],
        [0.0, 1.0, 0.0],
        [0.01, 0.99, 0.0],
        [0.0, 0.0, 1.0],
    ],
    dtype=np.float32,
)


def test_compute_similarity_normalizes_rows_and_zeros_diagonal():
    similarity = compute_similarity(VECTORS)

    assert similarity.shape == (5, 5)
    np.testing.assert_allclose(np.diag(similarity), 0.0)
    assert similarity[0, 1] > 0.99
    assert similarity[0, 2] < 0.1


def test_find_clusters_returns_two_pairs_and_one_semantic_orphan():
    similarity = compute_similarity(VECTORS)

    clusters = find_clusters_at_threshold(similarity, threshold=0.9, min_size=2)

    assert clusters == [[0, 1], [2, 3]]
    assert semantic_orphan_indices(5, clusters) == [4]


def test_clusters_are_sorted_by_size_then_first_member():
    similarity = compute_similarity(
        np.array(
            [
                [1.0, 0.0],
                [0.99, 0.01],
                [0.98, 0.02],
                [0.0, 1.0],
                [0.01, 0.99],
            ],
            dtype=np.float32,
        )
    )

    assert find_clusters_at_threshold(similarity, threshold=0.9, min_size=2) == [
        [0, 1, 2],
        [3, 4],
    ]


def test_compute_similarity_empty_matrix():
    similarity = compute_similarity(np.empty((0, 0), dtype=np.float32))

    assert similarity.shape == (0, 0)
    assert similarity.dtype == np.float32


def test_compute_similarity_zero_vector_is_finite():
    similarity = compute_similarity(np.array([[0.0, 0.0], [1.0, 0.0]], dtype=np.float32))

    assert np.isfinite(similarity).all()
    np.testing.assert_allclose(similarity, np.zeros((2, 2), dtype=np.float32))


def test_compute_similarity_rejects_non_matrix_input():
    with pytest.raises(ValueError, match="two-dimensional"):
        compute_similarity(np.array([1.0, 0.0], dtype=np.float32))


def test_find_clusters_rejects_invalid_inputs():
    with pytest.raises(ValueError, match="at least 2"):
        find_clusters_at_threshold(np.eye(2), threshold=0.5, min_size=1)

    with pytest.raises(ValueError, match="square"):
        find_clusters_at_threshold(np.zeros((2, 3)), threshold=0.5, min_size=2)


def test_find_clusters_all_unrelated_returns_no_clusters():
    similarity = np.zeros((3, 3), dtype=np.float32)

    assert find_clusters_at_threshold(similarity, threshold=0.5, min_size=2) == []
    assert semantic_orphan_indices(3, []) == [0, 1, 2]


def test_find_clusters_all_similar_returns_one_cluster():
    similarity = np.full((3, 3), 0.9, dtype=np.float32)
    np.fill_diagonal(similarity, 0.0)

    assert find_clusters_at_threshold(similarity, threshold=0.5, min_size=2) == [[0, 1, 2]]


def test_build_threshold_summary_reports_cluster_and_orphan_counts():
    similarity = compute_similarity(VECTORS)

    summary = build_threshold_summary(similarity, threshold=0.9, min_size=2)

    assert summary.threshold == 0.9
    assert summary.cluster_count == 2
    assert summary.max_cluster_size == 2
    assert summary.orphan_count == 1
    assert summary.clusters == [[0, 1], [2, 3]]


def _permanent_meta(note_id: str, title: str, *, archived: bool = False) -> NoteMeta:
    return NoteMeta(
        id=note_id,
        title=title,
        type=NoteType.PERMANENT,
        filepath=str(Path(f"/notes/{note_id}.md")),
        archived=archived,
    )


def test_diagnose_sorting_is_independent_of_vector_store_order():
    config = ZKConfig(base_dir=Path("/tmp/moc-test"))
    metas = [_permanent_meta("p0", "P0"), _permanent_meta("p1", "P1")]
    note_index = MagicMock()
    note_index.get_all_meta.return_value = metas
    graph = MagicMock()
    graph.build.return_value = graph
    graph.graph.in_degree.return_value = 0
    graph.graph.out_degree.return_value = 0
    bm25 = MagicMock(index_path=Path("x"), metadata_path=Path("y"), doc_ids=[], doc_types=[])

    def run(ids):
        vectors = {"p0": [1.0, 0.0], "p1": [0.99, 0.01]}
        store = MagicMock()
        store.get_all_embeddings.return_value = (
            ids,
            [None for _ in ids],
            np.array([vectors[note_id] for note_id in ids], dtype=np.float32),
        )
        with (
            patch("jfox.moc.cluster.get_note_index", return_value=note_index),
            patch("jfox.moc.cluster.VectorStore", return_value=store),
            patch("jfox.moc.cluster.BM25Index", return_value=bm25),
            patch("jfox.moc.cluster.KnowledgeGraph", return_value=graph),
        ):
            report = diagnose_moc_density(config, [0.9], 2, 0.9, 10)
        from jfox.moc.cli import report_to_dict

        return report_to_dict(report, kb="test")

    assert run(["p0", "p1"]) == run(["p1", "p0"])


def test_diagnose_filters_archived_and_orphan_vectors_and_enriches_graph():
    config = ZKConfig(base_dir=Path("/tmp/moc-test"))
    live_meta = [_permanent_meta(f"p{i}", f"Permanent {i}") for i in range(5)]
    archived = _permanent_meta("archived", "Archived", archived=True)
    vector_ids = [f"p{i}" for i in range(5)] + ["archived", "ghost"]
    vector_meta = [{"title": f"Vector {note_id}"} for note_id in vector_ids]
    embeddings = np.array(
        [
            [1.0, 0.0, 0.0],
            [0.99, 0.01, 0.0],
            [0.0, 1.0, 0.0],
            [0.01, 0.99, 0.0],
            [0.0, 0.0, 1.0],
            [1.0, 0.0, 0.0],
            [0.0, 1.0, 0.0],
        ],
        dtype=np.float32,
    )
    graph = MagicMock()
    graph.build.return_value = graph
    graph.graph.in_degree.side_effect = lambda note_id: {"p0": 4, "p1": 1}.get(note_id, 0)
    graph.graph.out_degree.side_effect = lambda note_id: 0

    bm25 = MagicMock(
        doc_ids=["p0", "p1", "p2", "p3", "p3", "archived", "ghost", "p4"],
        doc_types=[
            "permanent",
            "permanent",
            "permanent",
            "permanent",
            "permanent",
            "permanent",
            "permanent",
            "session",
        ],
    )
    note_index = MagicMock()
    note_index.get_all_meta.return_value = live_meta + [archived]
    vector_store = MagicMock()
    vector_store.get_all_embeddings.return_value = (vector_ids, vector_meta, embeddings)

    with (
        patch("jfox.moc.cluster.get_note_index", return_value=note_index),
        patch("jfox.moc.cluster.VectorStore", return_value=vector_store),
        patch("jfox.moc.cluster.BM25Index", return_value=bm25),
        patch("jfox.moc.cluster.KnowledgeGraph", return_value=graph),
    ):
        report = diagnose_moc_density(
            config,
            thresholds=[0.9],
            min_size=2,
            suggest_threshold=0.9,
            top=10,
        )

    assert report.coverage.filesystem == 5
    assert report.coverage.vector == 7
    assert report.coverage.vector_orphans == 2
    assert report.coverage.bm25 == 4
    assert report.coverage.bm25_coverage_ratio == 0.8
    assert report.suggest is not None
    assert report.suggest.clusters[0].hub is not None
    assert all(
        member.id not in {"archived", "ghost"}
        for cluster in report.suggest.clusters
        for member in cluster.members
    )
    assert (
        report.suggest.clusters[0].hub.link_degree
        >= report.suggest.clusters[0].members[-1].link_degree
    )
    p2_orphan = next(note for note in report.orphans.notes if note.id == "p2")
    assert p2_orphan.mean_similarity > 0.0


def test_diagnose_graph_failure_falls_back_to_mean_similarity():
    config = ZKConfig(base_dir=Path("/tmp/moc-test"))
    metas = [_permanent_meta("p0", "P0"), _permanent_meta("p1", "P1")]
    graph = MagicMock()
    graph.build.side_effect = RuntimeError("graph unavailable")
    bm25 = MagicMock(doc_ids=[], doc_types=[])
    note_index = MagicMock()
    note_index.get_all_meta.return_value = metas
    vector_store = MagicMock()
    vector_store.get_all_embeddings.return_value = (
        ["p0", "p1"],
        [{"title": "P0"}, {"title": "P1"}],
        np.array([[1.0, 0.0], [0.99, 0.01]], dtype=np.float32),
    )

    with (
        patch("jfox.moc.cluster.get_note_index", return_value=note_index),
        patch("jfox.moc.cluster.VectorStore", return_value=vector_store),
        patch("jfox.moc.cluster.BM25Index", return_value=bm25),
        patch("jfox.moc.cluster.KnowledgeGraph", return_value=graph),
    ):
        report = diagnose_moc_density(
            config,
            thresholds=[0.9],
            min_size=2,
            suggest_threshold=0.9,
            top=10,
        )

    assert any("graph" in warning.lower() for warning in report.warnings)
    assert report.suggest is not None
    assert report.suggest.clusters[0].hub is not None
    assert report.suggest.clusters[0].hub.mean_similarity == max(
        member.mean_similarity for member in report.suggest.clusters[0].members
    )
    assert report.suggest.clusters[0].hub.mean_similarity > 0.9


def test_diagnose_all_orphan_vectors_returns_empty_clusters():
    config = ZKConfig(base_dir=Path("/tmp/moc-test"))
    metas = [_permanent_meta("p0", "P0", archived=True)]
    note_index = MagicMock()
    note_index.get_all_meta.return_value = metas
    vector_store = MagicMock()
    vector_store.get_all_embeddings.return_value = (
        ["p0", "ghost"],
        [None, {"title": "Ghost"}],
        np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
    )
    graph = MagicMock()
    graph.build.return_value = graph

    with (
        patch("jfox.moc.cluster.get_note_index", return_value=note_index),
        patch("jfox.moc.cluster.VectorStore", return_value=vector_store),
        patch(
            "jfox.moc.cluster.BM25Index",
            return_value=MagicMock(index_path=Path("x"), metadata_path=Path("y")),
        ),
        patch("jfox.moc.cluster.KnowledgeGraph", return_value=graph),
    ):
        report = diagnose_moc_density(config, [0.65], 2, 0.65, 10)

    assert report.coverage.vector_orphans == 2
    assert report.suggest is not None
    assert report.suggest.clusters == []
    assert report.threshold_sweep[0].orphan_count == 0


def test_diagnose_includes_missing_vector_link_orphan_and_flags():
    config = ZKConfig(base_dir=Path("/tmp/moc-test"))
    metas = [_permanent_meta(f"p{i}", f"P{i}") for i in range(5)]
    note_index = MagicMock()
    note_index.get_all_meta.return_value = metas
    vector_store = MagicMock()
    vector_store.get_all_embeddings.return_value = (
        ["p0", "p1", "p2", "p4"],
        [None, None, None, None],
        np.array([[1.0, 0.0], [0.99, 0.01], [0.0, 1.0], [0.0, 0.0]], dtype=np.float32),
    )
    graph = MagicMock()
    graph.build.return_value = graph
    graph.graph.in_degree.side_effect = lambda note_id: {"p0": 1, "p1": 1, "p2": 1}.get(note_id, 0)
    graph.graph.out_degree.return_value = 0
    bm25 = MagicMock(index_path=Path("x"), metadata_path=Path("y"), doc_ids=[], doc_types=[])

    with (
        patch("jfox.moc.cluster.get_note_index", return_value=note_index),
        patch("jfox.moc.cluster.VectorStore", return_value=vector_store),
        patch("jfox.moc.cluster.BM25Index", return_value=bm25),
        patch("jfox.moc.cluster.KnowledgeGraph", return_value=graph),
    ):
        report = diagnose_moc_density(config, [0.65], 2, 0.65, 10)

    orphan = {note.id: note for note in report.orphans.notes}
    assert orphan["p2"].semantic_orphan is True
    assert orphan["p2"].link_orphan is False
    assert orphan["p3"].semantic_orphan is False
    assert orphan["p3"].link_orphan is True
    assert orphan["p4"].semantic_orphan is True
    assert orphan["p4"].link_orphan is True


def test_diagnose_graph_degree_covers_missing_vector_notes():
    config = ZKConfig(base_dir=Path("/tmp/moc-test"))
    metas = [
        _permanent_meta("p0", "P0"),
        _permanent_meta("p1", "P1"),
        _permanent_meta("linked-no-vector", "Linked without vector"),
        _permanent_meta("orphan-no-vector", "Orphan without vector"),
    ]
    note_index = MagicMock()
    note_index.get_all_meta.return_value = metas
    vector_store = MagicMock()
    vector_store.get_all_embeddings.return_value = (
        ["p0", "p1"],
        [None, None],
        np.array([[1.0, 0.0], [0.99, 0.01]], dtype=np.float32),
    )
    graph = MagicMock()
    graph.build.return_value = graph
    graph.graph.in_degree.side_effect = lambda note_id: {
        "p0": 1,
        "p1": 1,
        "linked-no-vector": 1,
    }.get(note_id, 0)
    graph.graph.out_degree.return_value = 0
    bm25 = MagicMock(index_path=Path("x"), metadata_path=Path("y"), doc_ids=[], doc_types=[])

    with (
        patch("jfox.moc.cluster.get_note_index", return_value=note_index),
        patch("jfox.moc.cluster.VectorStore", return_value=vector_store),
        patch("jfox.moc.cluster.BM25Index", return_value=bm25),
        patch("jfox.moc.cluster.KnowledgeGraph", return_value=graph),
    ):
        report = diagnose_moc_density(config, [0.65], 2, 0.65, 10)

    orphan = {note.id: note for note in report.orphans.notes}
    assert "linked-no-vector" not in orphan
    assert orphan["orphan-no-vector"].link_orphan is True
    assert orphan["orphan-no-vector"].semantic_orphan is False
    assert orphan["orphan-no-vector"].link_degree == 0


def test_diagnose_filesystem_failure_skips_unverified_semantic_clusters():
    config = ZKConfig(base_dir=Path("/tmp/moc-test"))
    vector_store = MagicMock()
    vector_store.get_all_embeddings.return_value = (
        ["archived", "ghost"],
        [{"title": "Archived"}, {"title": "Ghost"}],
        np.array([[1.0, 0.0], [0.99, 0.01]], dtype=np.float32),
    )
    with (
        patch("jfox.moc.cluster.get_note_index", side_effect=OSError("notes unreadable")),
        patch("jfox.moc.cluster.VectorStore", return_value=vector_store),
        patch("jfox.moc.cluster.BM25Index", side_effect=OSError("bm25 unreadable")),
    ):
        report = diagnose_moc_density(config, [0.65], 2, 0.65, 10)

    assert report.coverage.filesystem is None
    assert report.suggest is not None
    assert report.suggest.clusters == []
    assert report.threshold_sweep[0].cluster_count == 0
    assert report.threshold_sweep[0].max_cluster_size == 0
    assert report.threshold_sweep[0].orphan_count == 0
    assert report.orphans.notes == []
    assert any("permanent scope unavailable" in warning.lower() for warning in report.warnings)
    assert any("semantic clustering was skipped" in warning.lower() for warning in report.warnings)


def test_diagnose_malformed_bm25_metadata_reports_invalid_and_na_coverage(tmp_path):
    config = ZKConfig(base_dir=tmp_path)
    bm25 = BM25Index(index_dir=config.zk_dir)
    assert bm25.add_document("p0", "indexed content", "permanent")
    (config.zk_dir / BM25Index.METADATA_FILENAME).write_text("{malformed", encoding="utf-8")

    invalid = BM25Index(index_dir=config.zk_dir)
    assert invalid.load_status == "invalid"
    assert invalid.load_error

    note_index = MagicMock()
    note_index.get_all_meta.return_value = [_permanent_meta("p0", "P0")]
    vector_store = MagicMock()
    vector_store.get_all_embeddings.return_value = (
        ["p0"],
        [None],
        np.array([[1.0, 0.0]], dtype=np.float32),
    )

    with (
        patch("jfox.moc.cluster.get_note_index", return_value=note_index),
        patch("jfox.moc.cluster.VectorStore", return_value=vector_store),
    ):
        report = diagnose_moc_density(config, [0.65], 2, 0.65, 10)

    assert report.coverage.bm25 is None
    assert report.coverage.bm25_coverage_ratio is None
    assert any("BM25 coverage unavailable" in warning for warning in report.warnings)


def test_diagnose_rejects_vector_length_mismatch():
    config = ZKConfig(base_dir=Path("/tmp/moc-test"))
    note_index = MagicMock()
    note_index.get_all_meta.return_value = [_permanent_meta("p0", "P0")]
    vector_store = MagicMock()
    vector_store.get_all_embeddings.return_value = (
        ["p0"],
        [None],
        np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
    )
    with (
        patch("jfox.moc.cluster.get_note_index", return_value=note_index),
        patch("jfox.moc.cluster.VectorStore", return_value=vector_store),
    ):
        with pytest.raises(MocDiagnoseError, match="embeddings_shape"):
            diagnose_moc_density(config, [0.65], 2, 0.65, 10)


def _run_diagnose_with_vector_count(note_count: int, dense_limit: int):
    config = ZKConfig(base_dir=Path("/tmp/moc-limit-test"))
    metas = [_permanent_meta(f"p{i}", f"P{i}") for i in range(note_count)]
    note_index = MagicMock()
    note_index.get_all_meta.return_value = metas
    vector_store = MagicMock()
    vector_store.get_all_embeddings.return_value = (
        [meta.id for meta in metas],
        [None] * note_count,
        np.ones((note_count, 2), dtype=np.float32),
    )
    bm25 = MagicMock(doc_ids=[], doc_types=[])
    graph = MagicMock()
    graph.build.return_value = graph
    graph.graph.in_degree.return_value = 0
    graph.graph.out_degree.return_value = 0

    with (
        patch("jfox.moc.cluster.MAX_DENSE_CLUSTER_NOTES", dense_limit),
        patch("jfox.moc.cluster.get_note_index", return_value=note_index),
        patch("jfox.moc.cluster.VectorStore", return_value=vector_store),
        patch("jfox.moc.cluster.BM25Index", return_value=bm25),
        patch("jfox.moc.cluster.KnowledgeGraph", return_value=graph),
    ):
        return diagnose_moc_density(config, [0.65], 2, 0.65, 10)


def test_diagnose_dense_limit_includes_exact_boundary():
    report = _run_diagnose_with_vector_count(note_count=2, dense_limit=2)

    assert report.coverage.filesystem == 2
    assert report.threshold_sweep[0].cluster_count == 1


def test_diagnose_dense_limit_rejects_above_boundary_without_truncation():
    with pytest.raises(MocDiagnoseError) as error:
        _run_diagnose_with_vector_count(note_count=3, dense_limit=2)

    message = str(error.value)
    assert "2" in message
    assert "稀疏" in message
    assert "分块" in message


def test_diagnose_dense_limit_counts_only_verified_unique_live_rows():
    config = ZKConfig(base_dir=Path("/tmp/moc-filtered-limit-test"))
    live = [_permanent_meta("p0", "P0"), _permanent_meta("p1", "P1")]
    archived = _permanent_meta("archived", "Archived", archived=True)
    vector_ids = ["p0", "p1", "p1"] + ["archived"] * 4 + [f"ghost-{i}" for i in range(5)]
    vector_store = MagicMock()
    vector_store.get_all_embeddings.return_value = (
        vector_ids,
        [None] * len(vector_ids),
        np.ones((len(vector_ids), 2), dtype=np.float32),
    )
    note_index = MagicMock()
    note_index.get_all_meta.return_value = live + [archived]
    graph = MagicMock()
    graph.build.return_value = graph
    graph.graph.in_degree.return_value = 0
    graph.graph.out_degree.return_value = 0

    with (
        patch("jfox.moc.cluster.MAX_DENSE_CLUSTER_NOTES", 2),
        patch("jfox.moc.cluster.get_note_index", return_value=note_index),
        patch("jfox.moc.cluster.VectorStore", return_value=vector_store),
        patch(
            "jfox.moc.cluster.BM25Index",
            return_value=MagicMock(doc_ids=[], doc_types=[]),
        ),
        patch("jfox.moc.cluster.KnowledgeGraph", return_value=graph),
        patch("jfox.moc.cluster.compute_similarity", wraps=compute_similarity) as compute,
    ):
        report = diagnose_moc_density(config, [0.65], 2, 0.65, 10)

    assert report.coverage.vector == len(vector_ids)
    assert report.coverage.vector_orphans == len(vector_ids) - 2
    assert compute.call_args.args[0].shape == (2, 2)
    assert report.threshold_sweep[0].cluster_count == 1


def test_diagnose_empty_vectors_raises_rebuild_hint():
    config = ZKConfig(base_dir=Path("/tmp/moc-test"))
    note_index = MagicMock()
    note_index.get_all_meta.return_value = [_permanent_meta("p0", "P0")]
    vector_store = MagicMock()
    vector_store.get_all_embeddings.return_value = ([], [], np.empty((0, 0), dtype=np.float32))

    with (
        patch("jfox.moc.cluster.get_note_index", return_value=note_index),
        patch("jfox.moc.cluster.VectorStore", return_value=vector_store),
    ):
        with pytest.raises(MocDiagnoseError, match="rebuild"):
            diagnose_moc_density(
                config,
                thresholds=[0.9],
                min_size=2,
                suggest_threshold=0.9,
                top=10,
            )
