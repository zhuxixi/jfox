# Issue #561 backlinks 并发覆盖修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除 `jfox index rebuild --backlinks` 写回对并发编辑的静默覆盖——写回改为「重读 → 分歧检测 → 原子写」，发现并发改动即跳过本条笔记。

**Architecture:** 在 `jfox/note.py` 新增两个单元：纯函数 `backlinks_write_needed`（零写入守卫）与副作用包装 `apply_backlinks`（重读 → 分歧检测 → 原子写 → 刷新索引 meta）。`jfox/cli.py` 的 `_rebuild_backlinks_impl` 第三阶段由 `note.save_note()` 整条覆盖改为调用 `apply_backlinks`，并按返回值分派计数。并发分歧的笔记本轮跳过，下次 rebuild 自愈。

**Tech Stack:** Python ≥3.10、pytest（tmp_path + unittest.mock.patch）、black/ruff。

**Spec:** `docs/superpowers/specs/2026-09-29-issue-561-backlinks-snapshot-overwrite-design.md`（决策表 D1–D9 与验收矩阵 A1–A7/U1 以 spec 为准）

## Global Constraints

- **只在 worktree 内作业**：`WT=/home/elling/work/git-repo/jfox/.pi/worktrees/issue-561-backlinks-snapshot-overwrite`；所有文件操作用 `$WT` 开头的绝对路径，git 操作用 `git -C $WT`，禁止在主 checkout 改动。
- 按文件 `git add <file>`，**禁止 `git add -A`**。
- 行宽 100；`uv run black` / `uv run ruff check` 必须通过；注释与文档字符串用中文；commit message 用 conventional commits 英文/中文混合风格与仓库历史一致。
- 新测试不得加载 embedding 模型 / ChromaDB / 真实知识库（`~/.zettelkasten`）：文件用 `tmp_path`，`find_note_file` 与索引用 `patch`。
- JSON 输出**只增不改**：新增 `backlinks_skipped` 字段，既有字段名与语义不变。
- 非目标（spec §2）：不加文件锁、不改 rebuild 执行顺序、不碰 `list_notes(limit=10000)` 上限、不当场合并并发新增链接。

## Review Focus

spec 未明说、但合理用户会撞上的输入/条件，及其归属测试：

1. **手改格式的笔记文件**（frontmatter 字段顺序乱、有多余空行）：`to_markdown()` 归一化后不应误判分歧 → Task 2 `test_hand_formatted_file_is_not_false_divergence`。
2. **并发方只动了 `updated` 时间戳**（无语义变化）：保守判分歧跳过是可接受行为，pin 住 → Task 2 `test_updated_only_change_counts_as_divergence`。
3. **target_links / target_backlinks 含重复或乱序元素**：写入前必须排序去重 → Task 1 `test_equal_ignoring_order_and_duplicates` + Task 2 写入断言。
4. **空知识库 early-return 的 JSON 字段完整性**：`backlinks_skipped: 0` 必须在 → Task 3 `test_rebuild_empty_notes` 更新。
5. **skipped=0 时 table 输出与现状逐字节一致**（新提示只在 skipped>0 时打印，不破坏既有格式断言）→ Task 3 `test_rebuild_no_skipped_line_when_zero`。

---

### Task 1: `backlinks_write_needed` 纯函数

**验收:** spec A1（自动化验证 unit）
**Files:**

- Create: `tests/unit/test_apply_backlinks.py`
- Modify: `jfox/note.py`（在 `save_note` 之后新增函数；顶部 `typing` 导入加 `Sequence`）

**Interfaces:**

- Consumes: 无（首个任务）
- Produces: `note.backlinks_write_needed(links: Sequence[str], backlinks: Sequence[str], target_links: Sequence[str], target_backlinks: Sequence[str]) -> bool` —— Task 2 的 `apply_backlinks` 调用它做零写入守卫。

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/test_apply_backlinks.py`：

```python
"""
测试类型: 单元测试
目标功能: note.backlinks_write_needed / note.apply_backlinks（#561 分歧即跳过窄写）
预估耗时: 1-2秒

不依赖真实知识库与 embedding：文件用 tmp_path，find_note_file 与索引走 patch。
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

from jfox import note as note_module
from jfox.models import Note, NoteType


class TestBacklinksWriteNeeded:
    """backlinks_write_needed 纯函数：目标值与现值（各自排序去重后）是否不同"""

    def test_equal_ignoring_order_and_duplicates(self):
        assert (
            note_module.backlinks_write_needed(
                ["b", "a", "a"], ["x"], ["a", "b"], ["x"]
            )
            is False
        )

    def test_both_empty_equal(self):
        assert note_module.backlinks_write_needed([], [], [], []) is False

    def test_links_differ(self):
        assert note_module.backlinks_write_needed(["a"], [], ["a", "b"], []) is True

    def test_backlinks_differ(self):
        assert note_module.backlinks_write_needed([], [], [], ["c"]) is True

    def test_empty_to_nonempty(self):
        assert note_module.backlinks_write_needed([], [], ["a"], []) is True
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd $WT && uv run pytest tests/unit/test_apply_backlinks.py -q`
Expected: FAIL（`AttributeError: module 'jfox.note' has no attribute 'backlinks_write_needed'`）

- [ ] **Step 3: 实现**

`jfox/note.py` 顶部导入行改为：

```python
from typing import Any, Dict, List, Optional, Sequence
```

在 `save_note` 函数之后新增：

```python
def backlinks_write_needed(
    links: Sequence[str],
    backlinks: Sequence[str],
    target_links: Sequence[str],
    target_backlinks: Sequence[str],
) -> bool:
    """零写入守卫（#561）：重算目标值与现有值（各自排序去重后）是否不同。

    纯函数，无 I/O。供 apply_backlinks 在重读 fresh 后判断是否需要写盘。
    """
    return sorted(set(links)) != sorted(set(target_links)) or sorted(
        set(backlinks)
    ) != sorted(set(target_backlinks))
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd $WT && uv run pytest tests/unit/test_apply_backlinks.py -q`
Expected: PASS（5 个用例）

- [ ] **Step 5: Commit**

```bash
git -C $WT add tests/unit/test_apply_backlinks.py jfox/note.py
git -C $WT commit -m "feat(note): backlinks_write_needed 零写入守卫纯函数 (#561 A1)"
```

---

### Task 2: `apply_backlinks` 副作用包装（分歧即跳过）

**验收:** spec A2、A3、A4（自动化验证 unit）
**Files:**

- Modify: `jfox/note.py`（`backlinks_write_needed` 之后新增 `apply_backlinks`）
- Test: `tests/unit/test_apply_backlinks.py`（追加 `TestApplyBacklinks`）

**Interfaces:**

- Consumes: Task 1 的 `backlinks_write_needed`；同模块的 `find_note_file`、`load_note`、`_atomic_write`；`jfox.note_index.get_note_index`（函数内惰性导入）。
- Produces: `note.apply_backlinks(snapshot: Note, target_links: Sequence[str], target_backlinks: Sequence[str], cfg: Optional[ZKConfig] = None) -> str`，返回 `"updated" | "unchanged" | "skipped" | "error"` —— Task 3 的 `_rebuild_backlinks_impl` 按返回值分派计数。

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_apply_backlinks.py` 追加：

```python
def _make_note(
    note_id: str = "202601010000000001",
    title: str = "Note A",
    content: str = "Content A",
    links=None,
    backlinks=None,
    tags=None,
) -> Note:
    """构造最小 Note 对象"""
    from datetime import datetime

    return Note(
        id=note_id,
        title=title,
        content=content,
        type=NoteType.PERMANENT,
        created=datetime(2026, 1, 1),
        updated=datetime(2026, 1, 1),
        tags=tags or [],
        links=links or [],
        backlinks=backlinks or [],
    )


def _roundtrip_to_disk(n: Note, path: Path) -> Note:
    """落盘并重新 load，返回钉住真实路径的快照对象"""
    path.write_text(n.to_markdown(), encoding="utf-8")
    snapshot = note_module.load_note(path)
    assert snapshot is not None
    return snapshot


class TestApplyBacklinks:
    """apply_backlinks：重读 → 分歧检测 → 原子写（#561）"""

    def test_writes_recomputed_values_when_no_divergence(self, tmp_path):
        """A3：无分歧 → updated，links/backlinks 写重算值，其余字段原样，索引 meta 刷新"""
        path = tmp_path / "202601010000000001-note-a.md"
        snapshot = _roundtrip_to_disk(_make_note(tags=["keep"]), path)

        with patch("jfox.note_index.get_note_index") as mock_idx:
            status = note_module.apply_backlinks(
                snapshot, ["202601010000000002"], ["202601010000000003"]
            )

        assert status == "updated"
        fresh = note_module.load_note(path)
        assert fresh.links == ["202601010000000002"]
        assert fresh.backlinks == ["202601010000000003"]
        assert fresh.tags == ["keep"]  # 其余字段原样
        assert fresh.content == "Content A"
        mock_idx.return_value.update_note_meta.assert_called_once()

    def test_unchanged_when_targets_already_on_disk(self, tmp_path):
        """A3：目标值已在盘上 → unchanged 且零写入（mtime 不变）"""
        path = tmp_path / "202601010000000001-note-a.md"
        snapshot = _roundtrip_to_disk(
            _make_note(links=["202601010000000002"], backlinks=["202601010000000003"]),
            path,
        )
        mtime_before = path.stat().st_mtime_ns

        with patch("jfox.note_index.get_note_index") as mock_idx:
            status = note_module.apply_backlinks(
                snapshot, ["202601010000000002"], ["202601010000000003"]
            )

        assert status == "unchanged"
        assert path.stat().st_mtime_ns == mtime_before
        mock_idx.return_value.update_note_meta.assert_not_called()

    def test_skips_when_concurrent_modification_detected(self, tmp_path):
        """A2：快照后并发方改正文/标签 → skipped、零写入，并发方内容逐字节保留"""
        path = tmp_path / "202601010000000001-note-a.md"
        snapshot = _roundtrip_to_disk(_make_note(), path)

        # 并发方写入 v2（模拟另一会话的 jfox edit）
        concurrent = note_module.load_note(path)
        concurrent.content = "edited by another session"
        concurrent.tags = ["concurrent-tag"]
        path.write_text(concurrent.to_markdown(), encoding="utf-8")

        with patch("jfox.note_index.get_note_index") as mock_idx:
            status = note_module.apply_backlinks(
                snapshot, ["202601010000000002"], ["202601010000000003"]
            )

        assert status == "skipped"
        on_disk = note_module.load_note(path)
        assert on_disk.content == "edited by another session"
        assert on_disk.tags == ["concurrent-tag"]
        assert on_disk.links == []  # 重算值没有落盘
        assert on_disk.backlinks == []
        mock_idx.return_value.update_note_meta.assert_not_called()

    def test_updated_only_change_counts_as_divergence(self, tmp_path):
        """Review Focus 2：并发方只动 updated 时间戳也保守判分歧（可接受，pin 住）"""
        from datetime import datetime

        path = tmp_path / "202601010000000001-note-a.md"
        snapshot = _roundtrip_to_disk(_make_note(), path)

        concurrent = note_module.load_note(path)
        concurrent.updated = datetime(2026, 6, 6)
        path.write_text(concurrent.to_markdown(), encoding="utf-8")

        with patch("jfox.note_index.get_note_index"):
            status = note_module.apply_backlinks(snapshot, ["x"], [])

        assert status == "skipped"

    def test_hand_formatted_file_is_not_false_divergence(self, tmp_path):
        """Review Focus 1：手改格式（字段顺序/空行）的文件经 to_markdown 归一化后不误判分歧"""
        path = tmp_path / "202601010000000001-note-a.md"
        path.write_text(
            "---\n"
            "title: Note A\n"
            "id: '202601010000000001'\n"
            "type: permanent\n"
            "created: '2026-01-01T00:00:00'\n"
            "updated: '2026-01-01T00:00:00'\n"
            "\n"
            "tags: []\n"
            "links: []\n"
            "backlinks: []\n"
            "---\n"
            "\n"
            "# Note A\n"
            "\n"
            "Content A\n",
            encoding="utf-8",
        )
        snapshot = note_module.load_note(path)
        assert snapshot is not None

        with patch("jfox.note_index.get_note_index"):
            status = note_module.apply_backlinks(snapshot, ["202601010000000002"], [])

        # 未被误判分歧跳过：正常写入（文件格式被归一化是可接受的既有行为）
        assert status == "updated"
        assert note_module.load_note(path).links == ["202601010000000002"]

    def test_falls_back_to_find_note_file_when_pinned_path_missing(self, tmp_path):
        """A4①：快照钉住的路径失效（并发 edit --title 改名）→ find_note_file 兜底成功"""
        old_path = tmp_path / "202601010000000001-note-a.md"
        new_path = tmp_path / "202601010000000001-renamed.md"
        snapshot = _roundtrip_to_disk(_make_note(), old_path)
        old_path.rename(new_path)  # 模拟并发 rename

        with patch(
            "jfox.note.find_note_file", return_value=new_path
        ), patch("jfox.note_index.get_note_index"):
            status = note_module.apply_backlinks(snapshot, ["202601010000000002"], [])

        assert status == "updated"
        assert note_module.load_note(new_path).links == ["202601010000000002"]

    def test_id_mismatch_on_pinned_path_is_not_written(self, tmp_path):
        """A4②：钉住路径被别的 id 的文件占用且兜底找不到 → skipped，占位文件不动"""
        path = tmp_path / "202601010000000001-note-a.md"
        snapshot = _roundtrip_to_disk(_make_note(), path)
        # 并发方把别的笔记写到了这个路径（极端路径复用）
        occupant_bytes = _make_note(note_id="999999999999999999", title="Occupant").to_markdown()
        path.write_text(occupant_bytes, encoding="utf-8")

        with patch("jfox.note.find_note_file", return_value=None), patch(
            "jfox.note_index.get_note_index"
        ):
            status = note_module.apply_backlinks(snapshot, ["202601010000000002"], [])

        assert status == "skipped"
        assert path.read_text(encoding="utf-8") == occupant_bytes  # 占位文件逐字节未动

    def test_missing_returns_skipped_without_exception(self, tmp_path):
        """A4③：路径失效且 find_note_file 找不到（并发 delete）→ skipped，不写盘不抛异常"""
        path = tmp_path / "202601010000000001-note-a.md"
        snapshot = _roundtrip_to_disk(_make_note(), path)
        path.unlink()

        with patch("jfox.note.find_note_file", return_value=None), patch(
            "jfox.note._atomic_write"
        ) as mock_write, patch("jfox.note_index.get_note_index"):
            status = note_module.apply_backlinks(snapshot, ["202601010000000002"], [])

        assert status == "skipped"
        mock_write.assert_not_called()

    def test_write_error_returns_error(self, tmp_path):
        """A4：写盘异常 → error（捕获不向上抛），索引 meta 不刷新"""
        path = tmp_path / "202601010000000001-note-a.md"
        snapshot = _roundtrip_to_disk(_make_note(), path)

        with patch(
            "jfox.note._atomic_write", side_effect=OSError("disk full")
        ), patch("jfox.note_index.get_note_index") as mock_idx:
            status = note_module.apply_backlinks(snapshot, ["202601010000000002"], [])

        assert status == "error"
        mock_idx.return_value.update_note_meta.assert_not_called()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd $WT && uv run pytest tests/unit/test_apply_backlinks.py -q`
Expected: FAIL（`AttributeError: ... no attribute 'apply_backlinks'`；Task 1 的 5 个用例仍 PASS）

- [ ] **Step 3: 实现**

`jfox/note.py` 中 `backlinks_write_needed` 之后新增：

```python
def apply_backlinks(
    snapshot: Note,
    target_links: Sequence[str],
    target_backlinks: Sequence[str],
    cfg: Optional[ZKConfig] = None,
) -> str:
    """#561：发现分歧即跳过的 backlinks 窄写（替代 rebuild 的 save_note 整条覆盖）。

    流程：定位文件（快照钉住的真实路径优先，find_note_file 兜底）→ 重读 fresh
    → 分歧检测（fresh 与快照的序列化结果不一致说明有并发写入，本轮跳过）
    → 零写入守卫 → 在 fresh 上赋重算值 → 原子写 → 刷新索引 meta。

    Returns:
        "updated"   写入成功
        "unchanged" 目标值已在盘上，零写入
        "skipped"   文件缺失/被并发修改（正常竞态，非故障；下轮 rebuild 自愈）
        "error"     写盘异常（已捕获并记 warning，不向上抛）
    """
    use_config = cfg or config

    # D1：候选路径——快照钉住的真实路径优先；失效或 id 不匹配时 find_note_file 兜底
    candidates = [snapshot.filepath]
    fresh: Optional[Note] = None
    actual_path: Optional[Path] = None

    for path in candidates:
        if not path.exists():
            continue
        loaded = load_note(path)
        if loaded is not None and loaded.id == snapshot.id:
            fresh, actual_path = loaded, path
            break

    if fresh is None:
        fallback = find_note_file(use_config, snapshot.id)
        if fallback is not None and fallback.exists() and fallback != snapshot.filepath:
            loaded = load_note(fallback)
            if loaded is not None and loaded.id == snapshot.id:
                fresh, actual_path = loaded, fallback

    if fresh is None or actual_path is None:
        logger.info(
            "Skipped backlinks write for %s: 文件缺失或已改名（missing，下轮 rebuild 自愈）",
            snapshot.id,
        )
        return "skipped"

    # D2'：发现分歧即跳过——并发改动优先，本轮不碰这条笔记
    if fresh.to_markdown() != snapshot.to_markdown():
        logger.info(
            "Skipped backlinks write for %s: 检测到并发修改（diverged，下轮 rebuild 自愈）",
            snapshot.id,
        )
        return "skipped"

    # D4：零写入守卫
    if not backlinks_write_needed(
        fresh.links, fresh.backlinks, target_links, target_backlinks
    ):
        return "unchanged"

    fresh.links = sorted(set(target_links))
    fresh.backlinks = sorted(set(target_backlinks))
    try:
        _atomic_write(actual_path, fresh.to_markdown())
    except Exception as e:
        logger.warning("Failed to write backlinks for %s: %s", snapshot.id, e)
        return "error"

    # D6：刷新索引 meta，与 #422 的 delete/promote 修复保持一致
    from .note_index import get_note_index

    get_note_index(use_config).update_note_meta(fresh)
    return "updated"
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd $WT && uv run pytest tests/unit/test_apply_backlinks.py -q`
Expected: PASS（Task 1 的 5 个 + 本任务 9 个用例）

- [ ] **Step 5: Commit**

```bash
git -C $WT add jfox/note.py tests/unit/test_apply_backlinks.py
git -C $WT commit -m "feat(note): apply_backlinks 分歧即跳过窄写 (#561 A2-A4)"
```

---

### Task 3: `_rebuild_backlinks_impl` 第三阶段接入

**验收:** spec A5（自动化验证 unit）+ Review Focus 4/5
**Files:**

- Modify: `jfox/cli.py:389-500`（`_rebuild_backlinks_impl` 第三阶段、early-return 字典、结果字典、控制台输出）
- Test: `tests/unit/test_rebuild_backlinks_impl.py`（改造 mock 目标 + 新增分派用例）

**Interfaces:**

- Consumes: Task 2 的 `note.apply_backlinks(snapshot, target_links, target_backlinks) -> str`。
- Produces: `_rebuild_backlinks_impl` 返回字典新增 `backlinks_skipped: int`；其余字段不变。`jfox index rebuild --backlinks --format json` 的输出随之多一个字段（增量，向后兼容）。

- [ ] **Step 1: 改造既有测试（先让它们按新契约失败）**

`tests/unit/test_rebuild_backlinks_impl.py` 全部 6 个用例：装饰器 `@patch("jfox.note.save_note")` 改为 `@patch("jfox.note.apply_backlinks")`，形参名 `mock_save_note` 改 `mock_apply`，并按下表调整断言：

| 用例 | mock 行为 | 断言调整 |
|---|---|---|
| `test_rebuild_updates_changed_links_and_backlinks` | `mock_apply.return_value = "updated"` | `call_count == 2`；每次调用 `call.args[0]` 是笔记对象、`call.args[1]` 是合并后 links、`call.args[2]` 是重算 backlinks；A 的 backlinks 参数 `== [note_b.id]`，B 的 links 参数 `== [note_a.id]` |
| `test_rebuild_skips_unchanged_notes` | 不需要 | `mock_apply.assert_not_called()` |
| `test_rebuild_reports_unresolved_links` | 不需要 | 不变（links 未变化，apply 不被调用） |
| `test_rebuild_empty_notes` | 不需要 | 断言新增 `result["backlinks_skipped"] == 0` |
| `test_rebuild_filters_self_links` | 不需要 | `mock_apply.assert_not_called()` |
| `test_rebuild_includes_failed_count` | `mock_apply.return_value = "error"` | `updated == 0`、`failed == 2` |

注意：`_FakeNote` 不再需要真实 `to_markdown()`（apply 被 mock），保持现有替身即可。

再追加两个新用例：

```python
    @patch("jfox.note.apply_backlinks")
    @patch("jfox.note_index.get_note_index")
    @patch("jfox.note.list_notes")
    def test_rebuild_dispatches_skipped_and_updated(
        self, mock_list_notes, mock_get_index, mock_apply
    ):
        """A5：updated/skipped 分派到 backlinks_updated / backlinks_skipped，互不混淆"""
        import jfox.cli  # noqa: F401
        from jfox.cli import _rebuild_backlinks_impl

        note_a = _FakeNote(id="202601010000000001", title="Note A", content="Content A")
        note_b = _FakeNote(
            id="202601010000000002", title="Note B", content="Note B references [[Note A]]"
        )
        mock_list_notes.return_value = [note_a, note_b]
        mock_get_index.return_value = _make_index([note_a, note_b])
        mock_apply.side_effect = ["updated", "skipped"]

        result = _rebuild_backlinks_impl(output_format="json")

        assert result["backlinks_updated"] == 1
        assert result["backlinks_skipped"] == 1
        assert result["backlinks_failed"] == 0

    @patch("jfox.note.apply_backlinks")
    @patch("jfox.note_index.get_note_index")
    @patch("jfox.note.list_notes")
    def test_rebuild_no_skipped_line_when_zero(
        self, mock_list_notes, mock_get_index, mock_apply, capsys
    ):
        """Review Focus 5：skipped=0 时 table 输出不出现 skipped 提示行"""
        import jfox.cli  # noqa: F401
        from jfox.cli import _rebuild_backlinks_impl

        note_a = _FakeNote(id="202601010000000001", title="Note A", content="Content A")
        note_b = _FakeNote(
            id="202601010000000002", title="Note B", content="Note B references [[Note A]]"
        )
        mock_list_notes.return_value = [note_a, note_b]
        mock_get_index.return_value = _make_index([note_a, note_b])
        mock_apply.return_value = "updated"

        _rebuild_backlinks_impl(output_format="table")

        out = capsys.readouterr().out
        assert "Skipped" not in out
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd $WT && uv run pytest tests/unit/test_rebuild_backlinks_impl.py -q`
Expected: FAIL（`jfox.note` 没有 `apply_backlinks` 被 patch 时报错，或计数断言失败——`backlinks_skipped` 字段尚不存在）

- [ ] **Step 3: 实现**

`jfox/cli.py` `_rebuild_backlinks_impl` 的修改点：

① 空库 early-return 字典加字段：

```python
        return {
            "backlinks_rebuilt": True,
            "backlinks_updated": 0,
            "backlinks_total": 0,
            "backlinks_failed": 0,
            "backlinks_skipped": 0,
            "unresolved_links": [],
        }
```

② 第三阶段整体替换为（删除 `changed_note_ids` 死代码与快照原地赋值，见 spec D8/D9）：

```python
    # 第三阶段：比较并写回变化的笔记
    # #561：写回走 apply_backlinks（重读→分歧检测→原子写），并发改动不再被快照覆盖。
    # 注意：不得原地修改 n.links / n.backlinks——分歧检测以快照为比对基准（D8）。
    updated_count = 0
    failed_count = 0
    skipped_count = 0

    for n in notes:
        new_links_sorted = merged_links[n.id]
        new_backlinks_sorted = sorted(new_backlinks[n.id])

        if sorted(n.links) != new_links_sorted or sorted(n.backlinks) != new_backlinks_sorted:
            status = note.apply_backlinks(n, new_links_sorted, new_backlinks_sorted)
            if status == "updated":
                updated_count += 1
            elif status == "skipped":
                # 并发修改/文件缺失：正常竞态非故障，下轮 rebuild 自愈（D7）
                skipped_count += 1
            elif status == "error":
                failed_count += 1
                logger.warning(f"Failed to write backlinks for note {n.id} during backlinks rebuild")
            # "unchanged"：并发方已写入目标值，不计数
```

③ 结果字典加 `"backlinks_skipped": skipped_count`。

④ 控制台输出：`failed_count > 0` 的提示之后加：

```python
        if skipped_count > 0:
            console.print(
                f"[dim]Skipped {skipped_count} note(s) "
                f"(concurrent change or missing file; will heal on next rebuild)[/dim]"
            )
```

⑤ docstring 的 Returns 说明补 `backlinks_skipped`。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd $WT && uv run pytest tests/unit/test_rebuild_backlinks_impl.py tests/unit/test_apply_backlinks.py -q`
Expected: PASS（全部用例）

- [ ] **Step 5: Commit**

```bash
git -C $WT add jfox/cli.py tests/unit/test_rebuild_backlinks_impl.py
git -C $WT commit -m "fix(cli): rebuild --backlinks 写回改 apply_backlinks，并发分歧即跳过 (#561 A5)"
```

---

### Task 4: 回归 + 静态检查 + CHANGELOG

**验收:** spec A6（integration）、A7（static）
**Files:**

- Modify: `CHANGELOG.md`（`## [Unreleased]` → `### Fixes` 下加条目）

**Interfaces:**

- Consumes: Task 1–3 的全部产物。
- Produces: 无新接口。

- [ ] **Step 1: 跑既有集成测试（不回归）**

Run: `cd $WT && uv run pytest tests/integration/test_index_rebuild_backlinks.py -q`
Expected: PASS（既有 5 个集成用例；`cli_fast` 用 mock embedding，不加载真实模型）

- [ ] **Step 2: 跑受影响的邻近单测**

Run: `cd $WT && uv run pytest tests/unit/test_rebuild_backlinks_impl.py tests/unit/test_apply_backlinks.py tests/unit/test_delete_backlink_cleanup.py tests/unit/test_note_promote.py -q`
Expected: PASS（确认 note.py 改动未破坏 delete/promote 的 #422 行为）

- [ ] **Step 3: 静态检查**

Run: `cd $WT && uv run black --check jfox tests && uv run ruff check jfox tests && npx --yes markdownlint-cli2`
Expected: 无告警（如 black 有意见，先 `uv run black jfox tests` 再重跑检查）

- [ ] **Step 4: CHANGELOG**

`CHANGELOG.md` 的 `## [Unreleased]` → `### Fixes` 下追加：

```markdown
- **index**: `index rebuild --backlinks` 写回改为「重读→分歧检测→原子写」：检测到并发修改或文件缺失的笔记本轮跳过（计入新 JSON 字段 `backlinks_skipped`，下轮重建自愈），并发 `edit` 的正文不再被旧快照静默覆盖 (#561)
```

- [ ] **Step 5: Commit**

```bash
git -C $WT add CHANGELOG.md
git -C $WT commit -m "docs(changelog): #561 backlinks 并发覆盖修复条目"
```

---

### Task 5: U1 用户实测交接（用户执行，非代码任务）

**验收:** spec U1（用户实测）
**说明:** 无代码改动。合并前把下面的实测指引交给用户执行并回收结果。

实测步骤（在默认知识库上）：

1. `jfox index rebuild --backlinks --format json`
2. 观察输出：`backlinks_rebuilt == true`、`backlinks_failed == 0`、`backlinks_skipped` 字段存在（通常为 0）。
3. 抽查 1-2 条有链接关系的笔记：`jfox refs <id>`，确认 forward/backward 关系符合预期。
4. 通过标准：命令退出码 0、输出符合上述断言、抽查关系正确。

---

## Self-Review 记录

- **Spec coverage**：A1→Task 1；A2–A4→Task 2；A5→Task 3；A6/A7→Task 4；U1→Task 5。D1–D9 决策均有对应实现步骤（D8/D9 在 Task 3 Step 3②，D6 在 Task 2 Step 3，D7 在 Task 3 ②③）。
- **Placeholder scan**：所有代码步骤含完整代码，无 TBD/TODO。
- **Type consistency**：`apply_backlinks` 签名（`snapshot: Note, target_links: Sequence[str], target_backlinks: Sequence[str], cfg: Optional[ZKConfig]`) 在 Task 2 定义、Task 3 以位置参数 `(n, new_links_sorted, new_backlinks_sorted)` 调用，一致；返回值四个字符串字面量两侧一致。
- **Review Focus**：5 项均有归属测试（见上表逐项标注）。
