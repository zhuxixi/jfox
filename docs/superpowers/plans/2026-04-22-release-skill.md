# Release Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a `/release` skill that automates jfox's version bump → CHANGELOG → commit → PR → GitHub Release workflow.

**Architecture:** Skill file (`SKILL.md`) provides step-by-step instructions for Claude. A Python helper script (`release_helper.py`) handles deterministic work: semver calculation, file updates, CHANGELOG generation. Claude orchestrates git/GitHub operations and user confirmations.

**Tech Stack:** Python 3.10+, standard library only (re, json, subprocess, pathlib). Uses `uv run` for execution context.

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `.claude/skills/release/release_helper.py` | Create | Version calculation, file updates, CHANGELOG generation. Outputs JSON. |
| `.claude/skills/release/SKILL.md` | Create | Skill instructions for Claude: pre-checks → run script → confirm → git → PR → Release. |
| `tests/unit/test_release_helper.py` | Create | Unit tests for release_helper.py. |

No existing files are modified.

---

### Task 1: release_helper.py — Version Calculation

**Files:**
- Create: `.claude/skills/release/release_helper.py`
- Test: `tests/unit/test_release_helper.py`

- [ ] **Step 1: Write failing tests for version calculation**

Create `tests/unit/test_release_helper.py`:

```python
"""release_helper.py 单元测试"""
import json
import os
import subprocess
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

# 被测模块路径
HELPER = str(
    Path(__file__).resolve().parents[2] / ".claude" / "skills" / "release" / "release_helper.py"
)


def _run_helper(*args, env=None):
    """运行 release_helper.py 并返回 (stdout, stderr, returncode)"""
    result = subprocess.run(
        ["python", HELPER, *args],
        capture_output=True,
        text=True,
        cwd=Path(__file__).resolve().parents[2],
        env=env or os.environ.copy(),
    )
    return result.stdout, result.stderr, result.returncode


def _parse_json(stdout: str) -> dict:
    return json.loads(stdout.strip())


# ── 版本号计算 ──


class TestVersionParsing:
    """测试从 pyproject.toml 读取当前版本"""

    def test_read_current_version(self):
        """能正确读取当前项目版本"""
        stdout, _, rc = _run_helper("patch", "--dry-run")
        assert rc == 0, f"stderr: {_.strip()}"
        data = _parse_json(stdout)
        assert "current_version" in data
        # 验证是 semver 格式
        parts = data["current_version"].split(".")
        assert len(parts) == 3
        assert all(p.isdigit() for p in parts)


class TestVersionBump:
    """测试 bump 类型版本号计算"""

    def test_patch_bump(self):
        stdout, _, rc = _run_helper("patch", "--dry-run")
        assert rc == 0
        data = _parse_json(stdout)
        cur = [int(x) for x in data["current_version"].split(".")]
        new = [int(x) for x in data["new_version"].split(".")]
        assert new[0] == cur[0]
        assert new[1] == cur[1]
        assert new[2] == cur[1] + 1  # patch +1

    def test_minor_bump(self):
        stdout, _, rc = _run_helper("minor", "--dry-run")
        assert rc == 0
        data = _parse_json(stdout)
        cur = [int(x) for x in data["current_version"].split(".")]
        new = [int(x) for x in data["new_version"].split(".")]
        assert new[0] == cur[0]
        assert new[1] == cur[1] + 1
        assert new[2] == 0

    def test_major_bump(self):
        stdout, _, rc = _run_helper("major", "--dry-run")
        assert rc == 0
        data = _parse_json(stdout)
        cur = [int(x) for x in data["current_version"].split(".")]
        new = [int(x) for x in data["new_version"].split(".")]
        assert new[0] == cur[0] + 1
        assert new[1] == 0
        assert new[2] == 0

    def test_explicit_version(self):
        stdout, _, rc = _run_helper("99.99.99", "--dry-run")
        assert rc == 0
        data = _parse_json(stdout)
        assert data["new_version"] == "99.99.99"


class TestVersionValidation:
    """测试版本号校验"""

    def test_invalid_bump_type(self):
        _, stderr, rc = _run_helper("foobar")
        assert rc != 0
        # 应该输出错误 JSON
        data = _parse_json(_)
        assert "error" in data

    def test_same_version_rejected(self):
        """指定当前版本应被拒绝"""
        stdout, _, rc = _run_helper("patch", "--dry-run")
        data = _parse_json(stdout)
        current = data["current_version"]
        _, stderr, rc2 = _run_helper(current)
        assert rc2 != 0
        data2 = _parse_json(_)
        assert "error" in data2

    def test_lower_version_rejected(self):
        """指定比当前更低的版本应被拒绝"""
        stdout, _, _ = _run_helper("patch", "--dry-run")
        data = _parse_json(stdout)
        cur_parts = [int(x) for x in data["current_version"].split(".")]
        lower = f"{cur_parts[0]}.{cur_parts[1]}.{max(0, cur_parts[2] - 1)}"
        _, stderr, rc = _run_helper(lower)
        assert rc != 0
        data2 = _parse_json(_)
        assert "error" in data2

    def test_invalid_semver_rejected(self):
        """非 semver 格式应被拒绝"""
        _, stderr, rc = _run_helper("1.2")
        assert rc != 0
        data = _parse_json(_)
        assert "error" in data
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/test_release_helper.py -v`
Expected: FAIL — module not found

- [ ] **Step 3: Implement version calculation with `--dry-run` support**

Create `.claude/skills/release/release_helper.py` with the following structure:

```python
#!/usr/bin/env python3
"""
jfox release 辅助脚本

处理版本号计算、文件更新、CHANGELOG 生成。
输出 JSON 供 Claude 解析。

用法:
    python release_helper.py patch          # bump patch
    python release_helper.py minor          # bump minor
    python release_helper.py major          # bump major
    python release_helper.py 0.5.0          # 指定版本
    python release_helper.py ... --dry-run  # 只计算不修改文件
"""
import json
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

# 项目根目录（脚本位于 .claude/skills/release/，向上 3 级）
PROJECT_ROOT = Path(__file__).resolve().parents[3]
PYPROJECT_TOML = PROJECT_ROOT / "pyproject.toml"
INIT_PY = PROJECT_ROOT / "jfox" / "__init__.py"
CHANGELOG_MD = PROJECT_ROOT / "CHANGELOG.md"


def output_json(data: dict):
    """输出 JSON 到 stdout"""
    print(json.dumps(data, ensure_ascii=False))


def output_error(msg: str):
    """输出错误 JSON 并退出"""
    output_json({"error": msg})
    sys.exit(1)


def read_current_version() -> str:
    """从 pyproject.toml 读取当前版本号"""
    content = PYPROJECT_TOML.read_text(encoding="utf-8")
    match = re.search(r'^version\s*=\s*"(\d+\.\d+\.\d+)"', content, re.MULTILINE)
    if not match:
        output_error(f"未在 {PYPROJECT_TOML} 中找到 version 字段")
    return match.group(1)


def parse_bump(arg: str, current: str) -> str:
    """解析版本参数，返回新版本号"""
    # 尝试作为 bump 类型
    if arg in ("patch", "minor", "major"):
        parts = [int(x) for x in current.split(".")]
        if arg == "patch":
            parts[2] += 1
        elif arg == "minor":
            parts[1] += 1
            parts[2] = 0
        elif arg == "major":
            parts[0] += 1
            parts[1] = 0
            parts[2] = 0
        return f"{parts[0]}.{parts[1]}.{parts[2]}"

    # 尝试作为 semver
    if not re.match(r"^\d+\.\d+\.\d+$", arg):
        output_error(f"无效的版本号或 bump 类型: {arg}（期望 patch/minor/major 或 X.Y.Z）")

    # 确保新版本 > 当前版本
    new_parts = [int(x) for x in arg.split(".")]
    cur_parts = [int(x) for x in current.split(".")]
    if new_parts <= cur_parts:
        output_error(f"新版本 {arg} 不大于当前版本 {current}")

    return arg


def update_files(new_version: str, current_version: str):
    """更新 pyproject.toml、__init__.py、uv.lock"""
    # pyproject.toml
    content = PYPROJECT_TOML.read_text(encoding="utf-8")
    content = re.sub(
        r'^version\s*=\s"\d+\.\d+\.\d+"',
        f'version = "{new_version}"',
        content,
        flags=re.MULTILINE,
    )
    PYPROJECT_TOML.write_text(content, encoding="utf-8")

    # __init__.py
    content = INIT_PY.read_text(encoding="utf-8")
    content = re.sub(
        r'__version__\s*=\s*"\d+\.\d+\.\d+"',
        f'__version__ = "{new_version}"',
        content,
    )
    INIT_PY.write_text(content, encoding="utf-8")

    # uv.lock
    result = subprocess.run(
        ["uv", "lock"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        output_error(f"uv lock 失败: {result.stderr}")


def get_last_tag() -> str:
    """获取最新的 git tag"""
    result = subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return ""  # 没有 tag
    return result.stdout.strip()


def parse_commits(last_tag: str) -> list[dict]:
    """解析 last_tag..HEAD 之间的 commit，返回分类后的条目列表"""
    if last_tag:
        range_spec = f"{last_tag}..HEAD"
    else:
        range_spec = "HEAD"

    result = subprocess.run(
        ["git", "log", range_spec, "--oneline", "--format=%s"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        return []

    entries = []
    seen = set()  # 去重（merge commit 和 squash 可能重复）

    for line in result.stdout.strip().split("\n"):
        if not line.strip():
            continue

        # 跳过 bump version 的 commit
        if "bump version" in line.lower():
            continue

        # 跳过纯 merge commit
        if line.startswith("Merge ") and not any(
            x in line for x in ["feat", "fix", "refactor", "docs", "chore", "perf"]
        ):
            continue

        # 解析 conventional commit: type(scope): message (#PR)
        # 也支持 type: message (#PR) 无 scope 的情况
        match = re.match(
            r"^(feat|fix|refactor|docs|chore|perf)(?:\(([^)]+)\))?:\s*(.+?)(?:\s*\(#(\d+)\))?$",
            line,
        )
        if match:
            entry = {
                "type": match.group(1),
                "scope": match.group(2) or "",
                "message": match.group(3).strip(),
                "pr": int(match.group(4)) if match.group(4) else None,
            }
        else:
            # 非 conventional commit 格式，作为 change 处理
            # 尝试提取 PR 号
            pr_match = re.search(r"\(#(\d+)\)", line)
            entry = {
                "type": "other",
                "scope": "",
                "message": line.strip(),
                "pr": int(pr_match.group(1)) if pr_match else None,
            }

        # 去重 key
        key = (entry["type"], entry["scope"], entry["message"])
        if key not in seen:
            seen.add(key)
            entries.append(entry)

    return entries


def generate_changelog(new_version: str, current_version: str, entries: list[dict]) -> str:
    """生成 CHANGELOG Markdown 内容"""
    today = date.today().isoformat()
    last_tag = get_last_tag()

    # 按 type 分类
    features = [e for e in entries if e["type"] == "feat"]
    fixes = [e for e in entries if e["type"] == "fix"]
    changes = [e for e in entries if e["type"] not in ("feat", "fix")]

    lines = [f"## [{new_version}] - {today}", ""]

    def format_entry(e: dict) -> str:
        scope = f"**{e['scope']}**: " if e["scope"] else ""
        pr = f" (#{e['pr']})" if e["pr"] else ""
        return f"- {scope}{e['message']}{pr}"

    if features:
        lines.append("### Features")
        lines.extend(format_entry(e) for e in features)
        lines.append("")

    if fixes:
        lines.append("### Fixes")
        lines.extend(format_entry(e) for e in fixes)
        lines.append("")

    if changes:
        lines.append("### Changes")
        lines.extend(format_entry(e) for e in changes)
        lines.append("")

    # 底部比较链接
    tag_prev = last_tag.lstrip("v") if last_tag else current_version
    lines.append(
        f"[{new_version}]: https://github.com/zhuxixi/jfox/compare/"
        f"v{tag_prev}...v{new_version}"
    )

    return "\n".join(lines)


def update_changelog_file(new_changelog: str):
    """将新条目插入 CHANGELOG.md 头部"""
    if not CHANGELOG_MD.exists():
        content = "# Changelog\n\n"
    else:
        content = CHANGELOG_MD.read_text(encoding="utf-8")

    # 在第一个 ## 之前插入（跳过文件头注释）
    # 找到第一个 ## [version] 行
    insert_pos = content.find("\n## ")
    if insert_pos == -1:
        # 没有现有条目，追加到末尾
        content = content.rstrip("\n") + "\n\n" + new_changelog + "\n"
    else:
        content = content[: insert_pos + 1] + new_changelog + "\n\n" + content[insert_pos + 1 :]

    CHANGELOG_MD.write_text(content, encoding="utf-8")


def summarize_entries(entries: list[dict]) -> str:
    """生成条目摘要"""
    counts = {}
    for e in entries:
        t = e["type"]
        if t == "feat":
            counts["feature"] = counts.get("feature", 0) + 1
        elif t == "fix":
            counts["fix"] = counts.get("fix", 0) + 1
        else:
            counts["change"] = counts.get("change", 0) + 1

    parts = []
    for label in ("feature", "fix", "change"):
        if label in counts:
            parts.append(f"{counts[label]} {label}{'s' if counts[label] > 1 else ''}")
    return ", ".join(parts) if parts else "0 changes"


def main():
    if len(sys.argv) < 2:
        output_error("用法: release_helper.py <version|patch|minor|major> [--dry-run]")

    version_arg = sys.argv[1]
    dry_run = "--dry-run" in sys.argv

    # 1. 读取当前版本
    current_version = read_current_version()

    # 2. 计算新版本
    new_version = parse_bump(version_arg, current_version)

    # 3. 解析 commits
    last_tag = get_last_tag()
    entries = parse_commits(last_tag)

    # 4. 生成 CHANGELOG
    changelog = generate_changelog(new_version, current_version, entries)

    if dry_run:
        # 只输出计算结果，不修改文件
        output_json({
            "current_version": current_version,
            "new_version": new_version,
            "last_tag": last_tag,
            "changelog_preview": changelog,
            "changelog_entries": entries,
            "changelog_summary": summarize_entries(entries),
            "files_modified": ["pyproject.toml", "jfox/__init__.py", "uv.lock", "CHANGELOG.md"],
        })
        return

    # 5. 更新文件
    update_files(new_version, current_version)

    # 6. 更新 CHANGELOG
    update_changelog_file(changelog)

    # 7. 输出结果
    output_json({
        "current_version": current_version,
        "new_version": new_version,
        "last_tag": last_tag,
        "changelog_preview": changelog,
        "changelog_entries": entries,
        "changelog_summary": summarize_entries(entries),
        "files_modified": ["pyproject.toml", "jfox/__init__.py", "uv.lock", "CHANGELOG.md"],
    })


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/test_release_helper.py -v`
Expected: All tests PASS

- [ ] **Step 5: Commit**

```bash
git add .claude/skills/release/release_helper.py tests/unit/test_release_helper.py
git commit -m "feat(skills): add release helper script with version bump and CHANGELOG generation"
```

---

### Task 2: SKILL.md — Release Skill 指令文件

**Files:**
- Create: `.claude/skills/release/SKILL.md`

- [ ] **Step 1: Create SKILL.md**

Create `.claude/skills/release/SKILL.md`:

```markdown
---
name: release
description: Release a new version of jfox. Bumps version, generates CHANGELOG, creates PR and GitHub Release. Triggers on "发版", "release", "bump version", "发布版本".
---

# Release Skill

将 jfox 发版流程从多步手动操作简化为一条命令。覆盖版本号 bump → CHANGELOG → commit → PR → GitHub Release 全流程。

## 用法

```
/release 0.5.0          # 指定具体版本号
/release patch          # bump patch: 0.4.1 → 0.4.2
/release minor          # bump minor: 0.4.1 → 0.5.0
/release major          # bump major: 0.4.1 → 1.0.0
```

## 执行流程

严格按照以下步骤执行。每一步必须完成后再进入下一步。

### Step 1: 前置校验

运行以下检查，任何一项失败则立即停止并告知用户原因：

```bash
# 1. 当前分支必须是 main
git branch --show-current
# 期望输出: main

# 2. 工作区必须干净
git status --porcelain
# 期望输出: 空

# 3. 不存在未合并的 bump 分支
git branch --list 'chore/bump-*'
# 期望输出: 空

# 4. 没有未合并的 bump PR
gh pr list --state open --head "chore/bump-*"
# 期望输出: 空
```

### Step 2: 运行辅助脚本（预览模式）

用 `--dry-run` 先预览计算结果：

```bash
uv run python .claude/skills/release/release_helper.py <version> --dry-run
```

解析 JSON 输出，提取 `current_version`、`new_version`、`changelog_preview`、`changelog_summary`。

### Step 3: 展示变更摘要并等待确认

向用户展示：

```
📦 Release 预览:
  当前版本: {current_version}
  新版本号: {new_version}
  变更摘要: {changelog_summary}

CHANGELOG 预览:
{changelog_preview}

将修改的文件:
  - pyproject.toml
  - jfox/__init__.py
  - uv.lock
  - CHANGELOG.md
```

**必须等待用户明确确认后才继续。** 如果用户拒绝或要求修改，停止流程。

### Step 4: 运行辅助脚本（正式模式）

```bash
uv run python .claude/skills/release/release_helper.py <version>
```

确认脚本退出码为 0。如果非 0，读取错误信息并告知用户，停止流程。

### Step 5: Git 操作

```bash
# 创建分支
git checkout -b chore/bump-version-{new_version}

# 暂存文件
git add pyproject.toml jfox/__init__.py uv.lock CHANGELOG.md

# 提交
git commit -m "chore: bump version to {new_version}"

# 推送
git push -u origin chore/bump-version-{new_version}
```

### Step 6: 创建 PR

使用 CHANGELOG 内容作为 PR body：

```bash
gh pr create \
  --title "chore: bump version to {new_version}" \
  --body "$(cat <<'EOF'
## Summary
Bump version from {current_version} to {new_version}

{changelog_preview}

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

记录返回的 PR URL。

### Step 7: 等待合并

告知用户：

```
PR 已创建: {PR_URL}
请合并此 PR 后告知我，我将继续创建 GitHub Release。
```

等待用户确认 PR 已合并。

### Step 8: 切回 main 并拉取最新代码

```bash
git checkout main
git pull origin main
```

### Step 9: 创建 GitHub Release

```bash
gh release create v{new_version} \
  --title "v{new_version}" \
  --notes "$(cat <<'EOF'
{changelog_preview}
EOF
)"
```

告知用户：

```
Release v{new_version} 已创建！
GitHub Actions 将自动发布到 PyPI。
可在 https://github.com/zhuxixi/jfox/actions 监控发布状态。
```

## 错误处理

- 脚本返回非零退出码 → 读取 stderr 中的错误 JSON，展示给用户，停止流程
- git 操作失败 → 展示错误信息，建议用户手动修复
- PR 创建失败 → 检查是否已有同名 PR，或提示权限问题
- Release 创建失败 → 检查 tag 是否已存在，或提示权限问题

## 注意事项

- **不使用 `--no-verify`**，保持 pre-commit hook 正常运行
- **始终在新分支操作**，不直接修改 main
- **每个确认点都必须等待**，不自动跳过
```

- [ ] **Step 2: Test the skill invocation**

手动验证 skill 文件格式正确：
```bash
# 确认 SKILL.md 有正确的 frontmatter
head -5 .claude/skills/release/SKILL.md
```

期望看到：
```
---
name: release
description: Release a new version...
---
```

- [ ] **Step 3: Commit**

```bash
git add .claude/skills/release/SKILL.md
git commit -m "feat(skills): add release skill with full workflow instructions"
```

---

### Task 3: End-to-end Verification

- [ ] **Step 1: Verify helper script dry-run works**

```bash
uv run python .claude/skills/release/release_helper.py patch --dry-run
```

期望：输出合法 JSON，包含 `current_version`、`new_version`、`changelog_preview` 等字段。

- [ ] **Step 2: Verify helper script error handling**

```bash
# 无效 bump 类型
uv run python .claude/skills/release/release_helper.py foobar
# 期望: 非零退出码 + error JSON

# 无效版本号
uv run python .claude/skills/release/release_helper.py 1.2
# 期望: 非零退出码 + error JSON
```

- [ ] **Step 3: Run all release helper tests**

```bash
uv run pytest tests/unit/test_release_helper.py -v
```

期望：所有测试通过。
