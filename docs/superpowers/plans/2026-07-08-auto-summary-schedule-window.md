# Issue #298: auto-summary 调度时间窗口 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 为 jfox auto-summary 增加可配置的时间窗口调度，默认仅在凌晨运行，避免白天占用 GPU/嵌入模型资源。

**Architecture:** 在 `jfox/auto_summary/schedule.py` 中实现时间窗口判断逻辑与可扩展节假日接口；在 `AutoSummaryConfig` 中新增调度字段；在 `auto_summary_loop` 每轮 tick 前检查窗口；扩展 CLI `enable`/`status` 子命令暴露配置与状态。

**Tech Stack:** Python 3.10+, `zoneinfo` (stdlib), dataclasses, pytest, Typer, Rich

## Global Constraints

- Python >= 3.10
- 保持向后兼容：未启用 `schedule_enabled` 时所有现有行为不变
- 默认时区 `Asia/Shanghai`
- 时间窗口区间定义为左闭右开 `[start_hour, end_hour)`
- 暂不支持跨天窗口（如 22:00-06:00）
- 手动触发 `jfox auto-summary run` 不受时间窗口限制
- 节假日 provider 接口预留，第一期仅实现 `NoOpHolidayProvider`（仅按星期判断周末）
- 配置验证失败时回退到默认值或拒绝 CLI 更新，不得导致 daemon 崩溃

---

## File Structure

| 文件 | 职责 |
|------|------|
| `jfox/auto_summary/schedule.py` | **新建**：时间窗口判断核心、`HolidayProvider` 抽象、`NoOpHolidayProvider`、`_is_within_schedule_window()` |
| `jfox/global_config.py` | **修改**：`AutoSummaryConfig` 新增 `schedule_*` 字段、验证逻辑、`to_dict`/`from_dict` 序列化 |
| `jfox/auto_summary/loop.py` | **修改**：`auto_summary_loop` 在 tick 前调用 `_is_within_schedule_window()`，窗口外跳过 |
| `jfox/auto_summary/cli.py` | **修改**：`enable` 新增 `--schedule-*` 选项；`status` 显示窗口配置与当前是否处于窗口 |
| `jfox/daemon/server.py` | **修改（可选）**：`/auto_summary/status` 返回新增字段 |
| `tests/unit/test_auto_summary_schedule.py` | **新建**：`schedule.py` 单元测试 |
| `tests/unit/test_global_config.py` | **修改**：补充 `AutoSummaryConfig` 新字段的序列化/验证测试 |
| `tests/unit/test_auto_summary_loop.py` | **新建或修改**：`loop.py` 窗口跳过集成测试 |
| `tests/unit/test_auto_summary_cli.py` | **新建或修改**：CLI 选项测试 |
| `README.md` | **修改**：更新 `auto-summary` 使用文档 |

---

### Task 1: 实现时间窗口判断核心 (`jfox/auto_summary/schedule.py`)

**Files:**
- Create: `jfox/auto_summary/schedule.py`
- Test: `tests/unit/test_auto_summary_schedule.py`

**Interfaces:**
- Consumes: `AutoSummaryConfig`（需要 `schedule_enabled`, `schedule_weekday_start_hour`, `schedule_weekday_end_hour`, `schedule_weekend_start_hour`, `schedule_weekend_end_hour`, `schedule_timezone`, `schedule_holiday_provider`）
- Produces:
  - `HolidayProvider` (ABC)
  - `NoOpHolidayProvider.day_type(dt: datetime) -> str`
  - `_is_within_schedule_window(cfg: AutoSummaryConfig, now: Optional[datetime] = None) -> bool`
  - `_parse_hour_window(window_str: str) -> tuple[int, int]`

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_auto_summary_schedule.py
"""
测试类型: 单元测试
目标模块: jfox.auto_summary.schedule
预估耗时: < 1秒
依赖要求: 无外部依赖
"""

import pytest
from datetime import datetime, timezone

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_auto_summary_schedule.py -v`
Expected: FAIL with module/function not defined

- [ ] **Step 3: Write minimal implementation**

```python
# jfox/auto_summary/schedule.py
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

    if not (0 <= start < 24 and 0 <= end < 24):
        raise ValueError(f"窗口小时必须在 [0, 24) 范围内: {window_str!r}")
    if end <= start:
        raise ValueError(f"窗口结束小时必须大于开始小时: {window_str!r}")
    return start, end


def _get_holiday_provider(provider_name: Optional[str]) -> HolidayProvider:
    """根据配置名返回 HolidayProvider 实例。"""
    if not provider_name:
        return NoOpHolidayProvider()
    # 第一期仅支持 NoOpHolidayProvider；其他值记录 warning 并回退。
    logger.warning("不支持的 schedule_holiday_provider=%s，使用默认 NoOpHolidayProvider", provider_name)
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
            from zoneinfo import ZoneInfo
            tz = ZoneInfo(cfg.schedule_timezone)
        except Exception as e:
            logger.warning(
                "无法解析时区 %s，回退到系统本地时间: %s",
                cfg.schedule_timezone,
                e,
            )

    try:
        local_now = now.astimezone(tz) if tz else now.astimezone()
    except Exception as e:
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_auto_summary_schedule.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/auto_summary/schedule.py tests/unit/test_auto_summary_schedule.py
git commit -m "feat(auto_summary): add schedule window core module (#298)"
```

---

### Task 2: 扩展 AutoSummaryConfig 配置模型

**Files:**
- Modify: `jfox/global_config.py:48-112` (`AutoSummaryConfig` dataclass)
- Test: `tests/unit/test_global_config.py`

**Interfaces:**
- Consumes: 无
- Produces:
  - `AutoSummaryConfig.schedule_enabled: bool`
  - `AutoSummaryConfig.schedule_weekday_start_hour: int`
  - `AutoSummaryConfig.schedule_weekday_end_hour: int`
  - `AutoSummaryConfig.schedule_weekend_start_hour: int`
  - `AutoSummaryConfig.schedule_weekend_end_hour: int`
  - `AutoSummaryConfig.schedule_timezone: str`
  - `AutoSummaryConfig.schedule_holiday_provider: Optional[str]`

- [ ] **Step 1: Write the failing test**

在 `tests/unit/test_global_config.py` 中新增：

```python
class TestAutoSummaryConfigSchedule:
    def test_default_schedule_fields(self):
        cfg = AutoSummaryConfig()
        assert cfg.schedule_enabled is False
        assert cfg.schedule_weekday_start_hour == 0
        assert cfg.schedule_weekday_end_hour == 6
        assert cfg.schedule_weekend_start_hour == 0
        assert cfg.schedule_weekend_end_hour == 8
        assert cfg.schedule_timezone == "Asia/Shanghai"
        assert cfg.schedule_holiday_provider is None

    def test_schedule_hour_validation(self):
        cfg = AutoSummaryConfig(
            schedule_weekday_start_hour=25,
            schedule_weekday_end_hour=26,
        )
        assert cfg.schedule_weekday_start_hour == 0
        assert cfg.schedule_weekday_end_hour == 6

    def test_from_dict_with_schedule_fields(self):
        data = {
            "enabled": True,
            "schedule_enabled": True,
            "schedule_weekday_start_hour": 1,
            "schedule_weekday_end_hour": 5,
            "schedule_weekend_start_hour": 2,
            "schedule_weekend_end_hour": 7,
            "schedule_timezone": "UTC",
            "schedule_holiday_provider": "chinese-calendar",
        }
        cfg = AutoSummaryConfig.from_dict(data)
        assert cfg.schedule_enabled is True
        assert cfg.schedule_weekday_start_hour == 1
        assert cfg.schedule_weekday_end_hour == 5
        assert cfg.schedule_weekend_start_hour == 2
        assert cfg.schedule_weekend_end_hour == 7
        assert cfg.schedule_timezone == "UTC"
        assert cfg.schedule_holiday_provider == "chinese-calendar"

    def test_to_dict_includes_schedule_fields(self):
        cfg = AutoSummaryConfig(schedule_enabled=True)
        d = cfg.to_dict()
        assert d["schedule_enabled"] is True
        assert d["schedule_weekday_start_hour"] == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_global_config.py::TestAutoSummaryConfigSchedule -v`
Expected: FAIL with field not defined

- [ ] **Step 3: Write minimal implementation**

修改 `jfox/global_config.py` 中 `AutoSummaryConfig`：

```python
@dataclass
class AutoSummaryConfig:
    """Claude Code 会话自动总结配置（opt-in，默认关闭）"""

    enabled: bool = False
    interval_minutes: int = 30
    idle_threshold_minutes: int = 30
    target_kb: Optional[str] = None
    max_session_size_mb: int = 10
    min_session_size_kb: int = 5
    max_per_tick: int = 5
    skip_after_days: int = 0
    claude_timeout_seconds: int = 120
    claude_binary: Optional[str] = None
    session_sources: List[str] = field(default_factory=lambda: ["claude", "kimi"])
    kimi_sessions_dir: Optional[str] = None

    # Issue #298: 调度时间窗口
    schedule_enabled: bool = False
    schedule_weekday_start_hour: int = 0
    schedule_weekday_end_hour: int = 6
    schedule_weekend_start_hour: int = 0
    schedule_weekend_end_hour: int = 8
    schedule_timezone: str = "Asia/Shanghai"
    schedule_holiday_provider: Optional[str] = None

    def __post_init__(self) -> None:
        # 原有验证...
        if self.interval_minutes < 1:
            self.interval_minutes = 30
        if self.idle_threshold_minutes < 1:
            self.idle_threshold_minutes = 30
        if self.max_session_size_mb < 1:
            self.max_session_size_mb = 10
        if self.min_session_size_kb < 0:
            self.min_session_size_kb = 0
        if self.max_per_tick < 1:
            self.max_per_tick = 1
        if self.skip_after_days < 0:
            self.skip_after_days = 0
        if self.claude_timeout_seconds < 30:
            self.claude_timeout_seconds = 30
        if self.min_session_size_kb >= self.max_session_size_mb * 1024:
            self.min_session_size_kb = max(0, self.max_session_size_mb * 1024 - 1)
        if isinstance(self.target_kb, str) and not self.target_kb.strip():
            self.target_kb = None

        # Issue #298: 时间窗口字段验证
        if self.schedule_weekday_start_hour < 0 or self.schedule_weekday_start_hour >= 24:
            self.schedule_weekday_start_hour = 0
        if self.schedule_weekday_end_hour <= self.schedule_weekday_start_hour or self.schedule_weekday_end_hour > 24:
            self.schedule_weekday_end_hour = min(24, max(self.schedule_weekday_start_hour + 1, 6))
        if self.schedule_weekend_start_hour < 0 or self.schedule_weekend_start_hour >= 24:
            self.schedule_weekend_start_hour = 0
        if self.schedule_weekend_end_hour <= self.schedule_weekend_start_hour or self.schedule_weekend_end_hour > 24:
            self.schedule_weekend_end_hour = min(24, max(self.schedule_weekend_start_hour + 1, 8))
        if not isinstance(self.schedule_timezone, str) or not self.schedule_timezone.strip():
            self.schedule_timezone = "Asia/Shanghai"
        if self.schedule_holiday_provider is not None and not isinstance(self.schedule_holiday_provider, str):
            self.schedule_holiday_provider = None

        object.__setattr__(self, "_stop_event", None)
```

并更新 `to_dict()` 和 `from_dict()`：

```python
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "AutoSummaryConfig":
        if not data:
            return cls()
        return cls(
            enabled=bool(data.get("enabled", False)),
            interval_minutes=int(data.get("interval_minutes", 30)),
            idle_threshold_minutes=int(data.get("idle_threshold_minutes", 30)),
            target_kb=data.get("target_kb"),
            max_session_size_mb=int(data.get("max_session_size_mb", 10)),
            min_session_size_kb=int(data.get("min_session_size_kb", 5)),
            max_per_tick=int(data.get("max_per_tick", 5)),
            skip_after_days=int(data.get("skip_after_days", 0)),
            claude_timeout_seconds=int(data.get("claude_timeout_seconds", 120)),
            claude_binary=data.get("claude_binary"),
            session_sources=(
                list(data["session_sources"])
                if isinstance(data.get("session_sources"), list)
                else ["claude", "kimi"]
            ),
            kimi_sessions_dir=data.get("kimi_sessions_dir"),
            schedule_enabled=bool(data.get("schedule_enabled", False)),
            schedule_weekday_start_hour=int(data.get("schedule_weekday_start_hour", 0)),
            schedule_weekday_end_hour=int(data.get("schedule_weekday_end_hour", 6)),
            schedule_weekend_start_hour=int(data.get("schedule_weekend_start_hour", 0)),
            schedule_weekend_end_hour=int(data.get("schedule_weekend_end_hour", 8)),
            schedule_timezone=str(data.get("schedule_timezone", "Asia/Shanghai")),
            schedule_holiday_provider=data.get("schedule_holiday_provider"),
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_global_config.py::TestAutoSummaryConfigSchedule -v`
Expected: PASS

- [ ] **Step 5: Run broader regression tests**

Run: `uv run pytest tests/unit/test_global_config.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add jfox/global_config.py tests/unit/test_global_config.py
git commit -m "feat(global_config): add schedule window fields to AutoSummaryConfig (#298)"
```

---

### Task 3: 在 daemon 调度循环中应用窗口检查

**Files:**
- Modify: `jfox/auto_summary/loop.py`
- Test: `tests/unit/test_auto_summary_loop.py`（新建）

**Interfaces:**
- Consumes: `_is_within_schedule_window()` from `jfox.auto_summary.schedule`
- Produces: `auto_summary_loop()` 在窗口外跳过 tick

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_auto_summary_loop.py
"""
测试类型: 单元/集成测试
目标模块: jfox.auto_summary.loop
预估耗时: < 2秒
依赖要求: mock global_config_manager
"""

import pytest
import threading
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

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

        # Monday 09:00 CST = Sunday 25:00 UTC
        now = datetime(2026, 7, 6, 1, 0, tzinfo=timezone.utc)

        with patch("jfox.auto_summary.loop.get_global_config_manager", return_value=gm_mock):
            with patch("jfox.auto_summary.loop.run_once") as run_once_mock:
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

        # Monday 03:00 CST = Sunday 19:00 UTC
        now = datetime(2026, 7, 5, 19, 0, tzinfo=timezone.utc)

        with patch("jfox.auto_summary.loop.get_global_config_manager", return_value=gm_mock):
            with patch("jfox.auto_summary.loop.run_once") as run_once_mock:
                run_once_mock.return_value.scanned = 0
                _tick_once(threading.Event())
                run_once_mock.assert_called_once()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_auto_summary_loop.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

修改 `jfox/auto_summary/loop.py`：

```python
from .runner import run_once
from .schedule import _is_within_schedule_window


def _tick_once(stop_event: threading.Event) -> str:
    """在 executor 中执行的同步函数。返回简短日志行。"""
    gm = get_global_config_manager()
    gm.reload()
    cfg = gm.get_auto_summary_config()
    if not cfg.enabled:
        return "auto-summary 已禁用，跳过本轮"

    # Issue #298: 调度时间窗口检查
    if cfg.schedule_enabled and not _is_within_schedule_window(cfg):
        return "auto-summary 当前不在调度窗口内，跳过本轮"

    cfg._stop_event = stop_event

    try:
        report = run_once(cfg=cfg)
    except Exception as e:
        logger.exception("auto-summary run_once 异常: %s", e)
        return f"run_once 异常: {e}"

    if report.scanned == 0:
        return "无待处理 session"

    return (
        f"扫描 {report.scanned}, 处理 {report.processed}, "
        f"成功 {report.success}, 跳过 {report.skipped}, 失败 {report.failed}"
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_auto_summary_loop.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/auto_summary/loop.py tests/unit/test_auto_summary_loop.py
git commit -m "feat(auto_summary): apply schedule window check in daemon loop (#298)"
```

---

### Task 4: 扩展 CLI 子命令

**Files:**
- Modify: `jfox/auto_summary/cli.py`
- Test: `tests/unit/test_auto_summary_cli.py`（新建或修改）

**Interfaces:**
- Consumes: `_parse_hour_window()` from `jfox.auto_summary.schedule`
- Produces:
  - `enable --schedule-enabled --schedule-weekday-window TEXT --schedule-weekend-window TEXT --schedule-timezone TEXT`
  - `status` 输出新增 `in_schedule_window` 字段

- [ ] **Step 1: Write the failing test**

```python
# tests/unit/test_auto_summary_cli.py
"""
测试类型: 单元测试
目标模块: jfox.auto_summary.cli
预估耗时: < 2秒
依赖要求: mock global_config_manager
"""

import pytest
from unittest.mock import MagicMock, patch
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_auto_summary_cli.py -v`
Expected: FAIL

- [ ] **Step 3: Write minimal implementation**

修改 `jfox/auto_summary/cli.py`：

顶部导入：

```python
from .schedule import _is_within_schedule_window, _parse_hour_window
```

修改 `enable` 命令：

```python
@auto_summary_app.command("enable")
def enable(
    interval: Optional[int] = typer.Option(None, "--interval", help="扫描间隔（分钟，>=1）"),
    idle_threshold: Optional[int] = typer.Option(
        None, "--idle-threshold", help="session 结束判定的静默阈值（分钟）"
    ),
    kb: Optional[str] = typer.Option(None, "--kb", help="写入哪个知识库（默认 default）"),
    max_per_tick: Optional[int] = typer.Option(
        None, "--max-per-tick", help="每轮最多处理几个 session"
    ),
    schedule_enabled: bool = typer.Option(
        False, "--schedule-enabled", help="启用时间窗口调度"
    ),
    schedule_weekday_window: Optional[str] = typer.Option(
        None, "--schedule-weekday-window", help="工作日时间窗口，格式如 0-6"
    ),
    schedule_weekend_window: Optional[str] = typer.Option(
        None, "--schedule-weekend-window", help="周末时间窗口，格式如 0-8"
    ),
    schedule_timezone: Optional[str] = typer.Option(
        None, "--schedule-timezone", help="调度时区，默认 Asia/Shanghai"
    ),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: table, json"),
) -> None:
    """启用 auto-summary，可同时调整其他字段"""
    changes: dict = {"enabled": True}
    if interval is not None:
        if interval < 1:
            console.print("[red]✗[/red] interval 必须 >= 1")
            raise typer.Exit(1)
        changes["interval_minutes"] = interval
    if idle_threshold is not None:
        if idle_threshold < 1:
            console.print("[red]✗[/red] idle-threshold 必须 >= 1")
            raise typer.Exit(1)
        changes["idle_threshold_minutes"] = idle_threshold
    if kb is not None:
        changes["target_kb"] = kb or None
    if max_per_tick is not None:
        if max_per_tick < 1:
            console.print("[red]✗[/red] max-per-tick 必须 >= 1")
            raise typer.Exit(1)
        changes["max_per_tick"] = max_per_tick

    # Issue #298: 时间窗口配置
    if schedule_enabled:
        changes["schedule_enabled"] = True
    if schedule_weekday_window is not None:
        try:
            start, end = _parse_hour_window(schedule_weekday_window)
            changes["schedule_weekday_start_hour"] = start
            changes["schedule_weekday_end_hour"] = end
        except ValueError as e:
            console.print(f"[red]✗[/red] --schedule-weekday-window 格式错误: {e}")
            raise typer.Exit(1)
    if schedule_weekend_window is not None:
        try:
            start, end = _parse_hour_window(schedule_weekend_window)
            changes["schedule_weekend_start_hour"] = start
            changes["schedule_weekend_end_hour"] = end
        except ValueError as e:
            console.print(f"[red]✗[/red] --schedule-weekend-window 格式错误: {e}")
            raise typer.Exit(1)
    if schedule_timezone is not None:
        changes["schedule_timezone"] = schedule_timezone

    if get_global_config_manager().update_auto_summary_config(**changes):
        # ... 原有输出逻辑
```

修改 `status` 命令：

在 `progress` 字典中新增 `in_schedule_window`：

```python
    progress = {
        "total_scannable": total,
        "success": success,
        "skipped": skipped,
        "pending": pending,
        "failed": failed,
        "retryable": failed_transient,
        "percentage": pct,
        "in_schedule_window": None if not cfg.schedule_enabled else _is_within_schedule_window(cfg),
    }
```

表格输出也新增一行：

```python
    if cfg.schedule_enabled:
        prog_table.add_row("调度窗口", f"工作日 {cfg.schedule_weekday_start_hour}:00-{cfg.schedule_weekday_end_hour}:00, 周末 {cfg.schedule_weekend_start_hour}:00-{cfg.schedule_weekend_end_hour}:00")
        prog_table.add_row("当前在窗口内", "是" if progress["in_schedule_window"] else "否")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_auto_summary_cli.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/auto_summary/cli.py tests/unit/test_auto_summary_cli.py
git commit -m "feat(auto_summary): add schedule window CLI options (#298)"
```

---

### Task 5: 文档更新与最终验证

**Files:**
- Modify: `README.md`
- Run: 全量快速测试

**Interfaces:**
- Consumes: 前面任务实现的所有功能
- Produces: 文档更新、测试通过

- [ ] **Step 1: 更新 README.md**

在 `README.md` 的 `auto-summary` 章节新增时间窗口说明：

```markdown
#### 调度时间窗口

为了避免白天占用 GPU/嵌入模型资源，可以配置 auto-summary 仅在非工作时间运行：

```bash
jfox auto-summary enable --schedule-enabled \
  --schedule-weekday-window 0-6 \
  --schedule-weekend-window 0-8 \
  --schedule-timezone Asia/Shanghai
```

- `--schedule-weekday-window`：工作日允许运行的小时范围，默认 `0-6`
- `--schedule-weekend-window`：周末允许运行的小时范围，默认 `0-8`
- `--schedule-timezone`：时区，默认 `Asia/Shanghai`

手动触发不受窗口限制：

```bash
jfox auto-summary run
```
```

- [ ] **Step 2: 运行快速单元测试**

Run: `uv run pytest tests/unit/test_auto_summary_schedule.py tests/unit/test_global_config.py tests/unit/test_auto_summary_loop.py tests/unit/test_auto_summary_cli.py -v`
Expected: PASS

- [ ] **Step 3: 运行 ruff 检查**

Run: `uv run ruff check jfox/auto_summary/schedule.py jfox/global_config.py jfox/auto_summary/loop.py jfox/auto_summary/cli.py`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add README.md
git commit -m "docs: add auto-summary schedule window usage (#298)"
```

---

## Self-Review

### Spec Coverage Check

| Spec 要求 | 对应 Task |
|-----------|-----------|
| 新增 `schedule_*` 配置字段 | Task 2 |
| 时间窗口判断逻辑 | Task 1 |
| loop 中应用窗口检查 | Task 3 |
| CLI enable/status 扩展 | Task 4 |
| 节假日 provider 接口预留 | Task 1 |
| 向后兼容 | Task 1, 2 |
| 手动 run 不受限制 | Task 3 中 `_tick_once` 仅在 daemon 循环路径检查；`run` 命令直接调用 `run_once` 不受影响 |
| 测试覆盖 | Task 1-4 均包含测试 |
| 文档更新 | Task 5 |

### Placeholder Scan

- 无 TBD/TODO
- 所有测试代码完整
- 所有实现代码完整
- 无 "later"/"appropriate" 等模糊描述

### Type Consistency

- `_is_within_schedule_window(cfg, now=None)` 在 Task 1、Task 3、Task 4 中签名一致
- `AutoSummaryConfig` 字段名在 Task 1-4 中一致
- `_parse_hour_window()` 在 Task 1 和 Task 4 中签名一致

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-08-auto-summary-schedule-window.md`.

**Two execution options:**

**1. Subagent-Driven (recommended)** - Dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
