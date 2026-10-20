"""
pi coding agent session 来源：扫描官方目录（两层）与 agent-board 目录（扁平）。

id 一律读首行 session 记录，不解析文件名（agent-board 的 view_<hash>.jsonl 与 id 无关）。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Iterator, Optional, Sequence

from ..global_config import AutoSummaryConfig
from .extractor import ExtractedDialog
from .pi_extractor import extract_pi_dialog, parse_pi_header
from .scanner import DEFAULT_PROJECT_BLOCKLIST_SUBSTRINGS, SessionFile, _is_blocked_project

logger = logging.getLogger(__name__)


def _candidate_paths(root: Path) -> list:
    """官方两层（root/<encoded-cwd>/*.jsonl）+ agent-board 扁平（root/*.jsonl）。

    不递归更深层：sessions/<viewId>/<uuid>/run-0/session.jsonl 是 subagent transcript。
    """
    return sorted(root.glob("*.jsonl")) + sorted(root.glob("*/*.jsonl"))


def _read_header(path: Path) -> Optional[dict]:
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            return parse_pi_header(f.readline().strip())
    except OSError as e:
        logger.debug("读取 pi session 首行失败 %s: %s", path, e)
        return None


def iter_pi_session_files(
    roots: Sequence[Path],
    cfg: AutoSummaryConfig,
    now: Optional[float] = None,
) -> Iterator[SessionFile]:
    now = time.time() if now is None else now
    idle_sec = max(0, cfg.idle_threshold_minutes) * 60
    min_size = max(0, cfg.min_session_size_kb) * 1024
    max_size = max(0, cfg.max_session_size_mb) * 1024 * 1024
    skip_sec = max(0, cfg.skip_after_days) * 86400

    seen: dict = {}
    for root in roots:
        if not root.is_dir():
            logger.info("跳过 pi 根目录：不存在 %s", root)
            continue
        for path in _candidate_paths(root):
            if not path.is_file():
                continue
            try:
                stat = path.stat()
            except OSError as e:
                logger.debug("stat pi session 失败 %s: %s", path, e)
                continue
            size, mtime = stat.st_size, stat.st_mtime
            age = now - mtime
            if size < min_size:
                continue
            if max_size and size > max_size:
                continue
            if age < idle_sec:
                continue
            if skip_sec and age > skip_sec:
                continue

            header = _read_header(path)
            if header is None:
                continue
            cwd = header.get("cwd")
            if isinstance(cwd, str) and _is_blocked_project(
                cwd, DEFAULT_PROJECT_BLOCKLIST_SUBSTRINGS
            ):
                continue

            sid = header["id"]
            project = Path(cwd).name if isinstance(cwd, str) and cwd else path.parent.name
            sf = SessionFile(
                session_id=sid,
                project_dir_name=project,
                path=path,
                mtime=mtime,
                size_bytes=size,
                source="pi",
                agent="pi-coding-agent",
            )
            prev = seen.get(sid)
            if prev is None or sf.mtime > prev.mtime:
                seen[sid] = sf

    yield from seen.values()


class PiCodeSource:
    """pi session 来源：扫描 + 委派给 pi_extractor。"""

    name = "pi"

    def __init__(self, roots: Sequence[Path]):
        self.roots = list(roots)

    def iter_sessions(self, cfg: AutoSummaryConfig) -> Iterator[SessionFile]:
        yield from iter_pi_session_files(self.roots, cfg)

    def extract_dialog(self, sf: SessionFile) -> ExtractedDialog:
        return extract_pi_dialog(sf.path)
