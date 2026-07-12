# release-cc-plugin skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新建 `.claude/skills/release-cc-plugin/`（`release_cc_plugin_helper.py` + `SKILL.md`），把 cc-plugin marketplace 发版流程（三处版本号同步 bump + PR 合 main）固化，补 `/release`（CLI/PyPI 专用）的缺口。

**Architecture:** helper 脚本做确定性计算（读版本 / 算版本 / 原子 bump 三字段 / git log changelog / `--dry-run` JSON），SKILL.md 做流程编排（前置校验 → dry-run 预览 → 用户确认 → bump → 分支/PR）。原子性靠"先校验全部命中数、再落盘、写后断言三处相等"。

**Tech Stack:** Python 3.10+ 标准库（argparse / json / re / subprocess / pathlib / sys），pytest，Typer 无关。spec：`docs/superpowers/specs/2026-07-12-release-cc-plugin-skill-design.md`

## Global Constraints

- **分支**：`worktree-release-cc-plugin`（worktree 内，PR 前重命名为 `feat/release-cc-plugin-skill`）。main 受保护，所有改动 PR 合入。
- **标准库 only**：helper 只用 argparse/json/re/subprocess/pathlib/sys，不引第三方。
- **行宽 100**：black + ruff（pyproject.toml 已配）。
- **注释中文**。
- **测试纪律**：放 `tests/unit/`，快速无外部依赖，可自主跑（CLAUDE.md「快速单测」）。镜像 `tests/unit/test_release_helper.py` 的 subprocess 风格；写盘/原子性测试用 importlib + tmp_path 隔离。
- **PROJECT_ROOT**：`Path(__file__).resolve().parents[3]`（脚本在 `.claude/skills/release-cc-plugin/`）。
- **不发 PyPI / 不打 tag**：plugin 发版只 bump 三处 + PR；合 main 即发布。
- **真相源**：`packages/cc-plugin/.claude-plugin/plugin.json` 的 `version` 是当前版本唯一真相源，`marketplace.json` 必须与之同步（`metadata.version` + `plugins[0].version`）。

## File Structure

| 文件 | 职责 | 动作 |
|---|---|---|
| `.claude/skills/release-cc-plugin/release_cc_plugin_helper.py` | 版本计算 / 读版本 / changelog / 原子 bump 三字段 / CLI | **新建** |
| `.claude/skills/release-cc-plugin/SKILL.md` | 流程编排（校验 → dry-run → 确认 → bump → PR） | **新建** |
| `tests/unit/test_release_cc_plugin_helper.py` | 单测（subprocess 镜像 + importlib 隔离写路径） | **新建** |

helper 函数签名（各 task 共享，后续 task 只看这块即知邻接接口）：

```python
def read_current_version(root: Path) -> str: ...
def compute_new_version(current: str, spec: str) -> str: ...  # raise ValueError
def find_last_bump_commit(root: Path, current_version: str) -> str | None: ...
def get_changelog(root: Path, current_version: str) -> list[str]: ...
def assert_versions(root: Path, expected: str) -> None: ...  # raise AssertionError
def bump_version_files(root: Path, old: str, new: str) -> list[str]: ...  # raise ValueError；原子
def main() -> None: ...
```

---

## Task 1: helper — 版本计算 + changelog + dry-run

**Files:**
- Create: `.claude/skills/release-cc-plugin/release_cc_plugin_helper.py`
- Test: `tests/unit/test_release_cc_plugin_helper.py`

**Interfaces:**
- Produces: `read_current_version` / `compute_new_version` / `find_last_bump_commit` / `get_changelog` / `main`（dry-run 分支完整，非 dry-run 分支留给 Task 2）

- [ ] **Step 1: 写失败测试**（subprocess 风格，镜像 test_release_helper.py）

Create `tests/unit/test_release_cc_plugin_helper.py`:

```python
"""release_cc_plugin_helper.py 单元测试"""
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# 被测模块路径
HELPER = str(
    Path(__file__).resolve().parents[2]
    / ".claude"
    / "skills"
    / "release-cc-plugin"
    / "release_cc_plugin_helper.py"
)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run_helper(*args, env=None):
    """运行 helper 并返回 (stdout, stderr, returncode)"""
    e = env or os.environ.copy()
    e["PYTHONUTF8"] = "1"
    result = subprocess.run(
        ["python", HELPER, *args],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        env=e,
        encoding="utf-8",
        errors="replace",
    )
    return result.stdout, result.stderr, result.returncode


def _parse_json(stdout: str) -> dict:
    return json.loads(stdout.strip())


def _load_helper_module():
    """importlib 加载 helper 模块，用于直接测函数（写盘/原子性需隔离）"""
    spec = importlib.util.spec_from_file_location("release_cc_plugin_helper", HELPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ── dry-run：版本计算 ──


class TestDryRun:
    def test_current_version_is_semver(self):
        stdout, _, rc = _run_helper("patch", "--dry-run")
        assert rc == 0, f"stderr: {_}"
        cur = _parse_json(stdout)["current_version"].split(".")
        assert len(cur) == 3 and all(p.isdigit() for p in cur)

    def test_patch_bump(self):
        data = _parse_json(_run_helper("patch", "--dry-run")[0])
        cur = [int(x) for x in data["current_version"].split(".")]
        new = [int(x) for x in data["new_version"].split(".")]
        assert new == [cur[0], cur[1], cur[2] + 1]

    def test_minor_bump(self):
        data = _parse_json(_run_helper("minor", "--dry-run")[0])
        cur = [int(x) for x in data["current_version"].split(".")]
        new = [int(x) for x in data["new_version"].split(".")]
        assert new == [cur[0], cur[1] + 1, 0]

    def test_major_bump(self):
        data = _parse_json(_run_helper("major", "--dry-run")[0])
        cur = [int(x) for x in data["current_version"].split(".")]
        new = [int(x) for x in data["new_version"].split(".")]
        assert new == [cur[0] + 1, 0, 0]

    def test_explicit_version(self):
        data = _parse_json(_run_helper("0.7.3", "--dry-run")[0])
        assert data["new_version"] == "0.7.3"

    def test_files_to_change_lists_two(self):
        data = _parse_json(_run_helper("patch", "--dry-run")[0])
        assert data["files_to_change"] == [
            "packages/cc-plugin/.claude-plugin/plugin.json",
            ".claude-plugin/marketplace.json",
        ]

    def test_changelog_is_list(self):
        data = _parse_json(_run_helper("patch", "--dry-run")[0])
        assert isinstance(data["changelog_summary"], list)


# ── 校验：非法输入 ──


class TestValidation:
    def test_invalid_bump_type(self):
        stdout, _, rc = _run_helper("foobar", "--dry-run")
        assert rc != 0
        assert "error" in _parse_json(stdout)

    def test_invalid_semver(self):
        stdout, _, rc = _run_helper("1.2", "--dry-run")
        assert rc != 0
        assert "error" in _parse_json(stdout)


# ── changelog：解析 git log（mock subprocess）──


class TestChangelog:
    def test_get_changelog_parses_git_log(self, tmp_path):
        mod = _load_helper_module()
        fake = MagicMock(stdout="abc1234 feat: x\ndef5678 fix: y\n", returncode=0)
        with patch("release_cc_plugin_helper.subprocess.run", return_value=fake):
            result = mod.get_changelog(tmp_path, "0.5.1")
        assert result == ["abc1234 feat: x", "def5678 fix: y"]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_release_cc_plugin_helper.py -v`
Expected: FAIL — helper 文件不存在，`_run_helper` 报 `FileNotFoundError`（或 collection error）。

- [ ] **Step 3: 实现 helper（dry-run 完整，非 dry-run 留 Task 2）**

Create `.claude/skills/release-cc-plugin/release_cc_plugin_helper.py`:

```python
#!/usr/bin/env python3
"""
cc-plugin release 辅助脚本

处理版本号计算、三处版本号同步 bump、changelog 生成。
输出 JSON 供 Claude 解析。

用法:
    python release_cc_plugin_helper.py patch          # bump patch
    python release_cc_plugin_helper.py minor          # bump minor
    python release_cc_plugin_helper.py major          # bump major
    python release_cc_plugin_helper.py 0.6.0          # 指定版本
    python release_cc_plugin_helper.py ... --dry-run  # 只计算不修改文件
"""
import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# 项目根目录（脚本位于 .claude/skills/release-cc-plugin/，向上 3 级）
PROJECT_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_JSON_REL = "packages/cc-plugin/.claude-plugin/plugin.json"
MARKETPLACE_JSON_REL = ".claude-plugin/marketplace.json"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def output_json(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False))


def output_error(msg: str) -> None:
    output_json({"error": msg})
    sys.exit(1)


def read_current_version(root: Path) -> str:
    """从 plugin.json 读当前版本号（单一真相源）。"""
    data = json.loads((root / PLUGIN_JSON_REL).read_text(encoding="utf-8"))
    return data["version"]


def compute_new_version(current: str, spec: str) -> str:
    """patch/minor/major 递增，或 explicit x.y.z 直传。非法 raise ValueError。"""
    if not VERSION_RE.match(current):
        raise ValueError(f"非法当前版本号: {current!r}")
    if spec in ("patch", "minor", "major"):
        major, minor, patch = (int(x) for x in current.split("."))
        if spec == "patch":
            return f"{major}.{minor}.{patch + 1}"
        if spec == "minor":
            return f"{major}.{minor + 1}.0"
        return f"{major + 1}.0.0"
    if not VERSION_RE.match(spec):
        raise ValueError(f"非法版本号规格: {spec!r}（需 patch/minor/major 或 x.y.z）")
    return spec


def find_last_bump_commit(root: Path, current_version: str) -> str | None:
    """定位上次发版提交：引入 current_version 字符串的提交；降级为最近改 marketplace.json 的提交。"""
    rel = MARKETPLACE_JSON_REL
    for args in (
        ["git", "log", "-S", f'"version": "{current_version}"', "--format=%H", "--", rel],
        ["git", "log", "--format=%H", "-1", "--", rel],
    ):
        try:
            out = subprocess.run(
                args, cwd=root, capture_output=True, text=True, check=True
            )
        except subprocess.CalledProcessError:
            continue
        hits = [ln for ln in out.stdout.splitlines() if ln.strip()]
        if hits:
            return hits[0]
    return None


def get_changelog(root: Path, current_version: str) -> list[str]:
    """自上次发版以来 packages/cc-plugin/ 的 oneline 提交摘要。"""
    last = find_last_bump_commit(root, current_version)
    rng = f"{last}..HEAD" if last else "HEAD~30..HEAD"
    try:
        out = subprocess.run(
            ["git", "log", "--oneline", rng, "--", "packages/cc-plugin/"],
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.CalledProcessError:
        return []
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


def main() -> None:
    parser = argparse.ArgumentParser(description="cc-plugin release helper")
    parser.add_argument("version", help="patch | minor | major | x.y.z")
    parser.add_argument("--dry-run", action="store_true", help="只计算不修改文件")
    args = parser.parse_args()

    try:
        current = read_current_version(PROJECT_ROOT)
    except Exception as e:
        output_error(f"读取当前版本失败: {e}")  # output_error 会 sys.exit(1)

    try:
        new = compute_new_version(current, args.version)
    except ValueError as e:
        output_error(str(e))

    changelog = get_changelog(PROJECT_ROOT, current)

    if args.dry_run:
        output_json(
            {
                "current_version": current,
                "new_version": new,
                "files_to_change": [PLUGIN_JSON_REL, MARKETPLACE_JSON_REL],
                "changelog_summary": changelog,
            }
        )
        return

    # 非 dry-run 写盘路径在 Task 2 实现
    raise NotImplementedError("bump 写入在 Task 2 实现")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_release_cc_plugin_helper.py -v`
Expected: 10 passed（TestDryRun ×7 + TestValidation ×2 + TestChangelog ×1）。

- [ ] **Step 5: 提交**

```bash
git add .claude/skills/release-cc-plugin/release_cc_plugin_helper.py tests/unit/test_release_cc_plugin_helper.py
git commit -m "feat(release-cc-plugin): helper 版本计算 + changelog + dry-run"
```

---

## Task 2: helper — bump 三字段 + 原子性

**Files:**
- Modify: `.claude/skills/release-cc-plugin/release_cc_plugin_helper.py`
- Test: `tests/unit/test_release_cc_plugin_helper.py`（追加）

**Interfaces:**
- Consumes: `PLUGIN_JSON_REL` / `MARKETPLACE_JSON_REL`（Task 1 常量）
- Produces: `assert_versions` / `bump_version_files`；`main` 非 dry-run 分支接通

- [ ] **Step 1: 追加失败测试（importlib + tmp_path 隔离写盘）**

Append to `tests/unit/test_release_cc_plugin_helper.py`:

```python
# ── bump 三字段 + 原子性（直接调函数，tmp 隔离）──


def _setup_repo(tmp_path: Path, plugin_ver="0.5.1", market_versions=("0.5.1", "0.5.1")):
    """在 tmp_path 搭一个最小 plugin.json + marketplace.json"""
    plugin = tmp_path / "packages" / "cc-plugin" / ".claude-plugin" / "plugin.json"
    plugin.parent.mkdir(parents=True)
    plugin.write_text(
        json.dumps({"name": "jfox", "version": plugin_ver}, indent=2),
        encoding="utf-8",
    )
    market = tmp_path / ".claude-plugin" / "marketplace.json"
    market.parent.mkdir(parents=True)
    market.write_text(
        json.dumps(
            {
                "metadata": {"version": market_versions[0]},
                "plugins": [{"name": "jfox", "version": market_versions[1]}],
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return plugin, market


class TestBumpFiles:
    def test_bump_all_three(self, tmp_path):
        mod = _load_helper_module()
        plugin, market = _setup_repo(tmp_path)
        changed = mod.bump_version_files(tmp_path, "0.5.1", "0.6.0")
        assert json.loads(plugin.read_text(encoding="utf-8"))["version"] == "0.6.0"
        m = json.loads(market.read_text(encoding="utf-8"))
        assert m["metadata"]["version"] == "0.6.0"
        assert m["plugins"][0]["version"] == "0.6.0"
        assert "plugin.json" in changed[0]
        assert "marketplace.json" in changed[1]

    def test_count_mismatch_no_write(self, tmp_path):
        """marketplace 命中数不符 → 报错且 plugin.json 不被改（原子性）"""
        mod = _load_helper_module()
        plugin, market = _setup_repo(tmp_path)
        # 把 marketplace 第一个 version 改掉，命中数从 2 变 1
        txt = market.read_text(encoding="utf-8").replace(
            '"version": "0.5.1"', '"versionX": "0.5.1"', 1
        )
        market.write_text(txt, encoding="utf-8")
        with pytest.raises(ValueError):
            mod.bump_version_files(tmp_path, "0.5.1", "0.6.0")
        # plugin.json 未被改动
        assert json.loads(plugin.read_text(encoding="utf-8"))["version"] == "0.5.1"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_release_cc_plugin_helper.py::TestBumpFiles -v`
Expected: FAIL — `bump_version_files` 不存在 → AttributeError。

- [ ] **Step 3: 实现 bump + 接通 main**

In `release_cc_plugin_helper.py`，在 `main()` 之前插入两个函数，并把 main 的 `raise NotImplementedError(...)` 分支替换为正式写盘。

新增函数（插在 `get_changelog` 之后、`main` 之前）：

```python
def assert_versions(root: Path, expected: str) -> None:
    """断言三处版本号都 == expected，否则 raise AssertionError。"""
    plugin = json.loads((root / PLUGIN_JSON_REL).read_text(encoding="utf-8"))
    market = json.loads((root / MARKETPLACE_JSON_REL).read_text(encoding="utf-8"))
    actuals = [
        plugin["version"],
        market["metadata"]["version"],
        market["plugins"][0]["version"],
    ]
    if any(a != expected for a in actuals):
        raise AssertionError(f"写后版本号校验失败: 期望 {expected}，实际 {actuals}")


def bump_version_files(root: Path, old: str, new: str) -> list[str]:
    """原子 bump 三处版本号。返回改动文件相对路径列表。任一命中数不符则不写并 raise ValueError。"""
    targets = [
        (root / PLUGIN_JSON_REL, 1),
        (root / MARKETPLACE_JSON_REL, 2),
    ]
    needle = f'"version": "{old}"'
    replacement = f'"version": "{new}"'
    pending = []  # (path, new_text, rel)
    for path, expected_count in targets:
        text = path.read_text(encoding="utf-8")
        count = text.count(needle)
        if count != expected_count:
            raise ValueError(
                f"{path.relative_to(root)} 命中 {count} 次（期望 {expected_count}），"
                f"版本号 {old}。中止，未写任何文件。"
            )
        pending.append((path, text.replace(needle, replacement), path.relative_to(root)))
    # 全部计数校验通过才落盘
    for path, new_text, _ in pending:
        path.write_text(new_text, encoding="utf-8")
    assert_versions(root, new)  # 写后兜底断言
    return [str(rel) for _, _, rel in pending]
```

替换 `main()` 末尾的 `raise NotImplementedError("bump 写入在 Task 2 实现")` 为：

```python
    try:
        changed = bump_version_files(PROJECT_ROOT, current, new)
    except (ValueError, AssertionError) as e:
        output_error(str(e))

    output_json(
        {
            "current_version": current,
            "new_version": new,
            "changed_files": changed,
            "changelog_summary": changelog,
        }
    )
```

- [ ] **Step 4: 跑全部测试确认通过**

Run: `uv run pytest tests/unit/test_release_cc_plugin_helper.py -v`
Expected: 12 passed（原 10 + TestBumpFiles ×2）。

- [ ] **Step 5: 提交**

```bash
git add .claude/skills/release-cc-plugin/release_cc_plugin_helper.py tests/unit/test_release_cc_plugin_helper.py
git commit -m "feat(release-cc-plugin): helper 原子 bump 三字段 + 写后断言"
```

---

## Task 3: SKILL.md 流程编排

**Files:**
- Create: `.claude/skills/release-cc-plugin/SKILL.md`

**Interfaces:**
- Consumes: helper 的 `--dry-run` + 正式模式 JSON 契约（Task 1/2）

- [ ] **Step 1: 写 SKILL.md**

Create `.claude/skills/release-cc-plugin/SKILL.md`:

```markdown
---
name: release-cc-plugin
description: Release a new version of the cc-plugin (Claude Code marketplace). Bumps the three version fields in lockstep, opens a PR. Triggers on "发 cc-plugin", "plugin 发版", "release cc plugin", "bump plugin version", "发布 cc 插件".
---

# Release cc-plugin Skill

把 cc-plugin 发版流程固化：三处版本号同步 bump → PR 合 main。**不打 tag、不发 PyPI**
（`.claude-plugin/marketplace.json` 的 `source` 指向仓库内 `./packages/cc-plugin`，合 main 后用户 `/plugin update` 自动拉新）。

⚠️ 这是 **cc-plugin** 发版（marketplace，0.5.x）。CLI/PyPI 发版（1.x.x）用 `/release`。
kimi-plugin 是另一条轨道，本 skill 不管。

## 用法

```
/release-cc-plugin patch     # bump patch: 0.5.1 → 0.5.2
/release-cc-plugin minor     # bump minor: 0.5.1 → 0.6.0
/release-cc-plugin major     # bump major: 0.5.1 → 1.0.0
/release-cc-plugin 0.7.0     # 指定版本
```

默认建议 patch（无新 skill/command → semver patch）。

## 执行流程

严格按步，每步完成才进下一步。

### Step 1: 前置校验

任一不符即停并告知原因。

```bash
git branch --show-current                              # 期望 main
git status --porcelain                                 # 期望 空
git branch --list 'chore/bump-cc-plugin-*'             # 期望 空
gh pr list --state open --head "chore/bump-cc-plugin-*"  # 期望 空
```

### Step 2: dry-run 预览

```bash
uv run python .claude/skills/release-cc-plugin/release_cc_plugin_helper.py <version> --dry-run
```

解析 JSON：`current_version` / `new_version` / `files_to_change` / `changelog_summary`。

### Step 3: 展示并等确认

向用户展示：

```
📦 cc-plugin Release 预览:
  当前版本: {current_version}
  新版本号: {new_version}
  changelog:
  {changelog_summary 逐行}

将修改（三处同步，由 helper 原子 bump）:
  - packages/cc-plugin/.claude-plugin/plugin.json
  - .claude-plugin/marketplace.json（metadata.version + plugins[0].version）
```

**必须等用户明确确认。** 拒绝或要改则停。

### Step 4: 正式 bump

```bash
uv run python .claude/skills/release-cc-plugin/release_cc_plugin_helper.py <version>
```

退出码非 0 → 读 error JSON，告知用户，停。

### Step 5: 分支 / commit / push

```bash
git checkout -b chore/bump-cc-plugin-{new_version}
git add packages/cc-plugin/.claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "chore(cc-plugin): bump version {current_version} → {new_version}"
git push -u origin chore/bump-cc-plugin-{new_version}
```

### Step 6: 开 PR

```bash
gh pr create --title "chore(cc-plugin): bump version {current} → {new}" --body "<changelog>"
```

PR body 用 `changelog_summary` 作 release notes，并注明「合 main 后 `/plugin update` 自动拉新，无需 tag/PyPI」。

### Step 7: 告知用户合并

```
PR 已创建: {URL}
合并即生效（用户 /plugin update 拉新）。不打 tag、不发 Release。
```

等用户手动合并。**不自动创建 tag / GitHub Release。**

## 注意

- 三处版本号由 helper 原子 bump（命中数不符报错不写），堵 CLAUDE.md 点名的「漏改任一处」坑。
- 不要用 `/release`（那是 CLI/PyPI）。
- 合 main 即发布；如需追溯可手动 `gh release create cc-plugin-v<x>`，但非默认。
```

- [ ] **Step 2: 人工通读校验**

检查：流程自洽（7 步无悬挂引用）、确认点齐全（Step 3 必须等用户）、与 `/release` SKILL.md 风格一致、frontmatter `name: release-cc-plugin` 与目录名一致。

- [ ] **Step 3: 提交**

```bash
git add .claude/skills/release-cc-plugin/SKILL.md
git commit -m "feat(release-cc-plugin): SKILL.md 流程编排"
```

---

## Task 4: 端到端 smoke + PR

**Files:** 无新增（验证 + 发 PR）

- [ ] **Step 1: 真实仓库 dry-run 冒烟**

Run: `uv run python .claude/skills/release-cc-plugin/release_cc_plugin_helper.py patch --dry-run`
Expected: JSON，`current_version == "0.5.1"`、`new_version == "0.5.2"`、`files_to_change` 两项、`changelog_summary` 非空列表（含 #312 session-summary 等提交）。

- [ ] **Step 2: 全量单测**

Run: `uv run pytest tests/unit/test_release_cc_plugin_helper.py -v`
Expected: 12 passed。

- [ ] **Step 3: lint**

Run: `uv run ruff check .claude/skills/release-cc-plugin/ tests/unit/test_release_cc_plugin_helper.py`
Expected: 无错误。

- [ ] **Step 4: 重命名分支 + 推送**

```bash
git branch -m feat/release-cc-plugin-skill   # worktree 分支改名对齐 spec
git push -u origin feat/release-cc-plugin-skill
```

- [ ] **Step 5: 开 PR**

```bash
gh pr create --base main --head feat/release-cc-plugin-skill \
  --title "feat(release-cc-plugin): 新增 cc-plugin 发版 skill" \
  --body "<见下>"
```

PR body：

```markdown
## 背景

仓库已有 `.claude/skills/release`（CLI/PyPI 专用），不管 cc-plugin。本 PR 新增 `.claude/skills/release-cc-plugin/`，把 cc-plugin marketplace 发版流程（三处版本号同步 bump + PR 合 main）固化。

流程源自 cc-plugin 0.5.0 → 0.5.1 发版（#313）。

## 改动

- `release_cc_plugin_helper.py`：版本计算 + 原子 bump 三字段（命中数校验 + 写后断言）+ git log changelog + `--dry-run`
- `SKILL.md`：流程编排（校验 → dry-run 预览 → 用户确认 → bump → 分支/PR），不打 tag / 不发 PyPI
- `tests/unit/test_release_cc_plugin_helper.py`：12 项单测（subprocess 镜像 release_helper + importlib 隔离写盘）

## 设计文档

- Spec：`docs/superpowers/specs/2026-07-12-release-cc-plugin-skill-design.md`
- Plan：`docs/superpowers/plans/2026-07-12-release-cc-plugin-skill.md`

## 验证

- [x] `uv run pytest tests/unit/test_release_cc_plugin_helper.py -v` → 12 passed
- [x] 真实仓库 dry-run：0.5.1 → 0.5.2，changelog 含 #312
- [x] `ruff check` 无错

🤖 Generated with [Claude Code](https://claude.com/claude-code)
```

- [ ] **Step 6: 告知用户**

PR 创建后告知 URL，等用户 review/合并。合 main 后下次发 cc-plugin 即可用 `/release-cc-plugin`。
