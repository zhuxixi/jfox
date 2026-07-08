"""
测试类型: 单元测试
目标模块: jfox.auto_summary.schedule
预估耗时: < 1秒
依赖要求: 无外部依赖
"""

from datetime import datetime, timezone

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.auto_summary.schedule import (
    NoOpHolidayProvider,
    _is_within_schedule_window,
    _parse_hour_window,
)
from jfox.global_config import AutoSummaryConfig


class TestParseHourWindow:
    def test_valid_window(self):
        assert _parse_hour_window("0-6") == (0, 6)
        assert _parse_hour_window("22-23") == (22, 23)

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError):
            _parse_hour_window("abc")

    def test_reversed_range_raises(self):
        with pytest.raises(ValueError):
            _parse_hour_window("6-0")

    def test_equal_start_end_raises(self):
        with pytest.raises(ValueError):
            _parse_hour_window("6-6")


class TestNoOpHolidayProvider:
    def test_saturday_is_weekend(self):
        provider = NoOpHolidayProvider()
        dt = datetime(2026, 7, 4, 3, 0, tzinfo=timezone.utc)  # Saturday
        assert provider.day_type(dt) == "weekend"

    def test_monday_is_weekday(self):
        provider = NoOpHolidayProvider()
        dt = datetime(2026, 7, 6, 3, 0, tzinfo=timezone.utc)  # Monday
        assert provider.day_type(dt) == "weekday"


class TestIsWithinScheduleWindow:
    def test_weekday_inside_window(self):
        cfg = AutoSummaryConfig(
            schedule_enabled=True,
            schedule_weekday_start_hour=0,
            schedule_weekday_end_hour=6,
            schedule_weekend_start_hour=0,
            schedule_weekend_end_hour=8,
            schedule_timezone="Asia/Shanghai",
        )
        # 2026-07-06 Monday 03:00 CST
        now = datetime(2026, 7, 5, 19, 0, tzinfo=timezone.utc)
        assert _is_within_schedule_window(cfg, now) is True

    def test_weekday_outside_window(self):
        cfg = AutoSummaryConfig(
            schedule_enabled=True,
            schedule_weekday_start_hour=0,
            schedule_weekday_end_hour=6,
            schedule_weekend_start_hour=0,
            schedule_weekend_end_hour=8,
            schedule_timezone="Asia/Shanghai",
        )
        # 2026-07-06 Monday 09:00 CST
        now = datetime(2026, 7, 6, 1, 0, tzinfo=timezone.utc)
        assert _is_within_schedule_window(cfg, now) is False

    def test_schedule_disabled_always_true(self):
        cfg = AutoSummaryConfig(schedule_enabled=False)
        now = datetime(2026, 7, 6, 12, 0, tzinfo=timezone.utc)
        assert _is_within_schedule_window(cfg, now) is True

    def test_invalid_timezone_falls_back_to_local(self):
        cfg = AutoSummaryConfig(
            schedule_enabled=True,
            schedule_timezone="Invalid/Timezone",
        )
        # 只要没有抛异常就算通过
        now = datetime(2026, 7, 6, 3, 0, tzinfo=timezone.utc)
        result = _is_within_schedule_window(cfg, now)
        assert isinstance(result, bool)
