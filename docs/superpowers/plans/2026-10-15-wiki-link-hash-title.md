# wiki-link `#` 截断修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修掉「标题含 `#` 的 wiki-link 被当作锚点分隔符截断」这一 bug，让正文解析出的链接指向正确笔记，且不误改存量手写链接。

**Architecture:** 把 `#` 歧义的裁决从**提取阶段的无条件截断**（`_normalize_wiki_link_title` 里的 `target.split("#", 1)[0]`）推迟到**解析阶段的候选顺序试**。提取层新增 `split_wiki_target` / `extract_wiki_link_targets` 两个纯函数返回候选列表；解析侧按「完整原文精确 → `#` 前缀精确 → 完整原文子串」的顺序命中，**子串兜底不再对前缀生效**。四个正文解析消费者（`resolve_wiki_links` / `find_notes_referencing_title` / `promote_note` / `KnowledgeGraph`）全部迁移到候选契约，`redirect` 改消费同一契约但保持精确匹配语义。

**Tech Stack:** Python ≥3.10 · pytest · Typer · NetworkX · `uv` 管理依赖

**设计文档:** `docs/superpowers/specs/2026-10-15-wiki-link-hash-title-design.md`（issue #458）

## Global Constraints

- 工作目录：`/home/elling/git-repo/github/jfox/.pi/worktrees/issue-458-wiki-link-hash-title`（worktree）。**所有编辑路径以该绝对路径开头；git 操作用 `git -C <WT>`。不要碰主 checkout 的 main。**
- 行长度 100 字符；格式化 black；检查 ruff（`uv run black jfox/ tests/` / `uv run ruff check jfox/ tests/`）。
- 注释用中文，commit message 用英文 conventional commits。
- **`git add <file>` 按文件 stage，禁止 `git add -A`。**
- 子串兜底**只对 `candidates[0]`（完整原文）**生效，不得对 `#` 前缀生效（spec A2 用例⑧）。
- 候选比较的**精确标题匹配保持大小写不敏感**（`test_note_index.py:340` 钉住的契约，spec R2-D1）。
- `redirect` 的「只做精确匹配、不做子串模糊匹配」语义**不得改变**（`test_redirect.py:357` `test_no_substring_match` 钉住，spec A4）。
- `find_note_id_by_title_or_id` 的**既有导出与三层匹配语义保持不变**（其他调用方依赖，spec 非目标）。
- 不使用真实知识库、embedding、ChromaDB 编写测试；`NoteIndex` 用 `MagicMock` 替身（沿用 `tests/unit/test_wiki_link_resolution.py` 的 `_make_index` 模式）。
- 每个 task 结束后跑该 task 指定的测试命令；最后一个 task 跑全量回归。

## 验收 ID ↔ Task 双向追溯

| 验收 ID | 覆盖 Task |
|---|---|
| A1（`split_wiki_target` 纯函数） | Task 1 |
| A2（`resolve_link_target` 候选顺序 + 子串只对完整原文） | Task 2 |
| A3（#458 本体：含 `#` 完整标题解析到正确笔记） | Task 2 |
| A4（redirect 精确匹配不回归 + 含 `#` 锚点用例） | Task 7 |
| A5（端到端 add→show links 正确） | Task 3 |
| A6（既有解析行为不回归 + promote 含 `#` 锚点正向用例） | Task 5、Task 8 |
| A7（图谱建边迁移） | Task 6 |
| A8（`find_notes_referencing_title` 迁移 + casefold） | Task 4 |
| U1（存量手术，用户实测） | 本计划不含实现；spec 已给公式与脚本口径 |

反向检查：每个 task 都至少归属一个验收 ID（见各 task 的 **Acceptance** 行），无孤立实现 task。

---

### Task 1: 提取层候选契约（纯函数）

**Files:**
- Modify: `jfox/note_index.py`（新增 `split_wiki_target` / `extract_wiki_link_targets`，接在 `extract_wiki_links_from_text` 之后）
- Test: `tests/unit/test_wiki_link_target.py`（新建）

**Interfaces:**
- Consumes: 既有 `_WIKI_LINK_RE`（`jfox/note_index.py:19`）
- Produces:
  - `split_wiki_target(link_text: str) -> List[str]` —— 含 `#` 返回 `[完整原文, 前缀]`，否则 `[原文]`；空 `#` 前缀不产生空候选
  - `extract_wiki_link_targets(text: str) -> List[List[str]]` —— 每个 wiki-link 一组候选，顺序即优先级

**Acceptance:** A1

- [ ] **Step 1: 写失败的测试**

新建 `tests/unit/test_wiki_link_target.py`：

```python
"""
测试类型: 单元测试
目标功能: wiki-link 候选契约 split_wiki_target / extract_wiki_link_targets（issue #458）
预估耗时: <1 秒

不依赖真实知识库与 embedding；纯函数断言。
"""

from jfox.note_index import extract_wiki_link_targets, split_wiki_target


class TestSplitWikiTarget:
    """候选拆分（spec 回归用例清单①–④）"""

    def test_hash_title_returns_full_then_prefix(self):
        """① 含 # 时返回 [完整原文, 前缀]"""
        assert split_wiki_target("A#B") == ["A#B", "A"]

    def test_no_hash_single_candidate(self):
        """② 无 # 时单候选"""
        assert split_wiki_target("A") == ["A"]

    def test_alias_stripped_before_anchor(self):
        """③ 先剥 alias 再切锚点"""
        assert split_wiki_target("A#B|C") == ["A#B", "A"]

    def test_empty_prefix_no_empty_candidate(self):
        """④ 空前缀不得产生空候选"""
        assert split_wiki_target("#B") == ["#B"]


class TestExtractWikiLinkTargets:
    """每个链接一组候选，顺序即优先级"""

    def test_multiple_links(self):
        text = "见 [[A#B]] 与 [[C]]"
        assert extract_wiki_link_targets(text) == [["A#B", "A"], ["C"]]

    def test_real_title_with_hash_keeps_full_text(self):
        """#458 形态：完整标题含 #，完整原文必须是第一候选"""
        title = "jfox 增量索引修复方案（#387）：verify 差集 + 单条修复替代日常全量 rebuild"
        assert extract_wiki_link_targets(f"见 [[{title}]]")[0][0] == title
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_wiki_link_target.py -v`
Expected: FAIL —— `ImportError: cannot import name 'split_wiki_target'`

- [ ] **Step 3: 写最小实现**

在 `jfox/note_index.py` 的 `extract_wiki_links_from_text` 之后追加（`List` 已在文件内导入）：

```python
def split_wiki_target(link_text: str) -> List[str]:
    """把一个 wiki-link 的目标拆成按优先级排列的候选。

    含 `#` 时返回 [完整原文, 前缀]；无 `#` 时返回 [原文]。
    alias（`|` 左侧）在此剥离。空前缀不产生空候选。

    候选顺序即解析优先级：完整原文优先（覆盖「标题本身含 #」），
    `#` 前缀次之（保留既有锚点语义）。见 issue #458 设计文档
    「核心契约变更」——注意本函数**不做截断**，截断语义由调用方按候选顺序实现。
    """
    raw = link_text.split("|", 1)[0].strip()
    if "#" in raw:
        prefix = raw.split("#", 1)[0].strip()
        if prefix and prefix != raw:
            return [raw, prefix]
    return [raw]


def extract_wiki_link_targets(text: str) -> List[List[str]]:
    """提取每个 wiki-link 的候选目标列表（顺序即优先级）。

    不做剔除（fenced code block / HTML 注释 / inline code），调用方自行预处理——
    与既有 extract_wiki_links_from_text 的职责边界保持一致。
    """
    return [split_wiki_target(m.group(1).strip()) for m in _WIKI_LINK_RE.finditer(text)]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_wiki_link_target.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: 提交**

```bash
WT=/home/elling/git-repo/github/jfox/.pi/worktrees/issue-458-wiki-link-hash-title
git -C "$WT" add jfox/note_index.py tests/unit/test_wiki_link_target.py
git -C "$WT" commit -m "feat(note_index): add wiki-link candidate contract split_wiki_target (#458)"
```

---

### Task 2: 解析契约 `resolve_link_target`

**Files:**
- Modify: `jfox/cli.py`（在 `find_note_id_by_title_or_id` 之后新增 `resolve_link_target`；`List`/`Optional` 已在文件内导入）
- Test: `tests/unit/test_wiki_link_target.py`（追加 `TestResolveLinkTarget`）

**Interfaces:**
- Consumes: `split_wiki_target`（Task 1）；`NoteIndex.find_by_id` / `find_by_title` / `get_all_meta`
- Produces: `resolve_link_target(candidates: List[str]) -> Optional[str]`

**Acceptance:** A2、A3

- [ ] **Step 1: 写失败的测试**

在 `tests/unit/test_wiki_link_target.py` 追加（顶部 `from unittest.mock import MagicMock, patch`）：

```python
def _make_meta(note_id: str, title: str):
    meta = MagicMock()
    meta.id = note_id
    meta.title = title
    return meta


def _make_index(notes):
    """notes: List[Tuple[id, title]]，构造 mock NoteIndex（沿用 test_wiki_link_resolution 模式）"""

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


class TestResolveLinkTarget:
    """候选顺序解析（spec 回归用例清单⑤–⑩）"""

    def test_full_text_exact_hit(self):
        """⑤ 完整原文精确命中"""
        from jfox.cli import resolve_link_target

        notes = [("20260101000001", "A#B"), ("20260101000002", "A")]
        with patch("jfox.note_index.get_note_index", return_value=_make_index(notes)):
            assert resolve_link_target(["A#B", "A"]) == "20260101000001"

    def test_prefix_exact_hit_when_full_misses(self):
        """⑥ 完整原文不中、前缀精确命中（锚点语义保留）"""
        from jfox.cli import resolve_link_target

        notes = [("20260101000002", "A")]
        with patch("jfox.note_index.get_note_index", return_value=_make_index(notes)):
            assert resolve_link_target(["A#B", "A"]) == "20260101000002"

    def test_full_text_substring_hit(self):
        """⑦ 两者都不中、完整原文子串命中（缩写标题链接不回归）"""
        from jfox.cli import resolve_link_target

        notes = [("20260101000003", "Issue #81 执行计划 — 防崩溃 + 断点续跑（任务拆分与优先级）")]
        with patch("jfox.note_index.get_note_index", return_value=_make_index(notes)):
            assert resolve_link_target(["Issue #81 执行计划", "Issue"]) == "20260101000003"

    def test_prefix_substring_must_not_match(self):
        """⑧ 前缀能子串命中、完整原文不能 → 必须返回 None（本 spec 的核心行为变更）"""
        from jfox.cli import resolve_link_target

        # 完整原文 "Issue #81 执行计划" 不是任何标题的子串；前缀 "Issue" 是
        notes = [("20260101000004", "某条标题里含 Issue 字样")]
        with patch("jfox.note_index.get_note_index", return_value=_make_index(notes)):
            assert resolve_link_target(["Issue #81 执行计划", "Issue"]) is None

    def test_all_miss_returns_none(self):
        """⑨ 全不中 → None（悬空路径）"""
        from jfox.cli import resolve_link_target

        with patch("jfox.note_index.get_note_index", return_value=_make_index([])):
            assert resolve_link_target(["不存在的东西"]) is None

    def test_real_world_hash_truncation_case(self):
        """⑩ #458 评论区实测复现形态：真目标 vs 干扰笔记"""
        from jfox.cli import resolve_link_target

        title = "zima-blue-cli #213：执行历史缺 token/cost 账本（usage 采集）"
        noise = "改 zima-blue-cli 仓库根 CLAUDE.md 前怎么确认不破坏测试"
        notes = [("202609030803256065", title), ("202609141007301934", noise)]
        with patch("jfox.note_index.get_note_index", return_value=_make_index(notes)):
            assert resolve_link_target([title, "zima-blue-cli #213"]) == "202609030803256065"

    def test_candidates_case_insensitive_exact_title(self):
        """⑪ 候选比较须 casefold（test_note_index.py:340 契约）"""
        from jfox.cli import resolve_link_target

        notes = [("20260101000005", "SomeTITLE")]
        with patch("jfox.note_index.get_note_index", return_value=_make_index(notes)):
            assert resolve_link_target(["sometitle#x", "sometitle"]) == "20260101000005"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_wiki_link_target.py::TestResolveLinkTarget -v`
Expected: FAIL —— `ImportError: cannot import name 'resolve_link_target'`

- [ ] **Step 3: 写最小实现**

在 `jfox/cli.py` 的 `find_note_id_by_title_or_id` 之后新增：

```python
def resolve_link_target(candidates: List[str]) -> Optional[str]:
    """按候选顺序解析 wiki-link 目标。

    对每个候选依次试「精确 ID → 精确标题（大小写不敏感）」；命中即返回。
    全部候选都不中时，**只对 candidates[0]（完整原文）做子串兜底**——
    不对 `#` 前缀做子串匹配：前缀过短会把「本该悬空」的链接静默指向无关笔记
    并随索引顺序漂移（issue #458 的第二种后果）。

    Args:
        candidates: split_wiki_target 产出的候选列表（顺序即优先级）

    Returns:
        命中的 note id，或 None（悬空）
    """
    from .note_index import get_note_index

    if not candidates:
        return None

    idx = get_note_index()
    for candidate in candidates:
        if not candidate:
            continue
        meta = idx.find_by_id(candidate) or idx.find_by_title(candidate)
        if meta:
            return meta.id

    # 子串兜底：只对完整原文。非 # 链接的原文即前缀，行为与既有实现一致；
    # # 类链接改用完整原文子串，比旧的前缀子串更specific、不再时序脆弱。
    fallback = candidates[0].lower()
    if not fallback:
        return None
    for meta in idx.get_all_meta():
        if fallback in meta.title.lower():
            return meta.id
    return None
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_wiki_link_target.py -v`
Expected: PASS（13 passed）

- [ ] **Step 5: 提交**

```bash
WT=/home/elling/git-repo/github/jfox/.pi/worktrees/issue-458-wiki-link-hash-title
git -C "$WT" add jfox/cli.py tests/unit/test_wiki_link_target.py
git -C "$WT" commit -m "feat(cli): add resolve_link_target candidate-order resolution (#458)"
```

---

### Task 3: 迁移 `resolve_wiki_links`（frontmatter links 写入路径）

**Files:**
- Modify: `jfox/cli.py:378-395`（`resolve_wiki_links` 函数体）
- Test: `tests/integration/test_wiki_link_hash_title.py`（新建，A5）

**Interfaces:**
- Consumes: `extract_wiki_link_targets`（Task 1）、`resolve_link_target`（Task 2）、`_strip_wiki_link_exclusions`
- Produces: `resolve_wiki_links(content, self_id=None) -> Tuple[List[str], List[str]]`（签名不变）

**Acceptance:** A5

- [ ] **Step 1: 写失败的集成测试**

新建 `tests/integration/test_wiki_link_hash_title.py`：

```python
"""
测试类型: 集成测试
目标功能: 标题含 # 的 wiki-link 端到端解析正确（issue #458 · A5/A7）
预估耗时: 数秒

复用 conftest 的 temp_kb / cli fixture（见 tests/conftest.py）。
"""


class TestWikiLinkHashTitleEndToEnd:
    def test_add_note_with_hash_title_link_resolves_to_real_target(self, temp_kb, cli):
        """A5：add 正文含 [[完整标题（含#）]] 后，show --json 的 links 指向真实目标"""
        target = cli.add("目标笔记正文", title="jfox 增量索引修复方案（#387）：verify 差集", note_type="permanent")
        target_id = target.id

        source = cli.add(
            "参见 [[jfox 增量索引修复方案（#387）：verify 差集]]",
            title="引用方笔记",
            note_type="permanent",
        )
        shown = cli.show(source.id, json=True)
        assert target_id in shown["links"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/integration/test_wiki_link_hash_title.py -v`
Expected: FAIL —— `links` 不含 `target_id`（现状下 `#` 处截断，解析到别的笔记或悬空）

- [ ] **Step 3: 改写 `resolve_wiki_links` 为候选契约**

把 `jfox/cli.py` 的 `resolve_wiki_links` 函数体中的提取与解析两段替换为候选路径（docstring 与签名保持不变）：

```python
    from .note_index import _strip_wiki_link_exclusions, extract_wiki_link_targets

    stripped = _strip_wiki_link_exclusions(content)
    resolved_links: List[str] = []
    unresolved: List[str] = []
    for candidates in extract_wiki_link_targets(stripped):
        target_id = resolve_link_target(candidates)
        if target_id:
            if target_id == self_id:
                continue
            if target_id not in resolved_links:
                resolved_links.append(target_id)
        else:
            # 报告完整原文（candidates[0]），保持用户可读
            unresolved.append(candidates[0])
    return resolved_links, unresolved
```

同时删掉该函数体里对 `extract_wiki_links` 与 `find_note_id_by_title_or_id` 的调用（它们在本函数内不再需要；`find_note_id_by_title_or_id` 本身保留，其他调用方仍用）。

> 注意 `resolve_wiki_links` 定义在 `jfox/cli.py:362` 附近，`resolve_link_target` 在 Task 2 已加在同一模块、无需 import。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/integration/test_wiki_link_hash_title.py -v`
Expected: PASS

- [ ] **Step 5: 跑同族回归**

Run: `uv run pytest tests/unit/test_wiki_link_resolution.py -v`
Expected: PASS（既有 `TestResolveWikiLinks` 全部通过）

- [ ] **Step 6: 提交**

```bash
WT=/home/elling/git-repo/github/jfox/.pi/worktrees/issue-458-wiki-link-hash-title
git -C "$WT" add jfox/cli.py tests/integration/test_wiki_link_hash_title.py
git -C "$WT" commit -m "fix(cli): resolve_wiki_links uses candidate-order resolution (#458)"
```

---

### Task 4: 迁移 `find_notes_referencing_title`（backlink 回填反查）

**Files:**
- Modify: `jfox/note_index.py:269`（`find_notes_referencing_title` 的提取循环）
- Test: `tests/unit/test_note_index.py`（追加含 `#` 用例）

**Interfaces:**
- Consumes: `extract_wiki_link_targets`（Task 1）
- Produces: `find_notes_referencing_title(title) -> List[NoteMeta]`（签名与语义不变：精确标题匹配、大小写不敏感）

**Acceptance:** A8

- [ ] **Step 1: 写失败的测试**

在 `tests/unit/test_note_index.py` 的 `test_find_notes_referencing_title_*` 系列附近追加：

```python
    def test_find_notes_referencing_title_hash_in_title(self, kb_with_wiki_links):
        """A8：正文用 [[完整标题（含#）]] 引用时能被反查识别（issue #458）"""
        cfg = kb_with_wiki_links
        note_dir = cfg.notes_dir / NoteType.PERMANENT.value
        note_dir.mkdir(parents=True, exist_ok=True)

        (note_dir / "20260428006.md").write_text(
            "---\n"
            "id: '20260428006'\n"
            "title: 'jfox 增量索引修复方案（#387）：verify 差集'\n"
            "type: permanent\n"
            "created: '2026-04-28T00:06:00'\n"
            "updated: '2026-04-28T00:06:00'\n"
            "tags: []\n"
            "links: []\n"
            "backlinks: []\n"
            "---\n\n目标笔记正文\n",
            encoding="utf-8",
        )
        (note_dir / "20260428007.md").write_text(
            "---\n"
            "id: '20260428007'\n"
            "title: '引用方'\n"
            "type: permanent\n"
            "created: '2026-04-28T00:07:00'\n"
            "updated: '2026-04-28T00:07:00'\n"
            "tags: []\n"
            "links: []\n"
            "backlinks: []\n"
            "---\n\n"
            "参见 [[jfox 增量索引修复方案（#387）：verify 差集]] 与 [[目标笔记#章节]]。\n",
            encoding="utf-8",
        )

        idx = NoteIndex(cfg)
        idx.rebuild()

        ids = {
            m.id
            for m in idx.find_notes_referencing_title("jfox 增量索引修复方案（#387）：verify 差集")
        }
        assert "20260428007" in ids
```

> 放在 `TestFindNotesReferencingTitle` 类内、`test_find_notes_referencing_title_alias_and_anchor`（`tests/unit/test_note_index.py:394-418`）之后；该文件已导入 `NoteIndex` 与 `NoteType`，`kb_with_wiki_links` 是同文件既有 fixture。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_note_index.py -k "referencing and hash" -v`
Expected: FAIL —— 含 `#` 的完整标题引用未被识别（现状在 `#` 处截断）

- [ ] **Step 3: 改写提取循环为候选成员判断**

把 `jfox/note_index.py` 的 `find_notes_referencing_title` 内层循环：

```python
            for link_text in extract_wiki_links_from_text(body):
                if link_text.lower() == title_lower:
                    results.append(meta)
                    break
```

替换为：

```python
            for candidates in extract_wiki_link_targets(body):
                # 成员判断：任一候选 casefold 后等于目标标题即算引用。
                # 「任一」而非「首个命中」是对的——这里问的是「正文是否引用了该标题」，
                # 完整原文与 # 前缀都可能是引用形态（[[标题]] 与 [[标题#锚点]] 都算）。
                if any(c.casefold() == title_lower for c in candidates if c):
                    results.append(meta)
                    break
```

并把 `title_lower = title.lower()` 改为 `title_lower = title.casefold()`（保持大小写不敏感契约，`test_note_index.py:340` 钉住）。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_note_index.py -k referencing -v`
Expected: PASS（既有 7 个 `test_find_notes_referencing_title*` + 新增 1 个）

- [ ] **Step 5: 提交**

```bash
WT=/home/elling/git-repo/github/jfox/.pi/worktrees/issue-458-wiki-link-hash-title
git -C "$WT" add jfox/note_index.py tests/unit/test_note_index.py
git -C "$WT" commit -m "fix(note_index): find_notes_referencing_title consumes candidate list (#458)"
```

---

### Task 5: 迁移 `promote_note`（candidate → permanent 的 forward links）

**Files:**
- Modify: `jfox/note.py:601`（`link_titles` 构造与 `find_by_title` 循环）
- Test: `tests/unit/test_note_promote.py`（追加含 `#` 锚点用例）

**Interfaces:**
- Consumes: `extract_wiki_link_targets`（Task 1）
- Produces: `promote_note(...)` 行为不变（精确标题匹配、**无子串兜底**），新增对含 `#` 完整标题的支持

**Acceptance:** A6

- [ ] **Step 1: 写失败的测试**

在 `tests/unit/test_note_promote.py` 追加：

```python
def test_promote_links_hash_title():
    """A6：正文含 [[含#完整标题]] 时 promote 后 links 含正确目标（issue #458）"""
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            target = create_note(
                "目标内容", title="jfox 增量索引修复方案（#387）", note_type=NoteType.PERMANENT
            )
            save_note(target, add_to_index=False)
            c = _make_candidate("引用含#标题", "讲讲 [[jfox 增量索引修复方案（#387）]] 的事")
            promote_note(c.id)
            assert target.id in load_note_by_id(c.id).links


def test_promote_links_hash_anchor_variant():
    """A6：正文含 [[标题#章节]] 锚点形态时 promote 后 links 含正确目标"""
    with temp_kb_registered() as kb_name:
        with use_kb(kb_name):
            target = create_note(
                "目标内容", title="某章节笔记", note_type=NoteType.PERMANENT
            )
            save_note(target, add_to_index=False)
            c = _make_candidate("引用锚点", "讲讲 [[某章节笔记#小节]] 的事")
            promote_note(c.id)
            assert target.id in load_note_by_id(c.id).links
```

> 放在 `tests/unit/test_note_promote.py` 的 `test_promote_sets_forward_links` 之后；保持该文件的**模块级** `def test_*` 风格（不是类方法）。`temp_kb_registered` / `use_kb` / `create_note` / `save_note` / `_make_candidate` / `promote_note` / `load_note_by_id` / `NoteType` 均已在文件顶部导入。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_note_promote.py -k hash -v`
Expected: FAIL —— 含 `#` 的完整标题未落进 `links`

- [ ] **Step 3: 改写 link 构造为「候选逐个精确匹配、首个命中即止」**

把 `jfox/note.py` 中 `link_titles = extract_wiki_links_from_text(...) + list(n.grounded_by or [])` 及其后的循环，替换为：

```python
    # forward links 来源（spec §2.1）：正文 [[...]] 候选 + frontmatter grounded_by 参考笔记，合并去重。
    # 先剥 fenced code block/HTML 注释避免字面量误匹配；精确标题匹配，不子串 fallback。
    # 每个链接按候选顺序试：完整原文优先（覆盖标题本身含 #），# 前缀次之（锚点语义）；
    # 首个命中即止——不能把两个候选都当独立标题试，否则前缀可能额外命中别的笔记（#458）。
    idx = get_note_index()
    target_ids: List[str] = []
    for candidates in extract_wiki_link_targets(_strip_wiki_link_exclusions(n.content)):
        for candidate in candidates:
            if not candidate:
                continue
            tm = idx.find_by_title(candidate)
            if tm is not None:
                if tm.id not in target_ids:
                    target_ids.append(tm.id)
                break
    for raw in list(n.grounded_by or []):
        if (
            not isinstance(raw, str) or not raw
        ):  # 过滤非 str/空串（YAML null/int/bool、LLM 脏数据）防 .lower() 崩
            continue
        tm = idx.find_by_title(raw)
        if tm is None:
            continue
        if tm.id not in target_ids:
            target_ids.append(tm.id)
```

> 保留原代码中紧随其后的既有后续逻辑（写 `n.links`、回填 backlinks 等）不动。`grounded_by` 是 ID/标题列表，**不参与候选拆分**（spec R2-D4）。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_note_promote.py -v`
Expected: PASS（既有 22 个 + 新增 1 个）

- [ ] **Step 5: 提交**

```bash
WT=/home/elling/git-repo/github/jfox/.pi/worktrees/issue-458-wiki-link-hash-title
git -C "$WT" add jfox/note.py tests/unit/test_note_promote.py
git -C "$WT" commit -m "fix(note): promote_note resolves wiki links by candidate order (#458)"
```

---

### Task 6: 迁移 `KnowledgeGraph` 建边

**Files:**
- Modify: `jfox/graph.py:97`（提取）与 `jfox/graph.py:107-125`（`_resolve_link`）
- Test: `tests/integration/test_wiki_link_hash_title.py`（追加图谱用例）

**Interfaces:**
- Consumes: `extract_wiki_link_targets`（Task 1）
- Produces: `KnowledgeGraph._resolve_link(candidates: List[str]) -> Optional[str]`（**签名从 `str` 改为 `List[str]`**）；`KnowledgeGraph.build() -> KnowledgeGraph` 行为不变

**Acceptance:** A7

> `tests/integration/` 下**没有**可复用的 graph fixture；用 `tests/conftest.py:129/144` 的 `temp_kb` + `cli` 落库后直接构造 `KnowledgeGraph`，参照根级 `tests/test_advanced_features.py:55` 的构建模式。

- [ ] **Step 1: 写失败的测试**

在 `tests/integration/test_wiki_link_hash_title.py` 追加：

```python
class TestWikiLinkHashTitleGraph:
    def test_graph_edge_from_hash_title_link(self, temp_kb, cli):
        """A7：[[完整标题（含#）]] 在 graph 中生成指向真实目标的边"""
        from jfox.graph import KnowledgeGraph

        target = cli.add("目标笔记正文", title="pi-agent-board issue #42 键位决策", note_type="permanent")
        source = cli.add(
            "参见 [[pi-agent-board issue #42 键位决策]]",
            title="图谱引用方",
            note_type="permanent",
        )
        graph = KnowledgeGraph().build()
        assert graph.graph.has_edge(source.id, target.id)
```

> 若 `KnowledgeGraph().build()` 需要显式传配置/路径，按 `tests/test_advanced_features.py:55` 的调用方式调整（那里已演示如何在本仓构造并 build 图谱）。

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/integration/test_wiki_link_hash_title.py::TestWikiLinkHashTitleGraph -v`
Expected: FAIL —— 边不存在或指向错误节点

- [ ] **Step 3: 改写提取与解析**

`jfox/graph.py:97`：

```python
        for note_id, note in self._note_cache.items():
            for candidates in extract_wiki_link_targets(note.content):
                linked_id = self._resolve_link(candidates)
                if linked_id and linked_id in self._note_cache:
                    if not self.graph.has_edge(note_id, linked_id):
                        self.graph.add_edge(note_id, linked_id, type="wiki_link")
```

`jfox/graph.py:107-125` 的 `_resolve_link`：

```python
    def _resolve_link(self, candidates: List[str]) -> Optional[str]:
        """按候选顺序解析一个 wiki-link 目标（候选契约见 jfox/note_index.split_wiki_target）。

        每个候选先试精确 ID 再试精确标题（大小写不敏感）；全不中时只对
        candidates[0]（完整原文）做子串兜底——前缀不参与子串，避免误连
        （issue #458）。返回 None 表示悬空。
        """
        for candidate in candidates:
            if not candidate:
                continue
            if candidate in self._note_cache:
                return candidate
            for note_id, note in self._note_cache.items():
                if note.title.casefold() == candidate.casefold():
                    return note_id

        fallback = (candidates[0] if candidates else "").casefold()
        if not fallback:
            return None
        for note_id, note in self._note_cache.items():
            if fallback in note.title.casefold():
                return note_id
        return None
```

并把 `jfox/graph.py:19` 的 import 由 `extract_wiki_links_from_text` 改为 `extract_wiki_link_targets`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/integration/test_wiki_link_hash_title.py -v`
Expected: PASS（A5 + A7）

- [ ] **Step 5: 提交**

```bash
WT=/home/elling/git-repo/github/jfox/.pi/worktrees/issue-458-wiki-link-hash-title
git -C "$WT" add jfox/graph.py tests/integration/test_wiki_link_hash_title.py
git -C "$WT" commit -m "fix(graph): resolve wiki-link candidates and keep substring on full text (#458)"
```

---

### Task 7: `redirect` 消费候选契约（保持精确匹配语义）

**Files:**
- Modify: `jfox/redirect.py:136`（`_link_matches_old`）；import 行 `jfox/redirect.py:25`
- Test: `tests/unit/test_redirect.py`（追加含 `#` 锚点用例）

**Interfaces:**
- Consumes: `split_wiki_target`（Task 1）
- Produces: `_link_matches_old(inner, old_id, old_title) -> bool`（签名不变；**语义不变：仍只做精确匹配、不做子串模糊匹配**）

**Acceptance:** A4

- [ ] **Step 1: 写失败的测试**

在 `tests/unit/test_redirect.py` 追加：

```python
    def test_hash_title_exact_match(self):
        """A4：含 # 的旧标题仍能被精确匹配（候选前缀命中），且不引入子串匹配"""
        from jfox.redirect import _link_matches_old

        assert _link_matches_old("旧概念#锚点", "ID1", "旧概念") is True
        assert _link_matches_old("旧概念#锚点", "ID1", "旧概念") is True
        # 子串仍不算匹配（test_no_substring_match 的契约，含 # 形态也不放宽）
        assert _link_matches_old("旧概念延伸#锚点", "ID1", "旧概念") is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_redirect.py -k hash_title -v`
Expected: 注意——**这条测试在改动前可能已通过**（旧实现 `_normalize_wiki_link_title` 会截断到 `旧概念`，前缀精确命中）。若如此，Step 2 的「确认失败」不适用，改为确认它**必须继续通过**（作为迁移后的防回归锚点），并在 Step 3 迁移后重跑确认仍 PASS。此时 Step 2 记为 `PASS (pre-existing, guard for migration)`。

- [ ] **Step 3: 改为候选成员判断**

`jfox/redirect.py` 的 `_link_matches_old`：

```python
def _link_matches_old(inner: str, old_id: str, old_title: str) -> bool:
    """判断一个 wiki link 内容是否精确指向旧笔记。

    对每个候选（完整原文 / `#` 前缀）做精确 ID 或精确标题匹配；
    **不做 substring 模糊匹配**，避免把 [[Foo]] 误判为对 "Foo Bar" 的引用。
    候选契约见 jfox/note_index.split_wiki_target（issue #458）。
    """
    for target in split_wiki_target(inner):
        if not target:
            continue
        if target == old_id:
            return True
        if old_title and target.casefold() == old_title.casefold():
            return True
    return False
```

import 行改为：`from .note_index import get_note_index, split_wiki_target`（`_normalize_wiki_link_title` 仍被 `_rewritten_inner` 用于生成新内容，**保留导入**）。

> **不要**改 `_rewritten_inner`——它生成 canonical `[[KEEP|别名]]` / `[[KEEP#锚点]]` 的逻辑与本次修复无关，保持原样。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_redirect.py -v`
Expected: PASS（既有全部 + 新增；含 `test_no_substring_match` / `test_id_form_matches` 必须通过）

- [ ] **Step 5: 提交**

```bash
WT=/home/elling/git-repo/github/jfox/.pi/worktrees/issue-458-wiki-link-hash-title
git -C "$WT" add jfox/redirect.py tests/unit/test_redirect.py
git -C "$WT" commit -m "refactor(redirect): consume wiki-link candidate contract (#458)"
```

---

### Task 8: 清理旧提取函数族 + 全量回归

**Files:**
- Modify: `jfox/note_index.py`（删除 `extract_wiki_links_from_text`，若仍有调用方则改为转调取 `candidates[0]`）
- Modify: `jfox/cli.py`（删除 `extract_wiki_links` 包装，`cli.py:309-312`）
- Test: 全量单元 + 相关集成

**Interfaces:**
- Consumes: Task 3–7 已迁移的全部消费者
- Produces: 无新接口；移除旧提取入口，杜绝「继续吃截断文本」的通道

**Acceptance:** A6

- [ ] **Step 1: 确认旧函数已无产品调用方**

Run:
```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-458-wiki-link-hash-title
grep -rn "extract_wiki_links_from_text\|cli.extract_wiki_links\|from .note_index import.*extract_wiki_links\|import extract_wiki_links" jfox/ | grep -v "def extract_wiki_link"
```
Expected: 只应剩 `note_index.py` 的定义本身与（可能的）测试引用。若仍有产品调用方，**停下来**——说明前序 task 漏迁移，补完再继续。

- [ ] **Step 2: 删除旧函数与包装**

- `jfox/note_index.py`：删除 `extract_wiki_links_from_text` 函数定义（保留 `_WIKI_LINK_RE`、`split_wiki_target`、`extract_wiki_link_targets`、`_normalize_wiki_link_title`——最后一个仍被 `redirect` 使用）。
- `jfox/cli.py`：删除 `extract_wiki_links` 包装函数（`cli.py:308-312`）。

- [ ] **Step 3: 修掉受影响的测试引用**

Run: `uv run pytest tests/ -m "not embedding and not slow" -x -q --no-header 2>&1 | tail -20`
Expected: 若报 `ImportError` / `AttributeError` 指向 `extract_wiki_links_from_text`，把该测试改为直接断言 `extract_wiki_link_targets(...)[0]`（候选首项语义）。逐个修，不要批量 sed。

- [ ] **Step 4: 跑全量单元与集成回归**

Run:
```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-458-wiki-link-hash-title
uv run pytest tests/unit tests/integration -q --no-header 2>&1 | tail -25
```
Expected: 全绿。**A6 的通过标准**：以下五个文件必须全绿——
`tests/unit/test_wiki_link_resolution.py`、`tests/unit/test_note_index.py`、`tests/unit/test_rebuild_backlinks_impl.py`、`tests/unit/test_note_promote.py`、`tests/unit/test_add_backfill_links.py`；其中 `test_note_index.py:394-418`（别名+锚点）与 `:340`（大小写不敏感）必须通过。

- [ ] **Step 5: 运行 lint 与格式检查**

Run:
```bash
cd /home/elling/git-repo/github/jfox/.pi/worktrees/issue-458-wiki-link-hash-title
uv run black --check jfox/ tests/
uv run ruff check jfox/ tests/
```
Expected: 无输出（通过）。有报错则 `uv run black jfox/ tests/` 后重跑。

- [ ] **Step 6: 提交**

```bash
WT=/home/elling/git-repo/github/jfox/.pi/worktrees/issue-458-wiki-link-hash-title
git -C "$WT" add jfox/note_index.py jfox/cli.py tests/
git -C "$WT" commit -m "refactor(note_index): drop legacy truncated link extraction entrypoints (#458)"
```

---

## 完成后（不在本计划内，属流程步 9–10）

- **U1 存量手术**是**用户实测**项，用户确认设计后才执行：按 spec 的 U1 步骤 ⓪–⑦（`uv run --project <WT>` + `research/measure-458.py` 的 E 段 dry-run 作为门禁）。本计划不含其实现。
- 本地 CR（步 8）→ PR + Zima CR（步 9，**push 前需用户明确许可**）→ post-merge 清理（步 10）。

## Self-Review

**1. Spec coverage：**

| spec 要求 | 落在 |
|---|---|
| 核心契约变更（提取层候选） | Task 1 |
| 四消费者全迁移 | Task 3（cli）、Task 4（referencing）、Task 5（promote）、Task 6（graph） |
| 子串只对完整原文 | Task 2（Step 3 实现）+ 用例⑧ |
| redirect 保持精确匹配 | Task 7 |
| 旧提取函数族清理 | Task 8 |
| A1–A8 | 追溯表逐项对应 |
| U1 | 标注为不在本计划内（用户实测，spec 已给公式） |
| 开放项 1（删除 or 转调） | Task 8 Step 1–2（按 grep 结果决定，两者都保证不再截断） |
| 开放项 2（`split_wiki_target` 归属） | Task 1（留在 `note_index.py`） |
| 开放项 3（`_normalize_wiki_link_title` 去留） | Task 7 注（保留，redirect 仍需） |

无遗漏项。

**2. Placeholder scan：** 无占位符——所有测试与实现步骤均含完整可执行代码（Task 4/5 的测试在 v2 已补齐，不再用「照既有用例」的引用式描述）。

**3. Type consistency：**

- `split_wiki_target(str) -> List[str]`：Task 1 定义，Task 2/6/7 消费 ✓
- `extract_wiki_link_targets(str) -> List[List[str]]`：Task 1 定义，Task 3/4/5/6 消费 ✓
- `resolve_link_target(List[str]) -> Optional[str]`：Task 2 定义，Task 3 消费 ✓
- `KnowledgeGraph._resolve_link` 签名由 `str` 改为 `List[str]`：Task 6 内同步改调用点（`graph.py:97` 循环），无跨 task 不一致 ✓
- `_link_matches_old(inner, old_id, old_title) -> bool`：Task 7 签名未变 ✓
- `resolve_wiki_links` 签名未变 ✓
