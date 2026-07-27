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


def _run_git(args: list[str], root: Path) -> subprocess.CompletedProcess:
    """git 调用封装：与 release_helper._git / release_all_helper._git 一致地带上
    `-c core.quotepath=false -c i18n.logoutputencoding=utf-8`，防中文 commit subject 乱码。"""
    return subprocess.run(
        ["git", "-c", "core.quotepath=false", "-c", "i18n.logoutputencoding=utf-8", *args],
        cwd=root,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        check=True,
    )


def find_last_bump_commit(root: Path, current_version: str) -> str | None:
    """定位上次发版提交：引入 current_version 的提交；降级为最近改 kimi.plugin.json 的提交。"""
    rel = KIMI_PLUGIN_JSON_REL
    for args in (
        ["log", "-S", f'"version": "{current_version}"', "--format=%H", "--", rel],
        ["log", "--format=%H", "-1", "--", rel],
    ):
        try:
            out = _run_git(args, root)
        except subprocess.CalledProcessError:
            continue
        hits = [ln for ln in out.stdout.splitlines() if ln.strip()]
        if hits:
            return hits[0]
    return None


def get_changelog(root: Path, current_version: str) -> list[str]:
    """自上次发版以来 packages/kimi-plugin/ 的 oneline 提交摘要；无基线时取最近 30 条。"""
    last = find_last_bump_commit(root, current_version)
    if last:
        args = ["log", "--oneline", f"{last}..HEAD", "--", "packages/kimi-plugin/"]
    else:
        # 无基线：用 --max-count 避免 HEAD~30 在浅克隆/小仓报 bad revision
        args = ["log", "--oneline", "--max-count=30", "--", "packages/kimi-plugin/"]
    try:
        out = _run_git(args, root)
    except subprocess.CalledProcessError:
        return []
    return [ln for ln in out.stdout.splitlines() if ln.strip()]


def assert_versions(root: Path, expected: str) -> None:
    """写后断言 version == expected，否则 raise AssertionError。"""
    data = json.loads((root / KIMI_PLUGIN_JSON_REL).read_text(encoding="utf-8"))
    if data["version"] != expected:
        raise AssertionError(f"写后版本号校验失败: 期望 {expected}，实际 {data['version']}")


def _read_raw(path: Path) -> str:
    """读原始文本（不做换行转换），保留文件原换行。"""
    return path.read_bytes().decode("utf-8")


def _write_raw(path: Path, text: str) -> None:
    """写文本，newline='' 避免 Windows 把 LF 转 CRLF 污染 diff。"""
    path.write_text(text, encoding="utf-8", newline="")


def bump_version_files(root: Path, old: str, new: str) -> list[str]:
    """原子 bump 单一 version 字段：计数预校验（=1）+ 落盘 + 写后断言；失败回滚。"""
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
        assert_versions(root, new)  # 写后兜底断言；失败也走回滚
    except (OSError, AssertionError, ValueError, KeyError, IndexError):
        try:
            _write_raw(path, original)
        except OSError:
            pass  # 回滚失败只能尽力而为
        raise
    return [KIMI_PLUGIN_JSON_REL]


def main() -> None:
    parser = argparse.ArgumentParser(description="kimi-plugin release helper")
    parser.add_argument("version", help="patch | minor | major | x.y.z")
    parser.add_argument("--dry-run", action="store_true", help="只计算不修改文件")
    args = parser.parse_args()

    try:
        current = read_current_version(PROJECT_ROOT)
    except (
        json.JSONDecodeError,
        UnicodeDecodeError,
        KeyError,
        FileNotFoundError,
        PermissionError,
        OSError,
    ) as e:
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
                "files_to_change": [KIMI_PLUGIN_JSON_REL],
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
