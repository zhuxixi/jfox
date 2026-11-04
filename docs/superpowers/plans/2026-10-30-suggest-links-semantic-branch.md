# suggest-links 语义分支恒空修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 issue #583——让 `suggest_links` 的语义分支真正返回 cosine 语义结果（此前因 RRF 分数覆盖 + 0.6 阈值恒空），并同步 9 份文档与 CLI help/docstring。

**Architecture:** `jfox/note.py` 一行参数改动 + 新测试文件（全进程内接缝、显式 mock patch、命名避开 conftest 自动标记）+ 9 份 SKILL.md / docstring / help 文案统一澄清两量纲与 0.6 噪声地板。

**Tech Stack:** Python 3.10+ / pytest；markdownlint；grep。

**Spec:** `docs/superpowers/specs/2026-10-30-suggest-links-semantic-branch-design.md`（4 轮交叉复核收敛，sha256 `78f19062…`）

## Global Constraints

- 工作目录：`WT=/home/elling/git-repo/github/jfox/.pi/worktrees/issue-583-suggest-links-semantic-branch`；所有编辑以 `$WT` 开头；git 用 `git -C "$WT"`。
- 只改：`jfox/note.py`、`jfox/cli.py`、9 份 SKILL.md、新建 `tests/unit/test_link_assist_score_scale.py`。不动其他代码、不改 `cfg` 跨库限制、不改关键词分支准入 `threshold * 0.5`。
- **测试命名约束**：文件/函数名避开 `semantic` / `vector` / `embedding` / `search` / `suggest` / `query` / `bulk` / `batch`（conftest 自动标记会把它们排除出 Fast CI）；测试体内显式 `patch.object(embedding_backend, "get_backend", lambda: mock_embedding_backend)`。
- **接缝全进程内**：`temp_kb_registered()` → `use_kb(kb_name)`（先切库再写再查）→ 进程内 `create_note` / `save_note` → 进程内 `suggest_links`。禁止用 `cli_fast` 写入。
- 文档统一五要素：`semantic=cosine` / `keyword=关键词比率（准入 threshold×0.5）` / 两量纲不互通看 `match_type` / `0.6` 是噪声地板非强相关 / 排序优先于绝对分。
- commit message：conventional commits + `（#583）`。

## Canonical 文档统一插入段（A4 锚点来源）

在每个改动文档的「`jfox suggest-links` 命令参考行」或首次讲解其阈值处追加一段（语义一致、可按段落风格微调措辞）：

> `suggest-links` 返回两类分数（`match_type` 字段区分）：`semantic` 是 cosine 语义相似度，`keyword` 是关键词重合率合成分（0.3–0.6）。**两个量纲不可直接比较**，`score` 仅在同类型内可比。cosine 在本库中普遍偏高（无关笔记也可达 0.55–0.68），`0.6` 只能当噪声地板、不等于强相关——应按排序取 top-N 并看 `match_type`，不要只看绝对分。关键词分支的准入线是 `threshold × 0.5`；语义分支的阈值就是 `threshold`。

`cli.py` help/示例与 `note.py` docstring 同步把「语义相似度 + 关键词匹配的混合策略」扩写为上述两量纲说明。

## Task 1: 核心修复 + 测试（A1/A2/A3/A5/A6）

**Files:**

- Modify: `$WT/jfox/note.py`（`suggest_links` 语义分支调用 + docstring）
- Create: `$WT/tests/unit/test_link_assist_score_scale.py`

**Interfaces:**

- Consumes：无
- Produces：`suggest_links` 的 `match_type == "semantic"` 项带真实 cosine 分

- [ ] **Step 1: 核心一行改动**

`jfox/note.py` 的语义分支调用改为：

```python
        semantic_results = search_notes(content, top_k=top_k * 2, mode="semantic")
```

- [ ] **Step 2: docstring 同步**

把 `suggest_links` 的 docstring 中「使用语义相似度 + 关键词匹配的混合策略」改为：

```
    使用语义相似度（cosine，纯 semantic 模式）+ 关键词匹配的混合策略

    分数量纲：`semantic` 为 cosine 相似度（threshold 生效）；`keyword` 为
    关键词重合率合成分（0.3–0.6，准入线为 threshold×0.5）。两量纲不可直接
    比较，按 match_type 区分；cosine 在本库普遍偏高，0.6 为噪声地板非强相关，
    应按排序取 top-N。
```

- [ ] **Step 3: 新建测试文件（A1–A3 + 命名约束注释）**

```python
"""suggest_links 语义分支修复回归（issue #583）。

命名约束（关键）：tests/conftest.py 的 pytest_collection_modifyitems 会按
nodeid 关键词自动加标记——semantic/vector/embedding → embedding+very_slow；
search/suggest/query → slow。本文件与所有测试函数名刻意避开这些词，保证被
`-m "not embedding and not slow"`（CI Fast 口径）收集。改名前先看该文件。

接缝：全进程内。temp_kb_registered + use_kb（先切库重置单例）+ 进程内
create_note/save_note（走已 patch 的 384 维 mock 后端）+ 进程内 suggest_links。
mock 后端返回全正随机向量（cosine≈0.75 无区分度），所以只断言量纲与阈值，
不断言「相近/无关」的排序。
"""

import unittest.mock

import pytest

from jfox import embedding_backend
from jfox.config import use_kb
from jfox.models import NoteType
from jfox.note import create_note, save_note, suggest_links
from utils.temp_kb import temp_kb_registered

CORPUS = [
    ("Python 并发编程", "学习 Python 的 async/await 和多线程编程"),
    ("JavaScript 异步编程", "Promise 和 async/await 在 JS 中的使用"),
    ("机器学习入门", "监督学习和非监督学习的基本概念"),
]


@pytest.fixture
def _indexed_kb(mock_embedding_backend):
    """在 patch 下建临时注册库、切库、写入笔记。"""
    with unittest.mock.patch.object(
        embedding_backend, "get_backend", lambda: mock_embedding_backend
    ):
        with temp_kb_registered() as kb_name:
            with use_kb(kb_name):
                for title, body in CORPUS:
                    note = create_note(
                        content=body, title=title, note_type=NoteType.PERMANENT
                    )
                    assert save_note(note), f"save_note failed for {title}"
                yield kb_name


class TestCosineScale:
    def test_link_scores_use_cosine_scale(self, _indexed_kb):
        """A1：语义分支现在应返回 cosine 量纲（>0.1，RRF 只有 0.016–0.033）。"""
        results = suggest_links("Python 编程", top_k=5, threshold=0.05)
        semantic_items = [r for r in results if r["match_type"] == "semantic"]
        assert semantic_items, "修复后应有 semantic 结果（此前恒为空）"
        for item in semantic_items:
            assert item["score"] > 0.1, f"分数应非 RRF 量级: {item['score']}"
            assert item["score"] <= 1.0

    def test_threshold_filters_semantic_items(self, _indexed_kb):
        """A2：先证低阈值有结果，再证高阈值过滤（防「空集空断言」）。"""
        low = suggest_links("Python 编程", top_k=5, threshold=0.05)
        assert any(r["match_type"] == "semantic" for r in low)

        high = suggest_links("Python 编程", top_k=5, threshold=0.999)
        # 注意：不断言整体为空——keyword 项的准入线是 threshold×0.5，可能仍在
        assert not any(r["match_type"] == "semantic" for r in high)

    def test_missing_embedding_degrades_to_keyword(self, _indexed_kb):
        """A3：embedding 不可用时降级不炸，返回 keyword 或空。"""
        from jfox.embedding_backend import EmbedDependencyMissingError

        with unittest.mock.patch.object(
            embedding_backend,
            "get_backend",
            side_effect=EmbedDependencyMissingError("test: no embed"),
        ):
            results = suggest_links("Python 编程", top_k=5, threshold=0.05)
        assert isinstance(results, list)
        assert not any(r["match_type"] == "semantic" for r in results)
```

- [ ] **Step 4: 单文件直跑（A1–A3）**

Run: `cd "$WT" && uv run pytest tests/unit/test_link_assist_score_scale.py -q`
Expected: 3 passed。若出现 EmbedDependencyMissingError，检查 patch 是否包住整个 fixture（含 save_note）。

- [ ] **Step 5: A6 收集性断言**

Run: `cd "$WT" && uv run pytest tests/ -m "not embedding and not slow" --collect-only -q | grep -c test_link_assist_score_scale`
Expected: ≥3（A1–A3 三个用例都被 Fast 口径收集）

- [ ] **Step 6: 既有行为回归（A5）**

Run: `cd "$WT" && uv run pytest tests/test_suggest_links.py -q`
Expected: 全绿（若旧用例断言 score 量纲与 cosine 不符，按新语义修正断言，不要放宽断言绕过）

- [ ] **Step 7: commit**

```bash
git -C "$WT" add jfox/note.py tests/unit/test_link_assist_score_scale.py
git -C "$WT" commit -m "fix(links): suggest-links 语义分支改用纯 semantic 模式（#583）"
```

## Task 2: 文档与 help 文案同步（A4）

**Files:**

- Modify: `$WT/jfox/cli.py`（suggest-links help/示例）
- Modify: `$WT/jfox/note.py`（docstring，Task 1 已做则跳过重复）
- Modify 9 份 skill：pi/cc/kimi 的 session-to-permanent / organize / promote

- [ ] **Step 1: `jfox/cli.py` help 同步**

把 `suggest_links` 命令 docstring 的「使用语义相似度和关键词匹配混合策略，帮助发现知识间的联系。」改为：

```
    使用 cosine 语义相似度 + 关键词匹配的混合策略，帮助发现知识间的联系。

    返回项的 match_type 区分两类分数：semantic 是 cosine 语义相似度（threshold 生效）；
    keyword 是关键词重合率合成分（0.3–0.6，准入线为 threshold×0.5）。两量纲不可直接比较；
    cosine 在本库普遍偏高，0.6 为噪声地板非强相关，应按排序取 top-N 并看 match_type。
```

- [ ] **Step 2: 9 份 skill 文案统一**

对每份 skill 中 `jfox suggest-links` 的「阈值 ≥0.6 / 相似度」表述，替换为 Canonical 文档统一插入段的语义（不得改变既有阈值数字 0.6）：

| 文件 | 关键位置（原表述） | 修改方向 |
|------|---------------------|----------|
| `skills-recommend/pi/jfox-session-to-permanent/SKILL.md` | `:86-87`「语义找关联…阈值默认 ≥0.6」 | 保留阈值，追加两量纲 + match_type + 0.6 噪声地板说明 |
| `packages/cc-plugin/skills/session-to-permanent/SKILL.md` | 同上（同款段落） | 同上 |
| `packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md` | 同上 | 同上 |
| `skills-recommend/pi/jfox-organize/SKILL.md` | `:62-65`、`:142`、`:152`、`:162` | 「筛选 score ≥0.6」补一句「semantic=cosine；keyword 为准入 threshold×0.5，两量纲看 match_type；0.6 是噪声地板按排序取」 |
| `packages/cc-plugin/skills/organize/SKILL.md` | 同上 | 同上 |
| `packages/kimi-plugin/skills/jfox-organize/SKILL.md` | 同上 | 同上 |
| `skills-recommend/pi/jfox-promote/SKILL.md` | `:161`、`:215`、`:235` | 「阈值可放宽到 0.4–0.5」改为「keyword 项可放宽到 0.4–0.5；cosine 项低于 0.6 多为噪声，按排序取并看 match_type」；§6 已知坑补「语义分支已修（#583）」 |
| `packages/cc-plugin/skills/promote/SKILL.md` | `:155`、`:209`、`:229` | 同上 |
| `packages/kimi-plugin/skills/jfox-promote/SKILL.md` | `:178`、`:232`、`:252`、`:290-291` | 同上 |

注意：promote 里的 `cosine ≥0.95 / 0.88–0.95`（模式1 dedup 扫描）与 suggest-links 无关，**不要动**。

- [ ] **Step 3: A4 静态锚点验证**

```bash
cd "$WT"
for f in skills-recommend/pi/jfox-session-to-permanent/SKILL.md packages/cc-plugin/skills/session-to-permanent/SKILL.md packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md skills-recommend/pi/jfox-organize/SKILL.md packages/cc-plugin/skills/organize/SKILL.md packages/kimi-plugin/skills/jfox-organize/SKILL.md skills-recommend/pi/jfox-promote/SKILL.md packages/cc-plugin/skills/promote/SKILL.md packages/kimi-plugin/skills/jfox-promote/SKILL.md; do
  c1=$(grep -c "cosine" "$f"); c2=$(grep -c "match_type" "$f")
  echo "$f cosine=$c1 match_type=$c2"
done
grep -c "match_type" jfox/cli.py
grep -cE "量纲|match_type" jfox/note.py
```

Expected: 每个 md 的 cosine≥1 且 match_type≥1；cli.py match_type≥1；note.py ≥1

- [ ] **Step 4: markdownlint**

Run: `cd "$WT" && npx --yes markdownlint-cli2 <上述 9 个 md>`
Expected: 0 issues

- [ ] **Step 5: commit**

```bash
git -C "$WT" add <9 个 skill> jfox/cli.py
git -C "$WT" commit -m "docs(links): 统一 suggest-links 两量纲与 0.6 噪声地板表述（#583）"
```

## Task 3: 全量验证汇总（A1–A6 证据）

**Files:** 无新增

- [ ] **Step 1: A1–A3 单文件直跑**

Run: `cd "$WT" && uv run pytest tests/unit/test_link_assist_score_scale.py -q`
Expected: 3 passed

- [ ] **Step 2: A5 CI Fast 全量**

Run: `cd "$WT" && uv run pytest tests/ -m "not embedding and not slow" -q`
Expected: 全绿（基线 1911+）

- [ ] **Step 3: A6 收集性断言**

Run: `cd "$WT" && uv run pytest tests/ -m "not embedding and not slow" --collect-only -q | grep -c test_link_assist_score_scale`
Expected: ≥3

- [ ] **Step 4: A4 锚点复核 + lint**

按 Task 2 Step 3/4 的命令复跑，记录输出原文。
Expected: 锚点全部命中、lint 0 issues

- [ ] **Step 5: 证据落盘**

把以上命令与输出原文写入执行报告（供 PR 描述与 issue 评论使用）。

---

## 自检记录（Self-Review）

- Spec 覆盖：核心修复→Task 1（A1/A2/A3/A5/A6）；文档同步→Task 2（A4）；汇总→Task 3。无遗漏。
- 占位符扫描：无 TBD；测试与文案为成稿。
- 一致性：`match_type` / `cosine` / `threshold×0.5` / 0.6 噪声地板在代码、测试、文档间口径一致。
- 已知限制（不改）：`cfg` 跨库语义（语义分支忽略 cfg）；keyword 分支准入 `threshold×0.5`；promote 模式1 的 0.88/0.95 dedup 阈值（与 suggest-links 无关）。
