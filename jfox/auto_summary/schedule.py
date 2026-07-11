"""
auto-summary 调度时间窗口判断。

提供：
- HolidayProvider 抽象接口（预留节假日/调休扩展）
- NoOpHolidayProvider：仅按星期判断工作日/周末
- _is_within_schedule_window(): 判断当前时间是否在允许运行窗口内
- _parse_hour_window(): 解析 CLI 传入的 "0-6" 格式窗口字符串
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

if TYPE_CHECKING:
    from ..global_config import AutoSummaryConfig

logger = logging.getLogger(__name__)


class HolidayProvider(ABC):
    """节假日/工作日判断接口，预留中国节假日/调休扩展。"""

    @abstractmethod
    def day_type(self, dt: datetime) -> str:
        """
        返回日期类型：'weekday' | 'weekend' | 'holiday'

        调休上班日应返回 'weekday'。
        """
        ...


class NoOpHolidayProvider(HolidayProvider):
    """默认实现：仅根据星期判断，周六/周日为 weekend，其余为 weekday。"""

    def day_type(self, dt: datetime) -> str:
        return "weekend" if dt.weekday() >= 5 else "weekday"


def _parse_hour_window(window_str: str) -> tuple[int, int]:
    """解析 '0-6' 格式的小时窗口字符串，返回 (start, end)。"""
    parts = window_str.split("-")
    if len(parts) != 2:
        raise ValueError(f"窗口格式错误，应为 'start-end': {window_str!r}")
    try:
        start = int(parts[0].strip())
        end = int(parts[1].strip())
    except ValueError as exc:
        raise ValueError(f"窗口小时必须是整数: {window_str!r}") from exc

    if not (0 <= start < 24 and 0 < end <= 24):
        raise ValueError(f"窗口小时必须在 [0, 24] 范围内（结束小时可为 24）: {window_str!r}")
    if end <= start:
        raise ValueError(f"窗口结束小时必须大于开始小时: {window_str!r}")
    return start, end


def _get_holiday_provider(provider_name: Optional[str]) -> HolidayProvider:
    """根据配置名返回 HolidayProvider 实例。"""
    if not provider_name:
        return NoOpHolidayProvider()
    # 第一期仅支持 NoOpHolidayProvider；其他值记录 warning 并回退。
    logger.warning(
        "不支持的 schedule_holiday_provider=%s，使用默认 NoOpHolidayProvider",
        provider_name,
    )
    return NoOpHolidayProvider()


def _is_within_schedule_window(
    cfg: AutoSummaryConfig,
    now: Optional[datetime] = None,
) -> bool:
    """
    判断当前时间是否在 auto-summary 允许运行窗口内。

    - schedule_enabled=False 时始终返回 True（向后兼容）。
    - 时区解析失败时回退到系统本地时间。
    - 内部异常不应中断 daemon，保守返回 True 并记录 error。
    """
    if not cfg.schedule_enabled:
        return True

    now = now or datetime.now(timezone.utc)

    tz = None
    if cfg.schedule_timezone:
        try:
            tz = ZoneInfo(cfg.schedule_timezone)
        except (ZoneInfoNotFoundError, ValueError) as e:
            # 时区名无效时回退到系统本地时间
            logger.warning(
                "无法解析时区 %s，回退到系统本地时间: %s",
                cfg.schedule_timezone,
                e,
            )

    try:
        local_now = now.astimezone(tz) if tz else now.astimezone()
    except (TypeError, OSError) as e:
        logger.error("时间转换异常，保守允许运行: %s", e)
        return True

    try:
        provider = _get_holiday_provider(cfg.schedule_holiday_provider)
        day_type = provider.day_type(local_now)

        if day_type == "weekend":
            start = cfg.schedule_weekend_start_hour
            end = cfg.schedule_weekend_end_hour
        elif day_type == "holiday":
            # 本期未配置节假日窗口，先复用周末窗口作为兜底
            start = cfg.schedule_weekend_start_hour
            end = cfg.schedule_weekend_end_hour
        else:
            start = cfg.schedule_weekday_start_hour
            end = cfg.schedule_weekday_end_hour

        current_hour = local_now.hour
        return start <= current_hour < end
    except Exception as e:
        logger.error("调度窗口判断异常，保守允许运行: %s", e)
        return True
