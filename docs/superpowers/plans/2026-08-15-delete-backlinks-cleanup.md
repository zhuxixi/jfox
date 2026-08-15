# Delete-Side Backlink Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `jfox delete` 删除笔记时，把自身 id 从所有 target 笔记 frontmatter 的 `backlinks` 中移除，消除悬空 backlink（issue #386）。

**Architecture:** 在 `jfox/note.py delete_note()` 的删文件之前插入「backlinks 增量移除」循环——遍历 `note.links`，对每个 target 做移除 + `_atomic_write` + `update_note_meta`，与 `promote_note()` 的「增量回填」完全镜像对称。单 target 失败仅 warning 不中断，残留由既有 `jfox index rebuild --backlinks` 全量重算兜底。

**Tech Stack:** Python 3.10+ / Typer CLI / pytest（CliRunner + `temp_kb_registered` + `mock_embedding_backend`）/ ruff + black。

**Spec:** `docs/superpowers/specs/2026-08-15-delete-backlinks-cleanup-design.md`（v2，已 review）

## Global Constraints

- 行长度 100 字符（pyproject.toml）；格式化 black，检查 ruff。
- 注释用中文（项目规范）。
- 不改 `delete` 的 CLI `--json` 输出结构；不动 `archive_note`；不改 `_refs_impl` 的悬空过滤（独立 UX issue）。
- 测试断言 B 的 backlinks 一律用 `jfox show <id> --json` 的顶层 `.backlinks` 字段（frontmatter 真值）；**禁止用 `refs`**（它静默过滤 load 不到的悬空 id，会产生假绿灯——见 spec §三.1）。
- 测试标记 `pytestmark = [pytest.mark.unit, pytest.mark.fast]`，必须 mock embedding（不加载真模型）。
- 只 `git add` 明确列出的文件，禁止 `git add -A`。

---

### Task 1: delete_note() 增加 backlinks 增量移除（核心修复）

**Files:**
- Modify: `jfox/note.py:298-330`（`delete_note()`，try 块开头、`note.filepath.unlink()` 之前）
- Create: `tests/unit/test_delete_backlink_cleanup.py`

**Interfaces:**
- Consumes: `note.links: List[str]`（被删笔记的 frontmatter 出链）、`load_note_by_id(tid) -> Optional[Note]`（note.py:195）、`_atomic_write(filepath, content)`（note.py:112，同模块）、`get_note_index().update_note_meta(note)`（note_index.py:304）
- Produces: `delete_note(note_id) -> bool` 行为变更——删除前对每个 `note.links` 中的 target 移除 `note_id` 并落盘；无新公开 API。

- [ ] **Step 1: 写失败的核心回归测试**

创建 `tests/unit/test_delete_backlink_cleanup.py`：

```python
"""
测试类型: 单元测试
目标功能: jfox delete 清理目标笔记 backlinks（issue #386）
预估耗时: < 2秒
依赖要求: 临时知识库，mock embedding backend

复现 GitHub issue #386：A 引用 B，删除 A 后 B 的 frontmatter backlinks
不应残留 A 的 id。断言一律用 show --json 读 frontmatter 真值——
refs 会静默过滤悬空 backlink（load 不到的 id 不进输出），用它断言是假绿灯。
"""

import json
from unittest.mock import patch

import pytest
from typer.testing import CliRunner
from utils.temp_kb import temp_kb_registered

from jfox.cli import app

pytestmark = [pytest.mark.unit, pytest.mark.fast]

runner = CliRunner()


class TestDeleteCleansBacklinks:
    """测试 delete 命令的 backlinks 增量移除（与 promote 回填对称）"""

    def test_delete_removes_note_from_target_backlinks(self, mock_embedding_backend):
        """删除 A 后，B 的 backlinks 不残留 A 的 id（issue #386 核心）"""
        with temp_kb_registered() as kb_name:
            with patch(
                "jfox.embedding_backend.get_backend", return_value=mock_embedding_backend
            ):
                # 1. 创建 B（被引用方）
                b_result = runner.invoke(
                    app,
                    [
                        "add", "B body",
                        "--title", "笔记B", "--type", "permanent",
                        "--kb", kb_name, "--json",
                    ],
                )
                assert b_result.exit_code == 0, b_result.output
                b_id = json.loads(b_result.output)["note"]["id"]

                # 2. 创建 A 引用 B
                a_result = runner.invoke(
                    app,
                    [
                        "add", "A 引用 [[笔记B]]。",
                        "--title", "笔记A", "--type", "permanent",
                        "--kb", kb_name, "--json",
                    ],
                )
                assert a_result.exit_code == 0, a_result.output
                a_id = json.loads(a_result.output)["note"]["id"]

                # 前置确认：B.backlinks 已含 A（add 回填正常，否则测试自身无效）
                show_b = runner.invoke(app, ["show", b_id, "--kb", kb_name, "--json"])
                assert show_b.exit_code == 0, show_b.output
                assert a_id in json.loads(show_b.output)["backlinks"]

                # 3. 删除 A
                del_result = runner.invoke(app, ["delete", a_id, "--force", "--kb", kb_name])
                assert del_result.exit_code == 0, del_result.output

                # 4. 断言 frontmatter 真值：B.backlinks 不再含 A
                show_b2 = runner.invoke(app, ["show", b_id, "--kb", kb_name, "--json"])
                assert show_b2.exit_code == 0, show_b2.output
                backlinks_b = json.loads(show_b2.output)["backlinks"]
                assert a_id not in backlinks_b, "delete 后 B.backlinks 不应残留已删 A 的 id"
```

- [ ] **Step 2: 跑测试确认失败（复现 bug）**

Run: `uv run pytest tests/unit/test_delete_backlink_cleanup.py -v`
Expected: FAIL — `AssertionError: delete 后 B.backlinks 不应残留已删 A 的 id`（当前 delete 不清理 backlinks）

- [ ] **Step 3: 实现增量移除**

`jfox/note.py` `delete_note()` 内，`try:` 之后、`# 删除文件` 注释之前插入：

```python
        # backlinks 增量移除（#386）：把本笔记从各 target 的 backlinks 移除，与
        # promote_note 的增量回填对称。放在删文件之前：中途崩溃后重跑 delete 幂等
        # 收敛（backlinks 已清的 target 被 membership 守卫跳过，只剩删文件）。
        # 单 target 写盘失败仅 warning 不中断；残留悬空由
        # `jfox index rebuild --backlinks` 全量重算兜底。
        # target 损坏/解析失败（如手工编辑 backlinks: null）同样仅 warning 跳过，
        # 保证 delete 主流程不因无关 target 的坏状态而失败。
        from .note_index import get_note_index

        now = datetime.now()
        # 类型守卫（#386 CR）：note.links 可能为手编脏数据（links: null → None，或裸标量
        # → int/str）。非 list 时按空列表处理并 warning，防 `for tid in <int>` 抛
        # TypeError 落到外层 except → return False → 笔记无法删除。
        if not isinstance(note.links, list):
            logger.warning(
                f"Skip backlink cleanup for note {note_id}: links 类型异常 "
                f"({type(note.links).__name__})，按空列表处理"
            )
        for tid in note.links if isinstance(note.links, list) else []:
            try:
                t = load_note_by_id(tid)
                if not t:
                    continue
                if not isinstance(t.backlinks, list):
                    logger.warning(
                        f"Skip cleaning backlinks from target {tid}: backlinks 类型异常 "
                        f"({type(t.backlinks).__name__})"
                    )
                    continue
                if note_id in t.backlinks:
                    t.updated = now
                    t.backlinks = [bid for bid in t.backlinks if bid != note_id]
                    # 已知限制：t.filepath 按 type/标题 slug 重算，非 load 命中磁盘路径；
                    # 文件名发散时可能另写同 id 双文件，残留由 rebuild --backlinks/check 兜底。
                    # 已知限制：本循环无锁 read-modify-write，与常驻 daemon 并发写 target
                    # 时 last-writer-wins（与 promote 回填/update_note 同构，全库无文件锁）。
                    _atomic_write(t.filepath, t.to_markdown())
                    get_note_index().update_note_meta(t)
            except Exception as e:
                logger.warning(f"Failed to clean backlinks from target {tid}: {e}")
```

注意：`from .note_index import get_note_index` 必须函数内 import（与 promote_note 一致，避免顶层循环导入）；`datetime` / `_atomic_write` / `load_note_by_id` 已在模块作用域可用，无需新增顶层 import。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_delete_backlink_cleanup.py -v`
Expected: PASS（1 passed）

- [ ] **Step 5: Commit**

```bash
git add jfox/note.py tests/unit/test_delete_backlink_cleanup.py
git commit -m "fix(note): delete_note cleans note id from target backlinks (#386)"
```

---

### Task 2: 边界用例三连（写盘失败容错 / 无链接笔记 / 幂等守卫跳过）

**Files:**
- Modify: `tests/unit/test_delete_backlink_cleanup.py`（Task 1 创建的文件，追加 3 个测试方法到 `TestDeleteCleansBacklinks` 类）

**Interfaces:**
- Consumes: Task 1 的 `delete_note` 行为；`jfox.note._atomic_write` / `jfox.note.load_note_by_id`（patch/直调对象）；`use_kb(kb_name)`（jfox.config，测试内直调 note API 前必须进入）
- Produces: 无（纯测试补充）

- [ ] **Step 1: 追加三个测试方法**

在 `TestDeleteCleansBacklinks` 类内追加：

```python
    def test_delete_cleanup_write_failure_warns_but_deletes(self, mock_embedding_backend):
        """target 写盘失败时 delete 仍成功（A 文件已删），仅 warning——与 promote 回填容错语义一致"""
        import jfox.note as note_module

        with temp_kb_registered() as kb_name:
            with patch(
                "jfox.embedding_backend.get_backend", return_value=mock_embedding_backend
            ):
                b_result = runner.invoke(
                    app,
                    ["add", "B body", "--title", "笔记B", "--type", "permanent",
                     "--kb", kb_name, "--json"],
                )
                assert b_result.exit_code == 0, b_result.output
                b_id = json.loads(b_result.output)["note"]["id"]

                a_result = runner.invoke(
                    app,
                    ["add", "A 引用 [[笔记B]]。", "--title", "笔记A", "--type", "permanent",
                     "--kb", kb_name, "--json"],
                )
                assert a_result.exit_code == 0, a_result.output
                a_id = json.loads(a_result.output)["note"]["id"]

                # 只让写 B 的那次 _atomic_write 失败（用 b_id 定位），其余走原逻辑
                original_atomic_write = note_module._atomic_write

                def failing_atomic_write(filepath, content):
                    if b_id in str(filepath):
                        raise OSError("simulated disk failure")
                    return original_atomic_write(filepath, content)

                with patch.object(
                    note_module, "_atomic_write", side_effect=failing_atomic_write
                ):
                    del_result = runner.invoke(
                        app, ["delete", a_id, "--force", "--kb", kb_name]
                    )
                    assert del_result.exit_code == 0, del_result.output

                # A 已删：show A 找不到（exit 1 + not found）
                show_a = runner.invoke(app, ["show", a_id, "--kb", kb_name, "--json"])
                assert show_a.exit_code == 1

                # B.backlinks 仍含 A（清理失败 = bug 修复前状态，rebuild 兜底语义）
                show_b = runner.invoke(app, ["show", b_id, "--kb", kb_name, "--json"])
                assert show_b.exit_code == 0, show_b.output
                assert a_id in json.loads(show_b.output)["backlinks"]

    def test_delete_note_without_links_succeeds(self, mock_embedding_backend):
        """无 links 的笔记删除不受影响（清理循环空转不崩）"""
        with temp_kb_registered() as kb_name:
            with patch(
                "jfox.embedding_backend.get_backend", return_value=mock_embedding_backend
            ):
                c_result = runner.invoke(
                    app,
                    ["add", "孤岛笔记正文，无任何 wiki link。",
                     "--title", "孤岛笔记", "--type", "permanent",
                     "--kb", kb_name, "--json"],
                )
                assert c_result.exit_code == 0, c_result.output
                c_id = json.loads(c_result.output)["note"]["id"]

                del_result = runner.invoke(app, ["delete", c_id, "--force", "--kb", kb_name])
                assert del_result.exit_code == 0, del_result.output

                show_c = runner.invoke(app, ["show", c_id, "--kb", kb_name, "--json"])
                assert show_c.exit_code == 1  # 已删除，找不到

    def test_delete_skips_rewrite_when_backlink_absent(self, mock_embedding_backend):
        """不对称状态（A.links 含 B 但 B.backlinks 不含 A）→ membership 守卫跳过，B 文件不被重写"""
        from jfox.config import use_kb

        with temp_kb_registered() as kb_name:
            with patch(
                "jfox.embedding_backend.get_backend", return_value=mock_embedding_backend
            ):
                b_result = runner.invoke(
                    app,
                    ["add", "B body", "--title", "笔记B", "--type", "permanent",
                     "--kb", kb_name, "--json"],
                )
                assert b_result.exit_code == 0, b_result.output
                b_id = json.loads(b_result.output)["note"]["id"]

                a_result = runner.invoke(
                    app,
                    ["add", "A 引用 [[笔记B]]。", "--title", "笔记A", "--type", "permanent",
                     "--kb", kb_name, "--json"],
                )
                assert a_result.exit_code == 0, a_result.output
                a_id = json.loads(a_result.output)["note"]["id"]

                # 手工构造不对称：清空 B.backlinks 后落盘（模拟历史数据不一致）
                with use_kb(kb_name):
                    import jfox.note as note_module

                    b_note = note_module.load_note_by_id(b_id)
                    b_note.backlinks = []
                    note_module._atomic_write(b_note.filepath, b_note.to_markdown())
                    b_mtime = b_note.filepath.stat().st_mtime_ns

                del_result = runner.invoke(app, ["delete", a_id, "--force", "--kb", kb_name])
                assert del_result.exit_code == 0, del_result.output

                # 守卫判否 → B 未被重写（mtime 不变）
                with use_kb(kb_name):
                    b_path = note_module.load_note_by_id(b_id).filepath
                    assert b_path.stat().st_mtime_ns == b_mtime, "守卫跳过时不应重写 B 文件"
```

- [ ] **Step 2: 跑全部用例确认通过**

Run: `uv run pytest tests/unit/test_delete_backlink_cleanup.py -v`
Expected: PASS（4 passed）。若 `test_delete_cleanup_write_failure...` 失败并提示 delete exit code 非 0，说明实现把清理失败传播给了主流程——回到 Task 1 Step 3 检查 except 只 warning 的语义。

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_delete_backlink_cleanup.py
git commit -m "test(note): delete backlink cleanup edge cases — write failure, no-links, guard skip (#386)"
```

---

### Task 3: promote 注释命令名修正 + 回归验证

**Files:**
- Modify: `jfox/note.py:452`（`promote_note` 内注释）

**Interfaces:**
- Consumes: 无
- Produces: 注释文档正确性（`jfox index rebuild --backlinks` 是真实命令，cli.py:2466 `-b` flag）

- [ ] **Step 1: 修正注释命令名**

`jfox/note.py` promote_note 的回填注释中，将：

```python
    # 已落盘但某 target backlinks 缺失），用 `jfox rebuild-backlinks` 全量重算修复。
```

改为：

```python
    # 已落盘但某 target backlinks 缺失），用 `jfox index rebuild --backlinks` 全量重算修复。
```

- [ ] **Step 2: 相关测试回归**

Run: `uv run pytest tests/unit/test_delete_backlink_cleanup.py tests/unit/test_note_promote.py tests/unit/test_add_backfill_links.py tests/unit/test_note_dedup_sync.py -v`
Expected: PASS（全部）

- [ ] **Step 3: Lint + 格式检查**

Run: `uv run ruff check jfox/note.py tests/unit/test_delete_backlink_cleanup.py && uv run black --check jfox/note.py tests/unit/test_delete_backlink_cleanup.py`
Expected: 无报错。若 black 报格式差异，跑 `uv run black jfox/note.py tests/unit/test_delete_backlink_cleanup.py` 后复检。

- [ ] **Step 4: Commit**

```bash
git add jfox/note.py
git commit -m "docs(note): fix nonexistent rebuild-backlinks command name in promote comment (#386)"
```

---

## 验收对照（spec §四）

| 验收项 | 对应 |
|---|---|
| issue step6 → `B.backlinks == []` | Task 1（`show --json` 断言，同 issue 复现命令） |
| 新增测试全绿，重点既有测试不回归 | Task 2/3 Step 2 |
| rebuild --backlinks 兜底语义不变 | 未触碰 `_rebuild_backlinks_impl` |
| ruff / black | Task 3 Step 3 |
