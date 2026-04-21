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
    if not PYPROJECT_TOML.exists():
        output_error(f"未找到 {PYPROJECT_TOML}")
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
    if not PYPROJECT_TOML.exists():
        output_error(f"未找到 {PYPROJECT_TOML}")
    if not INIT_PY.exists():
        output_error(f"未找到 {INIT_PY}")

    # 先读取备份
    toml_content = PYPROJECT_TOML.read_text(encoding="utf-8")
    init_content = INIT_PY.read_text(encoding="utf-8")

    # 更新 pyproject.toml
    new_toml = re.sub(
        r'^version\s*=\s*"\d+\.\d+\.\d+"',
        f'version = "{new_version}"',
        toml_content,
        flags=re.MULTILINE,
    )
    PYPROJECT_TOML.write_text(new_toml, encoding="utf-8")

    # 更新 __init__.py
    new_init = re.sub(
        r'__version__\s*=\s*"\d+\.\d+\.\d+"',
        f'__version__ = "{new_version}"',
        init_content,
    )
    INIT_PY.write_text(new_init, encoding="utf-8")

    # uv.lock — 如果失败则回滚
    result = subprocess.run(
        ["uv", "lock"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0:
        # 回滚
        PYPROJECT_TOML.write_text(toml_content, encoding="utf-8")
        INIT_PY.write_text(init_content, encoding="utf-8")
        output_error(f"uv lock 失败，已回滚文件变更: {result.stderr}")


def get_last_tag() -> str:
    """获取最新的 git tag"""
    result = subprocess.run(
        ["git", "describe", "--tags", "--abbrev=0"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
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

    # -c core.quotepath=false 确保 git 输出中文不被转义
    result = subprocess.run(
        ["git", "-c", "core.quotepath=false", "-c", "i18n.logoutputencoding=utf-8",
         "log", range_spec, "--format=%s"],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if result.returncode != 0 or not result.stdout:
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
            # 非 conventional commit 格式
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


def generate_changelog(new_version: str, current_version: str, entries: list[dict], last_tag: str = "") -> str:
    """生成 CHANGELOG Markdown 内容"""
    today = date.today().isoformat()

    # 按 type 分类
    features = [e for e in entries if e["type"] == "feat"]
    fixes = [e for e in entries if e["type"] == "fix"]
    perfs = [e for e in entries if e["type"] == "perf"]
    changes = [e for e in entries if e["type"] not in ("feat", "fix", "perf")]

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

    if perfs:
        lines.append("### Performance")
        lines.extend(format_entry(e) for e in perfs)
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

    # 在第一个 ## 之前插入
    insert_pos = content.find("\n## ")
    if insert_pos == -1:
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
            plural = {"feature": "features", "fix": "fixes", "change": "changes"}
            name = plural[label] if counts[label] > 1 else label
            parts.append(f"{counts[label]} {name}")
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
    changelog = generate_changelog(new_version, current_version, entries, last_tag)

    result = {
        "current_version": current_version,
        "new_version": new_version,
        "last_tag": last_tag,
        "changelog_preview": changelog,
        "changelog_entries": entries,
        "changelog_summary": summarize_entries(entries),
        "files_modified": ["pyproject.toml", "jfox/__init__.py", "uv.lock", "CHANGELOG.md"],
    }

    if dry_run:
        output_json(result)
        return

    # 5. 更新文件
    update_files(new_version, current_version)

    # 6. 更新 CHANGELOG
    update_changelog_file(changelog)

    # 7. 输出结果
    output_json(result)


if __name__ == "__main__":
    main()
