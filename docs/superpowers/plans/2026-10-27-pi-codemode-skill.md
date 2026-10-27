# pi codemode Acceleration for session-to-permanent — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a pi-only codemode section to `skills-recommend/pi/jfox-session-to-permanent/SKILL.md` that merges the mechanical CLI steps (dedup queries, auto-tier write) into single scripts, with a static contract test guarding the shape.

**Architecture:** Two templates (batch dedup query, atomic auto-tier write) plus a verdict→outcome table, placed in one new section; the bash walkthrough stays authoritative and unchanged. A new pytest file asserts the section exists, is pi-only, consumes `jfox similarity check` verdicts, and never re-implements judgement logic. One unrelated line loses its `jq` dependency.

**Tech Stack:** Markdown skill docs, pytest static file assertions, markdownlint-cli2, jfox 1.17.0 CLI (`jfox similarity check`, `jfox add`).

**Spec:** `docs/superpowers/specs/2026-10-27-pi-codemode-skill-design.md`

## Global Constraints

- Only `skills-recommend/pi/jfox-session-to-permanent/SKILL.md` and the new test file may change. `packages/cc-plugin/...` and `packages/kimi-plugin/...` must stay byte-identical to `main`.
- The pi SKILL.md must never contain `--mode semantic` or `0.5–0.65` (pinned by `tests/unit/test_session_dedup_skill_docs.py:33-34`).
- No `--force` may appear inside any fenced code block of the auto-tier section.
- Judgement lives in jfox: templates consume `verdict` values `new` / `gray` / `covered` / `unavailable`; no thresholds, no percentile math in scripts.
- New test file must be `tests/unit/test_pi_codemode_skill_docs.py` with `pytestmark = [pytest.mark.unit, pytest.mark.fast]` (markers registered in `tests/conftest.py:236`, `:244`).
- All touched Markdown must pass `npx --yes markdownlint-cli2`.

## Review Focus

- **codemode unavailable** → template section must be skippable with no semantic change; a reader must not think bash flow became legacy.
- **`jfox search` result size** → template one must strip `document` and `matches`/`baseline`, otherwise the whole point (context compression) is lost.
- **Draft not on disk** → template two must write the draft before `similarity check --content-file`; reordering makes the check read a missing file.
- **Unknown verdict value** (future jfox adding a 5th verdict) → template must fail closed (`signal_missing`), not default to writing.
- **Isolated test KB under 30 permanent notes** → every verdict is `unavailable`; U2 must seed ≥30 topic-diverse notes or the acceptance step is vacuous.

---

### Task 1: Contract test skeleton + section existence (A1, A2)

**Files:**

- Create: `tests/unit/test_pi_codemode_skill_docs.py`
- Modify: `skills-recommend/pi/jfox-session-to-permanent/SKILL.md` (new section only)

**Interfaces:**

- Produces: `SKILL_PI`, `SKILL_OTHER` path constants; helpers `_read(path)`, `has_codemode_section(text)`, `has_both_templates(text)`
- Consumes: nothing

- [ ] **Step 1: Write the failing test**

```python
"""Static contracts for the pi-only codemode section (#585)."""

from pathlib import Path

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

REPO_ROOT = Path(__file__).resolve().parents[2]
SKILL_PI = REPO_ROOT / "skills-recommend/pi/jfox-session-to-permanent/SKILL.md"
SKILL_OTHER = [
    REPO_ROOT / "packages/cc-plugin/skills/session-to-permanent/SKILL.md",
    REPO_ROOT / "packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def has_codemode_section(text: str) -> bool:
    return "## codemode 加速" in text and "codemode" in text.split("## codemode 加速", 1)[1]


def has_both_templates(text: str) -> bool:
    return "### 模板一" in text and "### 模板二" in text


def test_pi_skill_has_codemode_section():
    text = _read(SKILL_PI)
    assert has_codemode_section(text)
    assert "fallback" in text.lower() or "不可用" in text


def test_pi_skill_has_both_templates():
    assert has_both_templates(_read(SKILL_PI))


@pytest.mark.parametrize("path", SKILL_OTHER, ids=lambda p: p.parent.name)
def test_other_platforms_have_no_codemode(path):
    assert "codemode" not in _read(path)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_pi_codemode_skill_docs.py -q`
Expected: FAIL (section missing)

- [ ] **Step 3: Add the section to the pi SKILL.md**

Insert between the end of `## 五步流程` and `## 命令参考`:

```markdown
## codemode 加速（pi 专属）

本节只提供**执行机制**，规则仍以五步流程为准；`codemode` 工具不可用时整段跳过，按上文 bash 流程执行，语义不变。

### 封装点映射

| 步骤 | 能否封装 | 收益 |
|------|----------|------|
| Step 2 去重查询 | 能 | 每批 10 次串行搜索压成一次并行，且只回传结论字段 |
| Step 3.5 S1 / S2 / S5 | 能 | 机械信号一次跑完 |
| Step 5 自动档落库 | 能 | 「重查 → 写入」进入同一脚本，收窄并发窗口 |
| Step 1 提取 / Step 3 起草 / Step 4 审阅 | 不能 | 需要模型理解与用户交互 |

### 模板一：批量去重查询（Step 2）

<JS 模板，见 Task 2>

### 模板二：自动档原子落库（Step 5，仅高确信 + 已授权）

<JS 模板，见 Task 2>
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_pi_codemode_skill_docs.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_pi_codemode_skill_docs.py skills-recommend/pi/jfox-session-to-permanent/SKILL.md
git commit -m "test(skill): pin pi codemode section shape (#585)"
```

---

### Task 2: Template bodies + verdict mapping (A6, A7, A8)

**Files:**

- Modify: `tests/unit/test_pi_codemode_skill_docs.py`
- Modify: `skills-recommend/pi/jfox-session-to-permanent/SKILL.md`

**Interfaces:**

- Produces: `_fenced_blocks(text)`, `_section(text, heading)`, `auto_tier_code_blocks_use_force(text)`, `template_two_uses_verdict(text)`, `template_one_is_data_only(text)`
- Consumes: `SKILL_PI` from Task 1

- [ ] **Step 1: Write the failing tests**

```python
import re

FENCE_RE = re.compile(r"```[a-z]*\n(.*?)```", re.DOTALL)


def _fenced_blocks(text: str) -> list[str]:
    return FENCE_RE.findall(text)


def _section(text: str, heading: str) -> str:
    start = text.index(heading)
    rest = text[start:]
    nxt = re.search(r"\n### ", rest[1:])
    return rest if nxt is None else rest[: nxt.start() + 1]


def auto_tier_code_blocks_use_force(text: str) -> bool:
    section = _section(text, "### 模板二")
    return any("--force" in block for block in _fenced_blocks(section))


def template_two_uses_verdict(text: str) -> bool:
    section = _section(text, "### 模板二")
    blocks = _fenced_blocks(section)
    return any("similarity check" in b and "verdict" in b for b in blocks)


def template_one_is_data_only(text: str) -> bool:
    section = _section(text, "### 模板一")
    joined = "\n".join(_fenced_blocks(section))
    if "document" in joined:
        return False
    return not any(word in joined for word in ("已覆盖", "可补充", "未记录"))


def test_auto_tier_template_keeps_dedup_gate():
    assert not auto_tier_code_blocks_use_force(_read(SKILL_PI))


def test_template_two_consumes_similarity_verdict():
    assert template_two_uses_verdict(_read(SKILL_PI))


def test_template_one_is_data_only():
    assert template_one_is_data_only(_read(SKILL_PI))
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_pi_codemode_skill_docs.py -q`
Expected: FAIL on the three new tests

- [ ] **Step 3: Replace the two template placeholders**

模板的**唯一事实源是 SKILL.md 本身**，本计划不再内嵌代码快照（曾因快照滞后于修复，把已修掉的 `JSON.stringify` shell 注入写法重新带回来）。

落笔时必须满足这组不变量（对应 A6/A7/A8）：

- 用户文本（标题/摘要/标签）一律经 `shq()` 单引号包裹，禁止用 `JSON.stringify` 拼 shell 命令。
- `run()` 用 `async` + `try/catch` 同时兜住工具失败与 `JSON.parse` 失败。
- 多条候选用 `Promise.allSettled`，失败项保留标题，保证审计清单不缺条。
- 模板一：`--top 25`、不加 `--type`、不调 `suggest-links`、不输出 `document`、回传 `all_keyword`。
- 模板二：写盘 → `similarity check` → 读 `verdict` → `add`，不传 `--force`，未知 verdict 落 `signal_missing`，最后给出汇总计数。

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_pi_codemode_skill_docs.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/unit/test_pi_codemode_skill_docs.py skills-recommend/pi/jfox-session-to-permanent/SKILL.md
git commit -m "feat(skill): codemode templates for dedup and auto-tier write (#585)"
```

---

### Task 3: Drop the jq dependency + full verification (A3, A4, A5)

**Files:**

- Modify: `skills-recommend/pi/jfox-session-to-permanent/SKILL.md:270`
- Modify: `tests/unit/test_pi_codemode_skill_docs.py`

**Interfaces:**

- Produces: `uses_jq(text)`
- Consumes: `_read`, `SKILL_PI`

- [ ] **Step 1: Write the failing test**

```python
def uses_jq(text: str) -> bool:
    return "jq " in text


def test_pi_skill_has_no_jq_dependency():
    assert not uses_jq(_read(SKILL_PI))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_pi_codemode_skill_docs.py::test_pi_skill_has_no_jq_dependency -q`
Expected: FAIL (line 270 still pipes through jq)

- [ ] **Step 3: Replace the jq pipeline**

```bash
# before
jfox show <已有笔记_id> --json | jq -r .content > /tmp/existing.md
# after（jfox show 默认输出原始 Markdown；--content-file 回灌时会剥 frontmatter 与 H1）
jfox show <已有笔记_id> > /tmp/existing.md
```

- [ ] **Step 4: Verify the roundtrip in an isolated KB**

```bash
W=/tmp/jq-585; rm -rf $W
ZK_CONFIG_PATH=$W/config.json ZK_KB_ROOT=$W/kbroot jfox add "第一段" --title "Probe" --type permanent --json
ID=$(ZK_CONFIG_PATH=$W/config.json ZK_KB_ROOT=$W/kbroot jfox search "Probe" --json | python3 -c "import json,sys;print(json.load(sys.stdin)['results'][0]['id'])")
ZK_CONFIG_PATH=$W/config.json ZK_KB_ROOT=$W/kbroot jfox show "$ID" > $W/out.md
printf '\n\n## 追加段\n新内容\n' >> $W/out.md
ZK_CONFIG_PATH=$W/config.json ZK_KB_ROOT=$W/kbroot jfox edit "$ID" --content-file $W/out.md --json
ZK_CONFIG_PATH=$W/config.json ZK_KB_ROOT=$W/kbroot jfox show "$ID" | grep -c '^# '
rm -rf $W
```

Expected: `jfox edit` returns `"success": true`, and the final `grep -c '^# '` prints `1` (no duplicated H1).

- [ ] **Step 5: Run the full gate**

Run:

```bash
uv run pytest tests/unit/test_pi_codemode_skill_docs.py \
  tests/unit/test_moc_skill_docs.py \
  tests/unit/test_session_dedup_skill_docs.py -q
npx --yes markdownlint-cli2 "skills-recommend/pi/jfox-session-to-permanent/SKILL.md" "packages/cc-plugin/skills/session-to-permanent/SKILL.md" "packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md"
git diff --stat main -- packages/
```

Expected: all tests pass; `0 issues` from markdownlint; `git diff --stat` prints nothing for `packages/`.

- [ ] **Step 6: Commit**

```bash
git add skills-recommend/pi/jfox-session-to-permanent/SKILL.md tests/unit/test_pi_codemode_skill_docs.py
git commit -m "refactor(skill): drop jq dependency from pi step 5 (#585)"
```

---

### Task 4: Record manual verification as pending (U1–U4)

**Files:**

- Create: `docs/superpowers/plans/2026-10-27-pi-codemode-skill-verification.md`

**Interfaces:**

- Consumes: the finished SKILL.md

- [ ] **Step 1: Write the verification checklist**

Copy U1–U4 verbatim from the spec §4 with the hard prerequisites from §4.0 (codemode enabled, daemon running, isolated KB with ≥30 topic-diverse permanent notes, post-merge session only).

- [ ] **Step 2: Commit**

```bash
git add docs/superpowers/plans/2026-10-27-pi-codemode-skill-verification.md
git commit -m "docs(skill): record pending manual verification for codemode templates (#585)"
```

---

## Verification Summary

| Acceptance | Task | Command |
|---|---|---|
| A1, A2 | 1 | `uv run pytest tests/unit/test_pi_codemode_skill_docs.py -q` |
| A6, A7, A8 | 2 | same file |
| A5 | 3 | same file, `test_pi_skill_has_no_jq_dependency` |
| A3 | 3 | `uv run pytest tests/unit/test_moc_skill_docs.py tests/unit/test_session_dedup_skill_docs.py -q` |
| A4 | 3 | `npx --yes markdownlint-cli2 <three SKILL.md>` |
| U1–U4 | 4 | manual, post-merge only (see verification doc) |
