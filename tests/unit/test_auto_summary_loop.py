"""
测试类型: 单元/集成测试
目标模块: jfox.auto_summary.loop
预估耗时: < 2秒
依赖要求: mock global_config_manager
"""

import asyncio
import logging
import threading
from unittest.mock import MagicMock, patch

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.auto_summary.loop import _tick_once, auto_summary_loop
from jfox.global_config import AutoSummaryConfig


class TestTickOnceNoWindowCheck:
    """调度窗口判断已从 _tick_once 移除，应由外层循环负责。"""

    def test_tick_once_does_not_check_window(self):
        """_tick_once 自身不调用 _is_within_schedule_window，窗口判断由外层循环负责。"""
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
                with patch("jfox.auto_summary.loop._is_within_schedule_window") as window_mock:
                    _tick_once(threading.Event())
                    run_once_mock.assert_called_once()
                    # _tick_once 不应检查调度窗口（已移至外层循环）
                    window_mock.assert_not_called()


class TestLoopScheduleWindow:
    """auto_summary_loop 在窗口外跳过 tick 并记录 DEBUG 日志。"""

    def _run_loop(self, cfg, within_window, caplog):
        """辅助函数：mock asyncio 的 executor 调用，运行一轮 loop 后退出。

        返回是否调度了 _tick_once（不实际执行 run_once）。
        """
        gm_mock = MagicMock()
        gm_mock.get_auto_summary_config.return_value = cfg
        stop_event = threading.Event()

        call_count = {"n": 0}
        tick_scheduled = {"called": False}

        async def fake_run_in_executor(_executor, fn, *args):
            call_count["n"] += 1
            if fn is _tick_once:
                tick_scheduled["called"] = True
                return "tick-summary"
            # lambda wait：第一次（启动延迟）返回 False，之后（间隔等待）返回 True
            return call_count["n"] != 1

        with caplog.at_level(logging.DEBUG, logger="jfox.auto_summary.loop"):
            with patch("jfox.auto_summary.loop.get_global_config_manager", return_value=gm_mock):
                with patch(
                    "jfox.auto_summary.loop._is_within_schedule_window",
                    return_value=within_window,
                ):
                    mock_asyncio = MagicMock()
                    mock_loop = MagicMock()
                    mock_loop.run_in_executor = fake_run_in_executor
                    mock_asyncio.get_running_loop.return_value = mock_loop
                    with patch("jfox.auto_summary.loop.asyncio", mock_asyncio):
                        asyncio.run(auto_summary_loop(stop_event))
        return tick_scheduled["called"]

    def test_loop_skips_tick_outside_window(self, caplog):
        cfg = AutoSummaryConfig(
            enabled=True,
            schedule_enabled=True,
            schedule_weekday_start_hour=0,
            schedule_weekday_end_hour=6,
            schedule_timezone="Asia/Shanghai",
        )
        tick_scheduled = self._run_loop(cfg, within_window=False, caplog=caplog)

        assert tick_scheduled is False
        assert "不在调度窗口" in caplog.text

    def test_loop_runs_tick_inside_window(self, caplog):
        cfg = AutoSummaryConfig(
            enabled=True,
            schedule_enabled=True,
            schedule_weekday_start_hour=0,
            schedule_weekday_end_hour=6,
            schedule_timezone="Asia/Shanghai",
        )
        tick_scheduled = self._run_loop(cfg, within_window=True, caplog=caplog)

        assert tick_scheduled is True
        assert "不在调度窗口" not in caplog.text

    def test_loop_runs_when_schedule_disabled(self, caplog):
        cfg = AutoSummaryConfig(
            enabled=True,
            schedule_enabled=False,
            schedule_weekday_start_hour=0,
            schedule_weekday_end_hour=6,
            schedule_timezone="Asia/Shanghai",
        )
        tick_scheduled = self._run_loop(cfg, within_window=False, caplog=caplog)

        assert tick_scheduled is True
        assert "不在调度窗口" not in caplog.text
