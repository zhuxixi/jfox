# Louvain MOC Clustering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace MOC density clustering's transitive connected-component behavior with deterministic, weighted Louvain community detection and raise only MOC command defaults to the validated 0.75 threshold.

**Architecture:** Keep `find_clusters_at_threshold(similarity, threshold, min_size)` as the public pure-function boundary. It will build the same thresholded graph, attach cosine similarity as edge weight, call NetworkX's built-in Louvain implementation with `resolution=1.0` and `seed=42`, then preserve the existing filtering and ordering contract. The validation script will retain a private implementation of the pre-#439 connected-components algorithm so its before/after comparison remains truthful after production code changes.

**Tech Stack:** Python 3.10+, NetworkX >= 3.0, NumPy, pytest, Typer, uv

## Global Constraints

- Python >= 3.10.
- Use NetworkX's built-in `networkx.algorithms.community.louvain_communities`; do not add a dependency.
- Preserve `find_clusters_at_threshold(similarity: np.ndarray, threshold: float, min_size: int) -> List[List[int]]`.
- Pass `weight="weight"`, `resolution=1.0`, and `seed=42` to production Louvain.
- Preserve `min_size` filtering and the existing cluster ordering `(-len(cluster), cluster[0])`.
- Change defaults only for MOC commands: create/update threshold `0.75`; diagnose thresholds `0.70,0.75,0.78,0.80`; diagnose suggestion `0.75`.
- Do not modify embedding, vector-store, search, graph-link, `--max-size`, or MOC data files.
- Do not add a production feature flag or expose `--resolution` in the MOC CLI.
- Work only in `/home/elling/git-repo/github/jfox/.pi/worktrees/issue-439-louvain-moc-clustering`; never modify the main checkout.
- Use `git add` with explicit paths; never use `git add -A`.

## File Structure

**Modified production files:**

- `jfox/moc/cluster.py` — production Louvain implementation and truthful orphan-related docstrings.
- `jfox/moc/cli.py` — four MOC default values.

**Modified tests:**

- `tests/unit/test_moc_cluster.py` — weak-bridge, complete-graph, deterministic/parameter regression tests.
- `tests/unit/test_moc_cli.py` — exact MOC default-value help assertions.

**Modified validation/documentation files:**

- `scripts/louvain_verify.py` — private legacy connected-components baseline plus production Louvain comparison.
- `scripts/LOUVAIN_VERIFY.md` — align mechanism, output labels, and current validation instructions.
- `skills-recommend/pi/jfox-moc/SKILL.md` — update MOC default threshold and explain the Louvain behavior.

**Intentionally not modified:** `CHANGELOG.md` in this feature PR. The next release flow will collect the conventional `feat(moc)` commit as #439; release notes can include the semantic-orphan and diagnose-output notes then. No existing MOC files are migrated because the feature is not in formal use.

---

### Task 1: Add regression tests before changing production behavior

**Files:**

- Modify: `tests/unit/test_moc_cluster.py`

**Interfaces:**

- Consumes: the existing `find_clusters_at_threshold()` API.
- Produces: three executable regression tests that describe the desired Louvain contract; the weak-bridge test must fail against the current connected-components implementation.

- [ ] **Step 1: Add the required test import**

Add this import beside the existing third-party imports:

```python
import networkx as nx
```

The existing file already imports `numpy as np`, `pytest`, `MagicMock`, and `patch`; do not duplicate those imports.

- [ ] **Step 2: Add the weak-bridge regression test**

Append this test to `tests/unit/test_moc_cluster.py`:

```python
def test_louvain_splits_dense_cores_with_weak_bridge():
    """Louvain must split dense cores that a weak bridge only connects transitively."""
    similarity = np.zeros((10, 10), dtype=np.float32)
    for start in (0, 5):
        for left in range(start, start + 5):
            for right in range(left + 1, start + 5):
                similarity[left, right] = 0.8
                similarity[right, left] = 0.8
    similarity[2, 7] = 0.66
    similarity[7, 2] = 0.66

    clusters = find_clusters_at_threshold(similarity, threshold=0.65, min_size=3)

    assert clusters == [list(range(5)), list(range(5, 10))]
```

- [ ] **Step 3: Add the complete-graph regression test**

Append:

```python
def test_louvain_complete_graph_stays_one_cluster():
    """A fully and strongly connected graph must not be over-split."""
    similarity = np.full((6, 6), 0.85, dtype=np.float32)
    np.fill_diagonal(similarity, 0.0)

    clusters = find_clusters_at_threshold(similarity, threshold=0.65, min_size=3)

    assert clusters == [list(range(6))]
```

- [ ] **Step 4: Add the deterministic and fixed-parameter regression test**

Append:

```python
def test_louvain_is_deterministic_and_uses_fixed_parameters():
    """The production call must be deterministic and use the selected Louvain settings."""
    similarity = np.zeros((10, 10), dtype=np.float32)
    for start in (0, 5):
        for left in range(start, start + 5):
            for right in range(left + 1, start + 5):
                similarity[left, right] = 0.8
                similarity[right, left] = 0.8
    similarity[2, 7] = 0.66
    similarity[7, 2] = 0.66

    with patch(
        "jfox.moc.cluster.community.louvain_communities",
        wraps=nx.community.louvain_communities,
    ) as louvain:
        runs = [
            find_clusters_at_threshold(similarity, threshold=0.65, min_size=3)
            for _ in range(3)
        ]

    assert runs[0] == runs[1] == runs[2]
    assert louvain.call_args.kwargs == {
        "weight": "weight",
        "resolution": 1.0,
        "seed": 42,
    }
```

- [ ] **Step 5: Run the new tests and verify the intended red/green split**

Run:

```bash
uv run pytest tests/unit/test_moc_cluster.py -k "louvain" -v
```

Expected before the production change: the weak-bridge test fails because the current connected-components implementation returns one 10-node cluster; the complete-graph test passes; the deterministic/parameter test fails because the production function does not call `community.louvain_communities`. Do not alter the tests to accommodate the old implementation.

- [ ] **Step 6: Commit the tests**

```bash
git add tests/unit/test_moc_cluster.py
git commit -m "test(moc): define Louvain clustering regressions

Refs #439"
```

---

### Task 2: Replace connected components with weighted Louvain

**Files:**

- Modify: `jfox/moc/cluster.py:1-175`

**Interfaces:**

- Consumes: `similarity: np.ndarray`, `threshold: float`, `min_size: int`.
- Produces: `List[List[int]]`, with the same size filtering and deterministic ordering used by current callers.

- [ ] **Step 1: Import NetworkX community algorithms**

Add the import directly after `import networkx as nx`:

```python
from networkx.algorithms import community
```

- [ ] **Step 2: Replace only the graph clustering block**

Inside `find_clusters_at_threshold()`, retain validation, graph node creation, upper-triangle thresholding, `min_size` filtering, and the final sort. Replace the unweighted edge construction and `nx.connected_components()` call with this exact logic:

```python
rows, columns = np.where(np.triu(matrix > threshold, k=1))
weighted_edges = [
    (int(row), int(column), float(matrix[row, column]))
    for row, column in zip(rows.tolist(), columns.tolist())
]
graph.add_weighted_edges_from(weighted_edges)

communities = community.louvain_communities(
    graph, weight="weight", resolution=1.0, seed=42
)
clusters = [sorted(members) for members in communities]
```

Then keep the existing filter and return:

```python
clusters = [component for component in clusters if len(component) >= min_size]
return sorted(clusters, key=lambda component: (-len(component), component[0]))
```

Do not add a `resolution` or `seed` parameter to the public function.

- [ ] **Step 3: Update the affected docstrings**

Change `find_clusters_at_threshold()` to say it finds Louvain communities in a thresholded weighted graph, and explicitly document that `seed=42` makes the partition reproducible. Change `semantic_orphan_indices()` to describe an orphan as an index absent from every qualifying community; do not claim that it has no similar neighbor.

- [ ] **Step 4: Run the focused tests**

Run:

```bash
uv run pytest tests/unit/test_moc_cluster.py -k "louvain or find_clusters or build_threshold_summary" -v
```

Expected: all selected tests pass, including the weak-bridge split, complete graph, and fixed-parameter assertions.

- [ ] **Step 5: Run the complete cluster unit test module**

Run:

```bash
uv run pytest tests/unit/test_moc_cluster.py -v
```

Expected: all tests pass. If an assertion depends on the old connected-component partition, update only that assertion when the new behavior is the direct consequence of the approved spec; do not weaken unrelated coverage.

- [ ] **Step 6: Commit the production algorithm**

```bash
git add jfox/moc/cluster.py
git commit -m "feat(moc): use deterministic weighted Louvain communities

Replace transitive connected components with NetworkX Louvain using
similarity weights, resolution 1.0, and seed 42.

Refs #439"
```

---

### Task 3: Change MOC defaults and lock the CLI contract

**Files:**

- Modify: `jfox/moc/cli.py:343,485,531,533`
- Modify: `tests/unit/test_moc_cli.py`

**Interfaces:**

- Consumes: existing Typer command definitions and `diagnose_moc_density()` call contract.
- Produces: MOC-only default changes; explicit user-provided thresholds continue to pass through unchanged.

- [ ] **Step 1: Add exact default assertions before changing CLI code**

Add these assertions to the existing help tests in `tests/unit/test_moc_cli.py`:

```python

def test_moc_create_help_uses_louvain_default_threshold():
    result = runner.invoke(app, ["moc", "create", "--help"])

    assert result.exit_code == 0
    assert "[default: 0.75]" in result.output


def test_moc_update_help_uses_louvain_default_threshold():
    result = runner.invoke(app, ["moc", "update", "--help"])

    assert result.exit_code == 0
    assert "[default: 0.75]" in result.output


def test_moc_diagnose_help_uses_louvain_defaults():
    result = runner.invoke(app, ["moc", "diagnose", "--help"])

    assert result.exit_code == 0
    assert "[default: 0.70,0.75,0.78,0.80]" in result.output
    assert result.output.count("[default: 0.75]") == 1
```

The existing `test_moc_*_help_registers_exact_contract` tests may be extended instead of adding duplicate tests, but the final test module must assert all four new defaults.

- [ ] **Step 2: Run the default tests to confirm they fail against current values**

Run:

```bash
uv run pytest tests/unit/test_moc_cli.py -k "louvain_default or help_uses" -v
```

Expected: the new default assertions fail because the current CLI still exposes 0.65 and the old sweep.

- [ ] **Step 3: Change only the four MOC defaults**

Apply these exact replacements in `jfox/moc/cli.py`:

```python
# moc create
threshold: float = typer.Option(0.75, "--threshold")

# moc update
threshold: float = typer.Option(0.75, "--threshold")

# moc diagnose
thresholds: str = typer.Option("0.70,0.75,0.78,0.80", "--thresholds")
suggest_threshold: float = typer.Option(0.75, "--suggest-threshold")
```

Do not change validation, explicit option handling, or defaults outside `jfox/moc/cli.py`.

- [ ] **Step 4: Run CLI tests and inspect help output**

Run:

```bash
uv run pytest tests/unit/test_moc_cli.py tests/unit/test_moc_create_cli.py tests/unit/test_moc_update_cli.py -v
uv run jfox moc create --help | grep threshold
uv run jfox moc update --help | grep threshold
uv run jfox moc diagnose --help | grep threshold
```

Expected: all selected tests pass; create/update show 0.75; diagnose shows the four-value sweep and suggestion default 0.75.

- [ ] **Step 5: Commit the MOC default changes**

```bash
git add jfox/moc/cli.py tests/unit/test_moc_cli.py
git commit -m "feat(moc): raise default clustering threshold to 0.75

Align create, update, and diagnose defaults with the bge-m3 Louvain spike.

Refs #439"
```

---

### Task 4: Keep the validation script's old/new comparison truthful and update user docs

**Files:**

- Modify: `scripts/louvain_verify.py`
- Modify: `scripts/LOUVAIN_VERIFY.md`
- Modify: `skills-recommend/pi/jfox-moc/SKILL.md`

**Interfaces:**

- Consumes: permanent vectors from the current KB and the production `find_clusters_at_threshold()` function.
- Produces: a validation report that labels the old algorithm as a private legacy baseline and the new algorithm as production Louvain.

- [ ] **Step 1: Add a private legacy baseline helper to the script**

In `scripts/louvain_verify.py`, add this function after `load_permanent_embeddings()` helpers and before the existing Louvain helper:

```python
def run_connected_components(
    similarity: np.ndarray,
    threshold: float,
    min_size: int,
) -> List[List[int]]:
    """Reproduce the pre-#439 algorithm for before/after comparison only."""
    graph = nx.Graph()
    graph.add_nodes_from(range(similarity.shape[0]))
    rows, columns = np.where(np.triu(similarity > threshold, k=1))
    graph.add_edges_from(zip(rows.tolist(), columns.tolist()))
    clusters = [sorted(component) for component in nx.connected_components(graph)]
    clusters = [cluster for cluster in clusters if len(cluster) >= min_size]
    return sorted(clusters, key=lambda cluster: (-len(cluster), cluster[0]))
```

This is the only place where the old connected-components algorithm remains, and it must not be imported by production code.

- [ ] **Step 2: Make the script use the helper for its old baseline**

Replace the current Step 2 call to `find_clusters_at_threshold()` with:

```python
clusters_cc = run_connected_components(similarity, args.threshold, min_size=3)
```

Keep the existing `run_louvain_on_cluster()` for the script's optional `--resolution` experiments. At the default `--resolution 1.0`, its NetworkX call must use the same `weight="weight"`, `resolution=1.0`, and `seed=42` settings as production. Do not describe its output as the current production result; label it as the legacy-baseline comparison.

- [ ] **Step 3: Make output labels and acceptance metrics explicit**

Change the script's output wording and surrounding logic so that it states:

```text
Step 2: 旧版连通分量基线（阈值 ...）
Step 3: 对旧版最大簇运行 Louvain（生产默认 resolution=1.0, seed=42）
```

The output must continue to show the old connected-component cluster size and the Louvain community count, maximum community size, 5–50 MOC-ready count, and size distribution. Add a small summary helper in the script to compute qualifying-community orphan counts as `node_count - sum(len(cluster) for cluster in clusters)`, and print old/new orphan counts in the comparison summary. Ensure the default invocation succeeds after production changes and no longer labels a Louvain result as connected components. The detailed title samples may continue to use `run_louvain_on_cluster()` on the legacy maximum cluster, but the top-level old/new metrics must use the private legacy helper and the production function respectively.

- [ ] **Step 4: Update the validation documentation**

In `scripts/LOUVAIN_VERIFY.md`:

- Explain that the script retains connected components only as a legacy comparison baseline.
- Correct the mechanism wording from “Louvain cuts weak edges” to “Louvain finds dense communities when the graph contains real dense cores; a pure semantic chain may remain one community.”
- Mark the 571/773 note counts, 167/741 cluster sizes, and 9/13 community results as historical snapshots, not hard-coded acceptance criteria.
- Document current acceptance on the single local `default` KB: old giant-cluster baseline remains visible, new communities are materially smaller, and title samples are manually reviewed.
- Keep the script's `--resolution` examples labeled as optional experiments, not production CLI behavior.

- [ ] **Step 5: Update the MOC user skill documentation**

In `skills-recommend/pi/jfox-moc/SKILL.md`:

- Change the documented default `--threshold` from 0.65 to 0.75.
- Explain that MOC clustering uses deterministic weighted Louvain with `seed=42` and fixed `resolution=1.0`.
- State that `--threshold` remains an explicit override and that the change does not affect non-MOC commands.
- Preserve the existing `--max-size` guidance.

- [ ] **Step 6: Run documentation and script checks**

Run:

```bash
uv run python -m py_compile scripts/louvain_verify.py
uv run python scripts/louvain_verify.py --top 1
npx --yes markdownlint-cli2 scripts/LOUVAIN_VERIFY.md skills-recommend/pi/jfox-moc/SKILL.md
```

Expected: the script loads the current `default` KB, reports a legacy connected-components baseline and Louvain subdivision without daemon access, and both Markdown files pass lint.

- [ ] **Step 7: Commit script and documentation changes**

```bash
git add scripts/louvain_verify.py scripts/LOUVAIN_VERIFY.md skills-recommend/pi/jfox-moc/SKILL.md
git commit -m "docs(moc): keep Louvain validation baseline and usage docs accurate

Preserve the pre-#439 connected-components comparison in the validation
script while documenting deterministic weighted Louvain behavior.

Refs #439"
```

---

### Task 5: Run branch-level verification and record issue evidence

**Files:**

- None expected; this task is verification and evidence collection only.

**Interfaces:**

- Consumes: all changes from Tasks 1–4.
- Produces: test output and a concise acceptance comment for issue #439.

- [ ] **Step 1: Run all relevant MOC unit and CLI tests**

Run:

```bash
uv run pytest tests/unit/test_moc_cluster.py tests/unit/test_moc_cli.py tests/unit/test_moc_create_cli.py tests/unit/test_moc_update_cli.py -v
```

Expected: all tests pass, including the three Louvain regressions and all changed help contracts.

- [ ] **Step 2: Run the local default-KB effect validation**

Run:

```bash
uv run python scripts/louvain_verify.py --top 1
```

Record the actual current counts from the output. Do not assert historical counts. Acceptance requires:

1. the old connected-components baseline is printed and remains a large/transitively connected cluster where the current data exhibits that problem;
2. the new Louvain result is printed separately;
3. the largest Louvain community is materially smaller than the old giant cluster;
4. the displayed community title samples are manually checked for obvious topic mixing;
5. no daemon restart or KB mutation occurs.

- [ ] **Step 3: Run static checks for the changed Python files**

Run:

```bash
uv run ruff check jfox/moc/cluster.py jfox/moc/cli.py tests/unit/test_moc_cluster.py tests/unit/test_moc_cli.py scripts/louvain_verify.py
uv run black --check jfox/moc/cluster.py jfox/moc/cli.py tests/unit/test_moc_cluster.py tests/unit/test_moc_cli.py scripts/louvain_verify.py
```

Expected: both commands pass. If formatting changes are required, apply them only to the listed files and rerun the checks.

- [ ] **Step 4: Inspect the final diff and working tree**

Run:

```bash
git diff --check main...HEAD
git diff --stat main...HEAD
git status --short
```

Expected: no whitespace errors; only the planned files are changed or committed; no knowledge-base data or temporary files are staged.

- [ ] **Step 5: Comment the evidence on issue #439**

After the commands above pass and the actual output has been manually reviewed, post a concise comment with the real counts and commands, using this structure without inventing numbers:

```markdown
## 实施验收：Louvain MOC 聚类

- 生产实现：`find_clusters_at_threshold()` 使用加权 Louvain，固定 `weight="weight"`、`resolution=1.0`、`seed=42`
- 回归测试：弱桥拆分、完全图不拆、确定性/参数断言通过
- CLI：MOC 默认阈值已更新为 0.75，diagnose sweep 为 0.70/0.75/0.78/0.80
- 效果验证：`uv run python scripts/louvain_verify.py --top 1`
- 当前 default KB 实际结果：旧版连通分量 <填写实际输出>；Louvain <填写实际输出>
- 人工检查：社区标题样本 <填写检查结论>
- 未重启 daemon，未修改知识库数据
```

Do not claim completion or merge readiness until the command output is available and reviewed.

---

## Plan Self-Review

- **Spec coverage:** production algorithm, fixed parameters, unchanged API, MOC-only defaults, two behavior tests plus determinism/parameter test, truthful validation baseline, current-default documentation, no migration work, and local default-KB acceptance are covered by Tasks 1–5.
- **Placeholder scan:** no implementation step uses TBD/TODO or an unspecified file/function. The issue-comment structure is a controller-side posting template only; the actual comment must be assembled from command output after verification, and no placeholder text may be posted or committed.
- **Type consistency:** every task uses `find_clusters_at_threshold(np.ndarray, float, int) -> List[List[int]]`; script helpers use `List[List[int]]`; all production Louvain parameters are exact and consistent.
- **Scope check:** the plan contains one cohesive MOC algorithm change; no embedding, search, schema, daemon, migration, or unrelated refactor work.
- **TDD check:** behavior tests are added and run before production replacement; CLI default tests are added and run before default changes; script/docs are validated after the production implementation exists.
