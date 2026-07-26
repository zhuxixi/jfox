"""备份调度判断：每日定点 schedule_time，今日已跑则跳过。

比 auto_summary 的窗口模型简单——备份只需"每日某时刻"，不需要工作日/周末分窗口。
"""

from __future__ import annotations

from datetime import datetime
from typing import Optional


def parse_time(s: str) -> tuple[int, int]:
    """解析 HH:MM，非法抛 ValueError"""
    h, m = s.split(":")
    hi, mi = int(h), int(m)
    if not (0 <= hi <= 23 and 0 <= mi <= 59):
        raise ValueError(f"非法时间: {s}")
    return hi, mi


def should_run_now(
    schedule_time: str,
    last_run_ts: Optional[str],
    now: Optional[datetime] = None,
) -> bool:
    """到今日 schedule_time 且今日未跑过 → True。

    - now 早于今日 schedule_time → False（还没到点）
    - last_run_ts 是今天 → False（今天已跑）
    - 否则 → True
    """
    now = now or datetime.now()
    hi, mi = parse_time(schedule_time)
    scheduled_today = now.replace(hour=hi, minute=mi, second=0, microsecond=0)
    if now < scheduled_today:
        return False
    if last_run_ts:
        try:
            last = datetime.fromisoformat(last_run_ts)
        except ValueError:
            last = None
        if last is not None and last.date() == now.date():
            return False
    return True
