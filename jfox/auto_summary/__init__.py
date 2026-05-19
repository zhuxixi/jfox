"""
Claude Code 会话自动总结

定时扫描 ~/.claude/projects/*/[uuid].jsonl，对静默超过阈值的"已结束"
session 调用 claude -p 生成结构化摘要并写入 jfox 知识库。

主要入口：
- run_once(): 同步执行一轮扫描+总结
- scan_pending(): 仅返回待处理 session 列表（dry-run）
- start_background_loop(): 在 asyncio 事件循环中启动后台循环（daemon 用）
"""

from .ledger import Ledger, LedgerEntry, SessionStatus
from .runner import RunReport, SummaryOutcome, run_once, scan_pending
from .scanner import SessionFile, iter_session_files

__all__ = [
    "Ledger",
    "LedgerEntry",
    "SessionStatus",
    "SessionFile",
    "iter_session_files",
    "run_once",
    "scan_pending",
    "RunReport",
    "SummaryOutcome",
]
