# MOC Density Diagnose Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `jfox moc diagnose`, a read-only permanent-note clustering diagnostic that compares index coverage, sweeps semantic thresholds, reports MOC candidates, and excludes orphan vectors.

**Architecture:** Extend `VectorStore` with a typed bulk embedding reader, keep cosine/connected-component clustering as pure numpy/networkx functions in `jfox/moc/cluster.py`, and put KB/index/graph coordination behind `diagnose_moc_density()`. A separate Typer sub-app formats the returned dataclasses as table or JSON; no clustering code imports Typer or Rich.

**Tech Stack:** Python 3.10+, numpy (already transitively installed and already imported by jfox), networkx, ChromaDB, Typer, Rich, pytest.

## Global Constraints

- Scope is permanent notes only; session, candidate, fleeting, and archived permanent notes do not participate in clustering.
- The command is read-only: it must not create, modify, archive, or delete notes or indexes.
- Do not call the embedding daemon; read embeddings already stored in ChromaDB and compute similarity on CPU.
- Add no new third-party dependency and do not edit `pyproject.toml` or `uv.lock` for this feature.
- Resolve live notes with `NoteIndex` / frontmatter IDs; never reuse `indexer._extract_note_id_from_filename()` because it rejects legacy filenames.
- Default thresholds are exactly `0.55,0.6,0.65,0.7`; default `min_size=3`, `suggest_threshold=0.65`, and `top=10`.
- Preserve `--kb`, `--format table|json`, and `--json` conventions used by existing jfox commands.
- Tests must be fast and must not load a real embedding model or ChromaDB database unless the collection is mocked.

---

## File Structure

- `jfox/vector_store.py`: one collection-boundary API for reading IDs, metadata, and embeddings.
- `jfox/moc/__init__.py`: package marker and public diagnostic exports.
- `jfox/moc/cluster.py`: dataclasses, pure similarity/clustering functions, coverage/orphan filtering, graph enrichment, and the diagnostic service.
- `jfox/moc/cli.py`: Typer sub-app, option validation, Rich table rendering, JSON serialization.
- `jfox/cli.py`: register `moc_app` as the top-level `moc` command group.
- `tests/unit/test_vector_store_embeddings.py`: collection contract tests without real ChromaDB.
- `tests/unit/test_moc_cluster.py`: pure algorithms plus mocked service orchestration.
- `tests/unit/test_moc_cli.py`: command registration, parameter validation, table/JSON output.
- `jfox/bm25_index.py`: Black-only cleanup already identified on current main; no behavior change.

---

### Task 1: Typed bulk embedding read boundary

**Files:**
- Modify: `jfox/vector_store.py:1-204`
- Create: `tests/unit/test_vector_store_embeddings.py`

**Interfaces:**
- Produces: `VectorStore.get_all_embeddings(note_type: Optional[str] = None) -> tuple[list[str], list[dict[str, Any]], np.ndarray]`
- The returned array is `float32` with shape `(N, D)`; an empty result is `np.empty((0, 0), dtype=np.float32)`.
- `note_type` becomes a Chroma `where={"type": note_type}` filter; `None` performs no metadata filtering.

- [ ] **Step 1: Write failing collection-contract tests**

```python
import numpy as np

from jfox.vector_store import VectorStore


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


def test_get_all_embeddings_empty_collection():
    store = VectorStore()
    store.collection = MagicMock()
    store.collection.get.return_value = {"ids": [], "metadatas": [], "embeddings": []}

    ids, metadata, embeddings = store.get_all_embeddings()

    assert ids == []
    assert metadata == []
    assert embeddings.shape == (0, 0)
    assert embeddings.dtype == np.float32
```

- [ ] **Step 2: Run tests and confirm the new API is absent**

Run: `uv run pytest tests/unit/test_vector_store_embeddings.py -q`

Expected: FAIL with `AttributeError: 'VectorStore' object has no attribute 'get_all_embeddings'`.

- [ ] **Step 3: Implement the minimal bulk reader**

Add `import numpy as np`, extend typing imports with `Tuple`, and implement:

```python
def get_all_embeddings(
    self, note_type: Optional[str] = None
) -> Tuple[List[str], List[Dict[str, Any]], np.ndarray]:
    """Return indexed IDs, metadata, and stored embeddings without re-encoding text."""
    if self.collection is None:
        self.init()

    kwargs: Dict[str, Any] = {"include": ["embeddings", "metadatas"]}
    if note_type is not None:
        kwargs["where"] = {"type": note_type}

    result = self.collection.get(**kwargs)
    ids = list(result.get("ids") or [])
    metadatas = list(result.get("metadatas") or [])
    raw_embeddings = result.get("embeddings")
    if raw_embeddings is None or len(raw_embeddings) == 0:
        return ids, metadatas, np.empty((0, 0), dtype=np.float32)
    return ids, metadatas, np.asarray(raw_embeddings, dtype=np.float32)
```

Do not swallow collection errors: the caller must distinguish an unavailable vector index from a genuinely empty collection.

- [ ] **Step 4: Run focused tests**

Run: `uv run pytest tests/unit/test_vector_store_embeddings.py tests/unit/test_vector_store_clear.py -q`

Expected: all PASS.

- [ ] **Step 5: Commit the boundary**

```bash
git add jfox/vector_store.py tests/unit/test_vector_store_embeddings.py
git commit -m "feat(moc): expose stored embeddings for diagnostics"
```

---

### Task 2: Pure semantic clustering kernel

**Files:**
- Create: `jfox/moc/__init__.py`
- Create: `jfox/moc/cluster.py`
- Create: `tests/unit/test_moc_cluster.py`

**Interfaces:**
- Produces: `ClusterMember`, `ClusterSummary`, `ThresholdSummary`, `CoverageReport`, `OrphanSummary`, and `MocDiagnoseReport` dataclasses.
- Produces: `compute_similarity(embeddings: np.ndarray) -> np.ndarray`.
- Produces: `find_clusters_at_threshold(similarity: np.ndarray, threshold: float, min_size: int) -> list[list[int]]`.
- Produces: `build_threshold_summary(...) -> ThresholdSummary`.
- All output ordering is deterministic: clusters sort by descending size then lowest member index; members sort by input index.

- [ ] **Step 1: Write failing pure-algorithm tests**

Use two obvious pairs plus one isolated vector:

```python
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
```

Also cover: empty `(0, 0)` input, a zero vector, `min_size < 2`, non-square similarity, all-similar input, and all-unrelated input.

- [ ] **Step 2: Run tests and confirm import failure**

Run: `uv run pytest tests/unit/test_moc_cluster.py -q`

Expected: FAIL because `jfox.moc.cluster` does not exist.

- [ ] **Step 3: Implement dataclasses and pure functions**

Key implementation rules:

```python
def compute_similarity(embeddings: np.ndarray) -> np.ndarray:
    matrix = np.asarray(embeddings, dtype=np.float32)
    if matrix.ndim != 2:
        raise ValueError("embeddings must be a two-dimensional matrix")
    if matrix.shape[0] == 0:
        return np.empty((0, 0), dtype=np.float32)
    norms = np.linalg.norm(matrix, axis=1, keepdims=True)
    normalized = np.divide(matrix, norms, out=np.zeros_like(matrix), where=norms != 0)
    similarity = normalized @ normalized.T
    np.fill_diagonal(similarity, 0.0)
    return similarity


def find_clusters_at_threshold(similarity, threshold, min_size):
    if min_size < 2:
        raise ValueError("min_size must be at least 2")
    if similarity.ndim != 2 or similarity.shape[0] != similarity.shape[1]:
        raise ValueError("similarity must be a square matrix")
    graph = nx.Graph()
    graph.add_nodes_from(range(similarity.shape[0]))
    rows, cols = np.where(np.triu(similarity > threshold, k=1))
    graph.add_edges_from(zip(rows.tolist(), cols.tolist()))
    clusters = [sorted(component) for component in nx.connected_components(graph)]
    clusters = [component for component in clusters if len(component) >= min_size]
    return sorted(clusters, key=lambda c: (-len(c), c[0]))
```

Use strict `>` consistently and document it; this avoids ambiguous equality at thresholds.

- [ ] **Step 4: Run pure tests**

Run: `uv run pytest tests/unit/test_moc_cluster.py -q`

Expected: all pure algorithm tests PASS.

- [ ] **Step 5: Commit the clustering kernel**

```bash
git add jfox/moc/__init__.py jfox/moc/cluster.py tests/unit/test_moc_cluster.py
git commit -m "feat(moc): add semantic clustering kernel"
```

---

### Task 3: Permanent-note coverage, orphan filtering, and graph enrichment

**Files:**
- Modify: `jfox/moc/cluster.py`
- Modify: `tests/unit/test_moc_cluster.py`

**Interfaces:**
- Consumes: `VectorStore.get_all_embeddings("permanent")` from Task 1.
- Consumes: `get_note_index(config).get_all_meta()` and keeps `meta.type == NoteType.PERMANENT and not meta.archived`.
- Consumes: `BM25Index(index_dir=config.zk_dir)`; match permanent entries by zipping `doc_ids` and `doc_types`.
- Consumes: `KnowledgeGraph(config).build()` and each live permanent ID's graph degree.
- Produces: `diagnose_moc_density(config: ZKConfig, thresholds: Sequence[float], min_size: int, suggest_threshold: float, top: int) -> MocDiagnoseReport`.

- [ ] **Step 1: Add failing service tests with mocked boundaries**

Build 5 live permanent `NoteMeta` entries plus one archived permanent entry. Mock vector data with:

- 5 live IDs,
- 1 archived ID,
- 1 nonexistent orphan-vector ID,
- metadata titles for all IDs,
- embeddings where live IDs form two pairs and one semantic orphan.

Assert:

```python
report.coverage.filesystem == 5
report.coverage.vector == 7
report.coverage.vector_orphans == 2  # archived + nonexistent
report.coverage.bm25 == 4
report.coverage.bm25_coverage_ratio == 0.8
assert all(member.id not in {"archived", "ghost"} for c in report.suggest.clusters for member in c.members)
assert report.suggest.clusters[0].hub.link_degree >= report.suggest.clusters[0].members[-1].link_degree
```

Add a test proving a graph-build exception becomes a warning and hub selection falls back to highest mean in-cluster similarity. Add a test proving an empty permanent vector set raises a dedicated `MocDiagnoseError` with an index-rebuild hint.

- [ ] **Step 2: Run service tests and confirm missing orchestration**

Run: `uv run pytest tests/unit/test_moc_cluster.py -q`

Expected: new tests FAIL because `diagnose_moc_density` and service dataclasses are absent/incomplete.

- [ ] **Step 3: Implement permanent filtering and coverage calculation**

Implementation sequence:

1. Build `live_meta_by_id` from NoteIndex, excluding archived and non-permanent notes.
2. Read all permanent vector rows. Keep the first row for each live ID and report every archived/nonexistent/duplicate row as an orphan warning/count. Preserve vector input order for deterministic clustering.
3. Count BM25 permanent IDs using `doc_types == "permanent"`; coverage ratio is `bm25_count / filesystem_count`, or `None` when filesystem count is zero.
4. Add a warning when BM25 ratio is below `0.9`; add a warning when vector orphans are non-zero.
5. Calculate each threshold summary using the same filtered matrix.
6. Build KnowledgeGraph once; degree is `graph.in_degree(id) + graph.out_degree(id)`. If graph construction fails, append a warning and use mean in-cluster semantic similarity for hub selection.
7. Define semantic orphans at `suggest_threshold` as live vectors not in any cluster of `min_size`; define the final orphan list as the union of semantic orphans and live permanent IDs with graph degree zero.
8. Sort suggested clusters by `(-size, hub.title, hub.id)`, cap only the `suggest.clusters` list at `top`, and retain full member lists in each returned cluster.

The service must never delete orphan vectors; it only reports and excludes them.

- [ ] **Step 4: Run cluster/service tests**

Run: `uv run pytest tests/unit/test_moc_cluster.py tests/unit/test_vector_store_embeddings.py -q`

Expected: all PASS.

- [ ] **Step 5: Commit orchestration**

```bash
git add jfox/moc/cluster.py tests/unit/test_moc_cluster.py
git commit -m "feat(moc): diagnose permanent note density"
```

---

### Task 4: `jfox moc diagnose` CLI and stable JSON contract

**Files:**
- Create: `jfox/moc/cli.py`
- Modify: `jfox/cli.py:90-132`
- Create: `tests/unit/test_moc_cli.py`

**Interfaces:**
- Consumes: `diagnose_moc_density(...) -> MocDiagnoseReport`.
- Produces: Typer `moc_app` with the `diagnose` subcommand.
- Produces: `report_to_dict(report) -> dict[str, Any]` with keys `success`, `kb`, `coverage`, `threshold_sweep`, `suggest`, `orphans`, and `warnings`.
- Produces valid JSON without Rich line wrapping or ANSI codes.

- [ ] **Step 1: Write failing command tests**

Mock `jfox.moc.cli.diagnose_moc_density` to return a deterministic report. Verify:

```python
def test_moc_registered_on_root_app():
    result = root_runner.invoke(app, ["moc", "--help"])
    assert result.exit_code == 0
    assert "diagnose" in result.output


def test_diagnose_json_contract():
    result = runner.invoke(moc_app, ["diagnose", "--json"])
    assert result.exit_code == 0
    payload = json.loads(strip_ansi(result.output))
    assert payload["success"] is True
    assert payload["coverage"]["vector_orphans"] == 2
    assert payload["suggest"]["threshold"] == 0.65


def test_suggest_threshold_must_be_in_sweep():
    result = runner.invoke(
        moc_app,
        ["diagnose", "--thresholds", "0.6,0.7", "--suggest-threshold", "0.65"],
    )
    assert result.exit_code == 1
    assert "must be one of" in result.output
```

Also test malformed/duplicate/out-of-range thresholds, `min_size < 2`, `top < 1`, `--kb` propagation through `use_kb`, and `MocDiagnoseError` in both table and JSON modes.

- [ ] **Step 2: Run CLI tests and confirm command absence**

Run: `uv run pytest tests/unit/test_moc_cli.py -q`

Expected: FAIL because `jfox.moc.cli` and root registration do not exist.

- [ ] **Step 3: Implement CLI parsing and output**

Use a local no-color JSON console matching `bookshelf/cli.py`:

```python
moc_app = typer.Typer(name="moc", help="诊断和维护 MOC 结构层", no_args_is_help=True)

@moc_app.command("diagnose")
def diagnose_cmd(
    thresholds: str = typer.Option("0.55,0.6,0.65,0.7", "--thresholds"),
    min_size: int = typer.Option(3, "--min-size"),
    suggest_threshold: float = typer.Option(0.65, "--suggest-threshold"),
    top: int = typer.Option(10, "--top"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k"),
    output_format: str = typer.Option("table", "--format", "-f"),
    json_output: bool = typer.Option(False, "--json"),
) -> None:
    ...
```

Validation rules:

- parse comma-separated floats, strip whitespace, reject empty/duplicate values,
- require every threshold to be strictly between `0` and `1`,
- compare `suggest_threshold` with `math.isclose(..., abs_tol=1e-9)`,
- normalize `--json` to `output_format="json"`,
- reject output formats outside `table|json`,
- wrap diagnostic execution in `with use_kb(kb):`, then construct `ZKConfig` from the active config.

Table rendering has exactly four sections: permanent coverage, threshold sensitivity, suggested MOC clusters, and permanent orphans. Coverage displays only permanent counts; vector orphan count appears as a warning line, not as another note type column.

- [ ] **Step 4: Register the sub-app and run CLI tests**

In `jfox/cli.py`, import and register:

```python
from .moc.cli import moc_app
app.add_typer(moc_app, name="moc", help="诊断和维护 MOC 结构层")
```

Run: `uv run pytest tests/unit/test_moc_cli.py tests/unit/test_index_kb_param.py -q`

Expected: all PASS.

- [ ] **Step 5: Commit CLI and JSON contract**

```bash
git add jfox/moc/cli.py jfox/cli.py tests/unit/test_moc_cli.py
git commit -m "feat(moc): add density diagnose command"
```

---

### Task 5: Formatting cleanup, diagnostics, and real-KB acceptance

**Files:**
- Modify: `jfox/bm25_index.py` (Black-only formatting; no behavior change)
- Modify as required by diagnostics: files changed in Tasks 1-4 only

**Interfaces:**
- Consumes the completed command and test suite.
- Produces a Black-clean branch and captured real-KB diagnostic evidence.

- [ ] **Step 1: Apply Black to the known formatting-only file and changed feature files**

Run:

```bash
uv run black jfox/bm25_index.py jfox/vector_store.py jfox/moc/cli.py jfox/moc/cluster.py tests/unit/test_vector_store_embeddings.py tests/unit/test_moc_cluster.py tests/unit/test_moc_cli.py
```

Review `git diff -- jfox/bm25_index.py`; it must contain formatting changes only. If any semantic change appears, restore that file and investigate before proceeding.

- [ ] **Step 2: Run proactive diagnostics**

Run LSP diagnostics for:

```text
jfox/vector_store.py
jfox/moc/cluster.py
jfox/moc/cli.py
jfox/cli.py
jfox/bm25_index.py
tests/unit/test_vector_store_embeddings.py
tests/unit/test_moc_cluster.py
tests/unit/test_moc_cli.py
```

Expected: no errors.

- [ ] **Step 3: Run focused fast verification**

Run:

```bash
uv run pytest \
  tests/unit/test_vector_store_embeddings.py \
  tests/unit/test_moc_cluster.py \
  tests/unit/test_moc_cli.py \
  tests/unit/test_vector_store_clear.py \
  tests/unit/test_index_kb_param.py \
  tests/unit/test_bm25_batch.py \
  tests/unit/test_bm25_concurrency.py -q
uv run ruff check jfox/vector_store.py jfox/moc jfox/cli.py jfox/bm25_index.py \
  tests/unit/test_vector_store_embeddings.py tests/unit/test_moc_cluster.py tests/unit/test_moc_cli.py
uv run black --check jfox/vector_store.py jfox/moc jfox/cli.py jfox/bm25_index.py \
  tests/unit/test_vector_store_embeddings.py tests/unit/test_moc_cluster.py tests/unit/test_moc_cli.py
```

Expected: all tests PASS; ruff and Black report clean.

- [ ] **Step 4: Run bounded real-KB manual acceptance**

Use the installed/default KB but the worktree code:

```bash
uv run jfox moc diagnose --kb default --json > /tmp/issue-390-diagnose.json
uv run python - <<'PY'
import json
p = json.load(open('/tmp/issue-390-diagnose.json'))
assert p['success'] is True
assert p['coverage']['filesystem'] > 0
assert p['coverage']['bm25_coverage_ratio'] >= 0.9
assert p['coverage']['vector_orphans'] >= 0
assert len(p['threshold_sweep']) == 4
print({
    'coverage': p['coverage'],
    'threshold_sweep': p['threshold_sweep'],
    'suggested_clusters': len(p['suggest']['clusters']),
    'orphans': p['orphans']['count'],
})
PY
uv run jfox moc diagnose --kb default --top 3
```

Expected: JSON parses, BM25 permanent coverage remains at least 90%, four threshold rows exist, and the table contains four readable sections. Do not run full/embedding test suites.

- [ ] **Step 5: Query session diagnostics**

Run `lens_diagnostics mode=all` restricted to the changed files. Expected: no blocking errors; review and disposition any warnings before completion.

- [ ] **Step 6: Commit formatting and verification cleanup**

```bash
git add jfox/bm25_index.py jfox/vector_store.py jfox/moc jfox/cli.py \
  tests/unit/test_vector_store_embeddings.py tests/unit/test_moc_cluster.py tests/unit/test_moc_cli.py
git commit -m "chore: format MOC diagnose changes"
```

If Black created no new changes after Tasks 1-4, skip the empty commit.

- [ ] **Step 7: Final branch state check**

Run:

```bash
git status --short
git log --oneline --decorate -6
```

Expected: clean worktree; design, plan, implementation, and optional formatting commits are visible. Do not push or create a PR until local code review is complete.
