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


def _version_tuple(v: str) -> tuple[int, ...]:
    return tuple(int(x) for x in v.split("."))


def read_current_version(root: Path) -> str:
    """从 plugin.json 读当前版本号（单一真相源）。"""
    data = json.loads((root / PLUGIN_JSON_REL).read_text(encoding="utf-8"))
    return data["version"]


def compute_new_version(current: str, spec: str) -> str:
    """patch/minor/major 递增或 explicit x.y.z；结果必须 > current，否则 raise ValueError。"""
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


def find_last_bump_commit(root: Path, current_version: str) -> str | None:
    """定位上次发版提交：引入 current_version 的提交；降级为最近改 marketplace.json 的提交。"""
    rel = MARKETPLACE_JSON_REL
    for args in (
        ["git", "log", "-S", f'"version": "{current_version}"', "--format=%H", "--", rel],
        ["git", "log", "--format=%H", "-1", "--", rel],
    ):
        try:
            out = subprocess.run(
                args,
                cwd=root,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                check=True,
            )
        except subprocess.CalledProcessError:
            continue
        hits = [ln for ln in out.stdout.splitlines() if ln.strip()]
        if hits:
            return hits[0]
    return None


def get_changelog(root: Path, current_version: str) -> list[str]:
    """自上次发版以来 packages/cc-plugin/ 的 oneline 提交摘要；无基线时取最近 30 条。"""
    last = find_last_bump_commit(root, current_version)
    if last:
        args = ["git", "log", "--oneline", f"{last}..HEAD", "--", "packages/cc-plugin/"]
    else:
        # 无基线：用 --max-count 避免 HEAD~30 在浅克隆/小仓报 bad revision
        args = ["git", "log", "--oneline", "--max-count=30", "--", "packages/cc-plugin/"]
    try:
        out = subprocess.run(
            args,
            cwd=root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=True,
        )
    except subprocess.CalledProcessError:
        return []
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


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


def _read_raw(path: Path) -> str:
    """读原始文本（不做换行转换），保留文件原换行。"""
    return path.read_bytes().decode("utf-8")


def _write_raw(path: Path, text: str) -> None:
    """写文本，newline='' 避免 Windows 把 LF 转 CRLF 污染 diff。"""
    path.write_text(text, encoding="utf-8", newline="")


def bump_version_files(root: Path, old: str, new: str) -> list[str]:
    """原子 bump 三处版本号：计数预校验 + 落盘失败回滚已写文件 + 写后断言。"""
    targets = [
        (root / PLUGIN_JSON_REL, 1),
        (root / MARKETPLACE_JSON_REL, 2),
    ]
    needle = f'"version": "{old}"'
    replacement = f'"version": "{new}"'
    # 预校验：读原文 + 计数，全过才准备落盘
    pending = []  # (path, original_text, new_text, rel)
    for path, expected_count in targets:
        original = _read_raw(path)
        count = original.count(needle)
        if count != expected_count:
            raise ValueError(
                f"{path.relative_to(root)} 命中 {count} 次（期望 {expected_count}），"
                f"版本号 {old}。中止，未写任何文件。"
            )
        pending.append(
            (path, original, original.replace(needle, replacement), path.relative_to(root))
        )
    # 落盘：任一写失败则回滚已写文件（尽力，堵 CLAUDE.md 版本不一致坑）
    written: list[tuple[Path, str]] = []
    try:
        for path, original, new_text, _ in pending:
            _write_raw(path, new_text)
            written.append((path, original))
    except Exception:
        for path, original in written:
            try:
                _write_raw(path, original)
            except OSError:
                pass  # 回滚失败只能尽力而为
        raise
    assert_versions(root, new)  # 写后兜底断言
    return [str(rel) for _, _, _, rel in pending]


def main() -> None:
    parser = argparse.ArgumentParser(description="cc-plugin release helper")
    parser.add_argument("version", help="patch | minor | major | x.y.z")
    parser.add_argument("--dry-run", action="store_true", help="只计算不修改文件")
    args = parser.parse_args()

    try:
        current = read_current_version(PROJECT_ROOT)
    except (json.JSONDecodeError, KeyError, FileNotFoundError, PermissionError, OSError) as e:
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

    try:
        changed = bump_version_files(PROJECT_ROOT, current, new)
    except (
        ValueError,
        AssertionError,
        KeyError,
        IndexError,
        OSError,
        json.JSONDecodeError,
    ) as e:
        output_error(str(e))

    output_json(
        {
            "current_version": current,
            "new_version": new,
            "changed_files": changed,
            "changelog_summary": changelog,
        }
    )


if __name__ == "__main__":
    main()
