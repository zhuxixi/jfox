"""
测试类型: 单元测试
目标模块: jfox.auto_summary.cli
预估耗时: < 2秒
依赖要求: mock global_config_manager
"""

from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.auto_summary.cli import auto_summary_app

runner = CliRunner()


class TestEnableScheduleOptions:
    def test_enable_schedule_options(self):
        gm_mock = MagicMock()
        gm_mock.update_auto_summary_config.return_value = True
        with patch("jfox.auto_summary.cli.get_global_config_manager", return_value=gm_mock):
            result = runner.invoke(
                auto_summary_app,
                [
                    "enable",
                    "--schedule-enabled",
                    "--schedule-weekday-window", "1-5",
                    "--schedule-weekend-window", "2-7",
                    "--schedule-timezone", "UTC",
                ],
            )
            assert result.exit_code == 0
            gm_mock.update_auto_summary_config.assert_called_once()
            call_kwargs = gm_mock.update_auto_summary_config.call_args.kwargs
            assert call_kwargs["schedule_enabled"] is True
            assert call_kwargs["schedule_weekday_start_hour"] == 1
            assert call_kwargs["schedule_weekday_end_hour"] == 5
            assert call_kwargs["schedule_weekend_start_hour"] == 2
            assert call_kwargs["schedule_weekend_end_hour"] == 7
            assert call_kwargs["schedule_timezone"] == "UTC"

    def test_enable_invalid_window_format(self):
        gm_mock = MagicMock()
        with patch("jfox.auto_summary.cli.get_global_config_manager", return_value=gm_mock):
            result = runner.invoke(
                auto_summary_app,
                ["enable", "--schedule-weekday-window", "abc"],
            )
            assert result.exit_code != 0
            assert "窗口" in result.output or "format" in result.output.lower()


class TestStatusScheduleOutput:
    def test_status_includes_schedule_info(self):
        from jfox.global_config import AutoSummaryConfig

        cfg = AutoSummaryConfig(
            schedule_enabled=True,
            schedule_weekday_start_hour=0,
            schedule_weekday_end_hour=6,
            schedule_timezone="Asia/Shanghai",
        )
        gm_mock = MagicMock()
        gm_mock.get_auto_summary_config.return_value = cfg
        with patch("jfox.auto_summary.cli.get_global_config_manager", return_value=gm_mock):
            result = runner.invoke(auto_summary_app, ["status", "--format", "json"])
            assert result.exit_code == 0
            import json
            data = json.loads(result.output)
            assert data["config"]["schedule_enabled"] is True
            assert "in_schedule_window" in data["progress"] or "schedule" in data
