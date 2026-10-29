# current-KB 指针劫持修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 issue #584——`jfox init` 默认切库导致的全局 current-KB 指针劫持，并补齐可观测性与回退防御。

**Architecture:** 三处产品改动（init 切库语义 / remove 回退 / 写入库名可观测）+ 一处测试harness 同步 + 三平台 skill 兜底条款。全部小函数可单测；P1 是行为变更，`ZKCLI.init()` 必须同步传 `--default`。

**Tech Stack:** Python 3.10+ / Typer / pytest；Markdown（skill 文档）。

**Spec:** `docs/superpowers/specs/2026-10-27-current-kb-pointer-hijack-design.md`（issue #584 定稿，2 轮交叉复核收敛，sha256 `4877a8f4…`）

## Global Constraints

- 工作目录（worktree）：`WT=/home/elling/git-repo/github/jfox/.pi/worktrees/issue-584-current-kb-pointer-hijack`；所有路径以 `$WT` 开头；git 用 `git -C "$WT"`。
- 不改 `tests/conftest.py` 的隔离；不改 `jfox kb use/switch` 语义；不自动删除 KB。
- P1 规则：显式 `--default`/`--no-default` 优先；未显式时仅 `name == "default"` 切 current。
- `--json` 输出必须保持 stdout 纯净（WARNING 走 `logging`，不写 stdout）。
- 测试命令口径：CI Fast = `uv run pytest tests/ -m "not embedding and not slow"`。
- commit message：conventional commits + `（#584）`。

## Task 1: P1——init 切库语义 + ZKCLI 同步（A1 / A5）

**Files:**

- Modify: `$WT/jfox/kb_manager.py`（新增 `should_switch_default`）
- Modify: `$WT/jfox/cli.py`（`init` 三态 flag + 调用）
- Modify: `$WT/tests/utils/jfox_cli.py`（`init()` 传 `--default`）
- Create: `$WT/tests/unit/test_init_default_switch.py`

**Interfaces:**

- Produces: `jfox.kb_manager.should_switch_default(name: str, explicit_default: Optional[bool]) -> bool`
- Consumes: 无（第一任务）

- [ ] **Step 1: 写失败测试（真值表五格）**

```python
"""init 默认切库语义（#584）：显式 flag 优先，未指定时仅 default 库切换。"""

from jfox.kb_manager import should_switch_default


class TestShouldSwitchDefault:
    def test_default_kb_without_flag_switches(self):
        assert should_switch_default("default", None) is True

    def test_named_kb_without_flag_does_not_switch(self):
        assert should_switch_default("test_abc123", None) is False

    def test_named_kb_with_explicit_default_switches(self):
        assert should_switch_default("work", True) is True

    def test_named_kb_with_explicit_no_default_does_not_switch(self):
        assert should_switch_default("work", False) is False

    def test_canonical_default_with_explicit_no_default_does_not_switch(self):
        assert should_switch_default("default", False) is False
```

- [ ] **Step 2: 运行确认失败**

Run: `cd "$WT" && uv run pytest tests/unit/test_init_default_switch.py -q`
Expected: FAIL（ImportError: cannot import name 'should_switch_default'）

- [ ] **Step 3: 实现纯函数**

在 `jfox/kb_manager.py` 顶部（`DEFAULT_KB_NAME` 常量之后、`KBStats` 之前）加入：

```python
def should_switch_default(name: str, explicit_default: Optional[bool]) -> bool:
    """决定 `jfox init` 创建知识库后是否切换全局 current 指针（#584）。

    规则：显式 --default / --no-default 优先；未显式指定时，仅规范库
    ``default`` 切换指针。防止临时库（测试/复现脚本）创建即劫持路由。
    """
    if explicit_default is not None:
        return explicit_default
    return name == DEFAULT_KB_NAME
```

- [ ] **Step 4: 改 `init` 的 flag 为三态并接线**

`jfox/cli.py` 的 `init()` 中，把

```python
    set_default: bool = typer.Option(True, "--default/--no-default", help="设为默认知识库"),
```

改为

```python
    set_default: Optional[bool] = typer.Option(
        None,
        "--default/--no-default",
        help="设为默认知识库（默认：仅 default 库切换当前指针）",
    ),
```

并在 `manager.create(...)` 前计算：

```python
        from .kb_manager import should_switch_default

        switch_default = should_switch_default(kb_name, set_default)
```

把 `set_as_default=set_default` 改为 `set_as_default=switch_default`。

- [ ] **Step 5: 同步测试 harness（A5 关键）**

`tests/utils/jfox_cli.py` 的 `init()`：

```python
        result = self._run("init")
```

改为

```python
        result = self._run("init", "--default")
```

（P1 后 `jfox init` 不再对 `test_*` 切库；测试依赖 current 指向测试库，必须显式 `--default`。）

- [ ] **Step 6: 运行纯函数 + 现有 kb current 测试**

Run: `cd "$WT" && uv run pytest tests/unit/test_init_default_switch.py tests/test_kb_current.py -q`
Expected: 全 PASS

- [ ] **Step 7: 验证 CLI 三态接线（integration）**

在 `tests/unit/test_init_default_switch.py` 追加：

```python
class TestInitCliWiring:
    def test_named_kb_without_flag_keeps_current(self, cli, temp_kb):
        before = cli.kb_current().json()["name"]
        other = temp_kb.parent / "other_kb"
        result = cli._run("init", "--name", "other_kb", "--path", str(other))
        assert result.success
        assert cli.kb_current().json()["name"] == before
        cli._run("kb", "remove", "other_kb", "--force")

    def test_named_kb_with_default_flag_switches(self, cli, temp_kb):
        other = temp_kb.parent / "other_kb2"
        result = cli._run("init", "--name", "other_kb2", "--path", str(other), "--default")
        assert result.success
        assert cli.kb_current().json()["name"] == "other_kb2"
        cli._run("kb", "remove", "other_kb2", "--force")
```

Run: `cd "$WT" && uv run pytest tests/unit/test_init_default_switch.py -q`
Expected: 全 PASS。若 Typer 不接受 `Optional[bool]` 三态，改为两个独立 flag（`--default`/`--no-default`）并用 `None` 默认；仍须保持 Step 7 的两条断言。

- [ ] **Step 8: commit**

```bash
git -C "$WT" add jfox/kb_manager.py jfox/cli.py tests/utils/jfox_cli.py tests/unit/test_init_default_switch.py
git -C "$WT" commit -m "fix(kb): init 默认不再切库，防止临时库劫持 current 指针（#584）"
```

## Task 2: P2——remove 回退优先 default（A2）

**Files:**

- Modify: `$WT/jfox/global_config.py`
- Modify: `$WT/tests/unit/test_global_config.py`

**Interfaces:**

- Produces: `jfox.global_config.pick_fallback_default(names: Iterable[str], removed: str) -> Optional[str]`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_global_config.py` 追加：

```python
from jfox.global_config import pick_fallback_default


class TestPickFallbackDefault:
    def test_prefers_canonical_default(self):
        assert pick_fallback_default(["test_a", "default"], "test_a") == "default"

    def test_skips_test_kbs_when_default_missing(self):
        assert pick_fallback_default(["test_a", "work"], "test_a") == "work"

    def test_dangling_default_when_only_test_kbs(self):
        assert pick_fallback_default(["test_a", "test_b"], "test_a") == "default"
```

- [ ] **Step 2: 运行确认失败**

Run: `cd "$WT" && uv run pytest tests/unit/test_global_config.py -k PickFallbackDefault -q`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现纯函数并接线**

在 `jfox/global_config.py` 模块级（`DEFAULT_KB_NAME` 之后）加入：

```python
_TEST_KB_PREFIXES = ("test_", "zk_test_")


def pick_fallback_default(names: Iterable[str], removed: str) -> Optional[str]:
    """删除当前默认库时选择回退目标（#584）。

    优先规范库 ``default``；其次第一个非测试库；只剩测试库时返回
    ``DEFAULT_KB_NAME``（允许悬空，由 get_default_kb_path 兜底）。
    判定是启发式：不以 test_/zk_test_ 开头的残留不在此防护内。
    """
    remaining = [n for n in names if n != removed]
    if not remaining:
        return None
    if DEFAULT_KB_NAME in remaining:
        return DEFAULT_KB_NAME
    for name in remaining:
        if not name.startswith(_TEST_KB_PREFIXES):
            return name
    return DEFAULT_KB_NAME
```

把 `remove_knowledge_base()` 中的

```python
        if config.default == name:
            config.default = next(iter(config.knowledge_bases.keys()))
```

改为

```python
        if config.default == name:
            fallback = pick_fallback_default(list(config.knowledge_bases.keys()), name)
            if fallback is not None:
                config.default = fallback
```

（需确认 `Iterable` 已导入，未导入则补 `from typing import Iterable`。）

- [ ] **Step 4: 运行测试**

Run: `cd "$WT" && uv run pytest tests/unit/test_global_config.py -q`
Expected: 全 PASS

- [ ] **Step 5: commit**

```bash
git -C "$WT" add jfox/global_config.py tests/unit/test_global_config.py
git -C "$WT" commit -m "fix(kb): 删除当前库时回退优先 default，避免落到测试库（#584）"
```

## Task 3: P3a/P3b——写入库名可观测（A3a / A3b）

**Files:**

- Modify: `$WT/jfox/config.py`（`current_kb_name()`）
- Modify: `$WT/jfox/cli.py`（`_add_note_impl` / `_edit_impl` / add wrapper 的 duplicate JSON）
- Modify: `$WT/jfox/candidates/cli.py`（`promote_cmd` JSON）
- Create: `$WT/tests/unit/test_write_kb_field.py`

**Interfaces:**

- Produces: `jfox.config.current_kb_name() -> str`

- [ ] **Step 1: 写失败测试**

```python
"""写入类命令的 --json 必须带实际写入库名（#584）。"""

import logging


class TestCurrentKbName:
    def test_resolves_registered_name_by_path(self, cli):
        from jfox.config import current_kb_name

        assert current_kb_name() == cli.kb_name


class TestAddJsonKbField:
    def test_add_json_contains_kb(self, cli):
        result = cli.add("kb 字段测试内容", title="kb-field-probe")
        assert result.success
        assert result.json()["kb"] == cli.kb_name

    def test_add_duplicate_json_contains_kb(self, cli):
        assert cli.add("重复内容探针", title="dup-probe").success
        dup = cli.add("重复内容探针", title="dup-probe")
        assert not dup.success
        assert dup.json()["skipped"] == "duplicate"
        assert dup.json()["kb"] == cli.kb_name


class TestTestKbWarning:
    def test_write_to_test_kb_without_explicit_kb_warns(self, temp_kb, caplog):
        from jfox.cli import _add_note_impl
        from jfox.config import use_kb

        with use_kb("test_warning_probe"):
            with caplog.at_level(logging.WARNING):
                _add_note_impl(
                    "warning 探针", "warning-probe", "fleeting", None, None, "json"
                )
        assert any("测试知识库" in r.message for r in caplog.records)
```

（`test_warning_probe` 需先注册：在该测试内用 `jfox.kb_manager.get_kb_manager().create(...)` 创建，或复用 `temp_kb_registered`；实施者按现有 fixture 模式落地，测试结束清理。）

- [ ] **Step 2: 运行确认失败**

Run: `cd "$WT" && uv run pytest tests/unit/test_write_kb_field.py -q`
Expected: FAIL（`current_kb_name` 不存在 / JSON 无 `kb`）

- [ ] **Step 3: 实现 `current_kb_name()`**

在 `jfox/config.py` 末尾加入（`Path`/`os` 已导入）：

```python
def current_kb_name() -> str:
    """返回当前生效知识库的注册名（#584）。

    优先级：按 active base_dir 在注册表中反查 > JFOX_KB > 目录名。
    反查可正确处理目录名为 ``kb`` 的自定义路径（测试库形态
    ``zk_test_xxx/kb``）。
    """
    base = Path(config.base_dir).resolve()
    env_kb = os.environ.get("JFOX_KB", "").strip()
    try:
        from .kb_manager import get_kb_manager

        for entry in get_kb_manager().config_manager.list_knowledge_bases():
            if Path(entry.path).resolve() == base:
                return entry.name
    except Exception:
        logger.warning("current_kb_name: KB registry lookup failed", exc_info=True)
    return env_kb or base.name
```

- [ ] **Step 4: JSON 加 `kb` 字段 + WARNING**

`_add_note_impl` 增加参数 `kb_explicit: bool = False`；在成功 result 的顶层加 `"kb": current_kb_name()`；并在写入前加：

```python
    kb_name = current_kb_name()
    if not kb_explicit and kb_name.startswith(("test_", "zk_test_")):
        logger.warning("写入测试知识库 %s 且未显式指定 --kb；如非测试请检查 current KB", kb_name)
```

`add` wrapper 调用 `_add_note_impl(...)` 时传 `kb_explicit=bool(kb)`（两个分支都要传）；`except DuplicateNoteError` 的 JSON 加 `"kb": current_kb_name()`（从 `.config` 导入）。

`_edit_impl` 的 JSON 输出同样加 `"kb"`，并加同样的 WARNING（`_edit_impl` 增加 `kb_explicit` 参数，edit wrapper 传 `bool(kb)`）。

`jfox/candidates/cli.py` 的 `promote_cmd`：成功/异常 JSON 各加 `"kb": current_kb_name()`（`from ..config import current_kb_name`）。

- [ ] **Step 5: 运行测试**

Run: `cd "$WT" && uv run pytest tests/unit/test_write_kb_field.py tests/unit/test_format_unify.py -q`
Expected: 全 PASS

- [ ] **Step 6: commit**

```bash
git -C "$WT" add jfox/config.py jfox/cli.py jfox/candidates/cli.py tests/unit/test_write_kb_field.py
git -C "$WT" commit -m "feat(cli): 写入类命令 --json 暴露实际库名并对测试库告警（#584）"
```

## Task 4: P4——skill 落库前核对当前库（A4）

**Files:**

- Modify: `$WT/skills-recommend/pi/jfox-session-to-permanent/SKILL.md`
- Modify: `$WT/packages/cc-plugin/skills/session-to-permanent/SKILL.md`
- Modify: `$WT/packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md`

**Interfaces:**

- Consumes: 无（纯文档）；三文件插入同一段文本（工具中立）。

- [ ] **Step 1: 在 Step 5 开头插入核对段（三文件逐字相同）**

插入位置：`### Step 5: 落库` 标题之后、`用户确认后再执行写入` 之前。

```markdown
**落库前核对当前知识库**：执行任何 `jfox add` / `jfox edit` 前，先跑 `jfox kb current --json` 确认 `name` 是预期库（默认 `default`）。不符则停止写入并报告，不得继续写（并发测试或其他会话可能劫持 current 指针，见 jfox #584）；确认后再继续。
```

- [ ] **Step 2: 验证（A4）**

```bash
cd "$WT"
for f in skills-recommend/pi/jfox-session-to-permanent/SKILL.md packages/cc-plugin/skills/session-to-permanent/SKILL.md packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md; do
  grep -q "jfox kb current --json" "$f" && echo "OK $f" || echo "MISSING $f"
done
npx --yes markdownlint-cli2 skills-recommend/pi/jfox-session-to-permanent/SKILL.md packages/cc-plugin/skills/session-to-permanent/SKILL.md packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md
```

Expected: 三条 OK；lint 0 issues

- [ ] **Step 3: commit**

```bash
git -C "$WT" add skills-recommend/pi/jfox-session-to-permanent/SKILL.md packages/cc-plugin/skills/session-to-permanent/SKILL.md packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md
git -C "$WT" commit -m "docs(skill): session-to-permanent 落库前核对 current KB（#584）"
```

## Task 5: 全量验证（A1–A5 汇总）

**Files:** 无新增（只跑命令、记录证据）

- [ ] **Step 1: CI Fast 全量**

Run: `cd "$WT" && uv run pytest tests/ -m "not embedding and not slow" -q`
Expected: 全 PASS（这是 A5 的核心验收）

- [ ] **Step 2: 最小冒烟集**

Run: `cd "$WT" && uv run pytest tests/test_kb_current.py tests/unit/test_init_default_switch.py tests/unit/test_global_config.py tests/unit/test_write_kb_field.py -q`
Expected: 全 PASS

- [ ] **Step 3: A4 静态校验**

Run: `cd "$WT" && npx --yes markdownlint-cli2 skills-recommend/pi/jfox-session-to-permanent/SKILL.md packages/cc-plugin/skills/session-to-permanent/SKILL.md packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md`
Expected: 0 issues

- [ ] **Step 4: 证据落盘**

把以上命令与输出原文写入执行报告（供 PR 描述与 issue 评论）。若 CI Fast 有与本次改动无关的既有失败，记录并标注（不得静默忽略）。

## Task 6（post-implementation manual verification）: U1–U2

**Files:** 无（用户实测）

- [ ] **Step 1: 部署前置**：修复合入 main 后（或修复 worktree 内 `uv run jfox`）；先确认 A5 已通过；路径校验 `uv run python -c "import jfox; print(jfox.__file__)"` 指向修复 checkout（版本号发版前仍为 1.16.3，不能作判据）
- [ ] **Step 2: U1**：`jfox init --name test_probe --path ~/.zettelkasten/zk_test_probe/kb` → `jfox kb current` 仍为 default；`jfox kb remove test_probe --force` 后无残留
- [ ] **Step 3: U2**：新 HOME 下 `jfox init` → 创建 default 并切 current；`jfox init --name demo --default` → 显式切换生效
- [ ] **Step 4: 结果回填** issue #584（PASS/FAIL/PENDING + 证据）

---

## 自检记录（Self-Review）

- Spec 覆盖：P1→Task1（A1/A5）、P2→Task2（A2）、P3→Task3（A3a/A3b）、P4→Task4（A4）、全量验证→Task5、U1/U2→Task6。无遗漏。
- 占位符扫描：无 TBD；测试与实现代码为成稿。
- 一致性：`should_switch_default` / `pick_fallback_default` / `current_kb_name` 三个接口名在任务间一致；`kb_explicit` 参数贯通 add/edit。
