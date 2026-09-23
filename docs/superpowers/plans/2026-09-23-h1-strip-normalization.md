# --content-file 输入标准化（#541）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `jfox add/edit --content-file`（文件与 stdin 同一语义）的输入经过统一标准化——无条件剥至多一行开头 H1、双 H1 报错、剥后为空报错——使「取出正文 → 追加 → 回灌」在全部输入形态下落盘结构恒定（1 个 fm 块 + 1 个 H1）。

**Architecture:** 读盘侧 `models.from_markdown` 本就无条件剥首个 H1；本计划在其对称位置（`cli._strip_frontmatter`）补齐写盘输入侧的纯函数转换器，stdin 分支改走同一标准化。不改文件格式、不改 `--content` 直传路径。

**Tech Stack:** Python 3.10+, Typer CLI, pytest（unit 纯函数测试 + integration 走 cli_fast mock embedding fixture）。

**Spec:** `docs/superpowers/specs/2026-09-23-h1-strip-normalization-design.md`（决策 D0–D4、形态 1–8、验收 A1–A9/U1）

**Worktree:** `/home/elling/git-repo/github/jfox/.pi/worktrees/issue-541-h1-strip-normalization`（所有命令以此目录为 cwd）

## Global Constraints

- 行宽 100（black），ruff 零告警；代码注释与报错文案用中文；commit message 用英文 conventional commits
- 纯函数边界：剥 H1 逻辑只能存在于 `_strip_leading_h1` / `_strip_frontmatter`，不得内联进 `_read_content_file` 或 add/edit 调用方
- D2 报错文案必须含「多个 H1」和「--content」修复指引；D4 报错文案必须含「正文为空」
- `--content` 直传路径行为不变（escape hatch，不做任何剥离）
- 纯正文 passthrough 语义不变（`_strip_leading_h1` 不匹配时逐字节返回）
- 仓库规则：全量/集成测试（~50min）不自主跑；本地跑目标测试文件 + 静态检查，完整 Fast 套件以 PR 的 CI Fast job 为准（承接 A8）

## File Structure

| 文件 | 动作 | 责任 |
|------|------|------|
| `jfox/cli.py` | Modify | 新增 `_strip_leading_h1` 纯函数；`_strip_frontmatter` 重构为五步标准化；`_read_content_file` stdin 分支接入标准化 + docstring 更新 |
| `tests/unit/test_content_file.py` | Modify | 新增 4 个纯函数测试类；改写 `test_stdin_passthrough` 为 3 个新契约测试 |
| `tests/integration/test_edit_roundtrip.py` | Create | A6 回灌端到端 + A7 add 标题派生（`pytestmark = [pytest.mark.integration]`，cli_fast） |

---

### Task 1: `_strip_leading_h1` 纯函数 + H1 无条件剥离（A1, A2, A3）

**Files:**

- Modify: `jfox/cli.py:1874-1886`（`_strip_frontmatter` 重构，新增 `_strip_leading_h1`）
- Test: `tests/unit/test_content_file.py`

**Interfaces:**

- Consumes: 无（纯函数，仅依赖 `re`）
- Produces: `_strip_leading_h1(body: str) -> str` —— 吃掉开头空行后至多剥掉一行 H1（不匹配逐字节返回）；`_strip_frontmatter(raw: str) -> str` 签名不变，Task 2/3 将在其返回前追加校验

- [ ] **Step 1: Write the failing tests**

在 `tests/unit/test_content_file.py` 顶部 import 行改为：

```python
from jfox.cli import _read_content_file, _strip_frontmatter, _strip_leading_h1
```

文件末尾追加两个测试类：

```python
class TestStripLeadingH1:
    """_strip_leading_h1 纯函数（#541）"""

    def test_strips_single_h1(self):
        assert _strip_leading_h1("# 标题\n正文") == "正文"

    def test_strips_h1_after_leading_blank_lines(self):
        assert _strip_leading_h1("\n\n# 标题\n正文") == "正文"

    def test_keeps_h2_heading(self):
        assert _strip_leading_h1("## 小节\n正文") == "## 小节\n正文"

    def test_keeps_hashtag_line(self):
        assert _strip_leading_h1("#标签\n正文") == "#标签\n正文"

    def test_plain_text_passthrough(self):
        assert _strip_leading_h1("Hello world") == "Hello world"


class TestStripFrontmatterH1Only:
    """无 frontmatter 时 H1 剥离（#541 主诉，spec 形态 4）"""

    def test_h1_only_no_frontmatter_stripped(self):
        raw = "# 回灌测试笔记\n\nB 原始正文。\n追加 B。\n"
        assert _strip_frontmatter(raw) == "B 原始正文。\n追加 B。\n"

    def test_h1_after_leading_blank_lines_stripped(self):
        assert _strip_frontmatter("\n\n# 标题\n正文") == "正文"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_content_file.py -k "StripLeadingH1 or StripFrontmatterH1Only"`
Expected: FAIL —— `ImportError: cannot import name '_strip_leading_h1'`

- [ ] **Step 3: Implement**

在 `jfox/cli.py` 的 `_strip_frontmatter` 定义之前插入 `_strip_leading_h1`，并将 `_strip_frontmatter` 整体替换为：

```python
def _strip_leading_h1(body: str) -> str:
    """吃掉开头空行后，至多剥掉一行 H1 标题行（# 后跟空白和非空内容）。

    与 models.from_markdown 读盘侧「无条件剥首个 H1」的口径对齐：
    标题行之前的空行、标题行之后的换行一并吃掉。不匹配（纯正文、## 二级
    标题、#标签 行）时逐字节原样返回。
    """
    m = re.match(r"^(?:[ \t]*\n)*#[ \t]+\S[^\n]*\n*", body)
    return body[m.end():] if m else body


def _strip_frontmatter(raw: str) -> str:
    """标准化 --content-file 输入为 Note.content 等价物（#541）。

    ① 剥 UTF-8 BOM；② 存在 frontmatter 则剥除；③ 无条件剥至多一行开头 H1
    ——读盘侧 from_markdown 无条件剥首个 H1，此处补齐写盘输入侧的对称转换。
    """
    # 去除 UTF-8 BOM
    if raw.startswith("﻿"):
        raw = raw[1:]
    match = re.match(r"^---\n.*?\n---\n+(.*)", raw, re.DOTALL)
    if match:
        body = _strip_leading_h1(match.group(1).strip()).strip()
    else:
        body = _strip_leading_h1(raw)
    return body
```

- [ ] **Step 4: Run new + existing tests to verify pass（A1 通过；A2/A3 不回归）**

Run: `uv run pytest tests/unit/test_content_file.py`
Expected: 全部 PASS（含既有 `test_plain_content_unchanged`、`test_content_with_frontmatter_stripped`、`test_content_with_frontmatter_no_title`、`test_bom_file_stripped`、`test_stdin_passthrough`、`test_file_not_found`——stdin 行为在 Task 4 才改，本任务不动）

- [ ] **Step 5: Commit**

```bash
git add jfox/cli.py tests/unit/test_content_file.py
git commit -m "feat(cli): strip leading H1 from --content-file input unconditionally (#541)"
```

---

### Task 2: 双 H1 报错（A4, D2）

**Files:**

- Modify: `jfox/cli.py`（`_strip_frontmatter` 返回前加第④步校验）
- Test: `tests/unit/test_content_file.py`

**Interfaces:**

- Consumes: Task 1 的 `_strip_frontmatter` / `_strip_leading_h1`
- Produces: `_strip_frontmatter` 新增 ValueError 分支（文案含「多个 H1」「--content」）

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_content_file.py` 末尾追加：

```python
class TestStripFrontmatterDoubleH1:
    """开头连续双 H1 报错（#541 spec 形态 6，决策 D2）"""

    def test_double_h1_no_frontmatter_raises(self):
        with pytest.raises(ValueError, match="多个 H1"):
            _strip_frontmatter("# 标题一\n# 标题二\n正文")

    def test_double_h1_with_frontmatter_raises(self):
        raw = "---\nid: '1'\n---\n\n# 标题一\n\n# 标题二\n\n正文\n"
        with pytest.raises(ValueError, match="--content"):
            _strip_frontmatter(raw)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_content_file.py -k DoubleH1`
Expected: FAIL —— 两个用例均未抛 ValueError

- [ ] **Step 3: Implement**

`jfox/cli.py` 的 `_strip_frontmatter`：docstring 第③行后追加第④步描述，并在 `return body` 前插入校验。函数尾部变为：

```python
    ① 剥 UTF-8 BOM；② 存在 frontmatter 则剥除；③ 无条件剥至多一行开头 H1
    ——读盘侧 from_markdown 无条件剥首个 H1，此处补齐写盘输入侧的对称转换；
    ④ 剥后开头仍是 H1（连续双 H1，疑似结构损坏文件）时报错。
    """
    # 去除 UTF-8 BOM
    if raw.startswith("﻿"):
        raw = raw[1:]
    match = re.match(r"^---\n.*?\n---\n+(.*)", raw, re.DOTALL)
    if match:
        body = _strip_leading_h1(match.group(1).strip()).strip()
    else:
        body = _strip_leading_h1(raw)
    if re.match(r"^#[ \t]+\S", body):
        raise ValueError(
            "输入内容开头存在多个 H1 标题行，疑似结构损坏的笔记（双 H1/嵌套笔记）。"
            "请手动删除多余的 H1 行，或用 --content 直传修复后的内容"
        )
    return body
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/unit/test_content_file.py`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/cli.py tests/unit/test_content_file.py
git commit -m "feat(cli): reject consecutive double-H1 input in content-file normalization (#541)"
```

---

### Task 3: 剥后为空报错（A9, D4）

**Files:**

- Modify: `jfox/cli.py`（`_strip_frontmatter` 第⑤步）
- Test: `tests/unit/test_content_file.py`

**Interfaces:**

- Consumes: Task 2 的 `_strip_frontmatter`
- Produces: `_strip_frontmatter` 新增「剥后为空且原输入非空」ValueError 分支（文案含「正文为空」）

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_content_file.py` 末尾追加：

```python
class TestStripFrontmatterEmpty:
    """剥后为空报错（#541 spec 形态 8，决策 D4）"""

    def test_single_h1_line_raises_empty(self):
        with pytest.raises(ValueError, match="正文为空"):
            _strip_frontmatter("# 只有标题没有正文")

    def test_empty_string_passthrough(self):
        assert _strip_frontmatter("") == ""

    def test_blank_lines_only_passthrough(self):
        assert _strip_frontmatter("\n\n") == "\n\n"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_content_file.py -k StripFrontmatterEmpty`
Expected: FAIL —— `test_single_h1_line_raises_empty` 未抛 ValueError（其余两个通过）

- [ ] **Step 3: Implement**

`jfox/cli.py` 的 `_strip_frontmatter`：docstring 第④步描述后追加第⑤步，并在函数末尾（`return body` 前）插入空校验。尾部变为：

```python
    ④ 剥后开头仍是 H1（连续双 H1，疑似结构损坏文件）时报错；
    ⑤ 剥后为空且原始输入非空时报错（防误传单行标题清空正文）。
    """
```

```python
    if not body and raw.strip():
        raise ValueError("剥除标题行后正文为空，请确认输入内容是否正确")
    return body
```

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/unit/test_content_file.py`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/cli.py tests/unit/test_content_file.py
git commit -m "feat(cli): reject empty-after-strip content-file input (#541)"
```

---

### Task 4: stdin 统一标准化（A5, D1）

**Files:**

- Modify: `jfox/cli.py:1888-1910`（`_read_content_file` stdin 分支 + docstring）
- Test: `tests/unit/test_content_file.py`（改写 `test_stdin_passthrough`）

**Interfaces:**

- Consumes: Task 3 完成的 `_strip_frontmatter`
- Produces: `_read_content_file(content_file: str) -> str` —— `"-"`（stdin）与文件路径同一标准化语义

- [ ] **Step 1: Write the failing tests**

`tests/unit/test_content_file.py` 中**删除** `test_stdin_passthrough`，替换为三个新契约测试（仍放在 `TestReadContentFile` 类内）：

```python
    def test_stdin_frontmatter_and_h1_stripped(self):
        """stdin 与文件路径同语义（#541 D1）：frontmatter + H1 剥离"""
        import sys

        old_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO("---\nid: x\n---\n\n# 标题\n\n正文\n")
            result = _read_content_file("-")
        finally:
            sys.stdin = old_stdin
        assert result == "正文"

    def test_stdin_h1_only_stripped(self):
        """stdin：无 frontmatter 的 H1 开头同样剥离"""
        import sys

        old_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO("# 标题\n\n正文\n")
            result = _read_content_file("-")
        finally:
            sys.stdin = old_stdin
        assert result == "正文\n"

    def test_stdin_plain_passthrough(self):
        """stdin：纯正文原样放行"""
        import sys

        old_stdin = sys.stdin
        try:
            sys.stdin = io.StringIO("Hello world")
            result = _read_content_file("-")
        finally:
            sys.stdin = old_stdin
        assert result == "Hello world"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_content_file.py -k stdin`
Expected: FAIL —— `test_stdin_frontmatter_and_h1_stripped` 断言失败（stdin 未剥离，`"---" in result`）

- [ ] **Step 3: Implement**

`jfox/cli.py` 的 `_read_content_file`：stdin 分支改为走标准化，docstring 更新。函数头变为：

```python
def _read_content_file(content_file: str) -> str:
    """从文件或 stdin 读取内容（--content-file 共用逻辑）。

    文件与 stdin 同一语义：统一经 _strip_frontmatter 标准化——剥 frontmatter
    （如有）、无条件剥至多一行开头 H1（#541）；连续双 H1 或剥后为空会报错。
    想让正文以井号标题行开头，用 --content 直传（不做任何剥离）。
    """
    if content_file == "-":
        import sys

        return _strip_frontmatter(sys.stdin.read())
```

（函数其余部分——文件存在性/权限/编码校验与末尾 `return _strip_frontmatter(raw)`——保持不动。）

- [ ] **Step 4: Run tests to verify pass**

Run: `uv run pytest tests/unit/test_content_file.py`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/cli.py tests/unit/test_content_file.py
git commit -m "feat(cli): normalize stdin --content-file input same as file path (#541)"
```

---

### Task 5: 集成测试——回灌端到端 + add 标题派生（A6, A7, D3）

**Files:**

- Create: `tests/integration/test_edit_roundtrip.py`

**Interfaces:**

- Consumes: Task 1–4 完成的 CLI 行为；`cli_fast` fixture（tests/conftest.py）；`cli_fast._run("show", note_id)`（jfox_cli 无 show 封装方法，直接调 `_run`）；add JSON 结构 `r.data["note"]["id"]` / `r.data["note"]["filepath"]`；show JSON 结构 `s.data["content_body"]`
- Produces: 无新生产代码（纯测试任务）

- [ ] **Step 1: Write the integration test file**

创建 `tests/integration/test_edit_roundtrip.py`：

```python
"""
测试类型: 集成测试
目标功能: issue #541 — --content-file 输入标准化后的回灌端到端验收（A6/A7）
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


def _count_structure(filepath: str) -> tuple:
    """返回 (frontmatter 分隔行数, H1 标题行数)"""
    lines = Path(filepath).read_text(encoding="utf-8").splitlines()
    fm_delims = sum(1 for line in lines if line == "---")
    h1s = sum(1 for line in lines if line.startswith("# "))
    return fm_delims, h1s


class TestEditRoundTrip:
    """A6：show → 追加 → edit --content-file 回灌，结构恒定（issue 实验 B 自动化）"""

    def test_edit_roundtrip_content_body(self, cli_fast, tmp_path):
        # 1. 建笔记
        r = cli_fast.add("原始正文第一段。", title="回灌复现笔记")
        assert r.success
        note_id = r.data["note"]["id"]
        filepath = r.data["note"]["filepath"]

        # 2. show --json 取 content_body（含 H1、无 frontmatter——即 #541 实验 B 输入）
        s = cli_fast._run("show", note_id)
        assert s.success
        body = s.data["content_body"]
        assert body.startswith("# ")

        # 3. 追加后整体回灌（文件路径通道）
        f = tmp_path / "body.md"
        f.write_text(body + "\n追加内容 B。\n", encoding="utf-8")
        e = cli_fast.edit(note_id, content_file=str(f))
        assert e.success

        # 4. 结构断言：恰好 1 个 fm 块（2 个 --- 行）、1 个 H1 行，追加内容在正文中
        fm_delims, h1s = _count_structure(filepath)
        assert fm_delims == 2
        assert h1s == 1
        n = _load_note(filepath)
        assert "追加内容 B。" in n.content

    def test_add_content_file_h1_title_derivation(self, cli_fast, tmp_path):
        """A7/D3：add --content-file 传 H1 开头正文，H1 被剥，标题派生自剥后首段"""
        f = tmp_path / "doc.md"
        f.write_text("# 外部文档标题\n\n真正的第一段。", encoding="utf-8")
        r = cli_fast._run("add", "--content-file", str(f))
        assert r.success
        filepath = r.data["note"]["filepath"]

        fm_delims, h1s = _count_structure(filepath)
        assert fm_delims == 2
        assert h1s == 1
        n = _load_note(filepath)
        assert n.title == "真正的第一段。"
        assert "# 外部文档标题" not in n.content
```

- [ ] **Step 2: Run integration tests to verify pass**

Run: `uv run pytest tests/integration/test_edit_roundtrip.py`
Expected: 2 个用例全部 PASS（修复已在 Task 1–4 落地，此处是验收不是红绿）

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_edit_roundtrip.py
git commit -m "test(integration): edit/add round-trip structure acceptance for content-file input (#541)"
```

---

### Task 6: 静态检查与回归验证（A8）

**Files:** 无（纯验证任务）

- [ ] **Step 1: ruff**

Run: `uv run ruff check jfox/cli.py tests/unit/test_content_file.py tests/integration/test_edit_roundtrip.py`
Expected: 零告警

- [ ] **Step 2: black**

Run: `uv run black --check jfox/cli.py tests/unit/test_content_file.py tests/integration/test_edit_roundtrip.py`
Expected: 全部 would be left unchanged；若有格式差异，跑 `uv run black` 格式化后 `git add -u && git commit -m "style: black format (#541)"`

- [ ] **Step 3: 目标测试全量回归**

Run: `uv run pytest tests/unit/test_content_file.py tests/integration/test_edit_roundtrip.py`
Expected: 全部 PASS

- [ ] **Step 4: 完整 Fast 套件交 CI**

本地不跑全量（仓库规则：全量/集成 ~50min 不自主运行）。PR 创建后由 GitHub Actions Fast job（`not embedding and not slow`）执行 A8 的完整部分，以 CI 绿为验收证据。

---

## 验收追溯矩阵（spec ID ↔ plan task）

| spec 验收 ID | Plan Task | 备注 |
|---|---|---|
| A1（形态 4 剥 H1） | Task 1 | unit 红绿 |
| A2（纯正文 passthrough） | Task 1 Step 4 | 既有测试保持绿 |
| A3（fm/BOM 不回归） | Task 1 Step 4 | 既有测试保持绿 |
| A4（双 H1 报错） | Task 2 | unit 红绿 |
| A5（stdin 统一） | Task 4 | unit 红绿（改写 #200 时代测试） |
| A6（回灌端到端） | Task 5 | integration |
| A7（add 标题派生，D3） | Task 5 | integration |
| A8（静态+全量） | Task 6 | 本地静态+目标回归；完整 Fast 以 CI 绿为准 |
| A9（剥后为空报错） | Task 3 | unit 红绿 |
| U1（真实 KB 冒烟） | 无（post-merge 用户实测） | 合并后由用户执行，结果记录在 issue 评论 |

决策映射：D0（格式不变）无任务；D1→Task 4；D2→Task 2；D3→Task 5；D4→Task 3。

## Self-Review 记录

- Spec 覆盖：形态 1–8 中，1/2/3/5 为不变项由 A2/A3 既有测试锁定（Task 1 Step 4 回归），4→Task 1，6→Task 2，7→Task 4，8→Task 3；非目标逐项无任务（符合）；决策 D0–D4 全部有归属或显式无任务。无遗漏。
- Placeholder 扫描：无 TBD/TODO；每个代码步骤含完整可运行代码。
- 类型/命名一致性：`_strip_leading_h1(body: str) -> str`、`_strip_frontmatter(raw: str) -> str`、`_read_content_file(content_file: str) -> str` 全计划一致；测试类名 TestStripLeadingH1 / TestStripFrontmatterH1Only / TestStripFrontmatterDoubleH1 / TestStripFrontmatterEmpty 与 `-k` 过滤词一致。
