"""
Session 来源抽象：把 Claude Code / Kimi Code 的「扫描 + 对话提取」收拢为
统一的 SessionSource 接口，runner 只面向接口编程。
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator, Protocol, runtime_checkable

from ..global_config import AutoSummaryConfig
from .extractor import ExtractedDialog, extract_dialog
from .kimi_source import KimiCodeSource
from .scanner import SessionFile, default_claude_projects_dir, iter_session_files

logger = logging.getLogger(__name__)


def session_key(sf: SessionFile) -> str:
    """统一的 ledger 去重键：{source}:{session_id}"""
    return f"{sf.source}:{sf.session_id}"


@runtime_checkable
class SessionSource(Protocol):
    name: str

    def iter_sessions(self, cfg: AutoSummaryConfig) -> Iterator[SessionFile]: ...

    def extract_dialog(self, sf: SessionFile) -> ExtractedDialog: ...


class ClaudeCodeSource:
    """封装现有 scanner + extractor，逻辑零改动。"""

    name = "claude"

    def iter_sessions(self, cfg: AutoSummaryConfig) -> Iterator[SessionFile]:
        yield from iter_session_files(
            idle_threshold_minutes=cfg.idle_threshold_minutes,
            max_session_size_mb=cfg.max_session_size_mb,
            min_session_size_kb=cfg.min_session_size_kb,
            skip_after_days=cfg.skip_after_days,
        )

    def extract_dialog(self, sf: SessionFile) -> ExtractedDialog:
        return extract_dialog(sf.path)


def kimi_sessions_dir(cfg: AutoSummaryConfig) -> Path:
    """返回 Kimi session 根目录（配置优先，否则 ~/.kimi-code/sessions）"""
    if cfg.kimi_sessions_dir:
        return Path(cfg.kimi_sessions_dir).expanduser()
    return Path.home() / ".kimi-code" / "sessions"


def get_sources(cfg: AutoSummaryConfig) -> list[SessionSource]:
    """按 cfg.session_sources 返回启用的来源实例，auto-detect 目录存在性。"""
    sources: list[SessionSource] = []
    for name in cfg.session_sources:
        if name == "claude":
            if default_claude_projects_dir().is_dir():
                sources.append(ClaudeCodeSource())
            else:
                logger.info("跳过 claude 来源：目录不存在 %s", default_claude_projects_dir())
        elif name == "kimi":
            kdir = kimi_sessions_dir(cfg)
            if kdir.is_dir():
                sources.append(KimiCodeSource(kdir))
            else:
                logger.info("跳过 kimi 来源：目录不存在 %s", kdir)
        else:
            logger.warning("未知 session source: %s（已忽略）", name)
    return sources


def extract_dialog_for(sf: SessionFile, cfg: AutoSummaryConfig) -> ExtractedDialog:
    """按 sf.source 直接构造对应 source 提取对话。

    刻意不经过 get_sources 的目录 auto-detect：sf 来自扫描阶段，来源已确定，
    extract 时不应因当前环境目录缺失而失败（例如 CI 环境没有 ~/.claude/projects）。
    """
    if sf.source == "claude":
        return ClaudeCodeSource().extract_dialog(sf)
    if sf.source == "kimi":
        return KimiCodeSource(kimi_sessions_dir(cfg)).extract_dialog(sf)
    raise ValueError(f"没有启用的来源匹配 source={sf.source!r}")
