# MOC add-member 末尾路径换行丢失/成员行粘连修复（Issue #547）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 `moc add-member` 在末尾空分组/末尾分组/末尾建组三条路径上的换行错位与成员行粘连（S1/S2/S3），通过纯函数层入口规范化恢复「每行带尾换行」不变量。

**Architecture:** 新增私有纯函数 `_normalize_lines(content)`（宽容输入契约：文件/内存表示均接受，输出文件表示）；`upsert_member_line` 与 `remove_member_lines` 入口接入；既有插入/扫描逻辑零改动。测试助手 `_doc()` 增加 `stripped=True` 模拟 `from_markdown` strip 后的内存表示。

**Tech Stack:** Python 3.10+, pytest；worktree 内作业。

**Spec:** `docs/superpowers/specs/2026-10-13-moc-add-member-newline-design.md`（验收矩阵 A1~A10 + U1，决策 D1~D6）

## Global Constraints

- 所有文件操作路径以 worktree 根 `$WT=/home/elling/git-repo/github/jfox/.pi/worktrees/issue-547-moc-add-member-newline` 开头；git 操作用 `git -C $WT`；**禁碰主 checkout**。
- 行长度 100 字符；格式化 `uv run black`；检查 `uv run ruff check`。
- commit message 用英文 conventional commits；`git add` 按文件逐个 stage，禁止 `git add -A`。
- 不改 `jfox/models.py` 的 `strip()` / `to_markdown` 全局契约（非目标，spec §6）。
- 幂等/no-match 早退分支必须返回入参原字符串（D6/R2-D2）。
- `legacy_title_unique` 为 keyword-only 必填参数（draft.py:393-401）。
- 两次 add-member 的验收用例必须用**不同**成员笔记（同成员第二次命中幂等分支，R2-D3）。

---

### Task 1: `_normalize_lines` 纯函数 + `_doc` stripped 参数

**Files:**

- Modify: `$WT/jfox/moc/draft.py`（`_detect_ending`（draft.py:274-281）之后插入新函数）
- Test: `$WT/tests/unit/test_moc_draft.py`（修改 `_doc`（:226-228）；新增测试类 `TestNormalizeLines`）

**Interfaces:**

- Produces: `_normalize_lines(content: str) -> tuple[List[str], str]`——返回 `(lines, ending)`；`lines` 每行自带尾换行（含末行）；`content=""` → `([], "\n")`；CRLF 跟随 `_detect_ending` 首个换行风格。
- Produces: `_doc(*lines: str, stripped: bool = False)`——`stripped=False` 时行为与现状完全一致（`"\n".join(lines) + "\n"`）；`stripped=True` 时返回 `"\n".join(lines).strip()`（与 models.py:223 `content_text.strip()` 同函数同语义）。
- Consumes: `_detect_ending(lines)`（既有，不改）。

**验收 ID：** A6（CRLF/混合风格/no-op，扩展）、A8（空串/纯空白不崩）

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_moc_draft.py` 末尾新增：

```python
class TestNormalizeLines:
    """_normalize_lines 直测（spec §5，挂 A6/A8 用例展开）。"""

    def test_empty_string_noop(self):
        from jfox.moc.draft import _normalize_lines

        assert _normalize_lines("") == ([], "\n")

    def test_whitespace_only(self):
        from jfox.moc.draft import _normalize_lines

        lines, ending = _normalize_lines("   ")
        assert lines == ["   \n"]
        assert ending == "\n"

    def test_single_line_without_newline(self):
        from jfox.moc.draft import _normalize_lines

        assert _normalize_lines("abc") == (["abc\n"], "\n")

    def test_multi_line_last_without_newline(self):
        from jfox.moc.draft import _normalize_lines

        assert _normalize_lines("a\nb") == (["a\n", "b\n"], "\n")

    def test_already_terminated_is_noop(self):
        from jfox.moc.draft import _normalize_lines

        assert _normalize_lines("a\n") == (["a\n"], "\n")

    def test_crlf_ending_detected_and_appended(self):
        from jfox.moc.draft import _normalize_lines

        assert _normalize_lines("a\r\nb") == (["a\r\n", "b\r\n"], "\r\n")

    def test_mixed_endings_first_wins(self):
        from jfox.moc.draft import _normalize_lines

        lines, ending = _normalize_lines("a\r\nb\nc")
        assert ending == "\r\n"
        assert lines == ["a\r\n", "b\n", "c\r\n"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd $WT && uv run pytest tests/unit/test_moc_draft.py::TestNormalizeLines -x -q`
Expected: FAIL（`ImportError: cannot import name '_normalize_lines'`）

- [ ] **Step 3: 实现 `_normalize_lines`**

在 `jfox/moc/draft.py` 的 `_detect_ending` 函数定义之后插入：

```python
def _normalize_lines(content: str) -> tuple[List[str], str]:
    """宽容输入契约：文件/内存表示均接受；返回每行自带尾换行的行列表与 ending。

    - 空 content → 空列表（no-op，spec D2）。
    - lines 非空且末行无尾换行（内存表示）→ 末行补 ending。
    - ending 跟随 _detect_ending 检测到的首个换行风格（spec D4）。
    """
    lines = content.splitlines(keepends=True)
    ending = _detect_ending(lines)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] = lines[-1] + ending
    return lines, ending
```

注：`"\r\n".endswith("\n")` 为 True，CRLF 已终结行不会被误补。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd $WT && uv run pytest tests/unit/test_moc_draft.py::TestNormalizeLines -q`
Expected: 7 passed

- [ ] **Step 5: `_doc` 加 stripped 参数 + 锁定测试**

修改 `tests/unit/test_moc_draft.py:226`：

```python
def _doc(*lines: str, stripped: bool = False) -> str:
    """按渲染格式拼一个 MOC 正文样本。

    stripped=True 时返回 "\n".join(lines).strip()，模拟 from_markdown
    strip() 后的内存表示（末行无尾换行；对本 spec 构造的无首尾空白样例
    与 rstrip("\n") 等价）。
    """
    text = "\n".join(lines)
    return text.strip() if stripped else text + "\n"
```

在 `TestNormalizeLines` 后新增锁定用例：

```python
class TestDocHelper:
    """_doc 助手 stripped 参数语义锁定。"""

    def test_default_unchanged(self):
        assert _doc("## g", "", "- [[a|b]]") == "## g\n\n- [[a|b]]\n"

    def test_stripped_has_no_trailing_newline(self):
        assert _doc("## g", "", "- [[a|b]]", stripped=True) == "## g\n\n- [[a|b]]"
        assert _doc("## 末尾空分组", stripped=True) == "## 末尾空分组"
```

- [ ] **Step 6: 跑全部 `_doc` 相关与现有用例确认不回归**

Run: `cd $WT && uv run pytest tests/unit/test_moc_draft.py -q`
Expected: 全部通过（含新 9 个用例）

- [ ] **Step 7: 格式化 + commit**

```bash
cd $WT && uv run black jfox/moc/draft.py tests/unit/test_moc_draft.py && uv run ruff check jfox/moc/draft.py tests/unit/test_moc_draft.py
git add jfox/moc/draft.py tests/unit/test_moc_draft.py
git commit -m "feat(moc): add _normalize_lines pure fn and _doc stripped param (issue-547 A6/A8)"
```

---

### Task 2: `upsert_member_line` 入口接入规范化（S1/S2/S3 修复）

**Files:**

- Modify: `$WT/jfox/moc/draft.py`（`upsert_member_line` 入口 draft.py:418-419 两行）
- Test: `$WT/tests/unit/test_moc_draft.py`（新增测试类 `TestUpsertStrippedInput`）

**Interfaces:**

- Consumes: `_normalize_lines`（Task 1）、`_doc(stripped=True)`（Task 1）
- Produces: `upsert_member_line` 输出契约升级为文件表示（spec §1；幂等分支返回原参数豁免，D6）

**验收 ID：** A1（S1）、A2（S2）、A3（S3）、A4（幂等豁免）、A5/A7（现有用例回归锁定）

- [ ] **Step 1: 写失败测试（stripped 输入复现症状）**

在 `tests/unit/test_moc_draft.py` 新增：

```python
class TestUpsertStrippedInput:
    """内存表示（strip 后末行无换行）输入的 upsert 行为（issue #547，A1~A4）。"""

    def test_s1_first_insert_keeps_blank_line_after_heading(self):
        content = _doc("## 既有的分组", "", "- [[m1|成员一]]", "", "## 末尾空分组", stripped=True)
        r = upsert_member_line(
            content, "m2", "成员二", [], "末尾空分组", legacy_title_unique=True
        )
        assert r.changed is True
        assert "## 末尾空分组\n\n- [[m2|成员二]]\n" in r.content

    def test_s2_second_insert_keeps_rows_separate(self):
        content = _doc("## 既有的分组", "", "- [[m1|成员一]]", "", "## 末尾空分组", stripped=True)
        r1 = upsert_member_line(
            content, "m2", "成员二", [], "末尾空分组", legacy_title_unique=True
        )
        # 模拟落盘再加载：to_markdown 补 \n，from_markdown strip
        c2 = (r1.content + "\n").strip()
        r2 = upsert_member_line(
            c2, "m3", "成员三", [], "末尾空分组", legacy_title_unique=True
        )
        assert "]]\n- [[" in r2.content
        assert "]]- [[" not in r2.content

    def test_s3_append_new_group_keeps_blank_line(self):
        content = _doc("## 组A", "", "- [[m1|成员一]]", stripped=True)
        r = upsert_member_line(
            content, "m2", "成员二", [], "组B", legacy_title_unique=True
        )
        assert "]]\n\n## 组B\n" in r.content

    def test_a4_idempotent_returns_input_verbatim(self):
        content = _doc("## 组A", "", "- [[m1|成员一]]", stripped=True)
        r = upsert_member_line(
            content, "m1", "成员一", [], "组A", legacy_title_unique=True
        )
        assert r.changed is False
        assert r.content == content  # D6：幂等分支返回原参数，不经规范化改写
```

注：文件头部需确保 `from jfox.moc.draft import upsert_member_line` 已导入（既有测试已用，确认导入行存在即可）。

- [ ] **Step 2: 跑测试确认症状复现（红）**

Run: `cd $WT && uv run pytest tests/unit/test_moc_draft.py::TestUpsertStrippedInput -q`
Expected: S1/S2/S3 三个用例 FAIL（复现 issue 症状），A4 用例 PASS（幂等本就不受影响）

- [ ] **Step 3: 改 `upsert_member_line` 入口（一行级改动）**

`jfox/moc/draft.py` 中 `upsert_member_line` 函数体内：

```python
# 修改前（draft.py:418-419）
    lines = content.splitlines(keepends=True)
    ending = _detect_ending(lines)
```

```python
# 修改后
    lines, ending = _normalize_lines(content)
```

其余逻辑（`_scan_body` / 选组 / legacy / `_insert_into_section` / `_append_new_group`）**零改动**。

- [ ] **Step 4: 跑新测试确认通过（绿）**

Run: `cd $WT && uv run pytest tests/unit/test_moc_draft.py::TestUpsertStrippedInput -q`
Expected: 4 passed

- [ ] **Step 5: 跑全文件回归（A5 对照组 + A7 legacy 路径）**

Run: `cd $WT && uv run pytest tests/unit/test_moc_draft.py -q`
Expected: 全部通过（既有用例输入均为文件表示，规范化对它们是 no-op）

- [ ] **Step 6: commit**

```bash
cd $WT && git add jfox/moc/draft.py tests/unit/test_moc_draft.py
git commit -m "fix(moc): normalize input lines at upsert entry — fixes trailing-section gluing (issue-547 A1/A2/A3/A4)"
```

---

### Task 3: `remove_member_lines` 入口接入规范化（D5 契约统一 + no-match 豁免）

**Files:**

- Modify: `$WT/jfox/moc/draft.py`（`remove_member_lines` 入口 draft.py:515 一行）
- Test: `$WT/tests/unit/test_moc_draft.py`（`TestRemoveStrippedInput`）

**Interfaces:**

- Consumes: `_normalize_lines`（Task 1）
- Produces: remove 输出契约同 spec §1（no-match 早退豁免：返回入参原样、changed=False）

**验收 ID：** A9（remove 回归 + no-match 豁免）

注：remove 只删不插，当前对内存表示输入行为已正确——本任务测试为**锁定/防御**性质（预期直接绿），改动为契约统一（spec D5）。

- [ ] **Step 1: 写锁定测试**

在 `tests/unit/test_moc_draft.py` 新增：

```python
class TestRemoveStrippedInput:
    """内存表示输入的 remove 行为锁定（issue #547，A9）。"""

    def test_remove_row_from_stripped_input(self):
        content = _doc("## 组A", "", "- [[m1|成员一]]", "- [[m2|成员二]]", stripped=True)
        r = remove_member_lines(content, "m2", "成员二", legacy_title_unique=True)
        assert r.changed is True
        assert "- [[m2|成员二]]" not in r.content
        assert "- [[m1|成员一]]" in r.content

    def test_no_match_returns_input_verbatim(self):
        content = _doc("## 组A", "", "- [[m1|成员一]]", stripped=True)
        r = remove_member_lines(content, "m9", "成员九", legacy_title_unique=True)
        assert r.changed is False
        assert r.content == content  # R2-D2：no-match 早退原样返回入参（内存表示）
```

确认文件头部 `from jfox.moc.draft import remove_member_lines` 导入存在。

- [ ] **Step 2: 跑测试（当前应为绿——锁定性质）**

Run: `cd $WT && uv run pytest tests/unit/test_moc_draft.py::TestRemoveStrippedInput -q`
Expected: 2 passed（若有红，说明 remove 在 stripped 输入下存在未预知问题，停下调查而非改测试）

- [ ] **Step 3: 改 `remove_member_lines` 入口**

`jfox/moc/draft.py` `remove_member_lines` 函数体内：

```python
# 修改前（draft.py:515）
    lines = content.splitlines(keepends=True)
```

```python
# 修改后（仅借规范化恢复不变量，不引入 ending 变量——只删不插）
    lines, _ = _normalize_lines(content)
```

- [ ] **Step 4: 跑全文件回归**

Run: `cd $WT && uv run pytest tests/unit/test_moc_draft.py -q`
Expected: 全部通过

- [ ] **Step 5: commit**

```bash
cd $WT && git add jfox/moc/draft.py tests/unit/test_moc_draft.py
git commit -m "refactor(moc): unify remove_member_lines input normalization (issue-547 A9/D5)"
```

---

### Task 4: e2e integration 用例（A10：盘上字节 + D3 收敛 + 重载环路）

**Files:**

- Modify: `$WT/tests/integration/test_moc_member_commands.py`（新增常量 + fixture 扩展 + 一个测试函数）

**Interfaces:**

- Consumes: 既有 `seeded_kb` fixture（tmp KB + monkeypatch 全局 config + mock embedding）、`_add_member_impl(cfg, moc_id, note_id, group)`、`_moc_file(cfg)`、`_reload(cfg)`、`_atomic_write`

**验收 ID：** A10

- [ ] **Step 1: 扩展 fixture 种子 + 写 e2e 测试**

在 `tests/integration/test_moc_member_commands.py` 顶部常量区新增：

```python
MEMBER_THREE = "20260820000003"
```

在文件末尾新增测试：

```python
def test_add_member_twice_to_trailing_empty_group(seeded_kb):
    """Issue #547 A10：末尾空分组连续两次 add-member（不同成员），
    盘上标题后空行存在、成员行独立、正文区以 ]]\\n\\n 结尾、重载环路收敛。"""
    # 成员三（permanent）现建，模式同 test_add_member_non_permanent_warns_but_applies
    three = Note(
        id=MEMBER_THREE,
        title="Zima Three",
        content="content of Zima Three",
        type=NoteType.PERMANENT,
        created=dt(2026, 8, 20),
        updated=dt(2026, 8, 20),
        tags=["zima"],
    )
    three.set_filepath(
        seeded_kb.notes_dir / "permanent" / f"{MEMBER_THREE}-zima-three.md"
    )
    _atomic_write(three.filepath, three.to_markdown())

    # 重置 MOC 正文：末尾空分组（内存表示写入，to_markdown 落盘补 \n）
    moc = _reload(seeded_kb)
    moc.content = "## zima\n\n- [[20260820000001|Zima One]] — 3 links\n\n## 末尾空分组"
    _atomic_write(moc.filepath, moc.to_markdown())

    p1 = _add_member_impl(seeded_kb, MOC_ID, MEMBER_TWO, "末尾空分组")
    assert p1["success"] is True and p1["applied"] is True
    p2 = _add_member_impl(seeded_kb, MOC_ID, MEMBER_THREE, "末尾空分组")
    assert p2["success"] is True and p2["applied"] is True

    text = _moc_file(seeded_kb).read_text(encoding="utf-8")
    assert "## 末尾空分组\n\n- [[" in text  # 标题后空行存在（S1 修复）
    assert "]]\n- [[" in text  # 两成员行各自独立（S2 修复）
    assert "]]- [[" not in text
    assert text.endswith("]]\n\n")  # D3 收敛态：content 尾换行 + to_markdown 补 \n

    # 环路收敛：重载后 content 与期望的 strip 态精确相等（无累积漂移）
    moc2 = _reload(seeded_kb)
    assert moc2.content == (
        "## zima\n\n- [[20260820000001|Zima One]] — 3 links\n\n"
        "## 末尾空分组\n\n"
        "- [[20260820000002|Zima Two]]\n"
        "- [[20260820000003|Zima Three]]"
    )
```

- [ ] **Step 2: 跑测试确认通过**

Run: `cd $WT && uv run pytest tests/integration/test_moc_member_commands.py::test_add_member_twice_to_trailing_empty_group -q`
Expected: PASS（Task 2 修复已接入；若 FAIL，按 systematic-debugging 先查实际盘上字节再动代码）

- [ ] **Step 3: 跑本文件全部集成测试回归**

Run: `cd $WT && uv run pytest tests/integration/test_moc_member_commands.py -q`
Expected: 全部通过（既有用例不受影响）

- [ ] **Step 4: commit**

```bash
cd $WT && git add tests/integration/test_moc_member_commands.py
git commit -m "test(moc): e2e coverage for trailing-empty-group double add-member (issue-547 A10)"
```

---

### Task 5: 全量回归 + 收尾

**Files:** 无新增改动（验证任务）

**验收 ID：** A5（回归总确认）、U1（标记 pending，合入后用户实测）

- [ ] **Step 1: moc 相关全量测试**

Run: `cd $WT && uv run pytest tests/unit/test_moc_draft.py tests/unit/test_moc_generate.py tests/integration/test_moc_member_commands.py -q`
Expected: 全部通过

- [ ] **Step 2: 快速套件回归（不加载模型）**

Run: `cd $WT && uv run pytest tests/ -m "not embedding and not slow" -q -x`
Expected: 全部通过（Fast job 等价口径）

- [ ] **Step 3: lint + format 检查**

```bash
cd $WT && uv run black --check jfox/moc/draft.py tests/unit/test_moc_draft.py tests/integration/test_moc_member_commands.py
cd $WT && uv run ruff check jfox/moc/draft.py tests/unit/test_moc_draft.py tests/integration/test_moc_member_commands.py
```

Expected: 无输出/无错误

- [ ] **Step 4: markdownlint 检查（本 plan 与 spec 文档）**

Run: `cd $WT && npx --yes markdownlint-cli2 "docs/superpowers/plans/2026-10-13-moc-add-member-newline.md" "docs/superpowers/specs/2026-10-13-moc-add-member-newline-design.md"`
Expected: 无错误（若报 MD013 行宽等既有禁用项外的新错误，修复后重跑）

- [ ] **Step 5: U1 标记 pending 并记录**

在 PR 描述中写明：U1（真实 CLI 目检）按 spec §4 三件套在合入后执行（载体：repo checkout `uv run jfox`；隔离：临时 KB / 可删 MOC；验收后回收）。不宣称全部验收完成。

---

## 验收 ID ↔ Task 双向追溯

| 验收 ID | 归属 Task |
|---|---|
| A1 S1 修复 | Task 2 |
| A2 S2 修复 | Task 2 |
| A3 S3 修复 | Task 2 |
| A4 幂等豁免 | Task 2 |
| A5 对照组回归 | Task 2 Step 5 / Task 5 |
| A6 CRLF/混合/no-op | Task 1 |
| A7 legacy 回归 | Task 2 Step 5（现有用例锁定） |
| A8 空正文/纯空白 | Task 1 |
| A9 remove 回归 + no-match | Task 3 |
| A10 e2e 字节 + D3 收敛 | Task 4 |
| U1 用户实测 | Task 5 Step 5（pending → 合入后执行） |
