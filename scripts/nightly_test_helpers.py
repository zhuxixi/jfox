"""夜间全量测试脚本的纯逻辑辅助函数（可单元测试）。

bash 编排脚本 scripts/nightly_test.sh 通过本模块的 CLI dispatcher 调用这些
纯逻辑：解析 pytest 失败、算失败签名（issue 去重用）、决定开新 issue 还是
追加评论、检查 #338 备份是否在今天完成。所有函数无副作用、便于 pytest 覆盖。
"""

from __future__ import annotations

import hashlib
import re

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
    """失败 nodeid 取前 N 个后排序，sha1[:12] 作为去重签名（与顺序无关）。"""
    head = sorted(failures[:top_n])
    digest = hashlib.sha1("\n".join(head).encode("utf-8")).hexdigest()
    return digest[:12]
