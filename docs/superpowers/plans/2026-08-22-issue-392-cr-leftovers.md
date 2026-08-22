# Issue #392 CR 低危遗留项修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 #392 的 5 项 CR 低危遗留：A1 warning 文案、A2 同 id 双文件、A3 并发丢更新、B1 conftest mock 缺方法、B2 refs 悬空静默过滤。

**Architecture:** A2+A3 合并为 re-read-and-merge——delete 清理循环与 promote 回填循环写盘前用 `find_note_file` 解析真实磁盘路径、重读 fresh、在 fresh 上修改再写回真实路径。A1 只改日志字符串。B1 给 conftest 共享 mock 补 `encode_single`。B2 让 refs 的 forward/backward 悬空条目带 `dangling` 标记可见化。

**Tech Stack:** Python 3.10+、pytest + typer CliRunner、unittest.mock、black/ruff、markdownlint。

## Global Constraints

- 所有作业在 worktree `/home/elling/git-repo/github/jfox/.pi/worktrees/issue-392-cr-low-risk-leftovers` 内完成，禁止碰 main checkout。
- 代码注释用中文；commit message 用英文 conventional commits（`fix:`/`test:`/`chore:`）。
- 测试文件标记 `pytestmark = [pytest.mark.unit, pytest.mark.fast]`（test_cli_format.py 除外，沿用其现有标记）。
- 每个 task 结束跑 `uv run black jfox/ tests/ && uv run ruff check jfox/ tests/`，改动的 md 文件跑 `npx --yes markdownlint-cli2 <file>`。
- 测试运行命令统一 `uv run pytest <file> -v`（pytest.ini 已含 -v，勿重复加）。
- 不全局改 `Note.from_markdown` 补 set_filepath（会破坏 update_note/promote 重命名检测，spec §4 非目标）。

---

### Task 1: B1 — conftest 共享 mock 补 encode_single

**Files:**

- Modify: `tests/conftest.py`（MockEmbeddingBackend 类，约 56-90 行）
- Create: `tests/unit/test_conftest_mock.py`

**Interfaces:**

- Consumes: `mock_embedding_backend` fixture（conftest 已有）
- Produces: `MockEmbeddingBackend.encode_single(text: str) -> np.ndarray`，shape `(384,)`

- [ ] **Step 1: Write the failing test**

Create `tests/unit/test_conftest_mock.py`:

```python
"""conftest 共享 mock 的契约测试。目标: tests/conftest.py MockEmbeddingBackend"""

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_mock_embedding_backend_has_encode_single(mock_embedding_backend):
    """共享 mock 应实现 encode_single（vector_store.add_note 调用；缺了打 AttributeError 日志）"""
    assert hasattr(mock_embedding_backend, "encode_single"), (
        "conftest MockEmbeddingBackend 缺 encode_single，"
        "vector_store.add_note 会打 AttributeError 日志（#392 B1）"
    )
    vec = mock_embedding_backend.encode_single("hello")
    assert vec.shape == (384,)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_conftest_mock.py`
Expected: FAIL with `AssertionError: conftest MockEmbeddingBackend 缺 encode_single...`

- [ ] **Step 3: Write minimal implementation**

In `tests/conftest.py`，在 `MockEmbeddingBackend.encode_batch` 方法之后加：

```python
        def encode_single(self, text: str):
            """单条编码（vector_store.add_note 调用）"""
            return self.encode([text])[0]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_conftest_mock.py`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/unit/test_conftest_mock.py
git commit -m "test: add encode_single to conftest mock embedding backend (#392 B1)"
```

---

### Task 2: A1 — delete 清理循环 warning 文案中性化

**Files:**

- Modify: `jfox/note.py`（delete_note 清理循环，约 349-355 行）
- Test: `tests/unit/test_delete_backlink_cleanup.py`

**Interfaces:**

- Consumes: 无（Task 1 独立）
- Produces: warning 文案含「如存在」，语义为「仅清理 str 引用（如存在）」

- [ ] **Step 1: Write the failing test**

在 `tests/unit/test_delete_backlink_cleanup.py` 的 `TestDeleteCleansBacklinks` 类中追加：

```python
    def test_delete_pure_dirty_backlinks_warns_neutral_text(self, mock_embedding_backend, caplog):
        """纯脏 list（不含本 id）时 warning 用中性表述「如存在」，不断言未发生的清理（#392 A1）"""
        import logging
        import re

        from jfox.config import use_kb

        with temp_kb_registered() as kb_name:
            with patch("jfox.embedding_backend.get_backend", return_value=mock_embedding_backend):
                b_result = runner.invoke(
                    app,
                    [
                        "add",
                        "B body",
                        "--title",
                        "笔记B",
                        "--type",
                        "permanent",
                        "--kb",
                        kb_name,
                        "--json",
                    ],
                )
                assert b_result.exit_code == 0, b_result.output
                b_id = json.loads(b_result.output)["note"]["id"]

                a_result = runner.invoke(
                    app,
                    [
                        "add",
                        "A 引用 [[笔记B]]。",
                        "--title",
                        "笔记A",
                        "--type",
                        "permanent",
                        "--kb",
                        kb_name,
                        "--json",
                    ],
                )
                assert a_result.exit_code == 0, a_result.output
                a_id = json.loads(a_result.output)["note"]["id"]

                # 手工编辑 B frontmatter：backlinks 改成纯脏 list（不含 a_id）
                with use_kb(kb_name):
                    import jfox.note as note_module

                    b_path = note_module.load_note_by_id(b_id).filepath
                    text = b_path.read_text(encoding="utf-8")
                    text = re.sub(
                        r"backlinks:.*(?:\n[ \t]*-[ \t]+.*)*",
                        "backlinks: [123456]",
                        text,
                        count=1,
                    )
                    b_path.write_text(text, encoding="utf-8")
                    b_mtime = b_path.stat().st_mtime_ns

                with caplog.at_level(logging.WARNING):
                    del_result = runner.invoke(app, ["delete", a_id, "--force", "--kb", kb_name])
                assert del_result.exit_code == 0, del_result.output

                # 中性表述：不断言「清理了」，只提示「如存在」
                assert "如存在" in caplog.text
                # 零写入：B 文件 mtime 不变
                with use_kb(kb_name):
                    assert b_path.stat().st_mtime_ns == b_mtime, "纯脏 list 零写入，不应重写 B 文件"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_delete_backlink_cleanup.py::TestDeleteCleansBacklinks::test_delete_pure_dirty_backlinks_warns_neutral_text`
Expected: FAIL with `AssertionError: assert '如存在' in ...`

- [ ] **Step 3: Write minimal implementation**

在 `jfox/note.py` delete_note 清理循环中，把：

```python
                if bad_types:
                    logger.warning(
                        f"Cleaning backlinks from target {tid}: backlinks 元素类型异常 "
                        f"({', '.join(bad_types)})，仅清理 str 引用"
                    )
```

改为：

```python
                if bad_types:
                    logger.warning(
                        f"target {tid} 的 backlinks 含非 str 元素 ({', '.join(bad_types)})，"
                        f"仅清理 str 引用（如存在）"
                    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_delete_backlink_cleanup.py`
Expected: 全文件 PASS（含既有 10 个测试）

- [ ] **Step 5: Commit**

```bash
git add jfox/note.py tests/unit/test_delete_backlink_cleanup.py
git commit -m "fix(note): neutralize delete cleanup warning wording (#392 A1)"
```

---

### Task 3: A2+A3 — delete_note 清理循环 re-read-and-merge

**Files:**

- Modify: `jfox/note.py`（delete_note 清理循环，约 360-366 行）
- Test: `tests/unit/test_delete_backlink_cleanup.py`

**Interfaces:**

- Consumes: `find_note_file(config, tid)`（note.py:1027 已有）、`load_note(filepath)`（note.py:176 已有）、`config`（note.py 已导入）
- Produces: 清理循环写盘前重读 fresh 并写回真实路径；后续 Task 4 复用同款模式

- [ ] **Step 1: Write the failing tests**

在 `tests/unit/test_delete_backlink_cleanup.py` 的 `TestDeleteCleansBacklinks` 类中追加两个测试：

```python
    def test_delete_cleans_backlink_when_disk_filename_diverges(self, mock_embedding_backend):
        """target 磁盘文件名与计算路径发散时，delete 写回真实路径，不产生同 id 双文件（#392 A2）"""
        import os

        from jfox.config import use_kb

        with temp_kb_registered() as kb_name:
            with patch("jfox.embedding_backend.get_backend", return_value=mock_embedding_backend):
                b_result = runner.invoke(
                    app,
                    [
                        "add",
                        "B body",
                        "--title",
                        "笔记B",
                        "--type",
                        "permanent",
                        "--kb",
                        kb_name,
                        "--json",
                    ],
                )
                assert b_result.exit_code == 0, b_result.output
                b_id = json.loads(b_result.output)["note"]["id"]

                a_result = runner.invoke(
                    app,
                    [
                        "add",
                        "A 引用 [[笔记B]]。",
                        "--title",
                        "笔记A",
                        "--type",
                        "permanent",
                        "--kb",
                        kb_name,
                        "--json",
                    ],
                )
                assert a_result.exit_code == 0, a_result.output
                a_id = json.loads(a_result.output)["note"]["id"]

                # 磁盘改名：文件名与按标题重算的路径发散（手改标题未同步改文件名的等价场景）
                with use_kb(kb_name):
                    import jfox.note as note_module

                    b_path = note_module.load_note_by_id(b_id).filepath
                    diverged = b_path.with_name(f"{b_id}-renamed.md")
                    os.rename(b_path, diverged)

                del_result = runner.invoke(app, ["delete", a_id, "--force", "--kb", kb_name])
                assert del_result.exit_code == 0, del_result.output

                # 无同 id 双文件：真实路径上的 backlinks 已清
                with use_kb(kb_name):
                    import jfox.note as note_module

                    matches = list(diverged.parent.glob(f"{b_id}*.md"))
                    assert len(matches) == 1, "不应产生同 id 双文件"
                    b_note = note_module.load_note(diverged)
                    assert a_id not in b_note.backlinks, "真实路径上的 backlinks 应已清"

    def test_delete_preserves_concurrent_update(self, mock_embedding_backend):
        """并发写模拟：delete 读盘后外部 writer 修改 target，re-read-and-merge 不丢对方更新（#392 A3）"""
        from jfox.config import use_kb

        with temp_kb_registered() as kb_name:
            with patch("jfox.embedding_backend.get_backend", return_value=mock_embedding_backend):
                b_result = runner.invoke(
                    app,
                    [
                        "add",
                        "B body",
                        "--title",
                        "笔记B",
                        "--type",
                        "permanent",
                        "--kb",
                        kb_name,
                        "--json",
                    ],
                )
                assert b_result.exit_code == 0, b_result.output
                b_id = json.loads(b_result.output)["note"]["id"]

                a_result = runner.invoke(
                    app,
                    [
                        "add",
                        "A 引用 [[笔记B]]。",
                        "--title",
                        "笔记A",
                        "--type",
                        "permanent",
                        "--kb",
                        kb_name,
                        "--json",
                    ],
                )
                assert a_result.exit_code == 0, a_result.output
                a_id = json.loads(a_result.output)["note"]["id"]

                with use_kb(kb_name):
                    import jfox.note as note_module

                    original_load_note = note_module.load_note
                    original_atomic_write = note_module._atomic_write
                    calls = {"n": 0}

                    def racing_load_note(filepath):
                        note = original_load_note(filepath)
                        if note and note.id == b_id:
                            calls["n"] += 1
                            if calls["n"] == 1:
                                # 模拟外部 writer：delete 首次读盘后、重读前修改 B 并落盘
                                concurrent = original_load_note(filepath)
                                concurrent.tags = ["concurrent-tag"]
                                original_atomic_write(filepath, concurrent.to_markdown())
                        return note

                    with patch.object(note_module, "load_note", side_effect=racing_load_note):
                        del_result = runner.invoke(
                            app, ["delete", a_id, "--force", "--kb", kb_name]
                        )
                    assert del_result.exit_code == 0, del_result.output

                # 并发方的更新保留 + backlink 已清
                show_b = runner.invoke(app, ["show", b_id, "--kb", kb_name, "--json"])
                assert show_b.exit_code == 0, show_b.output
                data_b = json.loads(show_b.output)
                assert a_id not in data_b["backlinks"], "backlink 应已清"
                assert "concurrent-tag" in data_b["tags"], "并发方的更新不应被覆盖丢失"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_delete_backlink_cleanup.py::TestDeleteCleansBacklinks::test_delete_cleans_backlink_when_disk_filename_diverges tests/unit/test_delete_backlink_cleanup.py::TestDeleteCleansBacklinks::test_delete_preserves_concurrent_update`
Expected: 两个都 FAIL（A2 测试：`len(matches) == 1` 失败，出现双文件；A3 测试：`concurrent-tag` 不在 tags）

- [ ] **Step 3: Write minimal implementation**

在 `jfox/note.py` delete_note 清理循环中，把：

```python
                if note_id in t.backlinks:
                    t.updated = now
                    t.backlinks = [bid for bid in t.backlinks if bid != note_id]
                    # 已知限制：t.filepath 是按 type/标题 slug 重算的路径，非 load 命中的
                    # 磁盘路径；文件名发散时可能另写同 id 双文件（与 promote 回填同病），
                    # 残留由 `jfox index rebuild --backlinks` / `jfox check` 兜底。
                    # 已知限制：本循环无锁 read-modify-write，与常驻 daemon 并发写同一
                    # target 时 last-writer-wins（与 promote 回填 / update_note 同构，全库
                    # 无文件锁，暂不在本 PR 收敛）。
                    _atomic_write(t.filepath, t.to_markdown())
                    get_note_index().update_note_meta(t)
```

改为：

```python
                if note_id in t.backlinks:
                    # A2+A3（#392）：写盘前从真实磁盘路径重读 fresh，在 fresh 上移除再写回。
                    # 修复：1) 文件名发散时不再另写同 id 双文件（写回 load 命中的真实路径）；
                    # 2) 与常驻 daemon 并发写同一 target 时不丢对方更新（re-read-and-merge）。
                    actual_path = find_note_file(config, tid)
                    if not actual_path:
                        logger.warning(
                            f"Failed to clean backlinks from target {tid}: 磁盘文件未找到"
                        )
                        continue
                    fresh = load_note(actual_path)
                    if not fresh:
                        logger.warning(
                            f"Failed to clean backlinks from target {tid}: 重新读取失败"
                        )
                        continue
                    if note_id not in fresh.backlinks:
                        continue  # 并发方已移除本 id，无需写盘
                    fresh.updated = now
                    fresh.backlinks = [bid for bid in fresh.backlinks if bid != note_id]
                    _atomic_write(actual_path, fresh.to_markdown())
                    get_note_index().update_note_meta(fresh)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_delete_backlink_cleanup.py`
Expected: 全文件 PASS（含既有 10 个测试 + 新增 2 个）

- [ ] **Step 5: Commit**

```bash
git add jfox/note.py tests/unit/test_delete_backlink_cleanup.py
git commit -m "fix(note): re-read-and-merge in delete backlink cleanup (#392 A2/A3)"
```

---

### Task 4: A2+A3 — promote_note 回填循环 re-read-and-merge

**Files:**

- Modify: `jfox/note.py`（promote_note 回填循环，约 520-530 行）
- Test: `tests/unit/test_note_promote.py`

**Interfaces:**

- Consumes: Task 3 同款模式（`find_note_file` + `load_note` 重读 + 写回真实路径）
- Produces: promote 回填循环同样不产生双文件、不丢并发更新

- [ ] **Step 1: Write the failing tests**

在 `tests/unit/test_note_promote.py` 中追加两个测试（文件顶部 import 行加 `load_note`）：

```python
def test_promote_backfill_writes_to_actual_disk_path():
    """target 磁盘文件名与计算路径发散时，回填写回真实路径，不产生同 id 双文件（#392 A2）"""
    import os

    from jfox.config import config
    from jfox.note import find_note_file

    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            target = create_note("目标内容", title="目标笔记", note_type=NoteType.PERMANENT)
            save_note(target, add_to_index=False)
            c = _make_candidate("引用目标", "讲讲 [[目标笔记]] 的事")

            # 磁盘改名：文件名与按标题重算的路径发散
            actual = find_note_file(config, target.id)
            diverged = actual.with_name(f"{target.id}-renamed.md")
            os.rename(actual, diverged)

            assert promote_note(c.id) is True

            matches = list(diverged.parent.glob(f"{target.id}*.md"))
            assert len(matches) == 1, "不应产生同 id 双文件"
            t = load_note(diverged)
            assert c.id in t.backlinks, "真实路径上的 backlinks 应已回填"


def test_promote_backfill_preserves_concurrent_update():
    """并发写模拟：promote 回填读盘后外部 writer 修改 target，re-read-and-merge 不丢对方更新（#392 A3）"""
    from unittest.mock import patch

    import jfox.note as note_module

    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            target = create_note("目标内容", title="目标笔记", note_type=NoteType.PERMANENT)
            save_note(target, add_to_index=False)
            c = _make_candidate("引用目标", "讲讲 [[目标笔记]] 的事")

            original_load_note = note_module.load_note
            original_atomic_write = note_module._atomic_write
            calls = {"n": 0}

            def racing_load_note(filepath):
                note = original_load_note(filepath)
                if note and note.id == target.id:
                    calls["n"] += 1
                    if calls["n"] == 1:
                        # 模拟外部 writer：promote 首次读盘后、重读前修改 target 并落盘
                        concurrent = original_load_note(filepath)
                        concurrent.tags = ["concurrent-tag"]
                        original_atomic_write(filepath, concurrent.to_markdown())
                return note

            with patch.object(note_module, "load_note", side_effect=racing_load_note):
                assert promote_note(c.id) is True

            t = load_note_by_id(target.id)
            assert c.id in t.backlinks, "promote 回填应完成"
            assert "concurrent-tag" in t.tags, "并发方的更新不应被回填覆盖丢失"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_note_promote.py::test_promote_backfill_writes_to_actual_disk_path tests/unit/test_note_promote.py::test_promote_backfill_preserves_concurrent_update`
Expected: 两个都 FAIL（A2 测试：双文件；A3 测试：`concurrent-tag` 不在 tags）

- [ ] **Step 3: Write minimal implementation**

在 `jfox/note.py` promote_note 回填循环中，把：

```python
    now = datetime.now()
    for tid in target_ids:
        t = load_note_by_id(tid)
        if t and n.id not in t.backlinks:
            t.updated = now
            t.backlinks = sorted(set(t.backlinks + [n.id]))
            try:
                _atomic_write(t.filepath, t.to_markdown())
                get_note_index().update_note_meta(t)
            except Exception as e:
                logger.warning(f"Failed to backfill backlinks for target {tid}: {e}")
```

改为：

```python
    now = datetime.now()
    for tid in target_ids:
        t = load_note_by_id(tid)
        if t and n.id not in t.backlinks:
            # A2+A3（#392）：写盘前从真实磁盘路径重读 fresh，在 fresh 上追加再写回。
            # 修复：1) 文件名发散时不再另写同 id 双文件；2) 并发写不丢对方更新。
            try:
                actual_path = find_note_file(config, tid)
                if not actual_path:
                    logger.warning(
                        f"Failed to backfill backlinks for target {tid}: 磁盘文件未找到"
                    )
                    continue
                fresh = load_note(actual_path)
                if not fresh:
                    logger.warning(
                        f"Failed to backfill backlinks for target {tid}: 重新读取失败"
                    )
                    continue
                if n.id in fresh.backlinks:
                    continue  # 并发方已回填本 id，无需写盘
                fresh.updated = now
                fresh.backlinks = sorted(set(fresh.backlinks + [n.id]))
                _atomic_write(actual_path, fresh.to_markdown())
                get_note_index().update_note_meta(fresh)
            except Exception as e:
                logger.warning(f"Failed to backfill backlinks for target {tid}: {e}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_note_promote.py tests/unit/test_gem_synth_backfill.py`
Expected: 全 PASS（promote 既有 10 个测试 + 新增 2 个；gem_synth_backfill 不受影响）

- [ ] **Step 5: Commit**

```bash
git add jfox/note.py tests/unit/test_note_promote.py
git commit -m "fix(note): re-read-and-merge in promote backfill loop (#392 A2/A3)"
```

---

### Task 5: B2 — refs 悬空引用可见化

**Files:**

- Modify: `jfox/cli.py`（`_refs_impl`，约 1293-1330 行）
- Test: `tests/test_cli_format.py`

**Interfaces:**

- Consumes: 无（独立于 Task 1-4）
- Produces: `forward_links`/`backward_links` 条目可选带 `"dangling": True` 字段；table 输出悬空条目显示「已删除/悬空」

- [ ] **Step 1: Write the failing test**

在 `tests/test_cli_format.py` 的 `TestCLIFormat` 类中追加：

```python
    def test_refs_note_shows_dangling_backlink(self, cli, sample_notes):
        """悬空 backlink 不再静默过滤：JSON 带 dangling 标记，table 显示「已删除/悬空」（#392 B2）"""
        note_id = sample_notes[0]["id"]
        dangling_id = "99999999999999"

        # 手工注入悬空 backlink：直接改 frontmatter
        note_files = list((cli.kb_path / "notes" / "permanent").glob(f"{note_id}*.md"))
        assert len(note_files) == 1
        text = note_files[0].read_text(encoding="utf-8")
        text = text.replace("backlinks: []", f"backlinks: ['{dangling_id}']")
        note_files[0].write_text(text, encoding="utf-8")

        result = cli.run("refs", "--note", note_id, "--format", "json")
        assert result.success
        data = json.loads(result.stdout)
        dangling = [b for b in data["backward_links"] if b.get("dangling")]
        assert len(dangling) == 1
        assert dangling[0]["id"] == dangling_id

        result_table = cli.run("refs", "--note", note_id, "--format", "table")
        assert result_table.success
        assert "已删除/悬空" in result_table.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_cli_format.py::TestCLIFormat::test_refs_note_shows_dangling_backlink`
Expected: FAIL with `AssertionError: assert 0 == 1`（悬空条目被静默过滤）

- [ ] **Step 3: Write minimal implementation**

在 `jfox/cli.py` `_refs_impl` 中，把：

```python
        # 获取链接到的笔记
        forward_links = []
        for link_id in n.links:
            link_note = note.load_note_by_id(link_id)
            if link_note:
                forward_links.append(
                    {"id": link_id, "title": link_note.title, "type": link_note.type.value}
                )

        # 获取反向链接
        backward_links = []
        for back_id in n.backlinks:
            back_note = note.load_note_by_id(back_id)
            if back_note:
                backward_links.append(
                    {"id": back_id, "title": back_note.title, "type": back_note.type.value}
                )
```

改为：

```python
        # 获取链接到的笔记（悬空 id 不再静默过滤，标记 dangling 可见化，#392 B2）
        forward_links = []
        for link_id in n.links:
            link_note = note.load_note_by_id(link_id)
            if link_note:
                forward_links.append(
                    {"id": link_id, "title": link_note.title, "type": link_note.type.value}
                )
            else:
                forward_links.append(
                    {
                        "id": link_id,
                        "title": "（已删除/悬空）",
                        "type": "dangling",
                        "dangling": True,
                    }
                )

        # 获取反向链接（同上，悬空可见化）
        backward_links = []
        for back_id in n.backlinks:
            back_note = note.load_note_by_id(back_id)
            if back_note:
                backward_links.append(
                    {"id": back_id, "title": back_note.title, "type": back_note.type.value}
                )
            else:
                backward_links.append(
                    {
                        "id": back_id,
                        "title": "（已删除/悬空）",
                        "type": "dangling",
                        "dangling": True,
                    }
                )
```

再把 table 渲染部分：

```python
            if forward_links:
                console.print("[cyan]→ Links to:[/cyan]")
                for link in forward_links:
                    console.print(f"  - [{link['type']}] {link['title']}")
                console.print()

            if backward_links:
                console.print("[green]← Linked by:[/green]")
                for link in backward_links:
                    console.print(f"  - [{link['type']}] {link['title']}")
                console.print()
```

改为：

```python
            if forward_links:
                console.print("[cyan]→ Links to:[/cyan]")
                for link in forward_links:
                    if link.get("dangling"):
                        console.print(f"  - [dim red]（已删除/悬空）[/dim red] {link['id']}")
                    else:
                        console.print(f"  - [{link['type']}] {link['title']}")
                console.print()

            if backward_links:
                console.print("[green]← Linked by:[/green]")
                for link in backward_links:
                    if link.get("dangling"):
                        console.print(f"  - [dim red]（已删除/悬空）[/dim red] {link['id']}")
                    else:
                        console.print(f"  - [{link['type']}] {link['title']}")
                console.print()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli_format.py`
Expected: 全文件 PASS（含既有 refs 测试 + 新增 1 个）

- [ ] **Step 5: Commit**

```bash
git add jfox/cli.py tests/test_cli_format.py
git commit -m "feat(refs): show dangling links/backlinks instead of silent filtering (#392 B2)"
```

---

## Final Verification

```bash
uv run pytest tests/unit/test_conftest_mock.py tests/unit/test_delete_backlink_cleanup.py tests/unit/test_note_promote.py tests/unit/test_gem_synth_backfill.py tests/test_cli_format.py
uv run black jfox/ tests/ && uv run ruff check jfox/ tests/
npx --yes markdownlint-cli2 docs/superpowers/specs/2026-08-22-issue-392-cr-leftovers-design.md docs/superpowers/plans/2026-08-22-issue-392-cr-leftovers.md
```
