# Issue #298: auto-summary 调度时间窗口设计

> 让 auto-summary 仅在非工作时间运行，避免白天占用 GPU/嵌入模型资源。

---

## 1. 背景与问题

当前 `auto-summary` 在 daemon 启动后按固定 `interval_minutes` 轮询，只要启用就会持续扫描 Claude Code/Kimi 会话并调用 `claude -p` 生成摘要。该过程会占用 GPU/嵌入模型资源，导致用户白天工作时出现卡顿。

Issue #298 要求将自动调度限制在**非工作时间**，默认仅在凌晨等低负载时段运行。

---

## 2. 目标

- 为 `auto-summary` 增加可配置的时间窗口，默认在凌晨运行。
- 支持工作日与周末使用不同的时间窗口。
- 预留中国节假日（含调休）的判断接口，供后续迭代扩展。
- 保持现有行为向后兼容：未启用时间窗口时行为不变。
- 通过 CLI 和全局配置管理时间窗口，无需每次启动 daemon 时手动指定参数。
- 手动触发 `jfox auto-summary run` 不受时间窗口限制（用户显式执行）。

---

## 3. 非目标

- 本期不实现中国节假日/调休的具体数据源集成。
- 不支持按单个日期临时跳过（如用户临时请假一天）。
- 不修改 `run_once` 内部的摘要生成逻辑。
- 不改变 `interval_minutes` 的轮询机制本身。

---

## 4. 设计方案

### 4.1 整体思路

在 `auto_summary_loop` 的每轮 tick 前增加一次**时间窗口检查**。如果当前时间不在允许的运行窗口内，则跳过本轮，仅记录 debug 日志。时间窗口通过 `AutoSummaryConfig` 持久化配置，支持工作日/周末分别设置。

同时定义一个 `HolidayProvider` 抽象接口。第一期内置 `NoOpHolidayProvider`（仅做周末判断），未来可通过配置 `schedule_holiday_provider` 切换为 `ChineseCalendarProvider` 等实现，而无需改动核心调度逻辑。

### 4.2 配置模型扩展

在 `jfox/global_config.py` 的 `AutoSummaryConfig` 中新增以下字段：

```python
schedule_enabled: bool = False
schedule_weekday_start_hour: int = 0
schedule_weekday_end_hour: int = 6
schedule_weekend_start_hour: int = 0
schedule_weekend_end_hour: int = 8
schedule_timezone: str = "Asia/Shanghai"
schedule_holiday_provider: Optional[str] = None  # 预留，第一期仅支持 None
```

**默认值说明：**

- `schedule_enabled=False`：默认不启用时间窗口，保持向后兼容。
- 工作日窗口 `00:00-06:00`，周末窗口 `00:00-08:00`（周末更宽松）。
- 时区默认 `Asia/Shanghai`，符合项目主要用户场景。

**验证规则（`__post_init__` / `from_dict`）：**

- `start_hour` 和 `end_hour` 必须在 `[0, 24)` 范围内。
- `end_hour` 必须大于 `start_hour`（暂不支持跨天窗口，如 22:00-06:00）。
- `schedule_timezone` 解析失败时回退到系统本地时间，并记录 warning。
- `schedule_holiday_provider` 第一期仅接受 `None`，其他值记录 warning 并忽略。

### 4.3 调度逻辑变更

修改 `jfox/auto_summary/loop.py`：

```python
async def auto_summary_loop(stop_event: threading.Event) -> None:
    # ... 启动延迟 ...
    while not stop_event.is_set():
        gm = get_global_config_manager()
        cfg = gm.get_auto_summary_config()
        interval_sec = max(60, cfg.interval_minutes * 60)

        if cfg.enabled:
            if cfg.schedule_enabled and not _is_within_schedule_window(cfg):
                logger.debug("auto-summary 当前不在调度窗口内，跳过本轮")
            else:
                try:
                    summary = await loop.run_in_executor(None, _tick_once, stop_event)
                    logger.info("auto-summary tick: %s", summary)
                except Exception as e:
                    logger.exception("auto-summary tick 异常: %s", e)
        else:
            logger.debug("auto-summary 处于禁用状态，等待下一轮")

        # ... 等待 interval_sec ...
```

新增辅助函数 `_is_within_schedule_window(cfg)`：

1. 获取当前 UTC 时间。
2. 使用 `zoneinfo` 转换为 `cfg.schedule_timezone`。
3. 通过 `HolidayProvider` 判断今天是工作日还是周末/节假日（第一期 `NoOpHolidayProvider` 仅按星期判断）。
4. 选择对应窗口的 `start_hour` / `end_hour`。
5. 比较当前小时是否在 `[start, end)` 范围内。

### 4.4 节假日可扩展接口

定义抽象接口：

```python
from abc import ABC, abstractmethod
from datetime import datetime

class HolidayProvider(ABC):
    @abstractmethod
    def day_type(self, dt: datetime, tz) -> str:
        """返回 'weekday', 'weekend', 'holiday' 之一"""
        ...

class NoOpHolidayProvider(HolidayProvider):
    """仅根据星期判断：周六/周日为 weekend，其余为 weekday"""
    def day_type(self, dt, tz):
        weekday = dt.weekday()
        return "weekend" if weekday >= 5 else "weekday"
```

未来实现 `ChineseCalendarProvider` 时，只需实现 `day_type()` 并返回 `holiday`（含调休上班日返回 `weekday`），调度逻辑即可自动选择 `schedule_holiday_*` 窗口。本期不新增 `schedule_holiday_start_hour` / `schedule_holiday_end_hour` 字段，但实现时应保留命名空间并在后续迭代中补全。

### 4.5 CLI 变更

#### `jfox auto-summary enable`

新增选项：

```bash
--schedule-enabled                       启用时间窗口
--schedule-weekday-window TEXT           格式 "0-6"
--schedule-weekend-window TEXT           格式 "0-8"
--schedule-timezone TEXT                 默认 "Asia/Shanghai"
```

解析 `--schedule-weekday-window` 时拆分为 start/end hour，非法格式给出明确错误。

#### `jfox auto-summary status`

新增输出：

- 时间窗口是否启用
- 工作日/周末窗口
- 当前时区
- 当前是否处于允许运行窗口（新增字段 `in_schedule_window`）

### 4.6 错误处理

- 配置解析时非法的 hour 范围会被修正为默认值或拒绝更新（CLI 层直接报错）。
- 时区解析失败回退到系统本地时间，避免 daemon 崩溃。
- `_is_within_schedule_window` 内部异常不应中断 daemon，应视为"允许运行"并记录 error 日志（保守策略，避免用户因配置错误而丢失摘要）。

---

## 5. 测试策略

### 5.1 单元测试

针对 `_is_within_schedule_window`：

- 工作日 03:00 → 在窗口内
- 工作日 09:00 → 不在窗口内
- 周六 07:00 → 在周末窗口内
- 周六 09:00 → 不在窗口内
- 不同时区（Asia/Shanghai vs UTC）边界行为

### 5.2 集成测试

- `auto_summary_loop` 在窗口外时不会调用 `_tick_once`（通过 mock `run_once` 断言）。
- `auto_summary_loop` 在窗口内时正常执行 `run_once`。

### 5.3 CLI 测试

- `jfox auto-summary enable --schedule-enabled --schedule-weekday-window 0-6` 正确写入全局配置。
- 非法窗口格式（如 `6-0` 或 `abc`）返回非零退出码并给出清晰错误。
- `status` 输出包含 `in_schedule_window` 字段。

### 5.4 兼容性测试

- 旧全局配置中没有新增字段时，`AutoSummaryConfig.from_dict()` 使用默认值，`schedule_enabled=False`，行为不变。

---

## 6. 兼容性

- 完全向后兼容：未启用 `schedule_enabled` 时所有现有行为不变。
- 全局配置文件新增字段，现有 `from_dict` 机制已支持缺省值。
- daemon API `/auto_summary/status` 可新增字段，不影响旧客户端解析。

---

## 7. 实现步骤概要

1. 在 `AutoSummaryConfig` 中新增时间窗口字段及验证逻辑。
2. 新增 `jfox/auto_summary/schedule.py`，包含 `HolidayProvider`、`NoOpHolidayProvider`、`_is_within_schedule_window()`。
3. 修改 `jfox/auto_summary/loop.py`，在 tick 前调用窗口检查。
4. 扩展 `jfox/auto_summary/cli.py` 的 `enable` 和 `status` 子命令。
5. 更新 `jfox/daemon/server.py` 的 `/auto_summary/status` 返回新增字段（可选）。
6. 添加单元测试和 CLI 测试。
7. 更新 `README.md` 或相关文档中 `auto-summary` 章节。

---

## 8. 相关文件

- `jfox/global_config.py`
- `jfox/auto_summary/loop.py`
- `jfox/auto_summary/cli.py`
- 新增：`jfox/auto_summary/schedule.py`
- 测试：`tests/unit/test_auto_summary_schedule.py`（建议新建）

---

## 9. 参考

- Issue #298: Auto-summary 调度时间改为非工作时间（避免白天占用资源）
- `jfox/auto_summary/runner.py`：摘要生成核心
- `jfox/auto_summary/loop.py`：daemon 后台调度循环
