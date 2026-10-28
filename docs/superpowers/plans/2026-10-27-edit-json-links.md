# `edit --json` links contract Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `jfox edit --json` 的响应补齐 `note.links` / `note.backlinks` 与顶层 `links_added` / `links_removed`，让脚本一次调用即可核验链接解析结果。

**Architecture:** 在 `jfox/cli.py` 新增两个模块级函数——纯函数 `diff_links()` 算边差异、`_edit_result_note()` 组装 `note` 快照；`_edit_impl` 改为调用它们并把 delta 写入顶层 `result`。其余命令的行为不变。

**Tech Stack:** Python 3.10+、Typer、pytest、uv

**Spec:** `docs/superpowers/specs/2026-10-27-edit-json-links-design.md`（issue #577）

## Global Constraints

- 只加键不改键：`success` / `note.id` / `note.title` / `note.type` / `note.filepath` / `title_changed` / `warnings` / `semantic_index_warning` 的形状与出现条件不变。
- `links_added` / `links_removed` **恒有**（无变化时为空数组），不得改成「非空才出现」。
- `note.links` / `note.backlinks` 必须是 `list` 类型（JSON 数组），不是 set。
- `--format table` / yaml / csv 分支的输出**不得**改变。
- 代码注释用英文；commit message 用 conventional commits。
- 工作目录固定为 worktree：`/home/elling/work/git-repo/jfox/.pi/worktrees/issue-577-edit-json-links`；禁止在 main 上直接改。
- 不使用 `git add -A`，按文件 stage。

## Review Focus

- **repeat 链接**：正文写两次 `[[同一目标]]` 时，`note.links` 只应出现一次，`links_added` 也不应重复——`resolve_wiki_links` 已去重，但 `diff_links` 必须自己对重复输入免疫（Task 1 测试钉住）。
- **自链**：正文写 `[[自己的 ID]]` 时必须被 `resolve_wiki_links` 过滤，且**不得**出现在 `links_added` 里（Task 2 测试钉住）。
- **顺序**：`links_removed` 必须按编辑前 `n.links` 的顺序，而实现里旧快照是 `set`——Task 2 Step 3 专门处理，否则顺序随机且没有测试能拦。
- **`content=None` 分支**（仅 `--title` / `--tag` 编辑）：四个链接键仍必须存在且 delta 为 `[]`。若实现把 delta 写入误挂进 `if content is not None`，会复现本 issue 的「键不存在→读成 `None`」病灶。
- **被链接笔记的 backlinks**：`edit` 的既有副作用（增删边时维护目标笔记 backlinks）不得因重构而丢——原有循环必须保留。

---

### Task 1: 纯函数 `diff_links` 与 `_edit_result_note`

**Files:**

- Modify: `jfox/cli.py`（在 `resolve_wiki_links` 之后、`_rebuild_backlinks_impl` 之前插入两个函数；并在 typing 导入里加 `Iterable`）
- Test: `tests/unit/test_edit_json_links.py`（新建）

**Interfaces:**

- Consumes: `jfox.note.Note` 的字段 `id` / `title` / `type` / `links` / `backlinks` / `filepath`
- Produces:
  - `diff_links(old_links: Iterable[str], new_links: Iterable[str]) -> Tuple[List[str], List[str]]`，返回 `(added, removed)`，`added` 按 `new_links` 顺序、`removed` 按 `old_links` 顺序，重复输入自动去重
  - `_edit_result_note(n: note.Note) -> Dict[str, Any]`，返回 `{"id","title","type","filepath","links","backlinks"}`，其中两个列表是拷贝

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/test_edit_json_links.py`：

```python
"""#577：edit --json 的链接字段——纯函数单元测试。

测试类型: 单元测试
目标模块: jfox.cli.diff_links / jfox.cli._edit_result_note
预估耗时: <1 秒
依赖要求: 无外部依赖（不建 KB、不写盘）
"""

from datetime import datetime
from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.models import Note, NoteType


def _note(**overrides) -> Note:
    """构造内存 Note，并用 set_filepath 钉住路径（避免读全局配置）。"""
    base = dict(
        id="20260101000000",
        title="T",
        content="c",
        type=NoteType.PERMANENT,
        created=datetime(2026, 1, 1),
        updated=datetime(2026, 1, 1),
    )
    base.update(overrides)
    n = Note(**base)
    if n._filepath is None:
        n.set_filepath(Path("/tmp/20260101000000-t.md"))
    return n


class TestDiffLinks:
    def test_added_preserves_new_order(self):
        from jfox.cli import diff_links

        added, removed = diff_links(["a"], ["b", "a", "c"])

        assert added == ["b", "c"]
        assert removed == []

    def test_removed_preserves_old_order(self):
        from jfox.cli import diff_links

        added, removed = diff_links(["c", "a", "b"], ["a"])

        assert added == []
        assert removed == ["c", "b"]

    def test_duplicates_collapse(self):
        from jfox.cli import diff_links

        added, removed = diff_links(["a", "a"], ["a", "b", "b", "c"])

        assert added == ["b", "c"]
        assert removed == []

    def test_empty_inputs(self):
        from jfox.cli import diff_links

        assert diff_links([], []) == ([], [])
        assert diff_links([], ["x"]) == (["x"], [])
        assert diff_links(["x"], []) == ([], ["x"])


class TestEditResultNote:
    def test_key_set(self):
        from jfox.cli import _edit_result_note

        payload = _edit_result_note(_note())

        assert set(payload) == {"id", "title", "type", "filepath", "links", "backlinks"}
        assert payload["type"] == "permanent"
        assert payload["links"] == []
        assert payload["backlinks"] == []

    def test_list_copies_are_independent(self):
        from jfox.cli import _edit_result_note

        n = _note(links=["a"], backlinks=["b"])
        payload = _edit_result_note(n)
        payload["links"].append("mutated")
        payload["backlinks"].append("mutated")

        assert n.links == ["a"]
        assert n.backlinks == ["b"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_edit_json_links.py -q`

Expected: FAIL —— `ImportError: cannot import name 'diff_links'`（`_edit_result_note` 同样缺失）。

- [ ] **Step 3: 写最小实现**

`jfox/cli.py` 顶部 typing 导入改为（只加 `Iterable`）：

```python
from typing import Any, Dict, Iterable, List, Optional, Tuple
```

在 `resolve_wiki_links` 函数体之后、`_rebuild_backlinks_impl` 之前插入：

```python
def diff_links(
    old_links: Iterable[str], new_links: Iterable[str]
) -> Tuple[List[str], List[str]]:
    """Return (added, removed) link deltas, order-preserving and dedup-safe (#577).

    `added` follows `new_links` order, `removed` follows `old_links` order.
    Duplicate inputs collapse to their first occurrence, so callers may pass
    raw lists without pre-normalising them.
    """
    old_order = list(old_links)
    new_order = list(new_links)
    old_set = set(old_order)
    new_set = set(new_order)
    added = [link for link in dict.fromkeys(new_order) if link not in old_set]
    removed = [link for link in dict.fromkeys(old_order) if link not in new_set]
    return added, removed


def _edit_result_note(n: note.Note) -> Dict[str, Any]:
    """Assemble the `note` payload of edit's --json response (#577).

    Mirrors add's `note` shape and adds backlinks so callers can verify links
    in a single call. Lists are copied: the caller must not be able to mutate
    the Note through the response payload.
    """
    return {
        "id": n.id,
        "title": n.title,
        "type": n.type.value,
        "filepath": str(n.filepath),
        "links": list(n.links),
        "backlinks": list(n.backlinks),
    }
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_edit_json_links.py -q`

Expected: PASS（6 passed）。

- [ ] **Step 5: Commit**

```bash
git add jfox/cli.py tests/unit/test_edit_json_links.py
git commit -m "feat(cli): add link-delta and note-payload helpers (#577)"
```

---

### Task 2: 接线 `_edit_impl`

**Files:**

- Modify: `jfox/cli.py:2028-2093`（`_edit_impl` 的快照、差值计算、响应组装三处）
- Test: `tests/unit/test_edit.py`（新增 `TestEditJSONLinks` 类）

**Interfaces:**

- Consumes: Task 1 的 `diff_links(old, new)` 与 `_edit_result_note(n)`
- Produces: `edit --json` 顶层新增 `links_added: List[str]`、`links_removed: List[str]`；`note` 新增 `links` / `backlinks`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_edit.py` 末尾追加（该文件已有 `json` 导入与 `create_note` / `save_note` / `load_note_by_id` 的导入）：

```python
class TestEditJSONLinks:
    """#577：edit --json 输出 links/backlinks 与本次边差异。"""

    def _make_config(self, tmp_path):
        cfg = ZKConfig(base_dir=tmp_path)
        cfg.ensure_dirs()
        return cfg

    @patch("jfox.vector_store.get_vector_store")
    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_edit_json_links_added(
        self, mock_global_config, mock_note_config, mock_vs, tmp_path, capsys
    ):
        from jfox.cli import _edit_impl

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir
        mock_vs.return_value.last_embed_warning = None

        target = create_note("target", title="LinkTarget", note_type=NoteType.PERMANENT)
        save_note(target, add_to_index=False)
        source = create_note("no links yet", title="LinkSource", note_type=NoteType.PERMANENT)
        save_note(source, add_to_index=False)

        _edit_impl(
            note_id=source.id,
            content=f"see [[{target.id}|LinkTarget]] twice [[{target.id}|LinkTarget]]",
            content_file=None,
            title=None,
            tags=None,
            note_type=None,
            source=None,
            output_format="json",
        )

        data = json.loads(capsys.readouterr().out)
        assert data["note"]["links"] == [target.id]
        assert data["note"]["backlinks"] == []
        # duplicate [[...]] collapses: no repeated id in the delta
        assert data["links_added"] == [target.id]
        assert data["links_removed"] == []
        # existing side effect must survive: the target gains the backlink
        target_loaded = load_note_by_id(target.id, cfg=cfg)
        assert source.id in target_loaded.backlinks

    @patch("jfox.vector_store.get_vector_store")
    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_edit_json_links_self_link_ignored(
        self, mock_global_config, mock_note_config, mock_vs, tmp_path, capsys
    ):
        from jfox.cli import _edit_impl

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir
        mock_vs.return_value.last_embed_warning = None

        source = create_note("no links yet", title="SelfLink", note_type=NoteType.PERMANENT)
        save_note(source, add_to_index=False)

        _edit_impl(
            note_id=source.id,
            content=f"self reference [[{source.id}|SelfLink]]",
            content_file=None,
            title=None,
            tags=None,
            note_type=None,
            source=None,
            output_format="json",
        )

        data = json.loads(capsys.readouterr().out)
        assert data["note"]["links"] == []
        assert data["links_added"] == []
        assert data["links_removed"] == []

    @patch("jfox.vector_store.get_vector_store")
    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_edit_json_links_removed(
        self, mock_global_config, mock_note_config, mock_vs, tmp_path, capsys
    ):
        from jfox.cli import _edit_impl

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir
        mock_vs.return_value.last_embed_warning = None

        target = create_note("target", title="DropTarget", note_type=NoteType.PERMANENT)
        save_note(target, add_to_index=False)
        source = create_note(
            f"links [[{target.id}|DropTarget]]",
            title="DropSource",
            note_type=NoteType.PERMANENT,
            links=[target.id],
        )
        save_note(source, add_to_index=False)
        target.backlinks.append(source.id)
        save_note(target, add_to_index=False)

        _edit_impl(
            note_id=source.id,
            content="no more links",
            content_file=None,
            title=None,
            tags=None,
            note_type=None,
            source=None,
            output_format="json",
        )

        data = json.loads(capsys.readouterr().out)
        assert data["note"]["links"] == []
        assert data["links_added"] == []
        assert data["links_removed"] == [target.id]
        # the existing side effect must survive: target loses the backlink
        target_loaded = load_note_by_id(target.id, cfg=cfg)
        assert source.id not in target_loaded.backlinks

    @patch("jfox.vector_store.get_vector_store")
    @patch("jfox.note.config")
    @patch("jfox.config.config")
    def test_edit_json_title_only_unchanged(
        self, mock_global_config, mock_note_config, mock_vs, tmp_path, capsys
    ):
        from jfox.cli import _edit_impl

        cfg = self._make_config(tmp_path)
        mock_global_config.notes_dir = cfg.notes_dir
        mock_note_config.notes_dir = cfg.notes_dir
        mock_vs.return_value.last_embed_warning = None

        keep = create_note("keep", title="KeepTarget", note_type=NoteType.PERMANENT)
        save_note(keep, add_to_index=False)
        source = create_note(
            f"links [[{keep.id}|KeepTarget]]",
            title="TitleOnly",
            note_type=NoteType.PERMANENT,
            links=[keep.id],
        )
        save_note(source, add_to_index=False)

        _edit_impl(
            note_id=source.id,
            content=None,
            content_file=None,
            title="TitleOnlyRenamed",
            tags=None,
            note_type=None,
            source=None,
            output_format="json",
        )

        data = json.loads(capsys.readouterr().out)
        # keys must exist even when content was not touched
        assert data["note"]["links"] == [keep.id]
        assert data["note"]["backlinks"] == []
        assert data["links_added"] == []
        assert data["links_removed"] == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_edit.py::TestEditJSONLinks -q`

Expected: FAIL —— `KeyError: 'links'`（`note` 里还没有该键）。若 Step 1 之前 Task 1 未完成，还会 `AttributeError`；先做 Task 1。

- [ ] **Step 3: 写最小实现**

`jfox/cli.py` 中 `_edit_impl` 三处改动：

(a) L2029 `old_links = set(n.links)` 改为有序快照（顺序承诺靠这一步兑现）：

```python
    old_title = n.title
    old_links_order = list(n.links)
    old_links = set(old_links_order)
```

(b) 响应组装前的差值计算换成纯函数（保留 backlinks 维护循环原样）：

```python
        # 更新反向链接
        new_links = set(n.links)
```

这行保留；随后把 `result` 的组装替换为：

```python
        links_added, links_removed = diff_links(old_links_order, n.links)
        result = {
            "success": True,
            "note": _edit_result_note(n),
            "links_added": links_added,
            "links_removed": links_removed,
        }
```

(c) 确认 `added_links` / `removed_links` 两个中间变量仍由集合差值算出并驱动原有循环——**不要**改成用 `links_added` / `links_removed` 驱动循环（两者语义相同，但保持既有代码路径改动最小、顺序无关的循环逻辑不动）。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_edit.py -q`

Expected: PASS（既有用例 + 新增 3 个全绿）。

- [ ] **Step 5: Commit**

```bash
git add jfox/cli.py tests/unit/test_edit.py
git commit -m "feat(cli): expose links, backlinks and link deltas in edit --json (#577)"
```

---

### Task 3: 真实 CLI 契约测试

**Files:**

- Modify: `tests/test_json_schema_contract.py`（`TestContractList.EXPECTED_SUCCESS_COMMANDS` 加一条；`TestAlreadyCompliantSmoke` 加一个用例）

**Interfaces:**

- Consumes: 已完成接线的 `jfox edit --json`
- Produces: 契约层对 `note.links` / `note.backlinks` / `links_added` / `links_removed` 的锁定

- [ ] **Step 1: 写失败测试**

在 `EXPECTED_SUCCESS_COMMANDS` 的 `# --- Task 3: index/kb ---` 之前插入：

```python
        ("edit", ["edit", "{note_id}", "--content", "契约编辑正文"], True),
```

在 `class TestAlreadyCompliantSmoke` 内追加：

```python
    def test_edit_link_fields_shape(self, cli):
        created = _run_json(cli, "add", "契约编辑前置正文", "--title", "Contract-Edit-Links")
        note_id = assert_json_shape(created.stdout, True)["note"]["id"]

        edited = _run_json(cli, "edit", note_id, "--content", "契约编辑正文")
        data = assert_json_shape(edited.stdout, True)

        for key in ("links", "backlinks"):
            assert isinstance(data["note"][key], list), f"note.{key} must be a list"
        for key in ("links_added", "links_removed"):
            assert isinstance(data[key], list), f"{key} must be a list"

        shown = assert_json_shape(_run_json(cli, "show", note_id).stdout, True)
        assert data["note"]["links"] == shown["links"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest "tests/test_json_schema_contract.py::TestContractList::test_success_has_top_level_success[edit]" "tests/test_json_schema_contract.py::TestAlreadyCompliantSmoke::test_edit_link_fields_shape" -q`

Expected: 若 Task 2 未完成则 FAIL（`KeyError: 'links_added'`）；Task 2 完成后应 PASS。这一步同时验证「测试确实跑到仓库源码」：先临时改回旧行为再跑一次可看到 FAIL，但**不要**为此改代码，直接以 Step 1 在 Task 2 前写测试的顺序保证先红后绿。

- [ ] **Step 3: 实现（无代码改动）**

本任务不改产品代码；若 Step 2 失败，说明 Task 2 未生效，回 Task 2 修。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest "tests/test_json_schema_contract.py::TestContractList::test_success_has_top_level_success[edit]" "tests/test_json_schema_contract.py::TestAlreadyCompliantSmoke::test_edit_link_fields_shape" -q`

Expected: PASS（2 passed）。

- [ ] **Step 5: Commit**

```bash
git add tests/test_json_schema_contract.py
git commit -m "test(contract): lock edit --json link fields (#577)"
```

---

### Task 4: 文档、CHANGELOG 与全量回归

**Files:**

- Modify: `docs/json-schemas.md:51`（`edit` 行）
- Modify: `CHANGELOG.md`（`## [Unreleased]` → `### Fixes` 追加一条）
- Modify: `tests/unit/test_json_schema_contract_doc.py`（新增 edit 字段防漂移断言）

**Interfaces:**

- Consumes: 最终实现的字段名
- Produces: 文档与实现一致；A7/A8 验收

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_json_schema_contract_doc.py` 末尾追加：

```python
def test_edit_link_fields_documented():
    text = DOC.read_text(encoding="utf-8")
    assert "`note{id,title,type,filepath,links,backlinks}`" in text
    assert "`links_added[], links_removed[]`（恒有，可为空数组）" in text
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_json_schema_contract_doc.py -q`

Expected: FAIL —— 两个断言找不到子串。

- [ ] **Step 3: 更新文档与 CHANGELOG**

`docs/json-schemas.md` 的 `edit` 行整行替换为：

```markdown
| `edit` | `success, note{id,title,type,filepath,links,backlinks}` + `links_added[], links_removed[]`（恒有，可为空数组） + 可选 `title_changed{old,new}, warnings, semantic_index_warning`（#519 无语义组件时） | 嵌套 `note` | `{success, error}` |
```

`CHANGELOG.md` 在 `## [Unreleased]` 的 `### Fixes` 段首行前追加：

```markdown
- **cli**: `edit --json` 补齐 `note.links` / `note.backlinks` 与顶层 `links_added` / `links_removed`（恒有，无变化时为空数组），脚本可在一次调用里核验链接解析结果，不必再跑 `show`；既有字段不变 (#577)
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_json_schema_contract_doc.py -q`

Expected: PASS。

- [ ] **Step 5: 跑全量快速集 + markdownlint**

Run: `uv run pytest tests/ -m "not embedding and not slow" -q`
Run: `npx --yes markdownlint-cli2`

Expected: 全部通过（0 failed）；markdownlint `0 issues`。

- [ ] **Step 6: Commit**

```bash
git add docs/json-schemas.md CHANGELOG.md tests/unit/test_json_schema_contract_doc.py
git commit -m "docs(cli): document edit --json link fields (#577)"
```

---

## 验收对照（spec §7）

| spec ID | 落地任务 | 验证命令 |
|---|---|---|
| A1 | Task 1 | `uv run pytest tests/unit/test_edit_json_links.py::TestDiffLinks` |
| A2 | Task 1 | `uv run pytest tests/unit/test_edit_json_links.py::TestEditResultNote` |
| A3 | Task 2 | `uv run pytest tests/unit/test_edit.py::TestEditJSONLinks::test_edit_json_links_added` |
| A4 | Task 2 | `uv run pytest tests/unit/test_edit.py::TestEditJSONLinks::test_edit_json_links_removed` |
| A5 | Task 2 | `uv run pytest tests/unit/test_edit.py::TestEditJSONLinks::test_edit_json_title_only_unchanged` |
| A6 | Task 3 | `uv run pytest "tests/test_json_schema_contract.py::TestContractList::test_success_has_top_level_success[edit]" "tests/test_json_schema_contract.py::TestAlreadyCompliantSmoke::test_edit_link_fields_shape"` |
| A7 | Task 4 | `uv run pytest tests/unit/test_json_schema_contract_doc.py` + `npx --yes markdownlint-cli2` |
| A8 | Task 4 | `uv run pytest tests/ -m "not embedding and not slow"` |
