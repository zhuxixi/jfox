"""
扫描 ~/.claude/projects/ 下的 Claude Code session 文件，筛选出"已结束、待总结"的。

判定结束：mtime 距今超过 idle_threshold_minutes。
排除条件：在 ledger 黑名单内 / 项目目录在硬编码黑名单内 / size 超阈值或太小 / 太老。
"""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Sequence

logger = logging.getLogger(__name__)

# claude -p 自身会创建 session 文件，下列子串若出现在 project 目录名中则跳过，避免递归
DEFAULT_PROJECT_BLOCKLIST_SUBSTRINGS: tuple[str, ...] = (
    "jfox-auto-summary-runs",
    "auto-session-summary",
)


def default_claude_projects_dir() -> Path:
    """返回 ~/.claude/projects/ 的路径"""
    return Path.home() / ".claude" / "projects"


@dataclass(frozen=True)
class SessionFile:
    """一个待处理的 session 文件"""

    session_id: str  # UUID（去掉 .jsonl 后缀的文件名）
    project_dir_name: str  # ~/.claude/projects/ 下的目录名
    path: Path
    mtime: float  # epoch seconds
    size_bytes: int

    @property
    def age_seconds(self) -> float:
        return max(0.0, time.time() - self.mtime)

    @property
    def size_mb(self) -> float:
        return self.size_bytes / (1024 * 1024)


def _is_blocked_project(name: str, blocklist: Sequence[str]) -> bool:
    lname = name.lower()
    return any(token.lower() in lname for token in blocklist)


def iter_session_files(
    claude_projects_dir: Path | None = None,
    idle_threshold_minutes: int = 30,
    max_session_size_mb: int = 10,
    min_session_size_kb: int = 5,
    skip_after_days: int = 7,
    project_blocklist: Sequence[str] = DEFAULT_PROJECT_BLOCKLIST_SUBSTRINGS,
    now: float | None = None,
) -> Iterator[SessionFile]:
    """
    遍历 claude_projects_dir 下所有 .jsonl session 文件，仅产出满足以下条件的：

    - 文件大小落在 [min_session_size_kb*1024, max_session_size_mb*1024*1024] 内
    - mtime 距今 >= idle_threshold_minutes（已静默）
    - mtime 距今 <= skip_after_days（不太老）
    - 项目目录名不在 project_blocklist 内

    不读取 ledger，调用方负责再过滤 ledger 中已处理的 session。
    """
    base = claude_projects_dir or default_claude_projects_dir()
    if not base.exists() or not base.is_dir():
        logger.debug("Claude projects 目录不存在: %s", base)
        return

    current_time = now if now is not None else time.time()
    idle_threshold_sec = max(0, idle_threshold_minutes) * 60
    skip_after_sec = max(0, skip_after_days) * 86400
    min_size = max(0, min_session_size_kb) * 1024
    max_size = max(0, max_session_size_mb) * 1024 * 1024

    for project_dir in sorted(base.iterdir()):
        if not project_dir.is_dir():
            continue
        if _is_blocked_project(project_dir.name, project_blocklist):
            logger.debug("跳过黑名单项目: %s", project_dir.name)
            continue

        for entry in sorted(project_dir.iterdir()):
            if not entry.is_file() or entry.suffix.lower() != ".jsonl":
                continue
            try:
                stat = entry.stat()
            except OSError as e:
                logger.debug("无法 stat %s: %s", entry, e)
                continue

            size = stat.st_size
            mtime = stat.st_mtime
            age = current_time - mtime

            if size < min_size:
                continue
            if max_size and size > max_size:
                logger.debug("跳过过大 session %s (%.1f MB)", entry.name, size / (1024 * 1024))
                continue
            if age < idle_threshold_sec:
                continue
            if skip_after_sec and age > skip_after_sec:
                logger.debug("跳过过旧 session %s (%.1f 天)", entry.name, age / 86400)
                continue

            yield SessionFile(
                session_id=entry.stem,
                project_dir_name=project_dir.name,
                path=entry,
                mtime=mtime,
                size_bytes=size,
            )


def isolated_runs_dir() -> Path:
    """返回 claude -p 隔离工作目录，并按需创建。

    runner 会在此目录下调用 claude -p，对应的 ~/.claude/projects/ 目录名包含
    'jfox-auto-summary-runs' 子串，会被默认黑名单排除，避免递归总结自身。
    """
    p = Path.home() / ".jfox-auto-summary-runs"
    p.mkdir(parents=True, exist_ok=True)
    # 占位文件，方便用户知道这是干什么的
    readme = p / "README.txt"
    if not readme.exists():
        try:
            readme.write_text(
                "This directory is the isolated cwd for `jfox auto-summary` runs.\n"
                "Each invocation of `claude -p` from auto-summary uses this as its\n"
                "working directory so that the resulting Claude Code session files\n"
                "land in a project path that is excluded from auto-summary scans.\n"
                "Safe to delete — will be recreated on next run.\n",
                encoding="utf-8",
            )
        except OSError:
            pass
    return p


def is_running_inside_isolated_dir() -> bool:
    """判断当前进程是否运行在隔离目录或其子目录下（防止误总结自己）"""
    try:
        cwd = Path(os.getcwd()).resolve()
    except OSError:
        return False
    iso = (Path.home() / ".jfox-auto-summary-runs").resolve()
    try:
        cwd.relative_to(iso)
        return True
    except ValueError:
        return False
