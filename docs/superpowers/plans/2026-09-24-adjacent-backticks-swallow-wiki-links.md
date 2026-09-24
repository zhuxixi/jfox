# Issue #548：相邻空反引号对吞 wiki link 修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 把 `_strip_wiki_link_exclusions` 的三次顺序 `re.sub` 改为单次遍历合并正则，修复「反引号包 HTML 注释」塌缩出相邻空反引号对、吞掉后续 wiki link 的 bug（issue #548）。

**Architecture:** 纯函数内部实现替换（签名不变），模块级预编译 `_EXCLUSION_RE`，alternation 顺序 fenced > HTML 注释 > inline code 即优先级。三个调用方（`resolve_wiki_links` / `find_notes_referencing_title` / `note.py` 链接提取）自动受益，无需改动。spec 见 `docs/superpowers/specs/2026-09-24-adjacent-backticks-swallow-wiki-links-design.md`。

**Tech Stack:** Python 3.10+，`re`（标准库），pytest。

## Global Constraints

- Work from: `/home/elling/git-repo/github/jfox/.pi/worktrees/issue-548-adjacent-backticks-swallow-wiki-links`（所有路径以它为根；禁止碰主 checkout 的 main）
- 注释用中文；commit message 用英文 Conventional Commits（`fix:`/`test:`/`docs:`）
- 验收矩阵（spec）：A1/A2=unit，A3=integration，U1=用户实测（post-merge）
- 测试命名避开子串 `search`/`semantic`/`embedding`/`vector`/`query`/`suggest`（conftest collection 过滤会整组 deselect）
- 测试生成笔记标题须全局唯一（#483 防重闸门）：本 plan 所有标题带 `548` 前缀
- 范围纪律：不碰 #458（`_normalize_wiki_link_title`）、#470（edit 去重）、`redirect.py`、`graph.py`
- 改完跑 `uv run ruff check jfox/note_index.py tests/` 与 `uv run black --check jfox/note_index.py tests/unit/test_wiki_link_resolution.py tests/integration/test_backlinks.py`
- `git add` 按文件 stage，禁止 `git add -A`

---

### Task 1: 合并正则修复 + unit 回归用例①–⑥（A1/A2）

**Files:**
- Modify: `jfox/note_index.py`（`_WIKI_LINK_RE` 定义之后加 `_EXCLUSION_RE`；替换 `_strip_wiki_link_exclusions` 函数体，约 42–53 行）
- Test: `tests/unit/test_wiki_link_resolution.py`（`TestStripWikiLinkExclusions` 类追加 6 个用例）

**Interfaces:**
- Consumes: 无（首任务）
- Produces: `_strip_wiki_link_exclusions(text: str) -> str`（签名不变，行为修复）；模块级 `_EXCLUSION_RE`。Task 2 的集成测试经 CLI 间接消费此行为。

- [ ] **Step 1: 写失败测试（用例①–⑥）**

在 `tests/unit/test_wiki_link_resolution.py` 的 `TestStripWikiLinkExclusions` 类内、`test_plain_text_untouched` 之后追加：

```python
    # ---- #548 回归：反引号包 HTML 注释塌缩成相邻空反引号对 ----

    def test_backtick_wrapped_html_comment_keeps_following_wiki_link(self):
        """①/A1：反引号包注释删除后空反引号对不吞后续 wiki link"""
        text = "页首标记 `<!-- print p.X -->` 说明\n\n见 [[笔记A]] 和 `code`"
        out = _strip_wiki_link_exclusions(text)
        assert "[[笔记A]]" in out

    def test_double_backtick_comment_pair_bracketing_wiki_link(self):
        """③/A1：两个「反引号包注释」夹住的链接存活（双塌缩形态）"""
        text = "`<!-- a -->` [[笔记A]] `<!-- b -->`"
        out = _strip_wiki_link_exclusions(text)
        assert "[[笔记A]]" in out

    def test_backtick_comment_without_trailing_backtick(self):
        """②/A2 对照：触发形态但后文无更多反引号（修复前后均正确，防过修）"""
        text = "页首标记 `<!-- print p.X -->` 见 [[笔记A]]"
        out = _strip_wiki_link_exclusions(text)
        assert "[[笔记A]]" in out

    def test_fenced_block_with_comment_inside_priority_unchanged(self):
        """④/A2 对照：fenced 优先级不变——块内链接不提取、块外存活"""
        text = "```\n<!-- c --> [[不应解析]]\n```\n\n见 [[笔记A]]"
        out = _strip_wiki_link_exclusions(text)
        assert "[[不应解析]]" not in out
        assert "[[笔记A]]" in out

    def test_inline_code_link_still_not_extracted(self):
        """⑤/A2 对照：inline code 内的链接仍不提取"""
        text = "见 `[[不应解析]]` 和 [[笔记A]]"
        out = _strip_wiki_link_exclusions(text)
        assert "[[不应解析]]" not in out
        assert "[[笔记A]]" in out

    def test_html_comment_containing_backticks_removed_whole(self):
        """⑥/A2 对照：注释内含反引号——注释整体剔除、注释外链接存活"""
        text = "<!-- `code` --> 见 [[笔记A]]"
        out = _strip_wiki_link_exclusions(text)
        assert "`code`" not in out
        assert "[[笔记A]]" in out
```

- [ ] **Step 2: 跑测试确认按预期失败**

Run: `uv run pytest tests/unit/test_wiki_link_resolution.py -k "backtick or fenced_block_with_comment or inline_code_link or html_comment_containing" -v`
Expected: **仅 ① `test_backtick_wrapped_html_comment_keeps_following_wiki_link` 与 ③ `test_double_backtick_comment_pair_bracketing_wiki_link` FAIL**（断言 `[[笔记A]]` 不在输出），②④⑤⑥ PASS。若失败面大于此，先停下核对环境。

- [ ] **Step 3: 实现——合并正则**

3a. 在 `jfox/note_index.py` 模块级 `_WIKI_LINK_RE = re.compile(r"\[\[(.*?)\]\]")` 之后空一行插入：

```python
# 单次遍历剔除：alternation 顺序即优先级（fenced > HTML 注释 > inline code），
# 保证 `<!-- -->` 这类「反引号包注释」在首个反引号处被 inline 分支原子吃掉，
# 不产生相邻空反引号对。禁止拆回多次顺序 re.sub——顺序剔除会让已删除区域
# 造出新结构（#548：注释删除→空反引号对→inline 跨界吞链接）。
_EXCLUSION_RE = re.compile(
    r"```[\s\S]*?```"      # fenced code block
    r"|<!--[\s\S]*?-->"    # HTML 注释
    r"|`[^`]+`",           # inline code（反引号 span）
)
```

3b. 把 `_strip_wiki_link_exclusions` 整个函数（含 docstring 与三行 `re.sub`）替换为：

```python
def _strip_wiki_link_exclusions(text: str) -> str:
    """移除不应参与 wiki-link 匹配的 Markdown 区域（fenced code block、HTML 注释、inline code）。

    单次遍历（见 _EXCLUSION_RE 注释）；轻量级处理，不保证解析所有 Markdown 边界情况。
    """
    return _EXCLUSION_RE.sub("", text)
```

- [ ] **Step 4: 跑测试确认全过**

Run: `uv run pytest tests/unit/test_wiki_link_resolution.py -v`
Expected: 全部 PASS（既有 3 个用例 + 新增 6 个）。

- [ ] **Step 5: lint**

Run: `uv run ruff check jfox/note_index.py tests/unit/test_wiki_link_resolution.py && uv run black --check jfox/note_index.py tests/unit/test_wiki_link_resolution.py`
Expected: 无告警；black 若报格式，跑 `uv run black jfox/note_index.py tests/unit/test_wiki_link_resolution.py` 后复检。

- [ ] **Step 6: Commit**

```bash
git add jfox/note_index.py tests/unit/test_wiki_link_resolution.py
git commit -m "fix(note_index): merge exclusion regexes into single pass to stop adjacent-backtick link loss (#548)"
```

---

### Task 2: 集成用例——add 落库后 links/backlink 不丢（A3）

**Files:**
- Modify: `tests/integration/test_backlinks.py`（文件末尾追加测试类）
- Test: 即本文件

**Interfaces:**
- Consumes: Task 1 修复后的 `_strip_wiki_link_exclusions` 行为（经 `jfox add` → `resolve_wiki_links` 间接消费）；`ZKCLI.add(content, title=, note_type=)`、`ZKCLI.refs(note_id=)`、`ZKCLI._run("show", <id>)`（JSON 输出）。
- Produces: 无（叶子任务）。

- [ ] **Step 1: 写集成测试**

在 `tests/integration/test_backlinks.py` 末尾追加（该文件已有 `pytestmark = [pytest.mark.integration, pytest.mark.slow]` 与 `cli` fixture 用法）：

```python
class TestWikiLinkExclusionOnAdd:
    """#548：反引号包 HTML 注释不吞落库链接（add → backlink/links 全链路）"""

    def test_add_keeps_link_after_backtick_wrapped_html_comment(self, cli):
        """A3：add 含触发内容的笔记后，目标收到 backlink、源笔记 links 含目标 id"""
        # 1. 创建目标笔记
        target = cli.add("Target content", title="548 Target Note", note_type="permanent")
        assert target.success
        target_id = target.data["note"]["id"]

        # 2. 创建源笔记：反引号包 HTML 注释 + 紧随的 wiki link + 后文反引码（触发形态）
        content = (
            "页首标记 `<!-- print p.X -->` 说明\n\n"
            "见 [[548 Target Note]] 和 `code`"
        )
        source = cli.add(content, title="548 Source Note", note_type="permanent")
        assert source.success
        source_id = source.data["note"]["id"]

        # 3. 目标笔记必须收到反向链接（issue 症状：backlinks 缺失）
        refs_result = cli.refs(note_id=target_id)
        assert refs_result.success
        backlink_ids = [link["id"] for link in refs_result.data.get("backward_links", [])]
        assert source_id in backlink_ids, f"backlink 缺失：{backlink_ids}"

        # 4. 源笔记存储的 links 含目标 id（issue 复现口径：show --json 的 links）
        show_result = cli._run("show", source_id)
        assert show_result.success
        assert target_id in (show_result.json or {}).get("links", [])
```

- [ ] **Step 2: 跑集成测试确认通过**

Run: `uv run pytest tests/integration/test_backlinks.py::TestWikiLinkExclusionOnAdd -v`
Expected: PASS。（若在 Task 1 之前先跑本步骤应 FAIL——实现顺序上 Task 1 已合入本 worktree 分支，故直接 PASS；如需复核 bug 形态，可 `git stash` Task 1 的 note_index.py 改动后重跑，应 FAIL。）

- [ ] **Step 3: 全量回归本 issue 触及的测试面**

Run: `uv run pytest tests/unit/test_wiki_link_resolution.py tests/integration/test_backlinks.py -v`
Expected: 全部 PASS。

- [ ] **Step 4: lint**

Run: `uv run ruff check tests/integration/test_backlinks.py && uv run black --check tests/integration/test_backlinks.py`
Expected: 无告警。

- [ ] **Step 5: Commit**

```bash
git add tests/integration/test_backlinks.py
git commit -m "test(backlinks): add #548 regression — link survives backtick-wrapped HTML comment"
```

---

## Post-merge：U1 手动验证（不在本 plan 的代码任务内）

修复合入 main 后，由用户对 issue 中命中的那条笔记执行（spec U1）：

```bash
jfox edit <受影响笔记id> --content-file <该笔记原文件>   # 重存触发 links 重算
jfox show <受影响笔记id> --json | jq '.links | length'   # 应恢复为 3
```

通过标准：links 条数恢复、缺失的那条 backlink 重新出现。完成后在 issue #548 评论核对结果并关闭 issue。

## 验收对账表

| 验收 ID | 承载 | 验证命令 |
|---------|------|----------|
| A1 | Task 1 用例①③ + 实现 | `uv run pytest tests/unit/test_wiki_link_resolution.py -k backtick` |
| A2 | Task 1 用例②④⑤⑥ + 既有用例 | `uv run pytest tests/unit/test_wiki_link_resolution.py` |
| A3 | Task 2 集成用例 | `uv run pytest tests/integration/test_backlinks.py::TestWikiLinkExclusionOnAdd` |
| U1 | Post-merge 手动步骤 | 见上节，用户执行后在 issue 留痕 |
