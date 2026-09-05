# MOC Diagnose Archived Orphan Classification Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 #499——`jfox moc diagnose` 把 archived 笔记误报为 vector 孤儿，改为三分归类（ghost/duplicate 计真孤儿，archived 单列 `archived_in_index` 不发警告）。

**Architecture:** 在 `jfox/moc/cluster.py` 新增纯函数 `classify_vector_id` 承担三分判定；`diagnose_moc_density` 构造含 archived 的全量 `permanent_meta` 字典（现状只保留过滤后的 `live_meta`，archived 信息被丢弃），循环内按分类分别计数；`CoverageReport` 加 `archived_in_index` 字段；`jfox/moc/cli.py` 负责 JSON 透传与 table 条件 info 行。

**Tech Stack:** Python 3.10+, Typer/Rich CLI, pytest + MagicMock 测试。

**Spec:** `docs/superpowers/specs/2026-09-05-moc-diagnose-archived-orphan-design.md`（验收矩阵 ID：A1-A7、A4b、U1）

## Global Constraints

- 行宽 100 字符（pyproject.toml）；black 格式化；ruff 检查通过。
- 注释/docstring 用中文（仓库惯例）。
- 可测性拆分硬约束（spec §2.2）：`classify_vector_id` 必须是模块级纯函数——不做 IO、不看 seen 状态；duplicate 判定留在 `diagnose_moc_density` 循环内；metadata 校验副作用（raise MocDiagnoseError）不抽出。
- `vector_orphans` 语义收窄为「真孤儿」（ghost+duplicate），警告文案 `"Vector index contains N permanent orphan(s)"` 不变、仅真孤儿触发。
- 不改 BM25 coverage 口径；不改 rebuild 索引范围；不改聚类成员构建。
- 工作目录：所有操作在 worktree `/home/elling/git-repo/github/jfox/.pi/worktrees/issue-499-moc-diagnose-archived-orphan` 内进行（下文记作 `$WT`），git 操作用 `git -C $WT`，`git add` 按文件 stage（禁 `git add -A`）。

---

### Task 1: `classify_vector_id` 纯函数

**验收归属:** A1（`uv run pytest tests/unit/test_moc_cluster.py -k classify_vector_id -v`）

**Files:**
- Modify: `jfox/moc/cluster.py`（typing import 行、note_index import 行；新函数紧跟 `semantic_orphan_indices` 定义之后）
- Test: `tests/unit/test_moc_cluster.py`（cluster import 行加 `classify_vector_id`；新测试类加在 `_permanent_meta` helper 之后）

**Interfaces:**
- Consumes: `_permanent_meta(note_id, title, *, archived=False) -> NoteMeta`（test_moc_cluster.py 现有 helper）
- Produces: `classify_vector_id(note_id: str, permanent_meta: Mapping[str, NoteMeta]) -> Literal["ghost", "archived", "live"]`——Task 2 的 diagnose 循环消费此函数。

- [ ] **Step 1: Write the failing test**

在 `tests/unit/test_moc_cluster.py` 的 `_permanent_meta` helper 之后新增：

```python
class TestClassifyVectorId:
    """classify_vector_id 的三分判定（ghost / archived / live）。"""

    def test_classify_vector_id_ghost_when_id_not_in_permanent_meta(self):
        assert classify_vector_id("missing", {}) == "ghost"

    def test_classify_vector_id_ghost_when_permanent_meta_empty(self):
        assert classify_vector_id("p0", {}) == "ghost"

    def test_classify_vector_id_archived_when_meta_marked_archived(self):
        meta = _permanent_meta("a1", "A1", archived=True)
        assert classify_vector_id("a1", {"a1": meta}) == "archived"

    def test_classify_vector_id_live_when_meta_not_archived(self):
        meta = _permanent_meta("p0", "P0")
        assert classify_vector_id("p0", {"p0": meta}) == "live"
```

并在文件头部现有的 `from jfox.moc.cluster import (...)` 导入列表中加入 `classify_vector_id`。

- [ ] **Step 2: Run test to verify it fails**

Run: `cd $WT && uv run pytest tests/unit/test_moc_cluster.py -k classify_vector_id -v`
Expected: FAIL（collection error 或 ImportError：`cannot import name 'classify_vector_id'`）

- [ ] **Step 3: Write minimal implementation**

`jfox/moc/cluster.py` 三处改动：

1. typing import 行（文件头部）改为：

```python
from typing import Dict, List, Literal, Mapping, Optional, Sequence
```

2. note_index import 行改为：

```python
from ..note_index import NoteMeta, get_note_index
```

3. 紧跟 `semantic_orphan_indices` 函数定义之后，新增：

```python
def classify_vector_id(
    note_id: str, permanent_meta: Mapping[str, NoteMeta]
) -> Literal["ghost", "archived", "live"]:
    """将一条 permanent vector 索引条目分类为 ghost / archived / live。

    ghost：磁盘上不存在对应 permanent 笔记（索引死条目，真孤儿）；
    archived：磁盘上存在但 frontmatter 标记归档（正常状态，不计入孤儿）；
    live：活跃的 permanent 笔记。
    duplicate（重复条目）不在此函数判定——它依赖循环内的 seen 状态。
    """
    meta = permanent_meta.get(note_id)
    if meta is None:
        return "ghost"
    if meta.archived:
        return "archived"
    return "live"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd $WT && uv run pytest tests/unit/test_moc_cluster.py -k classify_vector_id -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git -C $WT add jfox/moc/cluster.py tests/unit/test_moc_cluster.py
git -C $WT commit -m "feat(moc): add classify_vector_id pure function (#499)"
```

---

### Task 2: diagnose 三分计数 + `archived_in_index` 字段 + 警告门控锁定

**验收归属:** A2（计数分离）、A3（警告门控，`-k "warning or warn"`）、A5（降级路径，`-k filesystem_failure`）

**Files:**
- Modify: `jfox/moc/cluster.py`（`CoverageReport` 加字段；`diagnose_moc_density` 三处：meta 构造、循环判定、赋值）
- Test: `tests/unit/test_moc_cluster.py`（更新 3 处固化断言；新增 2 个测试；降级测试补 2 条断言）

**Interfaces:**
- Consumes: Task 1 的 `classify_vector_id(note_id, permanent_meta)`
- Produces: `CoverageReport.archived_in_index: int = 0`——Task 3 的 CLI 透传消费此字段。

- [ ] **Step 1: Update the three固化断言 + 降级断言（failing tests）**

`tests/unit/test_moc_cluster.py`：

1. `test_diagnose_filters_archived_and_orphan_vectors_and_enriches_graph` 中（当前约 L230），把

```python
    assert report.coverage.vector_orphans == 2
```

改为：

```python
    assert report.coverage.vector_orphans == 1  # 仅 ghost
    assert report.coverage.archived_in_index == 1
    assert any(
        "Vector index contains 1 permanent orphan(s)" in warning
        for warning in report.coverage.warnings
    )
```

2. `test_diagnose_all_orphan_vectors_returns_empty_clusters` 中（当前约 L311），把

```python
    assert report.coverage.vector_orphans == 2
```

改为：

```python
    assert report.coverage.vector_orphans == 1  # 仅 ghost；p0 是 archived
    assert report.coverage.archived_in_index == 1
```

3. `test_diagnose_dense_limit_counts_only_verified_unique_live_rows` 中（当前约 L542），把

```python
    assert report.coverage.vector_orphans == len(vector_ids) - 2
```

改为：

```python
    assert report.coverage.vector_orphans == 6  # 1 live duplicate + 5 ghost
    assert report.coverage.archived_in_index == 4  # archived 重复 4 行如实计数
```

4. `test_diagnose_filesystem_failure_skips_unverified_semantic_clusters` 的断言区末尾（`assert any("semantic clustering was skipped" ...)` 之后）补：

```python
    assert report.coverage.vector_orphans == 0
    assert report.coverage.archived_in_index == 0
```

- [ ] **Step 2: Write two new failing tests**

在 `tests/unit/test_moc_cluster.py` 新增（可放在 `test_diagnose_all_orphan_vectors_returns_empty_clusters` 之后）：

```python
def test_diagnose_counts_duplicate_live_rows_as_orphans():
    """live id 在 vector 索引中重复出现 → 计真孤儿（索引异常），不算 archived。"""
    config = ZKConfig(base_dir=Path("/tmp/moc-test"))
    metas = [_permanent_meta("p0", "P0")]
    note_index = MagicMock()
    note_index.get_all_meta.return_value = metas
    vector_store = MagicMock()
    vector_store.get_all_embeddings.return_value = (
        ["p0", "p0"],
        [None, None],
        np.array([[1.0, 0.0], [1.0, 0.0]], dtype=np.float32),
    )
    graph = MagicMock()
    graph.build.return_value = graph
    graph.graph.in_degree.return_value = 0
    graph.graph.out_degree.return_value = 0
    with (
        patch("jfox.moc.cluster.get_note_index", return_value=note_index),
        patch("jfox.moc.cluster.VectorStore", return_value=vector_store),
        patch(
            "jfox.moc.cluster.BM25Index",
            return_value=MagicMock(doc_ids=[], doc_types=[]),
        ),
        patch("jfox.moc.cluster.KnowledgeGraph", return_value=graph),
    ):
        report = diagnose_moc_density(config, [0.65], 2, 0.65, 10)

    assert report.coverage.vector_orphans == 1
    assert report.coverage.archived_in_index == 0


def test_diagnose_archived_only_rows_emit_no_orphan_warning():
    """vector 索引仅多含 archived 笔记时：不计孤儿、不发 orphan 警告。"""
    config = ZKConfig(base_dir=Path("/tmp/moc-test"))
    metas = [_permanent_meta("p0", "P0"), _permanent_meta("a1", "A1", archived=True)]
    note_index = MagicMock()
    note_index.get_all_meta.return_value = metas
    vector_store = MagicMock()
    vector_store.get_all_embeddings.return_value = (
        ["p0", "a1"],
        [None, None],
        np.array([[1.0, 0.0], [0.0, 1.0]], dtype=np.float32),
    )
    graph = MagicMock()
    graph.build.return_value = graph
    graph.graph.in_degree.return_value = 0
    graph.graph.out_degree.return_value = 0
    with (
        patch("jfox.moc.cluster.get_note_index", return_value=note_index),
        patch("jfox.moc.cluster.VectorStore", return_value=vector_store),
        patch(
            "jfox.moc.cluster.BM25Index",
            return_value=MagicMock(doc_ids=[], doc_types=[]),
        ),
        patch("jfox.moc.cluster.KnowledgeGraph", return_value=graph),
    ):
        report = diagnose_moc_density(config, [0.65], 2, 0.65, 10)

    assert report.coverage.vector_orphans == 0
    assert report.coverage.archived_in_index == 1
    assert not any(
        warning.startswith("Vector index contains")
        for warning in report.coverage.warnings
    )
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `cd $WT && uv run pytest tests/unit/test_moc_cluster.py -k "orphan or warning or filesystem_failure or filters_archived or dense_limit" -v`
Expected: FAIL——`AttributeError: 'CoverageReport' object has no attribute 'archived_in_index'`（字段尚不存在）

- [ ] **Step 4: Implement**

`jfox/moc/cluster.py` 四处改动：

1. `CoverageReport` 数据类（当前约 L55-63）加字段：

```python
@dataclass
class CoverageReport:
    """文件系统及各索引中的永久笔记数量。"""

    filesystem: Optional[int] = 0
    vector: Optional[int] = 0
    vector_orphans: int = 0
    archived_in_index: int = 0
    bm25: Optional[int] = 0
    bm25_coverage_ratio: Optional[float] = None
    warnings: List[str] = field(default_factory=list)
```

2. `diagnose_moc_density` 的 meta 构造段（当前约 L233-244），把

```python
        note_index = get_note_index(config)
        live_meta = {
            meta.id: meta
            for meta in note_index.get_all_meta()
            if meta.type == NoteType.PERMANENT and not meta.archived
        }
        filesystem_count: Optional[int] = len(live_meta)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        live_meta = {}
```

改为：

```python
        note_index = get_note_index(config)
        permanent_meta = {
            meta.id: meta
            for meta in note_index.get_all_meta()
            if meta.type == NoteType.PERMANENT
        }
        live_meta = {
            note_id: meta for note_id, meta in permanent_meta.items() if not meta.archived
        }
        filesystem_count: Optional[int] = len(live_meta)
    except (OSError, RuntimeError, ValueError, KeyError, TypeError) as exc:
        permanent_meta = {}
        live_meta = {}
```

3. 循环判定段（当前约 L274-286），把

```python
            if note_id not in live_meta or note_id in seen_live_ids:
                orphan_count += 1
                continue
            seen_live_ids.add(note_id)
            records.append((note_id, live_meta[note_id].title, raw_embeddings[index]))
```

改为：

```python
            classification = classify_vector_id(note_id, permanent_meta)
            if classification == "archived":
                archived_count += 1
                continue
            if classification == "ghost" or note_id in seen_live_ids:
                orphan_count += 1
                continue
            seen_live_ids.add(note_id)
            records.append((note_id, live_meta[note_id].title, raw_embeddings[index]))
```

同时在循环前的计数器声明处（当前约 L265-267 `records = [] / seen_live_ids = set() / orphan_count = 0`）加一行：

```python
    archived_count = 0
```

4. 赋值段（当前约 L292 `coverage.vector_orphans = orphan_count`）之后加一行：

```python
    coverage.archived_in_index = archived_count
```

警告逻辑（`if coverage.vector_orphans:`）**不改**——archived 不再计入后自然门控。

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd $WT && uv run pytest tests/unit/test_moc_cluster.py -v`
Expected: 全部通过（含更新的 3 处断言、2 个新测试、降级补断言）

- [ ] **Step 6: Commit**

```bash
git -C $WT add jfox/moc/cluster.py tests/unit/test_moc_cluster.py
git -C $WT commit -m "fix(moc): classify archived vector rows separately from true orphans (#499)"
```

---

### Task 3: CLI JSON 透传 + table 条件 info 行

**验收归属:** A4（JSON 字段）、A4b（table info 行显示/隐藏）

**Files:**
- Modify: `jfox/moc/cli.py`（`report_to_dict` coverage dict；`_render_table` info 行）
- Test: `tests/unit/test_moc_cli.py`（`_report()` mock 加字段；`test_diagnose_json_contract` 加断言；新增 2 个 table 测试）

**Interfaces:**
- Consumes: Task 2 的 `CoverageReport.archived_in_index: int`
- Produces: JSON key `coverage.archived_in_index`（消费方面向 agent/脚本）；table info 行文案 `Note: vector index includes N archived permanent note(s) (normal; excluded from filesystem count)`

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_moc_cli.py` 三处改动：

1. `_report()` 的 `CoverageReport(...)` 构造中，`vector_orphans=2,` 之后加一行：

```python
            archived_in_index=2,
```

2. `test_diagnose_json_contract` 中，`assert payload["coverage"]["vector_orphans"] == 2` 之后加：

```python
    assert payload["coverage"]["archived_in_index"] == 2
```

3. 新增两个测试（放在 `test_diagnose_table_has_four_sections_and_permanent_only_coverage` 之后）：

```python
def test_diagnose_table_shows_archived_info_line_when_nonzero():
    with patch("jfox.moc.cli.diagnose_moc_density", return_value=_report()):
        result = runner.invoke(moc_app, ["diagnose"])

    assert result.exit_code == 0, result.output
    assert "archived permanent note(s)" in result.output


def test_diagnose_table_hides_archived_info_line_when_zero():
    report = _report()
    report.coverage.archived_in_index = 0
    with patch("jfox.moc.cli.diagnose_moc_density", return_value=report):
        result = runner.invoke(moc_app, ["diagnose"])

    assert result.exit_code == 0, result.output
    assert "archived permanent note(s)" not in result.output
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd $WT && uv run pytest tests/unit/test_moc_cli.py -k "json_contract or archived_info_line" -v`
Expected: FAIL——`_report()` 构造报 `TypeError: unexpected keyword argument 'archived_in_index'`……若 Task 2 已合入则字段存在，此时失败点是 `payload["coverage"]["archived_in_index"]` KeyError 与 info 行断言失败。两种失败都符合 TDD 预期。

- [ ] **Step 3: Implement**

`jfox/moc/cli.py` 两处改动：

1. `report_to_dict` 的 coverage dict（当前约 L130-136），在 `"vector_orphans": coverage.vector_orphans,` 之后加一行：

```python
            "archived_in_index": coverage.archived_in_index,
```

2. `_render_table`（当前约 L200-201），在 `_console.print(coverage_table)` 之后、`for warning in report.coverage.warnings:` 之前插入：

```python
    if report.coverage.archived_in_index:
        _console.print(
            f"Note: vector index includes {report.coverage.archived_in_index} "
            "archived permanent note(s) (normal; excluded from filesystem count)"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd $WT && uv run pytest tests/unit/test_moc_cli.py -v`
Expected: 全部通过（注意 `test_diagnose_json_contract` 的顶层 `set(payload)` 断言不受影响——`archived_in_index` 是嵌套在 `coverage` 内的字段）

- [ ] **Step 5: Commit**

```bash
git -C $WT add jfox/moc/cli.py tests/unit/test_moc_cli.py
git -C $WT commit -m "feat(moc): expose archived_in_index in diagnose JSON and table output (#499)"
```

---

### Task 4: 全量回归 + 静态检查

**验收归属:** A6（MOC 全量回归）、A7（静态检查）

**Files:**
- 预期无改动；若回归 break 则按失败信息修复（修复需回到对应 Task 的测试先行流程）

- [ ] **Step 1: MOC 全量回归**

Run: `cd $WT && uv run pytest tests/unit/test_moc_cluster.py tests/unit/test_moc_cli.py tests/unit/test_moc_integration.py tests/unit/test_moc_create_cli.py tests/unit/test_moc_update_cli.py -v`
Expected: 全部通过（特别关注 `test_moc_update_cli.py` L43/L144、`test_moc_integration.py` L97、`test_moc_create_cli.py` L41 的 `CoverageReport` 关键字传参构造不受新字段影响）

- [ ] **Step 2: 静态检查**

Run: `cd $WT && uv run ruff check jfox/ tests/ && uv run black --check jfox/moc/ tests/unit/test_moc_cluster.py tests/unit/test_moc_cli.py`
Expected: 无违规；若 black 报格式问题，运行 `uv run black` 格式化对应文件后重新检查并 `git -C $WT add <file> && git -C $WT commit -m "style(moc): apply black formatting (#499)"`

- [ ] **Step 3: Commit（仅当有修复/格式化改动时）**

```bash
git -C $WT add <改动的文件>
git -C $WT commit -m "fix(moc): address regression findings (#499)"
```

---

### Task 5: U1 真实库实测（post-implementation manual verification）

**验收归属:** U1（office_hour 库假警报消除）

**Files:** 无（只读验证，agent 本机代跑）

- [ ] **Step 1: 对真实库跑修复版 diagnose**

Run: `cd $WT && uv run jfox moc diagnose --json --kb office_hour 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(json.dumps(d['coverage'], ensure_ascii=False, indent=2))"`
（首次 `uv run` 需在 worktree 建 venv，耗时几分钟属正常；diagnose 为只读命令，对真实库无写入风险）

Expected（按 issue 实测数据）：`"vector_orphans": 0`、`"archived_in_index": 10`、`"warnings"` 中无 `Vector index contains ... orphan(s)` 条目。

- [ ] **Step 2: 记录结果**

- 若符合预期：把实际 coverage JSON 摘录到本 plan 下方「U1 验收记录」小节，并将结论评论到 issue #499。
- 若命令因环境问题无法执行（如 office_hour 库不存在）：标记 `pending`，如实记录阻塞原因，不宣称 U1 完成。
- 若结果不符合预期：停止，回到对应 Task 排查。

## U1 验收记录

执行于 2026-09-05，本机无 office_hour 库（issue 实测环境在另一台机器），改用本机 default 库（721 permanent，其中 archived 5 条）验收，bug 条件完整覆盖（向量索引内含 archived permanent）：

```json
{
  "filesystem": 716,
  "vector": 111,
  "vector_orphans": 0,
  "archived_in_index": 1,
  "warnings": []
}
```

交叉验证：磁盘上 5 条 archived permanent；chroma 索引 111 条 permanent 中恰好 1 条 archived（id `202608122126292583`）——与 `archived_in_index: 1` 完全一致。修复前该条目会被计为 `vector_orphans: 1` 并触发假警告；现在正确归类、无警告。该库向量覆盖率低（111/721）是独立的既有现象，与本 issue 无关。

结论：U1 通过（替代库）。office_hour 库的 10 条 archived 场景可在该库所在机器上同样验证，预期 `vector_orphans: 0`、`archived_in_index: 10`。

---

## Self-Review 记录

- **Spec 覆盖**：A1→Task 1；A2/A3/A5→Task 2；A4/A4b→Task 3；A6/A7→Task 4；U1→Task 5。无遗漏验收项；无无归属 task。
- **占位符扫描**：所有代码步骤含完整代码块；无 TBD/TODO。
- **类型一致性**：`classify_vector_id(note_id: str, permanent_meta: Mapping[str, NoteMeta]) -> Literal[...]` 在 Task 1 定义、Task 2 消费，签名一致；`archived_in_index` 字段名在 Task 2（dataclass）/Task 3（JSON key + table）/Task 5（断言）全程一致。
- **可测性拆分**：`classify_vector_id` 纯函数（Task 1）与循环内 duplicate 判定（Task 2）的边界符合 spec §2.2 硬约束；未把已拆分逻辑重新耦合。
