"""
测试类型: 单元/集成测试
目标模块: jfox.auto_summary.loop
预估耗时: < 2秒
依赖要求: mock global_config_manager
"""

import threading
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.auto_summary.loop import _tick_once
from jfox.global_config import AutoSummaryConfig


class TestTickOnceScheduleWindow:
    def test_tick_skipped_outside_window(self):
        cfg = AutoSummaryConfig(
            enabled=True,
            schedule_enabled=True,
            schedule_weekday_start_hour=0,
            schedule_weekday_end_hour=6,
            schedule_timezone="Asia/Shanghai",
        )
        gm_mock = MagicMock()
        gm_mock.get_auto_summary_config.return_value = cfg

        with patch("jfox.auto_summary.loop.get_global_config_manager", return_value=gm_mock):
            with patch("jfox.auto_summary.loop.run_once") as run_once_mock:
                with patch("jfox.auto_summary.loop._is_within_schedule_window", return_value=False):
                    result = _tick_once(threading.Event())
                    run_once_mock.assert_not_called()
                    assert "不在调度窗口" in result

    def test_tick_runs_inside_window(self):
        cfg = AutoSummaryConfig(
            enabled=True,
            schedule_enabled=True,
            schedule_weekday_start_hour=0,
            schedule_weekday_end_hour=6,
            schedule_timezone="Asia/Shanghai",
        )
        gm_mock = MagicMock()
        gm_mock.get_auto_summary_config.return_value = cfg

        with patch("jfox.auto_summary.loop.get_global_config_manager", return_value=gm_mock):
            with patch("jfox.auto_summary.loop.run_once") as run_once_mock:
                run_once_mock.return_value.scanned = 0
                with patch("jfox.auto_summary.loop._is_within_schedule_window", return_value=True):
                    _tick_once(threading.Event())
                    run_once_mock.assert_called_once()
