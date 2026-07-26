"""
daemon 后台循环：每 interval_minutes 调用一次 run_once。

提供：
- auto_summary_loop(stop_event): async task body（接受 threading.Event）
- _tick_once(stop_event): 同步 wrapper（在 executor 中执行 run_once）
"""

from __future__ import annotations

import asyncio
import logging
import threading

from ..global_config import get_global_config_manager
from .runner import run_once
from .schedule import _is_within_schedule_window

logger = logging.getLogger(__name__)


def _tick_once(stop_event: threading.Event) -> str:
    """在 executor 中执行的同步函数。返回简短日志行。

    每轮先 reload 全局配置，然后通过 setattr 把 stop_event 传给 runner，
    使 claude -p 子进程可被外部中断。
    """
    gm = get_global_config_manager()
    gm.reload()
    cfg = gm.get_auto_summary_config()
    if not cfg.enabled:
        return "auto-summary 已禁用，跳过本轮"

    # 备份进行中则跳过写 tick，避免 ChromaDB 并发写（见 jfox/backup/）
    from jfox.backup.manager import BackupCoordinator

    if BackupCoordinator.is_running():
        return "backup 进行中，跳过本轮 auto-summary"

    # 将 stop_event 注入 config，让 _invoke_claude → _run_claude 能检查
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


async def auto_summary_loop(stop_event: threading.Event) -> None:
    """
    后台循环主体。stop_event.set() 后在 ~1s 内退出（包括终止 claude 子进程）。

    使用 threading.Event 而非 asyncio.Event，因为 run_in_executor 中的同步函数
    需要检查 stop 状态。
    """
    logger.info("auto-summary 后台循环已启动")
    loop = asyncio.get_running_loop()

    # 启动后短暂延迟，让 daemon 完成模型加载
    try:
        await loop.run_in_executor(None, lambda: stop_event.wait(timeout=10))
    except RuntimeError as e:
        # run_in_executor 在 event loop 关闭时抛 RuntimeError；
        # 延迟失败不应导致 daemon 崩溃
        logger.warning("auto-summary 启动延迟等待异常: %s", e)
    if stop_event.is_set():
        logger.info("auto-summary 后台循环：启动延迟期间收到停止信号，退出")
        return

    while not stop_event.is_set():
        gm = get_global_config_manager()
        # 窗口外会跳过 _tick_once（其内部含 reload）；主循环需自行 reload 才能读到
        # 最新磁盘配置，避免运行中改窗口配置不生效（stale config，#298 CR）
        gm.reload()
        cfg = gm.get_auto_summary_config()
        interval_sec = max(60, cfg.interval_minutes * 60)

        if cfg.enabled:
            # 窗口判断异常不应中断 daemon 循环，保守放行（与 _is_within_schedule_window
            # 内部兜底语义一致；此处为不依赖被调函数不变量的额外保护）
            try:
                in_window = not cfg.schedule_enabled or _is_within_schedule_window(cfg)
            except Exception as e:
                logger.exception("auto-summary 调度窗口判断异常，保守放行: %s", e)
                in_window = True
            if not in_window:
                logger.debug("auto-summary 当前不在调度窗口内，等待下一轮")
            else:
                try:
                    summary = await loop.run_in_executor(None, _tick_once, stop_event)
                    logger.info("auto-summary tick: %s", summary)
                except Exception as e:
                    # daemon 后台循环的顶层 catch-all：任何 tick 内部异常都不应导致 daemon 崩溃
                    logger.exception("auto-summary tick 异常: %s", e)
        else:
            logger.debug("auto-summary 处于禁用状态，等待下一轮")

        try:
            was_set = await loop.run_in_executor(
                None, lambda: stop_event.wait(timeout=interval_sec)
            )
            if was_set:
                break  # stop_event 已 set，退出循环
            # timeout 到期，继续下一轮
        except RuntimeError as e:
            # run_in_executor 在 event loop 关闭时可能抛 RuntimeError
            logger.warning("auto-summary 等待间隔异常: %s", e)
            continue

    logger.info("auto-summary 后台循环已退出")
