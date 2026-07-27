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
VERSION_RE = re.compile(r"^\d+\.\d+\.\d+$")


def output_json(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False))


def _git(args: list[str], root: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            "git",
            "-c",
            "core.quotepath=false",
            "-c",
            "i18n.logoutputencoding=utf-8",
            *args,
        ],
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
    v = json.loads((root / rel).read_text(encoding="utf-8"))["version"]
    if not VERSION_RE.match(v):
        raise ValueError(f"非法版本号格式: {v!r}（{rel}）")
    return v


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
    """jfox CLI：last v* tag..HEAD 是否有非 bump 的功能性 commit。"""
    try:
        current = _read_pyproject_version(root)
    except Exception as e:
        return {
            "name": "jfox",
            "changed": False,
            "current_version": "",
            "commits": [],
            "skip_reason": f"读取版本失败: {e}",
        }
    tag = _last_jfox_tag(root)
    out = _git(["log", f"{tag}..HEAD" if tag else "HEAD", "--format=%s"], root)
    if out.returncode != 0:
        return {
            "name": "jfox",
            "changed": False,
            "current_version": current,
            "baseline": tag,
            "commits": [],
            "skip_reason": f"git log 失败: {out.stderr.strip()}",
        }
    subjects = [
        s.strip() for s in out.stdout.splitlines() if s.strip() and "bump version" not in s.lower()
    ]
    if not subjects:
        return {
            "name": "jfox",
            "changed": False,
            "current_version": current,
            "baseline": tag,
            "commits": [],
            "skip_reason": f"自 {tag or '起点'} 以来无改动",
        }
    bump = "minor" if any(s.startswith("feat") for s in subjects) else "patch"
    return {
        "name": "jfox",
        "changed": True,
        "current_version": current,
        "baseline": tag,
        "commits": subjects,
        "suggested_bump": bump,
        "suggested_version": _bump_version(current, bump),
    }


def _detect_plugin(
    root: Path, name: str, version_source: str, baseline_file: str, watch_paths: list[str]
) -> dict:
    """cc/kimi 通用检测：自上次 bump commit 起是否有改 watch_paths 的提交。

    - version_source：含顶层 version 字段的文件（读当前版本）。
    - baseline_file：git log -S 定位上次 bump 的文件（cc=marketplace.json、
      kimi=kimi.plugin.json）。
    - watch_paths：检测改动的路径（cc/kimi 各自 packages/ 目录）。
    """
    try:
        current = _read_json_version(root, version_source)
    except Exception as e:
        return {
            "name": name,
            "changed": False,
            "current_version": "",
            "commits": [],
            "skip_reason": f"读取版本失败: {e}",
        }
    baseline = _find_last_bump_commit(root, current, baseline_file)
    if baseline:
        out = _git(["log", "--oneline", f"{baseline}..HEAD", "--", *watch_paths], root)
    else:
        out = _git(["log", "--oneline", "--max-count=30", "--", *watch_paths], root)
    if out.returncode != 0:
        return {
            "name": name,
            "changed": False,
            "current_version": current,
            "baseline": baseline,
            "commits": [],
            "skip_reason": f"git log 失败: {out.stderr.strip()}",
        }
    commits = [c for c in out.stdout.splitlines() if c.strip()]
    if not commits:
        return {
            "name": name,
            "changed": False,
            "current_version": current,
            "baseline": baseline,
            "commits": [],
            "skip_reason": f"自 {current} 以来无改动",
        }
    return {
        "name": name,
        "changed": True,
        "current_version": current,
        "baseline": baseline,
        "commits": commits,
        "suggested_bump": "patch",
        "suggested_version": _bump_version(current, "patch"),
    }


def detect_cc(root: Path) -> dict:
    # plugin.json 含顶层 version（读版本）；marketplace.json 用于 -S 定位 bump（与
    # release_cc_plugin_helper 一致）；watch packages/cc-plugin/（skills + plugin.json）
    # 外加 marketplace.json 本身——改其非 version 元数据也算 cc 改动，该发版。
    return _detect_plugin(
        root,
        "cc-plugin",
        CC_PLUGIN_JSON,
        CC_MARKETPLACE,
        ["packages/cc-plugin/", ".claude-plugin/marketplace.json"],
    )


def detect_kimi(root: Path) -> dict:
    return _detect_plugin(
        root, "kimi-plugin", KIMI_PLUGIN_JSON, KIMI_PLUGIN_JSON, ["packages/kimi-plugin/"]
    )


def detect(root: Path) -> dict:
    comps = [detect_jfox(root), detect_cc(root), detect_kimi(root)]
    return {"components": comps, "any_changed": any(c.get("changed") for c in comps)}


def main() -> None:
    # 仅支持 detect（默认）；无参数或参数为 detect 都走 detect
    try:
        output_json(detect(PROJECT_ROOT))
    except (OSError, subprocess.SubprocessError, ValueError) as e:
        output_json({"error": f"detect 失败: {e}"})
        sys.exit(1)


if __name__ == "__main__":
    main()
