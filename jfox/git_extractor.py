"""Git 仓库数据提取模块

从本地 Git 仓库提取 commit 历史，转换为结构化数据。
"""

import logging
import re
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# git log block 分隔符
_COMMIT_DELIMITER = "---COMMIT_START---"
# git log format 模板
_GIT_LOG_FORMAT = (
    f"{_COMMIT_DELIMITER}%n" f"Hash: %H%n" f"Subject: %s%n" f"Author: %an%n" f"Date: %ad%n" f"%n%b"
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
                body_lines = lines[i + 1 :]
                break

        # Join body lines with newlines
        commit["body"] = "\n".join(body_lines).strip()

        if commit["hash"]:
            commits.append(commit)

    return commits


def extract_commits(repo_path: str, limit: int = 50) -> List[Dict[str, str]]:
    """
    从 Git 仓库提取 commit 历史

    Args:
        repo_path: 仓库路径（支持 Windows / Git Bash 路径）
        limit: 最大提取条数

    Returns:
        commit 列表，每项包含 hash, subject, author, date, body

    Raises:
        ValueError: 路径不是 Git 仓库 或 git 未安装
    """
    repo = Path(repo_path).resolve()

    cmd = [
        "git",
        "-C",
        str(repo),
        "log",
        f"--format={_GIT_LOG_FORMAT}",
        "--date=short",
        f"-{limit}",
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except FileNotFoundError:
        raise ValueError("git 命令未找到，请确认 git 已安装")

    if result.returncode != 0:
        stderr = result.stderr.strip()
        raise ValueError(f"git log 执行失败: {stderr}")

    return parse_git_log_output(result.stdout)


def commits_to_notes(
    commits: List[Dict[str, str]],
    repo_name: Optional[str] = None,
    repo_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    将 commit 列表转换为 bulk-import 兼容的笔记格式

    Args:
        commits: parse_git_log_output 的返回值
        repo_name: 仓库名称（用于标签），None 时从 repo_path 提取
        repo_path: 仓库路径（repo_name 为 None 时使用）

    Returns:
        笔记数据列表，兼容 bulk_import_notes() 输入格式
    """
    if not commits:
        return []

    if not repo_name:
        if repo_path:
            repo_name = Path(repo_path).resolve().name
        else:
            repo_name = "unknown"

    notes = []
    for c in commits:
        short_hash = c["hash"][:7]

        # 清理 body：去掉 Co-authored-by 行和末尾空行
        body = c.get("body", "")
        body_lines = [
            line
            for line in body.split("\n")
            if line.strip() and not line.strip().lower().startswith("co-authored-by:")
        ]
        clean_body = "\n".join(body_lines).strip()

        content_parts = [
            f"Commit: {short_hash}",
            f"Author: {c['author']}",
            f"Date: {c['date']}",
        ]
        if clean_body:
            content_parts.append("")
            content_parts.append(clean_body)

        notes.append(
            {
                "title": c["subject"],
                "content": "\n".join(content_parts),
                "tags": [f"source:{repo_name}", "source:git-log"],
            }
        )

    return notes
