"""
Kimi Code session 来源：扫描 ~/.kimi-code/sessions/wd_*/session_*/agents/main/wire.jsonl，
解析 wire 协议提取对话。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Iterator

from ..global_config import AutoSummaryConfig
from .scanner import SessionFile

logger = logging.getLogger(__name__)


class KimiCodeSource:
    name = "kimi"

    def __init__(self, kimi_dir: Path):
        self.kimi_dir = kimi_dir

    def iter_sessions(self, cfg: AutoSummaryConfig) -> Iterator[SessionFile]:
        """遍历 kimi_dir/wd_*/session_*/agents/main/wire.jsonl，按 mtime/size 过滤。"""
        if not self.kimi_dir.is_dir():
            return

        now = time.time()
        idle_sec = max(0, cfg.idle_threshold_minutes) * 60
        min_size = max(0, cfg.min_session_size_kb) * 1024
        max_size = max(0, cfg.max_session_size_mb) * 1024 * 1024
        skip_sec = max(0, cfg.skip_after_days) * 86400

        for wd in sorted(self.kimi_dir.iterdir()):
            if not wd.is_dir() or not wd.name.startswith("wd_"):
                continue
            for sess in sorted(wd.iterdir()):
                if not sess.is_dir() or not sess.name.startswith("session_"):
                    continue
                wire = sess / "agents" / "main" / "wire.jsonl"
                if not wire.is_file():
                    continue
                try:
                    stat = wire.stat()
                except OSError as e:
                    logger.debug("无法 stat %s: %s", wire, e)
                    continue
                size, mtime = stat.st_size, stat.st_mtime
                age = now - mtime
                if size < min_size:
                    continue
                if max_size and size > max_size:
                    logger.debug("跳过过大 kimi session %s", wire)
                    continue
                if age < idle_sec:
                    continue
                if skip_sec and age > skip_sec:
                    continue
                yield SessionFile(
                    session_id=sess.name[len("session_") :],
                    project_dir_name=wd.name,
                    path=wire,
                    mtime=mtime,
                    size_bytes=size,
                    source="kimi",
                )
