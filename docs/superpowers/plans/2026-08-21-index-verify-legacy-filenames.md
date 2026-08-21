# index verify 改用 frontmatter 真实 ID 对账 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `jfox index verify` 以 frontmatter `id` 字段（而非文件名）与向量库对账，消除 legacy `14位时间戳-6位微秒-slug` 文件名导致的 orphan 误报。

**Architecture:** `Indexer.verify_index()` 复用 `jfox/note_index.py::_parse_frontmatter_only()` 逐文件取真实 ID，与 `vector_store.get_all_ids()` 做差集；unreadable 文件与重复 ID 单独报告；CLI 输出标注验证对象为 VectorStore。删除已无调用者的 `_extract_note_id_from_filename`。

**Tech Stack:** Python 3.10+, pytest, Typer/Rich（不引入新依赖）。

## Global Constraints

- verify 必须保持不加载 embedding 模型（秒级只读路径）；改动不碰 `VectorStore.add_note` 等写入路径。
- 返回 dict 保留键 `total_files` / `total_indexed` / `missing_from_index` / `orphaned_in_index` / `healthy`（`tests/unit/test_index_kb_param.py` 断言 `healthy` 存在，向后兼容）。
- `healthy` 语义 = missing 与 orphaned 均为空；unreadable/duplicate 不影响 healthy（文件层问题，repair 修不了）。
- 中文注释与现有代码风格一致（jfox 项目注释用中文）；行宽 100。
- 所有文件操作在 worktree 内（`/home/elling/git-repo/github/jfox/.pi/worktrees/issue-407-index-verify-legacy-filenames/`），禁止触碰主 checkout。

---

### Task 1: verify_index 数据源替换 + 删除旧解析函数（`jfox/indexer.py`）

**Files:**
- Modify: `jfox/indexer.py:30-50`（删除 `_extract_note_id_from_filename`）、`jfox/indexer.py:315-346`（重写 `verify_index`）、`jfox/indexer.py:11`（删 `import re`）
- Test: `tests/unit/test_indexer_verify.py`（整体重写）

**Interfaces:**
- Produces: `Indexer.verify_index() -> Dict[str, Any]`，键：
  - `total_files: int` — 扫描到的 md 文件总数（含 unreadable）
  - `valid_files: int` — 有有效 frontmatter id 的文件数（含重复）
  - `unique_ids: int` — 去重后的文件 ID 数
  - `total_indexed: int` — 向量库 ID 数
  - `unreadable_files: List[str]` — frontmatter 读不了/无 id 的文件绝对路径
  - `duplicate_ids: List[Dict[str, Any]]` — `[{"id": str, "files": [str]}]`，同 id 多文件，按 id 排序
  - `missing_from_index: List[str]` — 文件有、向量库无（sorted）
  - `orphaned_in_index: List[str]` — 向量库有、文件无（sorted）
  - `healthy: bool`
  - `checked: str` — 恒为 `"vector_store"`
  - notes_dir 不存在时：`{"error": "Notes directory not found"}`（保持现状）
- Consumes: `jfox.note_index._parse_frontmatter_only(filepath) -> Optional[dict]`（返回 None 表示解析失败）

- [ ] **Step 1: 写失败测试（重写 `tests/unit/test_indexer_verify.py`）**

```python
"""
测试 indexer.verify_index 以 frontmatter 真实 ID 对账

Issue #407: legacy 文件名（14位时间戳-6位微秒-slug）无法从文件名解析 ID，
导致 candidate/legacy permanent 全部误报 orphaned。
"""

import pytest

from jfox.config import ZKConfig
from jfox.indexer import Indexer


class FakeVectorStore:
    """verify_index 只调用 get_all_ids()；假对象避开 ChromaDB/embedding 依赖"""

    def __init__(self, ids):
        self._ids = list(ids)

    def get_all_ids(self):
        return list(self._ids)


@pytest.fixture
def indexer(tmp_path):
    """构造 notes 目录 + FakeVectorStore + Indexer"""
    cfg = ZKConfig(base_dir=tmp_path)
    cfg.ensure_dirs()
    return Indexer(cfg, FakeVectorStore([]))


def write_note(notes_dir, relpath, note_id, title="Test"):
    """手写含 frontmatter 的 md 文件，返回路径"""
    p = notes_dir / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        f"---\nid: {note_id}\ntitle: {title}\ntype: permanent\n"
        "created: '2026-01-01T00:00:00'\n---\n\n# {title}\n\nbody\n",
        encoding="utf-8",
    )
    return p


class TestLegacyFilenameReconciliation:
    """legacy 14位-6位-slug 文件名不再误报（#407 核心）"""

    def test_legacy_candidate_filename(self, indexer):
        notes_dir = indexer.config.notes_dir
        nid = "20260628004828-286060"
        write_note(notes_dir, f"candidate/{nid}-jfox-embedding-daemon.md", nid)
        indexer.vector_store = FakeVectorStore([nid])

        result = indexer.verify_index()
        assert result["missing_from_index"] == []
        assert result["orphaned_in_index"] == []
        assert result["healthy"] is True

    def test_legacy_permanent_filename(self, indexer):
        notes_dir = indexer.config.notes_dir
        nid = "20260708002136-108471"
        write_note(notes_dir, f"permanent/{nid}-cc-plugin-版本号.md", nid)
        indexer.vector_store = FakeVectorStore([nid])

        result = indexer.verify_index()
        assert result["healthy"] is True
        assert result["unique_ids"] == 1
        assert result["valid_files"] == 1

    def test_current_formats_still_reconcile(self, indexer):
        """18位-slug / fleeting 8-10 / session 18位 回归"""
        notes_dir = indexer.config.notes_dir
        write_note(notes_dir, "permanent/202604120150293323-some-slug.md", "202604120150293323")
        write_note(notes_dir, "fleeting/20260412-0150293323.md", "202604120150293323")
        write_note(notes_dir, "session/202604120150293399-session-a.md", "202604120150293399")
        indexer.vector_store = FakeVectorStore(
            ["202604120150293323", "202604120150293399"]
        )

        result = indexer.verify_index()
        assert result["healthy"] is True
        assert result["unique_ids"] == 2
        assert result["total_files"] == 3


class TestUnreadableAndDuplicate:
    """unreadable / duplicate 单独报告，不混入 missing/orphaned"""

    def test_unreadable_file_reported_separately(self, indexer):
        notes_dir = indexer.config.notes_dir
        good_id = "202604120150293323"
        write_note(notes_dir, "permanent/good.md", good_id)
        broken = notes_dir / "permanent" / "broken.md"
        broken.parent.mkdir(parents=True, exist_ok=True)
        broken.write_text("# no frontmatter here\n\njust body\n", encoding="utf-8")
        indexer.vector_store = FakeVectorStore([good_id])

        result = indexer.verify_index()
        assert result["unreadable_files"] == [str(broken)]
        assert result["missing_from_index"] == []
        assert result["orphaned_in_index"] == []
        assert result["total_files"] == 2
        assert result["valid_files"] == 1

    def test_frontmatter_without_id_is_unreadable(self, indexer):
        notes_dir = indexer.config.notes_dir
        p = notes_dir / "permanent" / "no-id.md"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("---\ntitle: No Id\ntype: permanent\n---\n\nbody\n", encoding="utf-8")

        result = indexer.verify_index()
        assert result["unreadable_files"] == [str(p)]
        assert result["healthy"] is True  # 对账无差集

    def test_duplicate_id_reported(self, indexer):
        notes_dir = indexer.config.notes_dir
        nid = "20260711104217-263635"
        f1 = write_note(notes_dir, f"permanent/{nid}-没爆就别修.md", nid, title="A")
        f2 = write_note(notes_dir, f"permanent/{nid}-代码审查务实原则.md", nid, title="B")
        indexer.vector_store = FakeVectorStore([nid])

        result = indexer.verify_index()
        assert len(result["duplicate_ids"]) == 1
        assert result["duplicate_ids"][0]["id"] == nid
        assert set(result["duplicate_ids"][0]["files"]) == {str(f1), str(f2)}
        assert result["missing_from_index"] == []
        assert result["orphaned_in_index"] == []
        assert result["unique_ids"] == 1
        assert result["valid_files"] == 2


class TestTrueDiff:
    """missing / orphaned 真值判定"""

    def test_missing_and_orphaned(self, indexer):
        notes_dir = indexer.config.notes_dir
        file_only = "202604120150293323"
        index_only = "202604120150293999"
        write_note(notes_dir, "permanent/file-only.md", file_only)
        indexer.vector_store = FakeVectorStore([index_only])

        result = indexer.verify_index()
        assert result["missing_from_index"] == [file_only]
        assert result["orphaned_in_index"] == [index_only]
        assert result["healthy"] is False
        assert result["checked"] == "vector_store"

    def test_empty_notes_dir(self, indexer):
        result = indexer.verify_index()
        assert result["total_files"] == 0
        assert result["healthy"] is True

    def test_missing_notes_dir(self, tmp_path):
        import shutil

        cfg = ZKConfig(base_dir=tmp_path)
        cfg.ensure_dirs()
        shutil.rmtree(cfg.notes_dir)
        idx = Indexer(cfg, FakeVectorStore([]))
        result = idx.verify_index()
        assert result == {"error": "Notes directory not found"}
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-407-index-verify-legacy-filenames
uv run pytest tests/unit/test_indexer_verify.py -v
```

Expected: FAIL（`test_legacy_candidate_filename` 报 orphaned 误报；`test_missing_notes_dir` 因新键不存在而断言差异——旧实现返回旧结构；旧版测试文件整体被替换）

- [ ] **Step 3: 实现（修改 `jfox/indexer.py`）**

删除 `_extract_note_id_from_filename` 函数（30-50 行）与 `import re`（第 11 行，该文件 `re` 仅此函数使用）。

重写 `verify_index`（315-346 行）：

```python
    def verify_index(self) -> Dict[str, any]:
        """
        Verify the vector store against note files, reconciling by frontmatter
        note IDs. Filename format is irrelevant — legacy `14位时间戳-6位微秒-slug`
        files reconcile correctly as long as their frontmatter `id` matches.

        Returns:
            Dict with verification results (see unit tests for the contract).
        """
        from .note_index import _parse_frontmatter_only

        notes_dir = Path(self.config.notes_dir)
        if not notes_dir.exists():
            return {"error": "Notes directory not found"}

        # 按 frontmatter 真实 id 收集文件（文件名格式无关）
        note_files = list(notes_dir.rglob("*.md"))
        id_to_files: Dict[str, List[str]] = {}
        unreadable_files: List[str] = []
        for f in note_files:
            fm = _parse_frontmatter_only(f)
            if fm is None or not fm.get("id"):
                unreadable_files.append(str(f))
                continue
            note_id = str(fm["id"])
            id_to_files.setdefault(note_id, []).append(str(f))

        duplicate_ids = [
            {"id": nid, "files": paths}
            for nid, paths in sorted(id_to_files.items())
            if len(paths) > 1
        ]
        file_ids = set(id_to_files)

        indexed_ids = set(self.vector_store.get_all_ids())
        missing_from_index = sorted(file_ids - indexed_ids)
        orphaned_in_index = sorted(indexed_ids - file_ids)

        return {
            "total_files": len(note_files),
            "valid_files": sum(len(v) for v in id_to_files.values()),
            "unique_ids": len(file_ids),
            "total_indexed": len(indexed_ids),
            "unreadable_files": unreadable_files,
            "duplicate_ids": duplicate_ids,
            "missing_from_index": missing_from_index,
            "orphaned_in_index": orphaned_in_index,
            "healthy": not missing_from_index and not orphaned_in_index,
            "checked": "vector_store",
        }
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-407-index-verify-legacy-filenames
uv run pytest tests/unit/test_indexer_verify.py -v
```

Expected: PASS（全部新用例）

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_indexer_verify.py jfox/indexer.py
git commit -m "fix(index): verify 以 frontmatter 真实 ID 对账向量库，修复 legacy 文件名误报 orphan (#407)"
```

---

### Task 2: CLI verify 分支输出更新（`jfox/cli.py`）

**Files:**
- Modify: `jfox/cli.py:2425-2457`（verify 分支）

**Interfaces:**
- Consumes: Task 1 的 `verify_index()` 返回结构（含 `error` / `checked` / `unreadable_files` / `duplicate_ids`）
- Produces: 无（CLI 终端输出）

- [ ] **Step 1: 修改 verify 分支（`jfox/cli.py:2425-2457`）**

```python
        elif action == "verify":
            verification = indexer.verify_index()

            result = verification

            if output_format == "json":
                print(output_json(result))
            else:
                if verification.get("error"):
                    console.print(f"[red]✗[/red] {verification['error']}")
                    raise typer.Exit(1)

                console.print(
                    "[bold]Vector Store Verification[/bold] "
                    "[dim](BM25 not covered — see `jfox index bm25-status`)[/dim]"
                )
                if verification["healthy"]:
                    console.print("[green]✓[/green] Vector index is healthy")
                else:
                    console.print("[yellow]⚠[/yellow] Vector index has issues")

                console.print(f"  Files: {verification['total_files']}")
                console.print(f"  Valid IDs: {verification['unique_ids']}")
                console.print(f"  Indexed: {verification['total_indexed']}")

                if verification["unreadable_files"]:
                    console.print(
                        f"\n[yellow]Unreadable files "
                        f"({len(verification['unreadable_files'])}):[/yellow]"
                    )
                    for p in verification["unreadable_files"][:5]:
                        console.print(f"  - {p}")

                if verification["duplicate_ids"]:
                    console.print(
                        f"\n[yellow]Duplicate IDs "
                        f"({len(verification['duplicate_ids'])}):[/yellow]"
                    )
                    for d in verification["duplicate_ids"][:5]:
                        console.print(f"  - {d['id']}")

                if verification["missing_from_index"]:
                    console.print(
                        f"\n[yellow]Missing from index "
                        f"({len(verification['missing_from_index'])}):[/yellow]"
                    )
                    for nid in verification["missing_from_index"][:5]:
                        console.print(f"  - {nid}")

                if verification["orphaned_in_index"]:
                    console.print(
                        f"\n[yellow]Orphaned in index "
                        f"({len(verification['orphaned_in_index'])}):[/yellow]"
                    )
                    for nid in verification["orphaned_in_index"][:5]:
                        console.print(f"  - {nid}")
```

- [ ] **Step 2: 运行 CLI 相关测试**

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-407-index-verify-legacy-filenames
uv run pytest tests/unit/test_index_kb_param.py -v
uv run pytest tests/unit/test_indexer_verify.py -v
```

Expected: PASS（`test_index_kb_param.py` 断言 `healthy` in data，新结构兼容）

- [ ] **Step 3: Commit**

```bash
git add jfox/cli.py
git commit -m "fix(cli): index verify 输出标注 VectorStore 并单独报告 unreadable/duplicate (#407)"
```

---

### Task 3: 集成测试断言更新（`tests/test_advanced_features.py`）

**Files:**
- Modify: `tests/test_advanced_features.py:133-135`（test_indexer 的 verify 断言）、`tests/test_advanced_features.py:189-225`（test_verify_index_matches_filenames_to_ids）

**Interfaces:**
- Consumes: Task 1 的返回结构

- [ ] **Step 1: 更新断言**

`test_indexer`（~134 行）:

```python
    # 测试 verify_index
    verification = indexer.verify_index()
    assert verification["total_files"] == 1
    assert verification["unique_ids"] == 1
    assert verification["checked"] == "vector_store"
    assert verification["healthy"] is True
```

`test_verify_index_matches_filenames_to_ids` 末尾（~216-222 行）追加：

```python
    assert result["missing_from_index"] == []
    assert result["orphaned_in_index"] == []
    assert result["unreadable_files"] == []
    assert result["checked"] == "vector_store"
```

（原断言 `result["healthy"] is True` 保留不变——新实现下依然通过，证明向后兼容。）

- [ ] **Step 2: 运行测试**

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-407-index-verify-legacy-filenames
uv run pytest tests/test_advanced_features.py -v
```

Expected: PASS

- [ ] **Step 3: 全量快速测试回归**

```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-407-index-verify-legacy-filenames
uv run pytest tests/ -m "not embedding and not slow" -q
```

Expected: PASS（若出现与本改动无关的既有失败，记录并在 commit message 注明，不顺手修）

- [ ] **Step 4: Commit**

```bash
git add tests/test_advanced_features.py
git commit -m "test(index): verify 集成测试断言对齐 frontmatter 对账结构 (#407)"
```

---

### Task 4: 文档文案（`README.md`）

**Files:**
- Modify: `README.md:300`

- [ ] **Step 1: 更新表格行**

`README.md:300` 原文：

```markdown
| `jfox index verify` | Cross-check files vs indexed entries |
```

改为：

```markdown
| `jfox index verify` | Cross-check note files vs vector store entries by frontmatter IDs |
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: index verify 表格描述标注 vector store 与 frontmatter ID 对账 (#407)"
```

---

## Self-Review

**1. Spec coverage:**
- 四种文件格式对账 → Task 1 `test_current_formats_still_reconcile` + `test_legacy_*`
- candidate 不再误报 → Task 1 legacy 用例（candidate 目录）
- missing/orphan 与 frontmatter 对账一致 → Task 1 `TestTrueDiff`（调研 R3 实测同口径）
- 输出区分 vector/BM25 → Task 2 `checked` 字段 + 标题；Task 4 文档
- 回归测试 legacy/unreadable/duplicate → Task 1 `TestLegacyFilenameReconciliation` + `TestUnreadableAndDuplicate`

**2. Placeholder scan:** 无 TBD/占位符；所有代码块为完整内容。

**3. Type consistency:** `verify_index` 返回键在 Task 1 Interface 定义、Task 2 CLI 与 Task 3 测试消费一致；`FakeVectorStore.get_all_ids()` 签名与 `VectorStore.get_all_ids()` 一致。
