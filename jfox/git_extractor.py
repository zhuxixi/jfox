"""Git 仓库数据提取模块

从本地 Git 仓库提取 commit 历史，转换为结构化数据。
"""

import logging
import re
from typing import Dict, List

logger = logging.getLogger(__name__)

# git log block 分隔符
_COMMIT_DELIMITER = "---COMMIT_START---"
# git log format 模板
_GIT_LOG_FORMAT = (
    f"{_COMMIT_DELIMITER}%n"
    f"Hash: %H%n"
    f"Subject: %s%n"
    f"Author: %an%n"
    f"Date: %ad%n"
    f"%n%b"
)


def parse_git_log_output(raw: str) -> List[Dict[str, str]]:
    """
    解析 git log block 分隔符格式的输出

    Args:
        raw: git log 原始输出

    Returns:
        commit 列表，每项包含 hash, subject, author, date, body
    """
    if not raw.strip():
        return []

    commits = []
    blocks = raw.split(_COMMIT_DELIMITER)

    for block in blocks:
        block = block.strip()
        if not block:
            continue

        commit: Dict[str, str] = {
            "hash": "",
            "subject": "",
            "author": "",
            "date": "",
            "body": "",
        }

        lines = block.split("\n")
        i = 0
        body_lines = []

        # Parse header fields
        for i, line in enumerate(lines):
            line = line.rstrip()
            if line.startswith("Hash:"):
                commit["hash"] = line[5:].strip()
            elif line.startswith("Subject:"):
                commit["subject"] = line[8:].strip()
            elif line.startswith("Author:"):
                commit["author"] = line[7:].strip()
            elif line.startswith("Date:"):
                commit["date"] = line[5:].strip()
            elif line == "":
                # Empty line marks end of headers, start collecting body
                body_lines = lines[i+1:]
                break

        # Join body lines with newlines
        commit["body"] = "\n".join(body_lines).strip()

        if commit["hash"]:
            commits.append(commit)

    return commits