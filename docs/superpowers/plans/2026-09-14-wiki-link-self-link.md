# Issue #511 Wiki-Link 自链与字面量误链修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 收敛 edit/add/rebuild 三条 wiki-link 解析路径到统一纯函数 `resolve_wiki_links`，修复自链落盘与正文字面量误链（issue #511）。

**Architecture:** 在 `jfox/cli.py` 新增纯函数 `resolve_wiki_links(content, self_id)`——内部第一步 `_strip_wiki_link_exclusions` 剥离（含新增 inline code 剥离），再经 `find_note_id_by_title_or_id` 解析，过滤自链并去重；edit/add/rebuild 三处内联解析循环全部替换为该函数。rebuild 保留 `target_id in note_by_id` 存在性过滤（文件系统对账兜底）。剥离只影响解析输入，落盘正文逐字节不变。

**Tech Stack:** Python >= 3.10、Typer CLI、pytest（unit 用 MagicMock 替身 NoteIndex，integration 用临时隔离知识库 + ZKCLI）。

**Worktree:** `/home/elling/git-repo/github/jfox/.pi/worktrees/issue-511-wiki-link-self-link`（下文记作 `$WT`）。所有文件路径以 `$WT` 开头，git 操作用 `git -C $WT`。禁止触碰主 checkout。

**Spec:** `docs/superpowers/specs/2026-09-14-wiki-link-self-link-design.md`（本 worktree 首个 commit）。验收 ID A1-A9 / U1 与 spec §4 一一对应。

## Global Constraints

- Python >= 3.10；行宽 100；`uv run black` 格式化；注释用中文
- 测试命令一律 `uv run pytest ...`（pytest.ini 已含 `-v`、`timeout=120`、`--strict-markers`）
- integration 测试打 `pytestmark = [pytest.mark.integration]`；涉及模型加载的不得混入本 plan
- `git add <file>` 按文件 stage，禁止 `git add -A`
- commit message 用 conventional commits（英文）
- **非目标**：substring fallback 改精确匹配、同名标题歧义、edit 的 links 覆盖 vs 合并语义（分属独立 issue 与 #470）

## 文件结构

| 文件 | 职责 | 动作 |
|------|------|------|
| `$WT/jfox/note_index.py` | `_strip_wiki_link_exclusions` 增剥 inline code | Modify（42-53 行函数体） |
| `$WT/jfox/cli.py` | 新增 `resolve_wiki_links`；三处调用点接入 | Modify（327 行后新增；520/1845/371 三段替换） |
| `$WT/tests/unit/test_wiki_link_resolution.py` | A1-A4 纯函数单测（mock NoteIndex） | Create |
| `$WT/tests/integration/test_links_edit_add.py` | A5-A8 CLI 全链路测试 | Create |

**接口契约（后续 task 依赖的精确签名）：**

```python
# jfox/cli.py，紧随 find_note_id_by_title_or_id 之后
def resolve_wiki_links(
    content: str, self_id: Optional[str] = None
) -> Tuple[List[str], List[str]]:
    """统一解析正文 wiki links：先剥离代码块/注释，再解析，过滤自链并去重。

    规则（edit/add/rebuild 三路径共用，杜绝规则漂移）：
    1. _strip_wiki_link_exclusions 剥离 fenced code block / HTML 注释 / inline code
    2. find_note_id_by_title_or_id 三级匹配（精确 ID → 精确标题 → 标题包含）
    3. target_id == self_id 跳过（自链过滤）
    4. resolved 去重（保序）
    5. 找不到目标的进 unresolved

    Args:
        content: 笔记正文（原文，不会被修改）
        self_id: 当前笔记 ID，用于自链过滤；add 场景传 None（新笔记尚未入索引，
                 find_note_id_by_title_or_id 不可能命中自身）

    Returns:
        (resolved_links, unresolved_titles)
    """
```

---

### Task 1: `_strip_wiki_link_exclusions` 增剥 inline code（验收 ID: A4）

**Files:**

- Modify: `$WT/jfox/note_index.py:42-53`
- Test: `$WT/tests/unit/test_wiki_link_resolution.py`（本 task 创建，含 TestStripWikiLinkExclusions；Task 2 继续往里加 TestResolveWikiLinks）

**Interfaces:**

- Consumes: 无（纯函数增强）
- Produces: `_strip_wiki_link_exclusions(text: str) -> str` 行为变更——反引号 span 内容被移除；Task 2-5 经 `resolve_wiki_links` 间接受益

- [ ] **Step 1: 写失败测试（创建测试文件）**

创建 `$WT/tests/unit/test_wiki_link_resolution.py`：

```python
"""
测试类型: 单元测试
目标功能: resolve_wiki_links 纯函数 + _strip_wiki_link_exclusions 增强（issue #511）
预估耗时: 1-2秒

不依赖真实知识库与 embedding；NoteIndex 用 MagicMock 替身
（沿用 tests/unit/test_rebuild_backlinks_impl.py 模式）。
"""

from unittest.mock import MagicMock, patch

from jfox.note_index import _strip_wiki_link_exclusions


def _make_meta(note_id: str, title: str):
    """构造 NoteIndex 需要的 meta 对象"""
    meta = MagicMock()
    meta.id = note_id
    meta.title = title
    return meta


def _make_index(notes):
    """notes: List[Tuple[id, title]]，构造 mock NoteIndex"""

    def _find_by_id(nid):
        for nid_, title in notes:
            if nid_ == nid:
                return _make_meta(nid_, title)
        return None

    def _find_by_title(title):
        tl = title.lower()
        for nid_, t in notes:
            if t.lower() == tl:
                return _make_meta(nid_, t)
        return None

    idx = MagicMock()
    idx.find_by_id.side_effect = _find_by_id
    idx.find_by_title.side_effect = _find_by_title
    idx.get_all_meta.return_value = [_make_meta(i, t) for i, t in notes]
    return idx


class TestStripWikiLinkExclusions:
    """_strip_wiki_link_exclusions 剥离行为"""

    def test_strip_inline_code(self):
        """A4：反引号 span 内的 [[...]] 被剥离"""
        out = _strip_wiki_link_exclusions("示例 `[[ID|标题]]` 文字")
        assert "[[" not in out

    def test_strip_fenced_block_kept(self):
        """回归：fenced code block 剥离行为保持"""
        out = _strip_wiki_link_exclusions("```\n[[X]]\n```\n[[Y]]")
        assert "[[X]]" not in out
        assert "[[Y]]" in out

    def test_plain_text_untouched(self):
        """非剥离区域的 [[...]] 不受影响"""
        out = _strip_wiki_link_exclusions("普通 [[链接]] 内容")
        assert "[[链接]]" in out
```

- [ ] **Step 2: 运行测试确认 test_strip_inline_code 失败**

```bash
cd $WT && uv run pytest tests/unit/test_wiki_link_resolution.py -v
```

预期：`test_strip_inline_code` FAIL（inline code 未被剥离，"[[" 仍在输出中）；另两个 PASS。

- [ ] **Step 3: 增强 `_strip_wiki_link_exclusions`（jfox/note_index.py:42-53）**

替换函数体为（注意顺序：fenced → HTML 注释 → inline code；inline 必须最后，避免单反引号正则 `[^`]+` 跨行吃掉 fenced 边界）：

```python
def _strip_wiki_link_exclusions(text: str) -> str:
    """移除不应参与 wiki-link 匹配的 Markdown 区域（fenced code block、HTML 注释、inline code）。

    这是轻量级处理，覆盖最常见的误匹配场景；不保证解析所有 Markdown 边界情况。
    """
    # fenced code block（支持可选语言标识）
    text = re.sub(r"```[\s\S]*?```", "", text)
    # HTML 注释
    text = re.sub(r"<!--[\s\S]*?-->", "", text)
    # inline code（反引号 span；须最后处理，避免吃掉 fenced 边界）
    text = re.sub(r"`[^`]+`", "", text)
    return text
```

只改 docstring 与新增一行；函数签名与既有两条正则不动。

- [ ] **Step 4: 运行测试确认全过**

```bash
cd $WT && uv run pytest tests/unit/test_wiki_link_resolution.py -v
```

预期：3 passed。

- [ ] **Step 5: Commit**

```bash
git -C $WT add jfox/note_index.py tests/unit/test_wiki_link_resolution.py
git -C $WT commit -m "feat(note_index): strip inline code from wiki-link exclusions (#511)"
```

---

### Task 2: 新增 `resolve_wiki_links` 纯函数（验收 ID: A1, A2, A3）

**Files:**

- Modify: `$WT/jfox/cli.py`（在 `find_note_id_by_title_or_id` 结束后、`_rebuild_backlinks_impl` 定义前插入，即 327-331 行之间）
- Test: `$WT/tests/unit/test_wiki_link_resolution.py`（追加 TestResolveWikiLinks）

**Interfaces:**

- Consumes: `_strip_wiki_link_exclusions`（Task 1 产物）、`extract_wiki_links`（cli.py:277）、`find_note_id_by_title_or_id`（cli.py:284）
- Produces: `resolve_wiki_links(content: str, self_id: Optional[str] = None) -> Tuple[List[str], List[str]]`——Task 3/4/5 的调用点依赖此签名

- [ ] **Step 1: 写失败测试（追加到 tests/unit/test_wiki_link_resolution.py 末尾）**

```python
class TestResolveWikiLinks:
    """resolve_wiki_links 统一解析规则（issue #511）"""

    def test_self_link_filtered(self):
        """A1：标题包含匹配命中自身时，resolved 不含 self_id"""
        from jfox.cli import resolve_wiki_links

        notes = [("20260914000000", "某机制与 ID canonical 说明")]
        with patch("jfox.note_index.get_note_index", return_value=_make_index(notes)):
            resolved, _unresolved = resolve_wiki_links(
                "说明文字 [[ID|标题]] 示例", self_id="20260914000000"
            )
        assert "20260914000000" not in resolved
        assert resolved == []

    def test_dedup(self):
        """A2：正文两次引用同一目标只解析一次"""
        from jfox.cli import resolve_wiki_links

        notes = [("20260101000001", "目标笔记")]
        with patch("jfox.note_index.get_note_index", return_value=_make_index(notes)):
            resolved, _ = resolve_wiki_links(
                "见 [[目标笔记]] 与 [[目标笔记]]", self_id="20260999999999"
            )
        assert resolved == ["20260101000001"]

    def test_unresolved_collected(self):
        """A3：找不到目标的链接进 unresolved，不影响 resolved"""
        from jfox.cli import resolve_wiki_links

        notes = [("20260101000001", "存在的笔记")]
        with patch("jfox.note_index.get_note_index", return_value=_make_index(notes)):
            resolved, unresolved = resolve_wiki_links(
                "见 [[存在的笔记]] 和 [[不存在的标题xyz]]", self_id="20260999999999"
            )
        assert resolved == ["20260101000001"]
        assert unresolved == ["不存在的标题xyz"]

    def test_inline_code_literal_not_resolved(self):
        """A4 端到端：反引号内字面量不参与解析（经 Task 1 剥离）"""
        from jfox.cli import resolve_wiki_links

        notes = [("20260101000001", "无关的 --commit-id 笔记")]
        with patch("jfox.note_index.get_note_index", return_value=_make_index(notes)):
            resolved, unresolved = resolve_wiki_links(
                "示例 `[[ID]]` 文字", self_id="20260999999999"
            )
        assert resolved == []
        assert unresolved == []
```

- [ ] **Step 2: 运行测试确认全部 ImportError 失败**

```bash
cd $WT && uv run pytest tests/unit/test_wiki_link_resolution.py::TestResolveWikiLinks -v
```

预期：4 个测试 FAIL（`ImportError: cannot import name 'resolve_wiki_links'`）。

- [ ] **Step 3: 在 cli.py 新增 `resolve_wiki_links`**

在 `find_note_id_by_title_or_id` 函数 `return None` 之后、`_rebuild_backlinks_impl` 的 `def` 之前插入：

```python
def resolve_wiki_links(
    content: str, self_id: Optional[str] = None
) -> Tuple[List[str], List[str]]:
    """统一解析正文 wiki links：先剥离代码块/注释，再解析，过滤自链并去重。

    规则（edit/add/rebuild 三路径共用，杜绝规则漂移）：
    1. _strip_wiki_link_exclusions 剥离 fenced code block / HTML 注释 / inline code
    2. find_note_id_by_title_or_id 三级匹配（精确 ID → 精确标题 → 标题包含）
    3. target_id == self_id 跳过（自链过滤）
    4. resolved 去重（保序）
    5. 找不到目标的进 unresolved

    Args:
        content: 笔记正文（原文，不会被修改）
        self_id: 当前笔记 ID，用于自链过滤；add 场景传 None（新笔记尚未入索引，
                 find_note_id_by_title_or_id 不可能命中自身）

    Returns:
        (resolved_links, unresolved_titles)
    """
    from .note_index import _strip_wiki_link_exclusions

    stripped = _strip_wiki_link_exclusions(content)
    wiki_links = extract_wiki_links(stripped)
    resolved_links: List[str] = []
    unresolved: List[str] = []
    for link_text in wiki_links:
        target_id = find_note_id_by_title_or_id(link_text)
        if target_id:
            if target_id == self_id:
                continue
            if target_id not in resolved_links:
                resolved_links.append(target_id)
        else:
            unresolved.append(link_text)
    return resolved_links, unresolved
```

- [ ] **Step 4: 运行测试确认全过**

```bash
cd $WT && uv run pytest tests/unit/test_wiki_link_resolution.py -v
```

预期：7 passed（3 个 Task 1 + 4 个本 task）。

- [ ] **Step 5: 顺带跑 rebuild 既有单测确认未受影响（此时调用点未改，应全绿）**

```bash
cd $WT && uv run pytest tests/unit/test_rebuild_backlinks_impl.py -v
```

预期：全 passed（本 task 未改任何调用点）。

- [ ] **Step 6: Commit**

```bash
git -C $WT add jfox/cli.py tests/unit/test_wiki_link_resolution.py
git -C $WT commit -m "feat(cli): add resolve_wiki_links unified parsing function (#511)"
```

---

### Task 3: `_edit_impl` 接入 `resolve_wiki_links`（验收 ID: A5, A7-edit）

**Files:**

- Modify: `$WT/jfox/cli.py:1845-1858`（`_edit_impl` 的 wiki links 解析段）
- Test: `$WT/tests/integration/test_links_edit_add.py`（本 task 创建）

**Interfaces:**

- Consumes: `resolve_wiki_links`（Task 2 产物）
- Produces: edit 后 `n.links` 无自链、无重复；backlinks 回填循环行为不变

- [ ] **Step 1: 写失败测试（创建 tests/integration/test_links_edit_add.py）**

```python
"""
测试类型: 集成测试
目标功能: issue #511 — add/edit 不自链、正文字面量不误链
预估耗时: 5-15秒
依赖要求: 临时隔离知识库（cli_fast fixture，mock embedding）
"""

from pathlib import Path

import pytest

from jfox.models import Note

pytestmark = [pytest.mark.integration]


def _load_note(filepath: str) -> Note:
    p = Path(filepath)
    return Note.from_markdown(p.read_text(encoding="utf-8"), p)


class TestEditSelfLink:
    """edit 路径（A5/A7）"""

    def test_edit_no_self_link(self, cli_fast):
        """A5：edit 追加含 [[ID|标题]] 字面量正文后，links/backlinks 均不含自身 ID"""
        # 1. 建标题含 "ID" 的 permanent（issue 复现场景）
        r = cli_fast.add("初始内容", title="某机制与 ID canonical 说明", note_type="permanent")
        assert r.success
        note_id = r.data["note"]["id"]
        filepath = r.data["note"]["filepath"]

        # 2. edit 追加含字面量的正文
        new_content = "初始内容\n\n说明文字 [[ID|标题]] 示例\n"
        e = cli_fast.edit(note_id, content=new_content)
        assert e.success

        # 3. links/backlinks 不含自身 ID（自链过滤生效）
        n = _load_note(filepath)
        assert note_id not in n.links
        assert note_id not in n.backlinks
        # 正文完整性：剥离只影响解析输入，落盘内容与输入一致
        assert "[[ID|标题]]" in n.content

    def test_edit_dedup(self):
        pass  # 占位由 test_edit_dedup_impl 承载——见下

    def test_edit_dedup_impl(self, cli_fast):
        """A2 链路级：edit 正文两次引用同一目标，links 去重"""
        t = cli_fast.add("T", title="去重目标", note_type="permanent")
        target_id = t.data["note"]["id"]
        r = cli_fast.add("源", title="去重源", note_type="permanent")
        src_path = r.data["note"]["filepath"]

        e = cli_fast.edit(r.data["note"]["id"], content="见 [[去重目标]] 再 [[去重目标]]")
        assert e.success
        assert _load_note(src_path).links == [target_id]
```

- [ ] **Step 2: 运行测试确认 test_edit_no_self_link 失败**

```bash
cd $WT && uv run pytest tests/integration/test_links_edit_add.py::TestEditSelfLink -v
```

预期：`test_edit_no_self_link` FAIL（links 含自身 ID——bug 复现）；`test_edit_dedup_impl` FAIL（links 重复）。

- [ ] **Step 3: 替换 `_edit_impl` 解析段（cli.py:1845-1858）**

旧代码：

```python
    # 如果内容被更新，解析 wiki links
    if content is not None:
        wiki_links = extract_wiki_links(content)
        resolved_links = []
        unresolved = []

        for link_text in wiki_links:
            target_id = find_note_id_by_title_or_id(link_text)
            if target_id:
                resolved_links.append(target_id)
            else:
                unresolved.append(link_text)

        n.links = resolved_links
    else:
        unresolved = []
```

替换为：

```python
    # 如果内容被更新，解析 wiki links（统一规则：剥离→自链过滤→去重，见 #511）
    if content is not None:
        resolved_links, unresolved = resolve_wiki_links(content, self_id=n.id)
        n.links = resolved_links
    else:
        unresolved = []
```

- [ ] **Step 4: 运行测试确认全过**

```bash
cd $WT && uv run pytest tests/integration/test_links_edit_add.py -v
```

预期：3 passed（含占位 test_edit_dedup 空过）。

- [ ] **Step 5: Commit**

```bash
git -C $WT add jfox/cli.py tests/integration/test_links_edit_add.py
git -C $WT commit -m "fix(edit): filter self-links and dedupe via resolve_wiki_links (#511)"
```

---

### Task 4: `_add_note_impl` 接入 `resolve_wiki_links`（验收 ID: A6, A7-add）

**Files:**

- Modify: `$WT/jfox/cli.py:520-529`（`_add_note_impl` 的 wiki links 解析段）
- Test: `$WT/tests/integration/test_links_edit_add.py`（追加 TestAddSelfLink、TestLiteralStripped）

**Interfaces:**

- Consumes: `resolve_wiki_links`（Task 2 产物）
- Produces: add 后 links 无重复；fenced/inline 内字面量不进 links；backfill 循环（cli.py:546 起）输入已去重

- [ ] **Step 1: 写失败测试（追加到 tests/integration/test_links_edit_add.py 末尾）**

```python
class TestAddSelfLink:
    """add 路径（A6/A7）"""

    def test_add_no_false_self_link(self, cli_fast):
        """A6：add 正文含与自身标题相关的字面量，links 不含自身 ID"""
        r = cli_fast.add(
            "说明文字 [[ID|标题]] 示例",
            title="某机制与 ID canonical 说明",
            note_type="permanent",
        )
        assert r.success
        note_id = r.data["note"]["id"]
        n = _load_note(r.data["note"]["filepath"])
        assert note_id not in n.links
        assert note_id not in n.backlinks

    def test_add_dedup(self, cli_fast):
        """A2 链路级：add 正文两次引用同一目标，links 去重"""
        t = cli_fast.add("T", title="add去重目标", note_type="permanent")
        target_id = t.data["note"]["id"]
        r = cli_fast.add(
            "见 [[add去重目标]] 再 [[add去重目标]]", title="add去重源", note_type="permanent"
        )
        assert r.success
        assert _load_note(r.data["note"]["filepath"]).links == [target_id]


class TestLiteralStripped:
    """字面量剥离（A7）"""

    def test_literal_in_fence_and_inline_not_linked(self, cli_fast):
        """fenced 块与反引号内的 [[...]] 不进 links；正文原样落盘"""
        t = cli_fast.add("T", title="剥离目标笔记", note_type="permanent")
        target_id = t.data["note"]["id"]

        content = (
            "正常引用 [[剥离目标笔记]]\n\n"
            "```\n示例 [[剥离目标笔记]] 在 fenced 内\n```\n\n"
            "行内 `[[剥离目标笔记]]` 示例\n"
        )
        r = cli_fast.add(content, title="剥离测试源", note_type="permanent")
        assert r.success
        n = _load_note(r.data["note"]["filepath"])
        # 正常引用解析一次；fenced 与 inline 内的字面量不进 links
        assert n.links == [target_id]
        # 剥离区域正文原样落盘（解析剥离 ≠ 落盘剥离）
        assert "`[[剥离目标笔记]]`" in n.content
        assert "示例 [[剥离目标笔记]] 在 fenced 内" in n.content
```

- [ ] **Step 2: 运行测试确认失败项**

```bash
cd $WT && uv run pytest tests/integration/test_links_edit_add.py -v
```

预期：`test_add_dedup` FAIL（add 未去重）；`test_literal_in_fence_and_inline_not_linked` FAIL（inline 字面量被解析 → links 含重复 target_id）。`test_add_no_false_self_link` 现状可能 PASS（add 时新笔记未入索引，本就命不中自身）——它作为防回归守护保留，不算 TDD 红灯，属正常。

- [ ] **Step 3: 替换 `_add_note_impl` 解析段（cli.py:520-529）**

旧代码：

```python
    # 从内容中提取维基链接
    wiki_links = extract_wiki_links(content)
    resolved_links = []
    unresolved = []

    for link_text in wiki_links:
        target_id = find_note_id_by_title_or_id(link_text)
        if target_id:
            resolved_links.append(target_id)
        else:
            unresolved.append(link_text)
```

替换为：

```python
    # 从内容中提取维基链接（统一规则：剥离→去重，见 #511；
    # 新笔记尚未入索引不会命中自身，self_id 传 None）
    resolved_links, unresolved = resolve_wiki_links(content, self_id=None)
```

- [ ] **Step 4: 运行测试确认全过**

```bash
cd $WT && uv run pytest tests/integration/test_links_edit_add.py -v
```

预期：全部 passed。

- [ ] **Step 5: Commit**

```bash
git -C $WT add jfox/cli.py tests/integration/test_links_edit_add.py
git -C $WT commit -m "fix(add): dedupe links and strip literal wiki-links (#511)"
```

---

### Task 5: `_rebuild_backlinks_impl` 接入 + 保留存在性过滤（验收 ID: A8）

**Files:**

- Modify: `$WT/jfox/cli.py:371-381`（`_rebuild_backlinks_impl` 第一阶段解析循环）
- Test: `$WT/tests/integration/test_links_edit_add.py`（追加 TestRebuildConsistency）

**Interfaces:**

- Consumes: `resolve_wiki_links`（Task 2 产物）
- Produces: rebuild 与 edit/add 解析规则一致；`target_id in note_by_id` 存在性对账保留；unresolved 语义保持（find 失败报标题文本，存在性失败报 ID）

- [ ] **Step 1: 写失败测试（追加到 tests/integration/test_links_edit_add.py 末尾）**

```python
class TestRebuildConsistency:
    """rebuild 与 edit/add 规则一致（A8）"""

    def test_rebuild_dedup_and_strip_consistent(self, cli_fast):
        """同一正文：rebuild 产出与 add 一致（去重 + 剥离）"""
        t = cli_fast.add("T", title="一致性目标", note_type="permanent")
        target_id = t.data["note"]["id"]

        content = "引用 [[一致性目标]] 两次 [[一致性目标]]，行内 `[[一致性目标]]` 不解析"
        r = cli_fast.add(content, title="一致性源", note_type="permanent")
        src_path = r.data["note"]["filepath"]
        assert _load_note(src_path).links == [target_id]

        # 手动污染 links 字段后 rebuild 应从正文解析恢复出相同结果
        n = _load_note(src_path)
        n.links = []
        Path(src_path).write_text(n.to_markdown(), encoding="utf-8")

        rb = cli_fast.index_rebuild(backlinks=True)
        assert rb.success
        assert _load_note(src_path).links == [target_id]
```

- [ ] **Step 2: 运行新测试确认失败**

```bash
cd $WT && uv run pytest tests/integration/test_links_edit_add.py::TestRebuildConsistency -v
```

预期：FAIL——污染后 rebuild 走旧循环（无剥离、有自链过滤和去重），`行内 \`[[一致性目标]]\`` 的字面量会被解析，links 恢复为 `[target_id]` 其实能过？——注意：旧 rebuild 循环有去重，正文里三处引用（两处正常 + 一处行内）都解析到 target_id 且去重后仍是 `[target_id]`，此测试在旧代码下**可能恰好通过**。此时接受：本测试是**行为守护**而非 TDD 红灯，真正验证 rebuild 改用纯函数的是 Step 4 的既有单测回归（它们 patch 点固定，若实现破坏契约会红）。继续往下走，不强行造红灯。

- [ ] **Step 3: 替换 `_rebuild_backlinks_impl` 第一阶段循环（cli.py:371-381）**

旧代码：

```python
    for n in notes:
        wiki_links = extract_wiki_links(n.content)
        for link_text in wiki_links:
            target_id = find_note_id_by_title_or_id(link_text)
            if target_id and target_id in note_by_id:
                # 过滤自链接，避免笔记指向自身
                if target_id == n.id:
                    continue
                # 避免同一笔记内重复链接同一目标
                if target_id not in parsed_links[n.id]:
                    parsed_links[n.id].append(target_id)
            else:
                unresolved.append(link_text)
```

替换为：

```python
    for n in notes:
        # 统一解析规则（剥离→自链过滤→去重，见 #511）
        parsed, unres = resolve_wiki_links(n.content, self_id=n.id)
        for target_id in parsed:
            # 存在性对账兜底：索引命中但文件系统无此笔记时视为悬空
            if target_id in note_by_id:
                parsed_links[n.id].append(target_id)
            else:
                unresolved.append(target_id)
        unresolved.extend(unres)
```

- [ ] **Step 4: 跑 rebuild 既有单测 + 集成测试回归**

```bash
cd $WT && uv run pytest tests/unit/test_rebuild_backlinks_impl.py tests/integration/test_index_rebuild_backlinks.py -v
```

预期：全 passed。这些测试 patch `jfox.note_index.get_note_index` / `jfox.note.list_notes` / `jfox.note.save_note`——`resolve_wiki_links` 内部经 `find_note_id_by_title_or_id` 走同一 `get_note_index`，patch 点兼容。

- [ ] **Step 5: 跑本文件全部测试**

```bash
cd $WT && uv run pytest tests/integration/test_links_edit_add.py -v
```

预期：全 passed。

- [ ] **Step 6: Commit**

```bash
git -C $WT add jfox/cli.py tests/integration/test_links_edit_add.py
git -C $WT commit -m "refactor(rebuild): share resolve_wiki_links parsing rules (#511)"
```

---

### Task 6: Fast 档全量回归（验收 ID: A9）

**Files:** 无改动（纯验证 task）

**Interfaces:**

- Consumes: Task 1-5 全部产物
- Produces: 回归证据

- [ ] **Step 1: Fast 档全量（与 CI fast job 同范围）**

```bash
cd $WT && uv run pytest tests/ -m "not slow and not embedding"
```

预期：全绿。如有失败：先确认是否本 plan 改动引入——是则修复后重跑；与本次改动无关的存量失败如实记录（不捎带修复）。

- [ ] **Step 2: 格式与 lint**

```bash
cd $WT && uv run black jfox/cli.py jfox/note_index.py tests/unit/test_wiki_link_resolution.py tests/integration/test_links_edit_add.py
cd $WT && uv run ruff check jfox/cli.py jfox/note_index.py tests/unit/test_wiki_link_resolution.py tests/integration/test_links_edit_add.py
```

预期：无 diff、无 lint 错误。若 black 产生改动，commit：

```bash
git -C $WT add jfox/cli.py jfox/note_index.py tests/unit/test_wiki_link_resolution.py tests/integration/test_links_edit_add.py
git -C $WT commit -m "style: black format (#511)"
```

---

### Task 7: U1 存量自链扫描（用户实测 · post-implementation manual verification）

**Files:** 无仓库改动（一次性脚本，不进库）

**Interfaces:**

- Consumes: 修复后的 CLI（可选——edit 自清依赖本修复）
- Produces: 存量自链清单 + 逐条处置记录

- [ ] **Step 1: 扫描 default 库存量自链**

```bash
cd /home/elling/git-repo/github/jfox && uv run python -c "
from jfox import note
bad = []
for n in note.list_notes(limit=10000):
    if n.id in n.links or n.id in n.backlinks:
        bad.append((n.id, n.title, n.id in n.links, n.id in n.backlinks))
for row in bad:
    print(row)
print(f'total: {len(bad)}')
"
```

预期：输出 `n.id in n.links`（自链）或 `n.id in n.backlinks`（自 backlink）的笔记清单。issue 实测的两条已手工修复，预期接近 0；若非 0 则记录清单。

- [ ] **Step 2: 逐条处置（edit 自清）**

对清单每条执行一次无实质改动的 edit（如尾随加一个空格再删，或直接 `jfox edit <id> --content "$(jfox show <id> 正文)"`）——修复后的 edit 会让 `new_links` 不含自身、`old_links` 含自身 → backlinks 回填循环反向删除自 backlink。处置后重跑 Step 1 确认清零。

- [ ] **Step 3: 结果记录**

把扫描与处置结果作为评论追加到 issue #511（实测证据留痕）。

---

## 验收双向追溯

| 验收 ID | 承载 Task | 说明 |
|---------|-----------|------|
| A1 自链过滤 | Task 2 Step 1（unit）+ Task 3 Step 1（integration） | unit 测纯函数，integration 测落盘 |
| A2 去重 | Task 2 Step 1（unit）+ Task 3/4（integration） | 同上 |
| A3 unresolved 语义 | Task 2 Step 1（unit） | — |
| A4 剥 inline code | Task 1（unit）+ Task 2 test_inline_code_literal_not_resolved（端到端） | — |
| A5 edit 不自链 | Task 3 | — |
| A6 add 不自链 | Task 4 | 防回归守护（现状即绿） |
| A7 剥离生效 + 正文完整性 | Task 3（edit 侧断言）+ Task 4（add 侧断言） | 落盘逐字节一致 |
| A8 rebuild 一致 | Task 5（新测试 + 既有 rebuild 单测/集成回归） | — |
| A9 Fast 档回归 | Task 6 | — |
| U1 存量扫描 | Task 7（用户实测） | 可选 |

## Self-Review 记录

- **Spec 覆盖**：D1→Task 2/3/4/5；D2→Task 5（含 note_by_id 保留）；D3→Task 2（剥离在函数内部）；D4→Task 1；D5/D6 非目标无 task（正确）；§3 可测性拆分→Task 1/2 纯函数 + Task 3/4/5 装配层。无缺口。
- **Placeholder 扫描**：Task 3 有一个 `test_edit_dedup` 空占位——为保持类内测试命名直白而留，实际断言在 `test_edit_dedup_impl`；如发现误导，实现时可删占位。
- **类型一致性**：`resolve_wiki_links` 签名在 Task 2/3/4/5 与接口契约一致（`self_id: Optional[str]`，返回 `Tuple[List[str], List[str]]`）。
- **已知接受项**：Task 5 Step 2 说明新一致性测试在旧代码下可能恰绿——该测试定位是行为守护，TDD 红灯由 Task 5 Step 4 的既有 rebuild 单测契约承担；rebuild 的 unresolved 在「索引有而磁盘无」场景报 ID 而非标题（无现有测试守护此边缘，差异可接受，spec 已注明）。
