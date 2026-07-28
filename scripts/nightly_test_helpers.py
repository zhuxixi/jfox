"""夜间全量测试脚本的纯逻辑辅助函数（可单元测试）。

bash 编排脚本 scripts/nightly_test.sh 通过本模块的 CLI dispatcher 调用这些
纯逻辑：解析 pytest 失败、算失败签名（issue 去重用）、决定开新 issue 还是
追加评论、检查 #338 备份是否在今天完成。所有函数无副作用、便于 pytest 覆盖。
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

# pytest -ra 汇总行形如：FAILED <nodeid> - <reason>
_FAILED_RE = re.compile(r"^FAILED\s+(\S+?)(?:\s+-\s+|$)", re.MULTILINE)


def extract_failures(pytest_output: str) -> list[str]:
    """从 pytest 输出提取失败的 test nodeid（去重、保持出现顺序）。"""
    seen: list[str] = []
    for m in _FAILED_RE.finditer(pytest_output):
        nodeid = m.group(1).strip()
        if nodeid and nodeid not in seen:
            seen.append(nodeid)
    return seen


def compute_signature(failures: list[str], top_n: int = 10) -> str:
    """失败 nodeid 排序后取前 N 个，sha1[:12] 作为去重签名（与顺序无关）。"""
    head = sorted(failures)[:top_n]
    digest = hashlib.sha1("\n".join(head).encode("utf-8")).hexdigest()
    return digest[:12]


def decide_issue_action(signature: str, open_issues: list[dict]) -> tuple[str, int | None]:
    """给定失败签名和当前 open 的 nightly-test-failure issue，决定复用还是新开。

    open_issues: `gh issue list --json number,title` 的结果，每项 {"number": int, "title": str}。
    返回 ("comment", issue_number) 复用既有，或 ("create", None) 新开。
    匹配规则：issue title 含 "sig:<signature>"。
    """
    needle = f"sig:{signature}"
    for issue in open_issues:
        if needle in str(issue.get("title", "")):
            return ("comment", int(issue["number"]))
    return ("create", None)


def check_backup_last_ok(state_path: Path, today: date) -> bool:
    """读 #338 backup state.json，判断今天的备份是否成功。

    state schema（jfox/backup/loop.py:42-48）：{last_run: ISO时间, last_ok: bool, last_archive}。
    要求 last_ok 为真且 last_run 的日期 == today。
    """
    if not state_path.exists():
        return False
    try:
        data = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    if not data.get("last_ok"):
        return False
    last_run = str(data.get("last_run", ""))
    return last_run[:10] == today.isoformat()


def _cli() -> int:
    """供 bash 脚本调用的 CLI。用法见各分支 stderr --help。"""
    if len(sys.argv) < 2:
        print("usage: nightly_test_helpers.py {check-backup|signature|decide} ...", file=sys.stderr)
        return 2
    cmd = sys.argv[1]
    if cmd == "check-backup":
        # argv[2] = state.json 路径；退出码 0=今天已备份成功，1=否
        ok = check_backup_last_ok(Path(sys.argv[2]), date.today())
        return 0 if ok else 1
    if cmd == "signature":
        # stdin = pytest 输出；stdout = "signature\t首个失败nodeid\t失败总数"
        failures = extract_failures(sys.stdin.read())
        sig = compute_signature(failures)
        first = failures[0] if failures else "(none)"
        print(f"{sig}\t{first}\t{len(failures)}")
        return 0
    if cmd == "decide":
        # argv[2] = signature；stdin = gh issue list --json number,title 的 JSON 数组
        issues = json.loads(sys.stdin.read() or "[]")
        action, num = decide_issue_action(sys.argv[2], issues)
        print(f"{action}\t{num if num is not None else ''}")
        return 0
    print(f"unknown command: {cmd}", file=sys.stderr)
    return 2


if __name__ == "__main__":
    raise SystemExit(_cli())
