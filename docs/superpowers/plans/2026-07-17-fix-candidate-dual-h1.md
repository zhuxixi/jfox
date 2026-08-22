# 修复 candidate 笔记双 H1 标题（#320）实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** gem-synth candidate 笔记落盘前剥掉 content 开头冗余 H1，消除「to_markdown 前置 `# title` + LLM content 自带 `# 标题`」导致的双 H1（#320）。

**Architecture:** 在 `jfox/gem_synth/synthesizer.py` 新增模块级纯函数 `_strip_leading_h1(content)`，剥掉 content 开头首个冗余 H1（正则 `\A\s*# .+\n*`，比 `Note.from_markdown` 故意放宽以兜底 LLM 退化输出，非严格对称）。`synthesize_anchor` 入口调用一次，`dedup_check` / `_save_candidate_note` / `upsert_dedup` 三处共用同一份 strip 后 content；`_save_candidate_note` 另保留幂等自守 strip。**不动 `to_markdown`**（所有笔记类型共用）。CR 驱动的演进（dedup 口径、正则放宽、空 content mark_failed 等）见文末「实现演进记录」，**以其 + 代码为准**（Task 1-3 描述保留作初始设计历史快照）。

**Tech Stack:** Python ≥ 3.10，pytest，Typer。无新依赖。

## Global Constraints

- **main 受保护**：所有改动在新分支 `fix/gem-synth-candidate-dual-h1`，commit 前用 `git branch --show-current` 守卫（防本机并发 session 串台，见 memory `concurrent-git-branch-hijack`）。本 session 按 in-place 配置工作，不开 worktree。
- **行宽 100**（black + ruff，`pyproject.toml` 配置）。提交前 `ruff check` 与 `black --check` 都要过（没装 black 用 `uv run --with black==26.3.1 black --check`，见 memory `run-black-not-just-ruff`）。
- **注释中文**。
- **范围严格**：只修「入口」（新 candidate 落盘）。存量 208 个带病 candidate 的 backfill、正文内多 H1 分节规范化，均属 #319，**本 PR 不做**（YAGNI + issue 原文边界）。
- **不碰**：`models.py` 的 `to_markdown` / `from_markdown`（降低回归风险）。
- **不碰**：`llm.py` 的 SYSTEM_PROMPT（方案 2「改 prompt 禁 H1」为可选增强，LLM 不可控、strip 兜底仍必须；本 PR 不扩）。
- 测试只跑**快速 unit**（单文件，几秒），可自主跑。**不跑**全量/集成/embedding 测试（CLAUDE.md 规定，交给用户）。

## File Structure

- **Modify:** `jfox/gem_synth/synthesizer.py`
  - 新增模块级常量 `_LEADING_H1_RE`（编译正则）
  - 新增模块级纯函数 `_strip_leading_h1(content: str) -> str`（与现有 `_safe_float`/`_coerce_grounded_by` 同风格，位置紧随其后）
  - `_save_candidate_note` 第 58 行后插入一行 `content = _strip_leading_h1(content)`
- **Test:** `tests/unit/test_gem_synth_synthesizer.py`（追加，沿用现有 `from unittest.mock import MagicMock, patch` 与无-KB 纯函数测试风格）

---

## Task 1: `_strip_leading_h1` 纯函数（TDD）

**Files:**

- Modify: `jfox/gem_synth/synthesizer.py`（在 `_coerce_grounded_by` 之后、`_save_candidate_note` 之前插入常量 + 函数）
- Test: `tests/unit/test_gem_synth_synthesizer.py`（追加测试）

**Interfaces:**

- Produces: `_strip_leading_h1(content: str) -> str` —— 剥掉入参开头首个冗余 H1 行（含前导空白、紧随换行）；剥后若为空则回退原值（防空正文）。Task 2 的 `_save_candidate_note` 依赖此函数名。

- [ ] **Step 1: 写失败测试**

追加到 `tests/unit/test_gem_synth_synthesizer.py` 末尾：

```python
def test_strip_leading_h1_strips_title_duplicate():
    """content 以冗余 H1 开头（title 已在 frontmatter）→ 剥掉，剩正文"""
    from jfox.gem_synth.synthesizer import _strip_leading_h1

    assert _strip_leading_h1("# 标题\n\n正文") == "正文"
    assert _strip_leading_h1("# 标题\n正文") == "正文"  # H1 后无空行
    assert _strip_leading_h1("\n\n# 标题\n\n正文") == "正文"  # 前导空白行


def test_strip_leading_h1_noop_without_h1():
    """content 不以 H1 开头 → 原样返回"""
    from jfox.gem_synth.synthesizer import _strip_leading_h1

    assert _strip_leading_h1("正文无 H1") == "正文无 H1"
    assert _strip_leading_h1("## 二级标题\n正文") == "## 二级标题\n正文"  # H2 不动
    assert _strip_leading_h1("") == ""


def test_strip_leading_h1_protects_all_h1_only():
    """content 仅一个 H1、剥后会空 → 回退原值，避免产出空正文"""
    from jfox.gem_synth.synthesizer import _strip_leading_h1

    assert _strip_leading_h1("# 只有一个标题\n") == "# 只有一个标题\n"
    assert _strip_leading_h1("# 只有一个标题") == "# 只有一个标题"  # 无尾换行：正则本就不匹配


def test_strip_leading_h1_only_first_leading():
    """只剥开头首个 H1；正文内后续 H1（3+H1 场景）保留——后者归 #319"""
    from jfox.gem_synth.synthesizer import _strip_leading_h1

    assert _strip_leading_h1("# A\n\n# B\n正文") == "# B\n正文"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_gem_synth_synthesizer.py -k strip_leading_h1 -v`
Expected: FAIL —— `ImportError: cannot import name '_strip_leading_h1'`

- [ ] **Step 3: 实现纯函数**

在 `jfox/gem_synth/synthesizer.py` 的 `import` 区补 `import re`（若尚未引入；当前文件无 `re`），并在 `_coerce_grounded_by` 函数之后、`_save_candidate_note` 之前插入：

```python
# content 开头冗余 H1 的正则：串首 \A + 可能有前导空白行 + `# 文本` + 紧随换行（含空行）
# 复用 Note.from_markdown（models.py:179 `re.sub(r"^# .+\n+", ..., count=1)`）剥首个
# H1 的语义，保持合成写入与解析读写的对称。
_LEADING_H1_RE = re.compile(r"\A\s*# .+\n+")


def _strip_leading_h1(content: str) -> str:
    """剥掉 content 开头首个冗余 H1 行，消除 candidate 双 H1（#320）。

    title 已单独存 frontmatter、to_markdown 会前置 `# title`，故 LLM content 若以
    `# 标题` 开头即为冗余（双 H1 根因）。仅剥**首个** leading H1；正文内的 H1 分节
    （3+H1 场景，LLM 误用 H1 当分节）超出 #320 范围、留给 #319。

    保护：剥后若 content 为空（整段只是一个 H1），回退原值，避免产出空正文笔记。
    """
    stripped = _LEADING_H1_RE.sub("", content, count=1)
    return stripped if stripped.strip() else content
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_gem_synth_synthesizer.py -k strip_leading_h1 -v`
Expected: PASS（4 个测试全绿）

- [ ] **Step 5: lint**

Run: `uv run ruff check jfox/gem_synth/synthesizer.py && uv run --with black==26.3.1 black --check jfox/gem_synth/synthesizer.py`
Expected: 两步均无报错

- [ ] **Step 6: commit**

```bash
git branch --show-current  # 守卫：确认在 fix/gem-synth-candidate-dual-h1，非 main
git add jfox/gem_synth/synthesizer.py tests/unit/test_gem_synth_synthesizer.py
git commit -m "fix(gem-synth): 新增 _strip_leading_h1，剥 candidate content 开头冗余 H1 (#320)

纯函数 + 单测；下个 task 接入 _save_candidate_note。"
```

---

## Task 2: 接入 `_save_candidate_note` + 集成测试（TDD）

**Files:**

- Modify: `jfox/gem_synth/synthesizer.py:58`（`_save_candidate_note` 内，取 content 之后接入 strip）
- Test: `tests/unit/test_gem_synth_synthesizer.py`（追加集成测试）

**Interfaces:**

- Consumes: Task 1 的 `_strip_leading_h1`
- Produces: candidate 笔记落盘时 `Note.content` 不含开头冗余 H1（`to_markdown` 只产出一个 `# title`）

- [ ] **Step 1: 写失败测试**

追加到 `tests/unit/test_gem_synth_synthesizer.py` 末尾：

```python
def test_save_candidate_note_strips_leading_h1_from_content():
    """_save_candidate_note 把 LLM content 开头冗余 H1 剥掉，避免 to_markdown 双 H1。

    mock _persist_note 捕获 Note 对象，断言其 content 不以 H1 开头
    （title 已在 frontmatter，to_markdown 会前置 # title）。
    """
    from jfox.gem_synth.synthesizer import _save_candidate_note

    llm_result = {
        "title": "Vocable 客户端优先架构",
        "content": "# Vocable 架构取向：本地打包词库\n\n正文：规避服务器查询成本",
        "confidence": 0.7,
        "knowledge_type": "factual",
        "grounded_by": [],
    }
    anchor = {"fragment_id": 7, "session_id": "s1", "timestamp": "2026-07-17 00:00:00"}
    captured = {}

    def fake_persist(note):
        captured["note"] = note

    with patch("jfox.gem_synth.synthesizer._persist_note", side_effect=fake_persist):
        note_id = _save_candidate_note(llm_result, anchor)

    assert note_id is not None
    # content 开头不再是 H1（被 strip），正文保留
    assert not captured["note"].content.lstrip().startswith("# ")
    assert "规避服务器查询成本" in captured["note"].content
    # title 仍来自 frontmatter 字段，未被破坏
    assert captured["note"].title == "Vocable 客户端优先架构"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_gem_synth_synthesizer.py::test_save_candidate_note_strips_leading_h1_from_content -v`
Expected: FAIL —— `AssertionError: assert True is False`（content 仍以 `#` 开头，strip 尚未接入）

- [ ] **Step 3: 接入 strip（一行）**

在 `jfox/gem_synth/synthesizer.py` 的 `_save_candidate_note` 内，把：

```python
        title = llm_result.get("title") or "未命名候选宝石"
        content = llm_result.get("content") or ""
```

改为：

```python
        title = llm_result.get("title") or "未命名候选宝石"
        # 剥掉 LLM content 开头冗余 H1（title 已在 frontmatter、to_markdown 会前置），
        # 消除 candidate 双 H1（#320）。dedup 仍用 synthesize_anchor 里的原始 content，
        # 不受影响。
        content = _strip_leading_h1(llm_result.get("content") or "")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_gem_synth_synthesizer.py::test_save_candidate_note_strips_leading_h1_from_content -v`
Expected: PASS

- [ ] **Step 5: lint**

Run: `uv run ruff check jfox/gem_synth/synthesizer.py && uv run --with black==26.3.1 black --check jfox/gem_synth/synthesizer.py`
Expected: 两步均无报错

- [ ] **Step 6: commit**

```bash
git branch --show-current
git add jfox/gem_synth/synthesizer.py tests/unit/test_gem_synth_synthesizer.py
git commit -m "fix(gem-synth): _save_candidate_note 接入 strip，消除 candidate 双 H1 (#320)"
```

---

## Task 3: 回归 + 验证 dedup 未受影响

**Files:** 无修改，仅验证。

**Why:** 确认 strip 只作用于 `_save_candidate_note` 局部，未污染 `synthesize_anchor` 里 dedup_check/upsert_dedup 使用的原始 content；且 synthesizer 既有编排测试无回归。

- [ ] **Step 1: 跑 synthesizer 全部单测（快速，无 embedding）**

Run: `uv run pytest tests/unit/test_gem_synth_synthesizer.py tests/unit/test_synthesizer_dedup.py -v`
Expected: 全 PASS（含既有 `test_synthesize_anchor_produces_candidate_note` 等 + 新增 strip 测试）

- [ ] **Step 2: 静态确认 dedup 路径用原始 content（人工核对，无需跑）**

确认 `synthesize_anchor`（synthesizer.py:153-176）的 dedup_check / upsert_dedup 仍直接用 `llm_result.get("content")`，**不经过** `_strip_leading_h1`：

```bash
grep -n 'llm_result.get("content")\|_strip_leading_h1' jfox/gem_synth/synthesizer.py
```

Expected: 看到 3 处 `llm_result.get("content")`（dedup_check / upsert_dedup / _save_candidate_note 内部经 strip）+ 1 处 `_strip_leading_h1` 调用。dedup 两处不经 strip = 隔离正确。

- [ ] **Step 3: 最终 lint 全量**

Run: `uv run ruff check jfox/ && uv run --with black==26.3.1 black --check jfox/`
Expected: 无报错

- [ ] **Step 4:（无代码改动则跳过 commit；本 task 纯验证）**

---

## Self-Review（写计划后自检）

1. **Spec 覆盖**：issue 要求「方案 1：strip content 开头 `#` 行，不动 to_markdown」→ Task 1（纯函数）+ Task 2（接入）覆盖；「存量归 #319」→ Global Constraints 明确不做 backfill，边界对齐。✅
2. **占位符扫描**：所有 step 含完整代码/命令/expected，无 TBD。✅
3. **类型一致**：Task 1 定义 `_strip_leading_h1(content: str) -> str`，Task 2 接入调用同名同签名；`_LEADING_H1_RE` 仅 Task 1 定义一次。✅
4. **回归面**：dedup 用原始 content 的隔离由 Task 3 Step 2 显式验证；既有编排测试 mock 了 `_save_candidate_note` 故不受 Task 2 内部改动影响（Task 3 Step 1 再确认）。✅

---

## 实现演进记录（Zima 双 Bot CR 反馈驱动，覆盖上方初始设计）

初始计划（上方 Task 1-3）在 CR 迭代中如下调整。**以代码 + 本记录为准**，Task 描述保留作历史快照：

- **正则 `\n+` → `\n*`**（kimi R1 + cc R3-issue5）：覆盖无尾随换行的退化 H1。模块级注释 + docstring 已明确「比 `from_markdown` 故意放宽、非严格对称」（合成侧兜底 LLM 退化输出 vs 解析侧只处理规范文件）。
- **dedup 策略：原始 content → strip 后 content**（cc R1）：`synthesize_anchor` 入口统一 strip，`dedup_check` / `_save_candidate_note` / `upsert_dedup` 三处共用。**推翻 Task 3 Step 2「dedup 用原始 content」的隔离假设**——原假设致 dedup/save 口径不一致、短正文近重复漏检。**跨版本 tradeoff**（存量 dedup embedding 基于原始 content）归 #319 `dedup-backfill` 重灌，不在本 PR（cc R3-issue4 acknowledged）。
- **`_strip_leading_h1` 移除回退**（kimi R1）：content 仅 H1 时返回空串（不会产出空笔记，`_save_candidate_note` 追加章节）。
- **空 content → mark_failed**（kimi R2）：入口 strip 后 content 为空（LLM 退化）则 `mark_failed('empty content after h1 strip')`，不落盘无知识 candidate。
- **`_save_candidate_note` 自守 strip**（cc R2-issue2）：恢复内部 `_strip_leading_h1`（幂等，独立调用也安全）。
- **不改 `llm_result` dict**（cc R2-issue3）：`synthesize_anchor` 用局部 `content` 变量，避免 LLM 层缓存/复用结果对象的副作用。
