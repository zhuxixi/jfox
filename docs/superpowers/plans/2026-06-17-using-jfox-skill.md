# using-jfox 总览/路由 skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a single `using-jfox` overview/routing skill to the cc-plugin that owns meta-intent ("jfox 能做什么 / 我该用哪个 skill"), routes to the five existing capability skills, and does not compete with them for triggering.

**Architecture:** One new auto-discovered Markdown skill at `packages/cc-plugin/skills/using-jfox/SKILL.md` (no `plugin.json` change — cc-plugin auto-discovers `skills/*`). A small pytest contract test guards the design invariants from issue #243: valid frontmatter, the description carries only meta triggers and **no** competing action verbs, and the body's pointers into `manage`/`organize` resolve to real sections. Nothing else is modified (方案 1 / pure-additive).

**Tech Stack:** Claude Code plugin skill (Markdown + YAML frontmatter), pytest (contract test, no KB/fixtures).

**Spec:** `docs/superpowers/specs/2026-06-17-using-jfox-skill-design.md`

**Work context:** Work in the isolated worktree `/home/elling/workspace/proj/github-personal/jfox-wt-243` on branch `feat/issue-243-using-jfox-skill` (based off `main`, independent of the in-flight `feat/kimi-auto-summary-242` branch). All paths below are relative to that worktree root.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `packages/cc-plugin/skills/using-jfox/SKILL.md` | **Create** | The skill itself: frontmatter (meta-only description) + body (what jfox is, capability-map decision table, note-model pointer, ≥2 composite workflows, conventions pointer, env check, self-boundary). |
| `tests/unit/test_using_jfox_skill.py` | **Create** | Contract test: asserts the skill exists, frontmatter is valid, description has no competing verbs + has meta triggers, and body pointers resolve. |

**No other files are touched.** In particular: `packages/cc-plugin/.claude-plugin/plugin.json` is NOT modified (auto-discovery), and none of the five existing skills (`search`/`ingest`/`manage`/`organize`/`session-summary`) are edited (方案 1).

---

## Task 1: Create the skill with its contract test (TDD red → green)

**Files:**
- Create: `tests/unit/test_using_jfox_skill.py`
- Create: `packages/cc-plugin/skills/using-jfox/SKILL.md`

- [ ] **Step 1: Write the failing contract test**

Create `tests/unit/test_using_jfox_skill.py`:

```python
"""
测试类型: 单元测试
目标: cc-plugin using-jfox 总览/路由 skill 的设计契约（issue #243）
预估耗时: < 1 秒
依赖要求: 无外部依赖（纯文件读取，不需要知识库 / fixture）

守护的设计不变量（见 docs/superpowers/specs/2026-06-17-using-jfox-skill-design.md）：
  1. skill 文件存在，frontmatter 合法（name=using-jfox，description 非空）
  2. description 只含元意图触发词，不含与 5 个能力型 skill 竞争的强动词
  3. body 中指向 manage / organize 的指针锚点确实存在
"""

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]  # tests/unit/x.py -> repo root
SKILL_DIR = REPO_ROOT / "packages" / "cc-plugin" / "skills"
USING_JFOX = SKILL_DIR / "using-jfox" / "SKILL.md"


def _frontmatter(path: Path) -> str:
    """Return the raw YAML frontmatter block (text between the --- fences)."""
    text = path.read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---", text, re.DOTALL)
    assert m, f"{path} has no YAML frontmatter"
    return m.group(1)


def test_skill_file_exists():
    assert USING_JFOX.is_file(), f"expected skill at {USING_JFOX}"


def test_frontmatter_name():
    assert re.search(r"^name:\s*using-jfox\s*$", _frontmatter(USING_JFOX), re.MULTILINE)


def test_frontmatter_has_description():
    assert "description:" in _frontmatter(USING_JFOX)


# 设计核心（#243）：description 绝不能携带 5 个能力型 skill 拥有的强动词，
# 否则会在 auto-discovery 路由时与它们竞争同一个意图。
@pytest.mark.parametrize(
    "verb",
    ["搜索", "导入", "整理", "保存会话", "创建知识库", "管理知识库"],
)
def test_description_has_no_competing_verbs(verb):
    assert verb not in _frontmatter(USING_JFOX), (
        f"competing verb {verb!r} must not appear in using-jfox frontmatter "
        f"(see spec Section 2 / issue #243)"
    )


@pytest.mark.parametrize("trigger", ["能做什么", "overview", "入门"])
def test_description_carries_meta_triggers(trigger):
    assert trigger in _frontmatter(USING_JFOX), (
        f"description should carry meta trigger {trigger!r}"
    )


def test_pointers_resolve():
    """body 指向 manage / organize 的锚点必须真实存在，避免路由到缺失章节。"""
    assert USING_JFOX.is_file()
    checks = [
        (SKILL_DIR / "manage" / "SKILL.md", "共享约定"),     # §4.1
        (SKILL_DIR / "manage" / "SKILL.md", "知识库路径"),   # §2
        (SKILL_DIR / "manage" / "SKILL.md", "健康检查"),     # §5
        (SKILL_DIR / "organize" / "SKILL.md", "Inbox"),      # Step 1
        (SKILL_DIR / "organize" / "SKILL.md", "提炼"),       # Step 2
    ]
    missing = [
        (str(p), anchor)
        for p, anchor in checks
        if anchor not in p.read_text(encoding="utf-8")
    ]
    assert not missing, f"pointers point at missing sections: {missing}"
```

- [ ] **Step 2: Run the test to verify it fails (red)**

Run: `pytest tests/unit/test_using_jfox_skill.py -v`
Expected: FAIL — `test_skill_file_exists` fails because `packages/cc-plugin/skills/using-jfox/SKILL.md` does not exist yet (and the pointer test is skipped behind that assertion, but the existence/name/verb tests will error on the missing file).

- [ ] **Step 3: Write the skill (minimal implementation that satisfies the contract)**

Create `packages/cc-plugin/skills/using-jfox/SKILL.md`:

````markdown
---
name: using-jfox
description: |
  Use when the user asks meta or overview questions about jfox as a whole — what jfox
  can do, how to get started, or which jfox skill/command fits their goal. Triggers on
  "jfox 能做什么", "jfox 怎么用", "知识库怎么用", "我该用哪个 jfox 命令", "我该用哪个
  jfox skill", "jfox 有哪些功能", "jfox 入门", "jfox overview", "what can jfox do",
  "which jfox skill". This skill orients the user and routes to the specific skill; it
  is not for performing a concrete action.
---

# JFox 总览与路由

JFox 是一个本地优先的 Zettelkasten 知识管理 CLI：混合搜索（BM25 + 语义）、知识图谱、多知识库，并提供 Claude Code / Kimi Code 插件集成。

本 skill **只做总览与路由**：帮你判断「该用哪个 skill」，然后把具体动作派发出去。它不自己执行搜索 / 导入 / 整理 / 保存会话 / 管理这些动作。

## 环境检查

确认 jfox 已安装：

```bash
jfox --version
```

未安装时：

```bash
uv tool install jfox-cli
```

## 我该用哪个 skill

| 你想做的 | 用这个 skill | 典型触发词 |
|---------|-------------|-----------|
| 搜索 / 查找笔记、检索知识 | `search` | 搜索 / 查找 / find |
| 把 git 仓库 / PR / issues 导入成素材 | `ingest` | 导入仓库 / ingest repo |
| 提炼 fleeting→permanent、清理 inbox、补 wiki link、优化图谱 | `organize` | 整理 / 提炼 / clean inbox |
| 把当前会话总结存入知识库 | `session-summary` | 保存会话 / save session |
| 创建 / 切换 / 删除知识库、命令参考、健康检查、daemon | `manage` | 创建知识库 / kb status / 健康检查 |

5 个 skill 一句话职责：

- **search** — 笔记检索：BM25 / 语义 / 混合搜索 + 知识图谱查询。
- **ingest** — git 仓库 → fleeting 素材笔记（git log / PR / issues）。
- **organize** — fleeting → permanent 提炼 + 图谱优化（orphans / 补链）。
- **session-summary** — 当前会话 → 知识库笔记。
- **manage** — 知识库生命周期 + 笔记 CRUD 权威参考 + 健康检查 + embedding daemon。

## 笔记模型（一句话）

JFox 笔记分 fleeting / literature / permanent 三类，靠 `[[wiki link]]` 互链。完整的模型与提炼流程见 **organize** skill（Step 1 收件箱分析、Step 2 提炼）。

## 典型复合工作流

1. **沉淀新知识**：`ingest`（导入素材为 fleeting）→ `organize`（提炼成 permanent + 补 `[[wiki link]]`）→ `search`（日后检索复用）。
2. **会话沉淀**：`session-summary`（把这次对话存入知识库）→ `organize`（提炼要点为 permanent）。
3. **知识库维护**：`manage`（§5 体检 / 衰减信号检测）→ `organize`（清理 orphans / 补链接）。

## 公共约定（一句话）

所有 jfox 命令支持 `--kb <name>` 指定知识库、`--json` / `--format json` 输出 JSON、`--content-file <path>` 从文件读取长内容。完整约定见 **manage** skill §4.1。

## 本 skill 不做

- 不执行具体动作（搜索 / 导入 / 整理 / 保存会话 / 管理）——交给对应 skill。
- 不重复各 skill 的命令速查——命令在各 skill 内有权威版本。
````

- [ ] **Step 4: Run the test to verify it passes (green)**

Run: `pytest tests/unit/test_using_jfox_skill.py -v`
Expected: PASS — all 12 test cases green (existence, name, has-description, 6× no-competing-verbs, 3× meta-triggers, pointers-resolve).

- [ ] **Step 5: Commit**

```bash
git add packages/cc-plugin/skills/using-jfox/SKILL.md tests/unit/test_using_jfox_skill.py
git commit -m "feat(cc-plugin): add using-jfox overview/routing skill (#243)

新增 using-jfox skill 承接元意图（jfox 能做什么 / 我该用哪个 skill），
路由到现有 5 个能力型 skill。description 只用元词、不含强动词，避免触发竞争。
附 unit 契约测试守护：frontmatter 合法、无竞争动词、指针锚点可解析。

方案 1（纯加法），不改 plugin.json，不编辑现有 5 个 skill。"
```

---

## Task 2: Final verification gate

**Files:** none modified (verification only)

- [ ] **Step 1: Re-run the contract test in isolation**

Run: `pytest tests/unit/test_using_jfox_skill.py -v`
Expected: PASS (all green). Confirms the invariant holds after the commit.

- [ ] **Step 2: Confirm auto-discovery picks up the new skill**

Run: `ls packages/cc-plugin/skills/`
Expected output includes `using-jfox` alongside `ingest manage organize search session-summary`. No `plugin.json` edit is needed — cc-plugin auto-discovers `skills/*`.

- [ ] **Step 3: Confirm no existing skill or plugin manifest was modified**

Run: `git diff --stat main -- packages/cc-plugin`
Expected: only `packages/cc-plugin/skills/using-jfox/SKILL.md` shows as added; `ingest/manage/organize/search/session-summary/SKILL.md` and `.claude-plugin/plugin.json` show **no** changes.

- [ ] **Step 4: Manual routing sanity (human)**

With the plugin installed/reloaded, ask two prompts and confirm the routing:
- 「jfox 能做什么」→ should route to **using-jfox** (overview).
- 「搜索一下关于 X 的笔记」→ should route to **search**, **not** using-jfox.

If the second one wrongly hits using-jfox, the description picked up a competing verb — re-run the contract test (it should already have caught this) and tighten the description.

- [ ] **Step 5: Done — report**

The feature is complete. Note in the PR/issue:
- Files added (1 skill + 1 test).
- Acceptance criteria from spec Section 7 all met (verify the checklist).
- Follow-ups FU-1 (single-source refactor, post #244–247) and FU-2 (Kimi consistency) remain open, tracked in the spec.

(Do not push or open a PR unless the user asks. If asked, push `feat/issue-243-using-jfox-skill` and open a PR against `main` with `Closes #243`.)

---

## Self-Review (run before handing off)

**Spec coverage** — every spec section maps to a task:
- §1 File & naming → Task 1 Step 3 (file path + `name: using-jfox`).
- §2 Description / trigger strategy → Task 1 Step 3 (frontmatter) + guarded by Task 1 Step 1 tests.
- §3 Body structure (6 sections) → Task 1 Step 3 (env check, capability map, note model, workflows, conventions, boundary).
- §4 Capability-map decision table → Task 1 Step 3.
- §5 ≥2 composite workflows → Task 1 Step 3 (3 workflows).
- §6 Boundary / non-goals → Task 1 Step 3 "本 skill 不做" + Task 2 Step 3 (no-modification check).
- §7 Acceptance criteria → Task 2 Step 5 checklist + Task 2 Step 4 routing sanity.
- §8 Verification → Task 1 Step 1 (contract test) + Task 2 Steps 1–4.
- §9 Follow-ups → Task 2 Step 5 (reported, not implemented by design).

**Placeholder scan:** none — all code/content is complete; no TBD/TODO/"add error handling".

**Type/name consistency:** skill name `using-jfox` and the five sibling names are used identically across the skill body, the test, and the commit message. Pointer anchors (`共享约定`/`知识库路径`/`健康检查`/`Inbox`/`提炼`) match the test's `checks` list exactly.
