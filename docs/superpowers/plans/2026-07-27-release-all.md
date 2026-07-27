# /release-all 统一发版编排 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 新增 `/release-all` 编排 skill，一条命令检测三组件未发布改动、跳过无改动者、批量建 PR、最后发 jfox Release；顺带补 kimi helper(+skill)，并把 #333 的 verify 折进 `release_helper.py`。

**Architecture:** 编排层（`release_all_helper.py detect`）只做检测，发版动作复用三组件 helper；verify 作为 `release_helper.py` 的子命令，`/release` 与 `/release-all` 共用。三组件独立 PR、独立版本轨道不变。

**Tech Stack:** Python 3.10+、stdlib only（json/re/subprocess/pathlib/argparse）、pytest、git CLI。

## Global Constraints

- 行宽 100（black + ruff）；中文注释。
- 新 helper 放 `.claude/skills/<skill>/`，脚本 `PROJECT_ROOT = Path(__file__).resolve().parents[3]`。
- 测试 flat 放 `tests/unit/`（与现有 `test_release_helper.py` / `test_release_cc_plugin_helper.py` 一致）。
- helper 通过 stdout JSON 通信，错误走 `{"error": ...}` + `sys.exit(1)`。
- 版本号护栏：新版本必须严格 > 当前（不允许降级/同号）。
- 提交前必跑 `ruff check` **和** `black --check`（CI 跑两步）。
- windows 路径：测试用 `str(Path(...))`，不硬编码 unix 串。

---

## File Structure

新增：
- `.claude/skills/release-kimi-plugin/release_kimi_plugin_helper.py` — kimi 发版 helper（单一 version 字段，镜像 cc）
- `.claude/skills/release-kimi-plugin/SKILL.md` — kimi 发版 skill（镜像 cc SKILL）
- `.claude/skills/release-all/release_all_helper.py` — 编排检测层（detect 子命令）
- `.claude/skills/release-all/SKILL.md` — 编排 skill 散文
- `tests/unit/test_release_helper_verify.py` — verify 逻辑测试
- `tests/unit/test_release_kimi_plugin_helper.py` — kimi helper 测试
- `tests/unit/test_release_all_helper.py` — detect 逻辑测试

修改：
- `.claude/skills/release/release_helper.py` — 加 verify 子命令 + main 分发
- `.claude/skills/release/SKILL.md` — Step 9 前插 verify 步骤
- `CLAUDE.md` — 发版相关段落补 `/release-all`、`/release-kimi-plugin`、verify（doc drift 防御）

---

## Task 1: release_helper.py 加 verify 子命令（关 #333）

**Files:**
- Modify: `.claude/skills/release/release_helper.py`
- Test: `tests/unit/test_release_helper_verify.py`

**Interfaces:**
- Produces: `verify(root: Path | None = None) -> dict` 返回 `{"ok": bool, "missing": list[int], "extra": list[int], "functional_commits": int}`；`functional_commits_since_last_tag(root) -> list[str]`；`changelog_top_prs(root) -> set[int]`。CLI: `python release_helper.py verify` → 退出码 0(ok) / 1(missing)。

- [ ] **Step 1: 写 verify 失败测试**

Create `tests/unit/test_release_helper_verify.py`:

```python
"""release_helper.py verify 子命令测试（#333 CHANGELOG 漂移校验）"""

import importlib.util
import json
import subprocess
from pathlib import Path

HELPER = str(
    Path(__file__).resolve().parents[2] / ".claude" / "skills" / "release" / "release_helper.py"
)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_helper_module():
    spec = importlib.util.spec_from_file_location("release_helper", HELPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _git_repo(tmp_path: Path, commits: list[str], tag: str = "v0.1.0"):
    """在 tmp_path 建最小 git 仓：init + commits（每条 subject）+ 打 tag。"""
    env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True, env=env)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(tmp_path), check=True)
    for i, msg in enumerate(commits):
        (tmp_path / f"f{i}.txt").write_text(str(i), encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
        subprocess.run(["git", "commit", "-q", "-m", msg], cwd=str(tmp_path),
                       check=True, env=env)
    subprocess.run(["git", "tag", tag], cwd=str(tmp_path), check=True)
    return tag


def _write_changelog(tmp_path: Path, prs: list[int], version: str = "0.2.0"):
    cl = tmp_path / "CHANGELOG.md"
    body = "\n".join(f"- something (#{p})" for p in prs)
    cl.write_text(
        f"# Changelog\n\n## [{version}] - 2026-07-27\n\n{body}\n\n## [0.1.0] - 2026-07-01\n\n- old (#1)\n",
        encoding="utf-8",
    )


class TestVerify:
    def test_ok_when_changelog_covers_all_functional_prs(self, tmp_path):
        mod = _load_helper_module()
        _git_repo(tmp_path, ["feat: a (#101)", "fix: b (#102)"], tag="v0.1.0")
        # tag 之后再来两个功能 commit
        env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        for i, msg in enumerate(["feat: c (#103)", "fix: d (#104)"]):
            (tmp_path / f"g{i}.txt").write_text(str(i), encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
            subprocess.run(["git", "commit", "-q", "-m", msg], cwd=str(tmp_path),
                           check=True, env=env)
        _write_changelog(tmp_path, [103, 104])
        res = mod.verify(tmp_path)
        assert res["ok"] is True
        assert res["missing"] == []

    def test_missing_when_changelog_lags(self, tmp_path):
        mod = _load_helper_module()
        _git_repo(tmp_path, ["feat: a (#101)"], tag="v0.1.0")
        env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        (tmp_path / "g.txt").write_text("x", encoding="utf-8")
        subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
        subprocess.run(["git", "commit", "-q", "-m", "feat: b (#202)"],
                       cwd=str(tmp_path), check=True, env=env)
        _write_changelog(tmp_path, [101])  # 漏了 202
        res = mod.verify(tmp_path)
        assert res["ok"] is False
        assert 202 in res["missing"]

    def test_chore_and_bump_commits_excluded(self, tmp_path):
        mod = _load_helper_module()
        _git_repo(tmp_path, ["feat: a (#101)"], tag="v0.1.0")
        env = {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
               "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t"}
        for i, msg in enumerate(["chore: x (#303)", "chore: bump version to 0.2.0 (#304)"]):
            (tmp_path / f"h{i}.txt").write_text(str(i), encoding="utf-8")
            subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
            subprocess.run(["git", "commit", "-q", "-m", msg], cwd=str(tmp_path),
                           check=True, env=env)
        _write_changelog(tmp_path, [])  # CHANGELOG 只含非功能 → 不应 missing
        res = mod.verify(tmp_path)
        assert res["ok"] is True
        assert res["missing"] == []


class TestVerifyCLI:
    def test_cli_returns_json_with_ok_key(self):
        e = {"PYTHONUTF8": "1"}
        import os
        e = {**os.environ, "PYTHONUTF8": "1"}
        result = subprocess.run(
            ["python", HELPER, "verify"], capture_output=True, text=True,
            cwd=str(PROJECT_ROOT), env=e, encoding="utf-8", errors="replace",
        )
        data = json.loads(result.stdout.strip())
        assert "ok" in data and "missing" in data
        assert result.returncode in (0, 1)
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_release_helper_verify.py -v`
Expected: FAIL — `verify` 不存在（AttributeError）。

- [ ] **Step 3: 实现 verify**

Modify `.claude/skills/release/release_helper.py` — 在 `main()` 之前插入：

```python
def _git(args: list[str], cwd: Path) -> subprocess.CompletedProcess:
    """git 调用封装（verify 用，cwd 可注入便于测试）。"""
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", "-c", "i18n.logoutputencoding=utf-8", *args],
        cwd=str(cwd),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def functional_commits_since_last_tag(root: Path) -> list[str]:
    """last v* tag..HEAD 的功能类 commit subject。

    功能类 = conventional type 属于 feat/fix/refactor/docs/perf（含 other 非 conventional）；
    排除 chore/test/style/ci/build 与含 "bump version" 的提交。
    """
    out = _git(["describe", "--tags", "--abbrev=0", "--match", "v*"], root)
    tag = out.stdout.strip() if out.returncode == 0 else ""
    rng = f"{tag}..HEAD" if tag else "HEAD"
    out = _git(["log", rng, "--format=%s"], root)
    excluded = {"chore", "test", "style", "ci", "build"}
    result = []
    for line in out.stdout.splitlines():
        s = line.strip()
        if not s or "bump version" in s.lower():
            continue
        m = re.match(r"^(\w+)(?:\([^)]*\))?:", s)
        ctype = m.group(1).lower() if m else ""
        if ctype in excluded:
            continue
        result.append(s)
    return result


def changelog_top_prs(root: Path) -> set[int]:
    """解析 CHANGELOG.md 最新版本段（首个 ## [ ... 到下一个 ## [）内的 (#NNN) 集合。"""
    cl = root / "CHANGELOG.md"
    if not cl.exists():
        return set()
    text = cl.read_text(encoding="utf-8")
    m = re.search(
        r"^##\s*\[[^\]]+\][^\n]*\n(.*?)(?=^##\s*\[|\Z)",
        text,
        re.MULTILINE | re.DOTALL,
    )
    section = m.group(1) if m else text
    return {int(x) for x in re.findall(r"\(#(\d+)\)", section)}


def verify(root: Path | None = None) -> dict:
    """#333：创建 Release 前核对 last_tag..HEAD 功能 commit 的 PR 号是否都被 CHANGELOG 顶段收录。

    返回 {"ok": bool, "missing": sorted[int], "extra": sorted[int], "functional_commits": int}。
    ok=False 表示有功能 commit 的 PR 未进 CHANGELOG（漂移），应阻止发 Release。
    """
    root = Path(root) if root else PROJECT_ROOT
    func_prs: set[int] = set()
    for s in functional_commits_since_last_tag(root):
        for x in re.findall(r"\(#(\d+)\)", s):
            func_prs.add(int(x))
    cl_prs = changelog_top_prs(root)
    missing = sorted(func_prs - cl_prs)
    extra = sorted(cl_prs - func_prs)
    return {
        "ok": not missing,
        "missing": missing,
        "extra": extra,
        "functional_commits": len(func_prs),
    }
```

Modify `main()` — 在函数体最前面插入 verify 分支（在 `if len(sys.argv) < 2:` 之前）：

```python
def main():
    if len(sys.argv) >= 2 and sys.argv[1] == "verify":
        res = verify()
        output_json(res)
        sys.exit(0 if res["ok"] else 1)

    if len(sys.argv) < 2:
        output_error("用法: release_helper.py <version|patch|minor|major|verify> [--dry-run]")
    # ... 其余不变
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_release_helper_verify.py -v`
Expected: PASS（4 项）。

- [ ] **Step 5: 跑现有 release_helper 测试确认无回归**

Run: `uv run pytest tests/unit/test_release_helper.py -v`
Expected: PASS。

- [ ] **Step 6: 提交**

```bash
git add .claude/skills/release/release_helper.py tests/unit/test_release_helper_verify.py
git commit -m "feat(release): #333 release_helper 加 verify 子命令（CHANGELOG 漂移校验）"
```

---

## Task 2: release_kimi_plugin_helper.py + SKILL.md（镜像 cc）

**Files:**
- Create: `.claude/skills/release-kimi-plugin/release_kimi_plugin_helper.py`
- Create: `.claude/skills/release-kimi-plugin/SKILL.md`
- Test: `tests/unit/test_release_kimi_plugin_helper.py`

**Interfaces:**
- Produces: CLI `python release_kimi_plugin_helper.py <version> [--dry-run]` → JSON `{current_version, new_version, files_to_change|changed_files, changelog_summary}`。函数 `read_current_version(root)`、`compute_new_version(current, spec)`、`bump_version_files(root, old, new)`、`get_changelog(root, current)`、`assert_versions(root, expected)`。
- Consumes: 无（独立轨道）。

- [ ] **Step 1: 写 kimi helper 失败测试**

Create `tests/unit/test_release_kimi_plugin_helper.py`:

```python
"""release_kimi_plugin_helper.py 单元测试"""

import importlib.util
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

HELPER = str(
    Path(__file__).resolve().parents[2]
    / ".claude" / "skills" / "release-kimi-plugin" / "release_kimi_plugin_helper.py"
)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _run_helper(*args, env=None):
    import os
    e = env or {**os.environ, "PYTHONUTF8": "1"}
    result = subprocess.run(
        ["python", HELPER, *args], capture_output=True, text=True,
        cwd=str(PROJECT_ROOT), env=e, encoding="utf-8", errors="replace",
    )
    return result.stdout, result.stderr, result.returncode


def _parse_json(stdout):
    return json.loads(stdout.strip())


def _load_helper_module():
    spec = importlib.util.spec_from_file_location("release_kimi_plugin_helper", HELPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod
```

（`import subprocess` 加在文件顶部。）

```python
class TestDryRun:
    def test_patch_bump(self):
        data = _parse_json(_run_helper("patch", "--dry-run")[0])
        cur = [int(x) for x in data["current_version"].split(".")]
        new = [int(x) for x in data["new_version"].split(".")]
        assert new == [cur[0], cur[1], cur[2] + 1]

    def test_files_to_change_single(self):
        data = _parse_json(_run_helper("patch", "--dry-run")[0])
        assert data["files_to_change"] == ["packages/kimi-plugin/kimi.plugin.json"]

    def test_invalid_version_rejected(self):
        stdout, _, rc = _run_helper("0.1", "--dry-run")
        assert rc != 0
        assert "error" in _parse_json(stdout)


def _setup_repo(tmp_path: Path, ver="0.14.0"):
    p = tmp_path / "packages" / "kimi-plugin" / "kimi.plugin.json"
    p.parent.mkdir(parents=True)
    p.write_text(json.dumps({"name": "jfox", "version": ver}, indent=2),
                 encoding="utf-8")
    return p


class TestBumpFiles:
    def test_bump_single_field(self, tmp_path):
        mod = _load_helper_module()
        p = _setup_repo(tmp_path)
        changed = mod.bump_version_files(tmp_path, "0.14.0", "0.15.0")
        assert json.loads(p.read_text(encoding="utf-8"))["version"] == "0.15.0"
        assert "kimi.plugin.json" in changed[0]

    def test_count_mismatch_no_write(self, tmp_path):
        """version 字段命中数 ≠ 1 → 报错且不写"""
        mod = _load_helper_module()
        p = _setup_repo(tmp_path)
        txt = p.read_text(encoding="utf-8").replace(
            '"version": "0.14.0"', '"versionX": "0.14.0"', 1)
        p.write_text(txt, encoding="utf-8")
        with pytest.raises(ValueError):
            mod.bump_version_files(tmp_path, "0.14.0", "0.15.0")

    def test_downgrade_rejected(self, tmp_path):
        mod = _load_helper_module()
        _setup_repo(tmp_path, "0.14.0")
        with pytest.raises(ValueError):
            mod.compute_new_version("0.14.0", "0.13.0")


class TestChangelog:
    def test_get_changelog_parses_git_log(self, tmp_path):
        mod = _load_helper_module()
        fake = MagicMock(stdout="abc1234 feat: x\ndef5678 fix: y\n", returncode=0)
        with patch.object(mod.subprocess, "run", return_value=fake):
            result = mod.get_changelog(tmp_path, "0.14.0")
        assert result == ["abc1234 feat: x", "def5678 fix: y"]
```

（测试文件顶部 import 块：`import importlib.util, json, subprocess` + `from pathlib import Path` + `from unittest.mock import MagicMock, patch` + `import pytest`。）

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_release_kimi_plugin_helper.py -v`
Expected: FAIL — helper 文件不存在（collect error）。

- [ ] **Step 3: 实现 kimi helper**

Create `.claude/skills/release-kimi-plugin/release_kimi_plugin_helper.py`:

```python
#!/usr/bin/env python3
"""
kimi-plugin release 辅助脚本

单一 version 字段（packages/kimi-plugin/kimi.plugin.json）的 bump + changelog。
输出 JSON 供 Claude 解析。镜像 release_cc_plugin_helper.py，差异：仅一处版本号。

用法:
    python release_kimi_plugin_helper.py patch          # bump patch
    python release_kimi_plugin_helper.py minor          # bump minor
    python release_kimi_plugin_helper.py major          # bump major
    python release_kimi_plugin_helper.py 0.15.0         # 指定版本
    python release_kimi_plugin_helper.py ... --dry-run  # 只计算不修改文件
"""

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

# 项目根目录（脚本位于 .claude/skills/release-kimi-plugin/，向上 3 级）
PROJECT_ROOT = Path(__file__).resolve().parents[3]
KIMI_PLUGIN_JSON_REL = "packages/kimi-plugin/kimi.plugin.json"
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def output_json(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False))


def output_error(msg: str) -> None:
    output_json({"error": msg})
    sys.exit(1)


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def read_current_version(root: Path) -> str:
    """读 kimi.plugin.json 的 version（单一真相源）。"""
    data = json.loads((root / KIMI_PLUGIN_JSON_REL).read_text(encoding="utf-8"))
    return data["version"]


def compute_new_version(current: str, spec: str) -> str:
    """patch/minor/major 递增或 explicit x.y.z；结果必须 > current。"""
    if not VERSION_RE.match(current):
        raise ValueError(f"非法当前版本号: {current!r}")
    if spec in ("patch", "minor", "major"):
        major, minor, patch = _version_tuple(current)
        if spec == "patch":
            new = f"{major}.{minor}.{patch + 1}"
        elif spec == "minor":
            new = f"{major}.{minor + 1}.0"
        else:
            new = f"{major + 1}.0.0"
    elif VERSION_RE.match(spec):
        new = spec
    else:
        raise ValueError(f"非法版本号规格: {spec!r}（需 patch/minor/major 或 x.y.z）")
    if _version_tuple(new) <= _version_tuple(current):
        raise ValueError(f"新版本 {new} 须大于当前 {current}（不允许降级/同号）")
    return new


def find_last_bump_commit(root: Path, current_version: str) -> str:
    """定位上次发版提交：引入 current_version 的提交；降级为最近改 kimi.plugin.json 的提交。"""
    rel = KIMI_PLUGIN_JSON_REL
    for args in (
        ["git", "log", "-S", f'"version": "{current_version}"', "--format=%H", "--", rel],
        ["git", "log", "--format=%H", "-1", "--", rel],
    ):
        try:
            out = subprocess.run(
                args, cwd=root, capture_output=True, text=True,
                encoding="utf-8", errors="replace", check=True,
            )
        except subprocess.CalledProcessError:
            continue
        hits = [ln for ln in out.stdout.splitlines() if ln.strip()]
        if hits:
            return hits[0]
    return ""


def get_changelog(root: Path, current_version: str) -> list[str]:
    """自上次发版以来 packages/kimi-plugin/ 的 oneline 提交摘要；无基线时取最近 30 条。"""
    last = find_last_bump_commit(root, current_version)
    if last:
        args = ["git", "log", "--oneline", f"{last}..HEAD", "--", "packages/kimi-plugin/"]
    else:
        args = ["git", "log", "--oneline", "--max-count=30", "--", "packages/kimi-plugin/"]
    try:
        out = subprocess.run(
            args, cwd=root, capture_output=True, text=True,
            encoding="utf-8", errors="replace", check=True,
        )
    except subprocess.CalledProcessError:
        return []
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


def assert_versions(root: Path, expected: str) -> None:
    """写后断言 version == expected。"""
    data = json.loads((root / KIMI_PLUGIN_JSON_REL).read_text(encoding="utf-8"))
    if data["version"] != expected:
        raise AssertionError(
            f"写后版本号校验失败: 期望 {expected}，实际 {data['version']}"
        )


def _read_raw(path: Path) -> str:
    return path.read_bytes().decode("utf-8")


def _write_raw(path: Path, text: str) -> None:
    path.write_text(text, encoding="utf-8", newline="")


def bump_version_files(root: Path, old: str, new: str) -> list[str]:
    """原子 bump 单一 version 字段：计数预校验（=1）+ 落盘 + 写后断言。"""
    path = root / KIMI_PLUGIN_JSON_REL
    needle = f'"version": "{old}"'
    replacement = f'"version": "{new}"'
    original = _read_raw(path)
    count = original.count(needle)
    if count != 1:
        raise ValueError(
            f"{KIMI_PLUGIN_JSON_REL} 命中 {count} 次（期望 1），版本号 {old}。中止，未写。"
        )
    try:
        _write_raw(path, original.replace(needle, replacement))
        assert_versions(root, new)
    except Exception:
        try:
            _write_raw(path, original)
        except OSError:
            pass
        raise
    return [KIMI_PLUGIN_JSON_REL]


def main() -> None:
    parser = argparse.ArgumentParser(description="kimi-plugin release helper")
    parser.add_argument("version", help="patch | minor | major | x.y.z")
    parser.add_argument("--dry-run", action="store_true", help="只计算不修改文件")
    args = parser.parse_args()

    try:
        current = read_current_version(PROJECT_ROOT)
    except (json.JSONDecodeError, UnicodeDecodeError, KeyError,
            FileNotFoundError, PermissionError, OSError) as e:
        output_error(f"读取当前版本失败: {e}")

    try:
        new = compute_new_version(current, args.version)
    except ValueError as e:
        output_error(str(e))

    changelog = get_changelog(PROJECT_ROOT, current)

    if args.dry_run:
        output_json({
            "current_version": current,
            "new_version": new,
            "files_to_change": [KIMI_PLUGIN_JSON_REL],
            "changelog_summary": changelog,
        })
        return

    try:
        changed = bump_version_files(PROJECT_ROOT, current, new)
    except (ValueError, AssertionError, KeyError, IndexError,
            OSError, json.JSONDecodeError) as e:
        output_error(str(e))

    output_json({
        "current_version": current,
        "new_version": new,
        "changed_files": changed,
        "changelog_summary": changelog,
    })


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_release_kimi_plugin_helper.py -v`
Expected: PASS。

- [ ] **Step 5: 写 kimi SKILL.md**

Create `.claude/skills/release-kimi-plugin/SKILL.md` — 镜像 `.claude/skills/release-cc-plugin/SKILL.md`，差异：

```markdown
---
name: release-kimi-plugin
description: Release a new version of the kimi-plugin (Kimi Code 集成). Bumps the single version field in kimi.plugin.json, opens a PR. Triggers on "发 kimi-plugin", "release kimi plugin", "bump kimi version", "发布 kimi 插件".
---

# Release kimi-plugin Skill

把 kimi-plugin 发版流程固化：单一版本号 bump → PR 合 main。**不打 tag、不发 Release、不发 PyPI**
（合 main 后用户拉新即生效）。

⚠️ 这是 **kimi-plugin** 发版（0.14.x）。CLI/PyPI 发版用 `/release`；cc-plugin 用 `/release-cc-plugin`。

## 用法

\`\`\`
/release-kimi-plugin patch    # 0.14.0 → 0.14.1
/release-kimi-plugin minor    # 0.14.0 → 0.15.0
/release-kimi-plugin 0.15.0   # 指定版本
\`\`\`

默认建议 patch（无新 skill → semver patch）。

## 执行流程

### Step 1: 前置校验
\`\`\`bash
git branch --show-current                                # 期望 main
git status --porcelain                                   # 期望 空
git branch --list 'chore/bump-kimi-plugin-*'             # 期望 空
gh pr list --state open --head "chore/bump-kimi-plugin-*"  # 期望 空
\`\`\`

### Step 2: dry-run 预览
\`\`\`bash
uv run python .claude/skills/release-kimi-plugin/release_kimi_plugin_helper.py <version> --dry-run
\`\`\`
解析 JSON：current_version / new_version / files_to_change / changelog_summary。

### Step 3: 展示并等确认
展示 current→new、changelog_summary、将修改 `packages/kimi-plugin/kimi.plugin.json`（单一字段，helper 原子 bump）。**等用户明确确认。**

### Step 4: 正式 bump
\`\`\`bash
uv run python .claude/skills/release-kimi-plugin/release_kimi_plugin_helper.py <version>
\`\`\`

### Step 5: 分支 / commit / push
\`\`\`bash
git checkout -b chore/bump-kimi-plugin-{new_version}
git add packages/kimi-plugin/kimi.plugin.json
git commit -m "chore(kimi-plugin): bump version {current_version} → {new_version}"
git push -u origin chore/bump-kimi-plugin-{new_version}
\`\`\`

### Step 6: 开 PR
\`\`\`bash
gh pr create --title "chore(kimi-plugin): bump version {current_version} → {new_version}" --body "<changelog>"
\`\`\`

### Step 7: 告知用户合并
合 main 即生效。不打 tag、不发 Release。

## 注意
- 单一 version 字段由 helper 原子 bump（命中数 ≠ 1 报错不写）。
- 三轨道之一；与 `/release`（CLI/PyPI）、`/release-cc-plugin`（cc marketplace）并列。
```

- [ ] **Step 6: 提交**

```bash
git add .claude/skills/release-kimi-plugin/ tests/unit/test_release_kimi_plugin_helper.py
git commit -m "feat(release): #334 新增 /release-kimi-plugin（镜像 cc，单一 version 字段）"
```

---

## Task 3: release_all_helper.py detect（编排检测层）

**Files:**
- Create: `.claude/skills/release-all/release_all_helper.py`
- Test: `tests/unit/test_release_all_helper.py`

**Interfaces:**
- Produces: CLI `python release_all_helper.py [detect]` → JSON `{components: [...], any_changed: bool}`，每组件 `{name, changed, current_version, baseline, commits, suggested_bump?, suggested_version?, skip_reason?}`。函数 `detect(root) -> dict`、`detect_jfox(root)`、`detect_cc(root)`、`detect_kimi(root)`。
- Consumes: 三组件版本文件路径（pyproject.toml / plugin.json / kimi.plugin.json）+ git。

- [ ] **Step 1: 写 detect 失败测试**

Create `tests/unit/test_release_all_helper.py`:

```python
"""release_all_helper.py detect 测试"""

import importlib.util
import json
import subprocess
from pathlib import Path

HELPER = str(
    Path(__file__).resolve().parents[2]
    / ".claude" / "skills" / "release-all" / "release_all_helper.py"
)
PROJECT_ROOT = Path(__file__).resolve().parents[2]


def _load_helper_module():
    spec = importlib.util.spec_from_file_location("release_all_helper", HELPER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


_GIT_ENV = {
    "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t",
    "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@t",
}


def _git_repo(tmp_path: Path):
    subprocess.run(["git", "init", "-q"], cwd=str(tmp_path), check=True, env=_GIT_ENV)
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(tmp_path), check=True)


def _commit(tmp_path: Path, msg: str, files: dict[str, str]):
    for rel, content in files.items():
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=str(tmp_path), check=True)
    subprocess.run(["git", "commit", "-q", "-m", msg], cwd=str(tmp_path),
                   check=True, env=_GIT_ENV)


def _pyproject(ver):
    return f'version = "{ver}"\n'


def _plugin_json(ver):
    return json.dumps({"name": "jfox", "version": ver}, indent=2)


def _marketplace(ver):
    return json.dumps(
        {"metadata": {"version": ver}, "plugins": [{"name": "jfox", "version": ver}]},
        indent=2,
    )


def _kimi_json(ver):
    return json.dumps({"name": "jfox", "version": ver}, indent=2)


def _bootstrap_all(tmp_path, jfox="1.5.0", cc="0.6.0", kimi="0.14.0"):
    _git_repo(tmp_path)
    _commit(tmp_path, "chore: bump version to " + jfox, {
        "pyproject.toml": _pyproject(jfox),
        "jfox/__init__.py": f'__version__ = "{jfox}"\n',
    })
    subprocess.run(["git", "tag", "v" + jfox], cwd=str(tmp_path), check=True)
    _commit(tmp_path, f"chore(cc-plugin): bump version 0.5.1 → {cc}", {
        "packages/cc-plugin/.claude-plugin/plugin.json": _plugin_json(cc),
        ".claude-plugin/marketplace.json": _marketplace(cc),
    })
    _commit(tmp_path, f"chore(kimi-plugin): bump version 0.13.0 → {kimi}", {
        "packages/kimi-plugin/kimi.plugin.json": _kimi_json(kimi),
    })


class TestDetectJfox:
    def test_unchanged_when_only_tag_commit(self, tmp_path):
        mod = _load_helper_module()
        _bootstrap_all(tmp_path)
        res = mod.detect_jfox(tmp_path)
        assert res["changed"] is False
        assert "无改动" in res["skip_reason"]

    def test_changed_with_feat_suggests_minor(self, tmp_path):
        mod = _load_helper_module()
        _bootstrap_all(tmp_path)
        _commit(tmp_path, "feat(x): new (#101)", {"jfox/x.py": "1"})
        res = mod.detect_jfox(tmp_path)
        assert res["changed"] is True
        assert res["suggested_bump"] == "minor"
        assert res["suggested_version"] == "1.6.0"

    def test_changed_with_fix_suggests_patch(self, tmp_path):
        mod = _load_helper_module()
        _bootstrap_all(tmp_path)
        _commit(tmp_path, "fix(x): bug (#102)", {"jfox/y.py": "1"})
        res = mod.detect_jfox(tmp_path)
        assert res["changed"] is True
        assert res["suggested_bump"] == "patch"
        assert res["suggested_version"] == "1.5.1"

    def test_plugin_bump_commits_not_counted_as_jfox(self, tmp_path):
        """cc/kimi bump commit 在 jfox tag..HEAD 内，但含 'bump version' 应被滤掉"""
        mod = _load_helper_module()
        _bootstrap_all(tmp_path)
        # 不加任何 jfox 功能 commit → jfox 应判 unchanged
        res = mod.detect_jfox(tmp_path)
        assert res["changed"] is False


class TestDetectCcKimi:
    def test_cc_unchanged_then_changed(self, tmp_path):
        mod = _load_helper_module()
        _bootstrap_all(tmp_path)
        assert mod.detect_cc(tmp_path)["changed"] is False
        _commit(tmp_path, "docs(promote): rewrite (#342)", {
            "packages/cc-plugin/skills/promote/SKILL.md": "x"})
        assert mod.detect_cc(tmp_path)["changed"] is True

    def test_kimi_unchanged_then_changed(self, tmp_path):
        mod = _load_helper_module()
        _bootstrap_all(tmp_path)
        assert mod.detect_kimi(tmp_path)["changed"] is False
        _commit(tmp_path, "feat: k skill (#300)", {
            "packages/kimi-plugin/skills/search/SKILL.md": "x"})
        assert mod.detect_kimi(tmp_path)["changed"] is True


class TestDetectAggregate:
    def test_any_changed_and_components_count(self, tmp_path):
        mod = _load_helper_module()
        _bootstrap_all(tmp_path)
        res = mod.detect(tmp_path)
        assert len(res["components"]) == 3
        assert res["any_changed"] is False
        _commit(tmp_path, "feat: a (#1)", {"jfox/a.py": "1"})
        res2 = mod.detect(tmp_path)
        assert res2["any_changed"] is True


class TestDetectCLI:
    def test_cli_returns_three_components(self):
        import os
        e = {**os.environ, "PYTHONUTF8": "1"}
        result = subprocess.run(
            ["python", HELPER, "detect"], capture_output=True, text=True,
            cwd=str(PROJECT_ROOT), env=e, encoding="utf-8", errors="replace",
        )
        data = json.loads(result.stdout.strip())
        assert len(data["components"]) == 3
        names = [c["name"] for c in data["components"]]
        assert names == ["jfox", "cc-plugin", "kimi-plugin"]
        assert "any_changed" in data
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_release_all_helper.py -v`
Expected: FAIL — helper 不存在。

- [ ] **Step 3: 实现 detect**

Create `.claude/skills/release-all/release_all_helper.py`:

```python
#!/usr/bin/env python3
"""
release-all 编排辅助脚本：检测三组件（jfox CLI / cc-plugin / kimi-plugin）未发布改动，
跳过无改动者。只做检测，不发版、不碰文件；发版动作由各组件 helper 负责。

用法:
    python release_all_helper.py [detect]    # 默认 detect
"""

import json
import re
import subprocess
import sys
from pathlib import Path

# 项目根目录（脚本位于 .claude/skills/release-all/，向上 3 级）
PROJECT_ROOT = Path(__file__).resolve().parents[3]

PYPROJECT_TOML = "pyproject.toml"
CC_PLUGIN_JSON = "packages/cc-plugin/.claude-plugin/plugin.json"
CC_MARKETPLACE = ".claude-plugin/marketplace.json"
KIMI_PLUGIN_JSON = "packages/kimi-plugin/kimi.plugin.json"


def output_json(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False))


def _git(args: list[str], root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", "-c", "i18n.logoutputencoding=utf-8", *args],
        cwd=str(root),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _bump_version(current: str, spec: str) -> str:
    major, minor, patch = (int(x) for x in current.split("."))
    if spec == "patch":
        return f"{major}.{minor}.{patch + 1}"
    if spec == "minor":
        return f"{major}.{minor + 1}.0"
    if spec == "major":
        return f"{major + 1}.0.0"
    raise ValueError(f"非法 bump 规格: {spec}")


def _last_jfox_tag(root: Path) -> str:
    out = _git(["describe", "--tags", "--abbrev=0", "--match", "v*"], root)
    return out.stdout.strip() if out.returncode == 0 else ""


def _find_last_bump_commit(root: Path, version: str, rel_path: str) -> str:
    """定位引入该 version 的提交（git log -S），fallback 到最后改该文件的提交。"""
    needle = f'"version": "{version}"'
    for args in (
        ["log", "-S", needle, "--format=%H", "--", rel_path],
        ["log", "--format=%H", "-1", "--", rel_path],
    ):
        out = _git(args, root)
        hits = [ln for ln in out.stdout.splitlines() if ln.strip()]
        if hits:
            return hits[0]
    return ""


def _read_json_version(root: Path, rel: str) -> str:
    return json.loads((root / rel).read_text(encoding="utf-8"))["version"]


def _read_pyproject_version(root: Path) -> str:
    m = re.search(
        r'^version\s*=\s*"(\d+\.\d+\.\d+)"',
        (root / PYPROJECT_TOML).read_text(encoding="utf-8"),
        re.MULTILINE,
    )
    if not m:
        raise ValueError("未在 pyproject.toml 找到 version")
    return m.group(1)


def detect_jfox(root: Path) -> dict:
    try:
        current = _read_pyproject_version(root)
    except Exception as e:
        return {"name": "jfox", "changed": False, "current_version": "",
                "commits": [], "skip_reason": f"读取版本失败: {e}"}
    tag = _last_jfox_tag(root)
    out = _git(["log", f"{tag}..HEAD" if tag else "HEAD", "--format=%s"], root)
    subjects = [s.strip() for s in out.stdout.splitlines()
                if s.strip() and "bump version" not in s.lower()]
    if not subjects:
        return {"name": "jfox", "changed": False, "current_version": current,
                "baseline": tag, "commits": [],
                "skip_reason": f"自 {tag or '起点'} 以来无改动"}
    bump = "minor" if any(s.startswith("feat") for s in subjects) else "patch"
    return {"name": "jfox", "changed": True, "current_version": current,
            "baseline": tag, "commits": subjects, "suggested_bump": bump,
            "suggested_version": _bump_version(current, bump)}


def _detect_plugin(root: Path, name: str, ver_file: str, watch_paths: list[str]) -> dict:
    try:
        current = _read_json_version(root, ver_file)
    except Exception as e:
        return {"name": name, "changed": False, "current_version": "",
                "commits": [], "skip_reason": f"读取版本失败: {e}"}
    baseline = _find_last_bump_commit(root, current, ver_file)
    if baseline:
        out = _git(["log", "--oneline", f"{baseline}..HEAD", "--", *watch_paths], root)
    else:
        out = _git(["log", "--oneline", "--max-count=30", "--", *watch_paths], root)
    commits = [c for c in out.stdout.splitlines() if c.strip()]
    if not commits:
        return {"name": name, "changed": False, "current_version": current,
                "baseline": baseline, "commits": [],
                "skip_reason": f"自 {current} 以来无改动"}
    return {"name": name, "changed": True, "current_version": current,
            "baseline": baseline, "commits": commits,
            "suggested_bump": "patch",
            "suggested_version": _bump_version(current, "patch")}


def detect_cc(root: Path) -> dict:
    return _detect_plugin(root, "cc-plugin", CC_MARKETPLACE,
                          [CC_PLUGIN_JSON, CC_MARKETPLACE])


def detect_kimi(root: Path) -> dict:
    return _detect_plugin(root, "kimi-plugin", KIMI_PLUGIN_JSON,
                          [KIMI_PLUGIN_JSON])


def detect(root: Path) -> dict:
    comps = [detect_jfox(root), detect_cc(root), detect_kimi(root)]
    return {"components": comps, "any_changed": any(c.get("changed") for c in comps)}


def main() -> None:
    # 仅支持 detect（默认）
    output_json(detect(PROJECT_ROOT))


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_release_all_helper.py -v`
Expected: PASS。

- [ ] **Step 5: 提交**

```bash
git add .claude/skills/release-all/release_all_helper.py tests/unit/test_release_all_helper.py
git commit -m "feat(release): #334 release_all_helper detect——三组件改动检测"
```

---

## Task 4: /release-all SKILL.md + /release SKILL verify 接线

**Files:**
- Create: `.claude/skills/release-all/SKILL.md`
- Modify: `.claude/skills/release/SkILL.md`（Step 9 前插 verify）

**Interfaces:**
- Produces: `/release-all` skill 编排散文；`/release` Step 9 增加 verify gate。

- [ ] **Step 1: 写 release-all SKILL.md**

Create `.claude/skills/release-all/SKILL.md`:

```markdown
---
name: release-all
description: Release all three components (jfox CLI + cc-plugin + kimi-plugin) in one command. Detects per-component changes since last release, skips unchanged ones, batches bump PRs, then creates the jfox GitHub Release last (with CHANGELOG verify). Triggers on "全发", "release all", "三件套发版", "一起发版".
---

# Release-All Skill

一条命令编排三条独立发版轨道：jfox CLI → cc-plugin → kimi-plugin。自动检测各组件自上次发版以来的改动，**跳过无改动者**；为有改动者批量建 bump PR；用户合并后，最后发 jfox GitHub Release（带 #333 verify 校验）。

⚠️ 三组件版本轨道独立、语义各自不同。本 skill 不统一版本号，只统一编排。

## 用法

\`\`\`
/release-all              # 逐组件确认 suggested_bump
/release-all minor        # 统一指定 bump 类型（套用到所有 changed 组件）
/release-all patch
\`\`\`

## 编排模型

**批量建 PR + 最后发 jfox Release**：detect 全部 → 展示计划 → 为每个 changed 组件 bump+建 PR → 用户依次合并全部 PR → 拉最新 main → verify → 建 jfox GitHub Release。

## 执行流程

### Step 1: 前置校验（任一不符即停）
\`\`\`bash
git branch --show-current                       # 期望 main
git status --porcelain                          # 期望 空
git branch --list 'chore/bump-*'                # 期望 空（三组件任一 bump 分支都不能存在）
gh pr list --state open --head "chore/bump-*"   # 期望 空
\`\`\`

### Step 2: 检测
\`\`\`bash
uv run python .claude/skills/release-all/release_all_helper.py detect
\`\`\`

### Step 3: 展示合并计划 + 确认 bump 类型
展示 detect 结果：
\`\`\`
📦 Release-All 计划:
  jfox        1.5.0 → 1.6.0 (minor)  ✓ 有改动  [feat(backup)#339, feat(gem-synth)#335]
  cc-plugin   0.6.0 → 0.6.1 (patch)  ✓ 有改动  [docs(promote)#342]
  kimi-plugin 0.14.0                ✗ 无改动，跳过
\`\`\`
- 命令带参数（\`/release-all minor\`）→ 统一套用到所有 changed 组件。
- 否则逐组件确认 suggested_bump（用户可改 patch/minor/major 或指定 x.y.z）。
- 全部 changed=false → 打印「三组件均无未发布改动，无需发版」并结束。

### Step 4: 逐组件 bump + 建 PR（顺序 jfox → cc → kimi，仅 changed 者）
detect 已算出 suggested_version 并经确认，跳过各单组件 skill 的 dry-run 预览步，直接正式 bump → 分支 → commit → push → \`gh pr create\`：

- **jfox** → \`release_helper.py <v>\` → 分支 \`chore/bump-version-<v>\` → PR（body 用 changelog_preview）
- **cc-plugin** → \`release_cc_plugin_helper.py <v>\` → 分支 \`chore/bump-cc-plugin-<v>\` → PR
- **kimi-plugin** → \`release_kimi_plugin_helper.py <v>\` → 分支 \`chore/bump-kimi-plugin-<v>\` → PR

三组件文件不冲突，PR 可并存。收集所有 PR URL。

### Step 5: 告知用户合并
\`\`\`
已创建 N 个 bump PR：
  - jfox:       <URL>
  - cc-plugin:  <URL>
  - kimi-plugin: <URL>
请依次合并后告知我，我将继续创建 jfox GitHub Release（cc/kimi 合 main 即生效，无需 Release）。
\`\`\`
等待用户确认全部合并。**只有 jfox 在计划内时才需要合并后回流；若 jfox 被跳过，cc/kimi 合完即结束。**

### Step 6: 发 jfox Release（仅当 jfox 在计划内）
\`\`\`bash
git checkout main && git pull origin main
uv run python .claude/skills/release/release_helper.py verify    # #333 兜底
# verify 退出码 0 才继续：
gh release create v<jfox_ver> --title "v<jfox_ver>" --notes "<changelog_preview>"
\`\`\`
verify 非 0 → 打印 missing 条目，**停**，提示用户补 CHANGELOG（开 docs(changelog) PR 合并）后重跑 verify + release。**不自动建 Release。**

## 跳过提示
detect 阶段 changed=false 的组件，全程打印一次「<组件> 自 <ver> 以来无改动，跳过」后不再出现。

## 错误处理
- detect 某组件异常 → 该组件 changed=false + skip_reason，继续其他组件，不中断。
- 某组件 bump 中途失败 → 已建的早期组件 PR 保留（独立），报告失败组件、停。
- 用户只合并部分 PR → Step 6 不执行，提示「还有 X 个 PR 未合并」。
- verify 非 0 → 不建 Release，打印 missing，停。

## 与单组件 skill 的关系
- \`/release\`、\`/release-cc-plugin\`、\`/release-kimi-plugin\` 不变其单组件职责。
- 本 skill 是编排层，**委托**三组件 helper，自身只做 detect + 调度 + skip + verify 串接，无特判分支。
```

- [ ] **Step 2: /release SKILL.md Step 9 前插 verify**

Modify `.claude/skills/release/SKILL.md` — 在 `### Step 9: 创建 GitHub Release` 标题之后、`gh release create` 命令之前插入：

```markdown
**先跑 verify 校验**（#333：核对 last_tag..HEAD 功能 commit 的 PR 号都已进 CHANGELOG，防漂移）：

\`\`\`bash
uv run python .claude/skills/release/release_helper.py verify
\`\`\`

退出码非 0 → 打印 missing 条目，**停止**，提示用户补 CHANGELOG（开 \`docs(changelog)\` PR 合并）后重跑本步。退出码 0 才继续创建 Release：
```

（原 `gh release create ...` 命令块保持不变，跟在上述提示之后。）

- [ ] **Step 3: 手动核对 SKILL 语法**

Run: `head -5 .claude/skills/release-all/SKILL.md && grep -n "verify" .claude/skills/release/SKILL.md`
Expected: 看到 release-all frontmatter；release SKILL 出现 verify 行。

- [ ] **Step 4: 提交**

```bash
git add .claude/skills/release-all/SKILL.md .claude/skills/release/SKILL.md
git commit -m "feat(release): #334 /release-all 编排 skill + /release Step9 接 verify"
```

---

## Task 5: CLAUDE.md 文档同步 + 全量验证

**Files:**
- Modify: `CLAUDE.md`

**Interfaces:** 无（文档）。

- [ ] **Step 1: 同步 CLAUDE.md 发版相关段落**

在 `CLAUDE.md` 的「Claude Code Plugin」段或合适位置，补一段（具体插入点实现时 grep `release-cc-plugin` / `release_helper` 定位）：

```markdown
## Release Tooling

三条独立发版轨道，各有单组件 skill + 一个编排 skill：

| 轨道 | skill | helper | 发版方式 |
|------|-------|--------|----------|
| jfox CLI | \`/release\` | \`release_helper.py\` | tag \`v*\` + GitHub Release + PyPI |
| cc-plugin | \`/release-cc-plugin\` | \`release_cc_plugin_helper.py\` | 三处原子 bump + PR，合 main 即发布 |
| kimi-plugin | \`/release-kimi-plugin\` | \`release_kimi_plugin_helper.py\` | 单一 version bump + PR，合 main 即发布 |
| 编排 | \`/release-all\` | \`release_all_helper.py\` | 检测三组件跳过无改动者、批量建 PR、最后发 jfox Release |

- \`release_helper.py verify\`（#333）：创建 jfox GitHub Release 前核对 \`last_tag..HEAD\` 功能 commit 的 PR 号是否都进 CHANGELOG，防漂移。\`/release\` Step 9 与 \`/release-all\` 都调用。
```

- [ ] **Step 2: 全量 unit 测试**

Run: `uv run pytest tests/unit/test_release_helper.py tests/unit/test_release_cc_plugin_helper.py tests/unit/test_release_helper_verify.py tests/unit/test_release_kimi_plugin_helper.py tests/unit/test_release_all_helper.py -v`
Expected: 全 PASS。

- [ ] **Step 3: lint（ruff + black 都要过）**

Run:
```bash
uv run ruff check .claude/skills/release/release_helper.py .claude/skills/release-kimi-plugin/ .claude/skills/release-all/ tests/unit/test_release_helper_verify.py tests/unit/test_release_kimi_plugin_helper.py tests/unit/test_release_all_helper.py
uv run --with black==26.3.1 black --check .claude/skills/release/release_helper.py .claude/skills/release-kimi-plugin/ .claude/skills/release-all/ tests/unit/test_release_helper_verify.py tests/unit/test_release_kimi_plugin_helper.py tests/unit/test_release_all_helper.py
```
Expected: 无错误（有则修后重跑）。

- [ ] **Step 4: 提交**

```bash
git add CLAUDE.md
git commit -m "docs(claude.md): #334 发版工具链段落补 /release-all、/release-kimi-plugin、verify"
```

---

## Self-Review（plan 写完后已自查）

- **Spec 覆盖**：detect(§3.1)=Task 3；kimi helper+skill(§3.2)=Task 2；verify(§3.3)=Task 1；release-all SKILL(§3.4)=Task 4；批量编排(§2 决策2)=Task 4 Step 4-6；测试(§6)=Task 1-3；CLAUDE.md(§7)=Task 5。全覆盖。
- **类型一致**：`detect_jfox/detect_cc/detect_kimi/detect(root)->dict`、`verify(root)->dict`、`bump_version_files(root,old,new)` 在 Task 间签名一致。
- **占位符**：无 TBD/TODO；所有代码块完整。
