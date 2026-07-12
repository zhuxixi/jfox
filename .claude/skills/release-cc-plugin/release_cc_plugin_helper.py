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
