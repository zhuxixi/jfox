"""
daemon 后台循环：每 interval_minutes 调用一次 run_once。

提供：
- auto_summary_loop(stop_event): asyncio task body
- _tick_once(): 同步 wrapper（在 executor 中执行 run_once，避免阻塞事件循环）
"""

from __future__ import annotations

import asyncio
import logging

from ..global_config import get_global_config_manager
from .runner import run_once

logger = logging.getLogger(__name__)


def _tick_once() -> str:
    """在 executor 中执行的同步函数。返回简短日志行供 await 后打印。

    每轮先 reload 全局配置：daemon 进程可能持有旧缓存，CLI `enable` / `disable`
    已写入新值到磁盘。
    """
    gm = get_global_config_manager()
    gm.reload()
    cfg = gm.get_auto_summary_config()
    if not cfg.enabled:
        return "auto-summary 已禁用，跳过本轮"
    try:
        report = run_once(cfg=cfg)
    except Exception as e:  # 兜底，避免循环退出
        logger.exception("auto-summary run_once 异常: %s", e)
        return f"run_once 异常: {e}"

    if report.scanned == 0:
        return "无待处理 session"

    return (
        f"扫描 {report.scanned}, 处理 {report.processed}, "
        f"成功 {report.success}, 跳过 {report.skipped}, 失败 {report.failed}"
    )


async def auto_summary_loop(stop_event: asyncio.Event) -> None:
    """
    后台循环主体。stop_event.set() 后立即退出。

    每轮：
    - 重新读取 GlobalConfig（用户可能在运行期改了 interval / enable）
    - 通过 run_in_executor 跑 run_once，避免阻塞 daemon 的 HTTP 请求
    - sleep interval（可被 stop_event 提前中断）
    """
    logger.info("auto-summary 后台循环已启动")
    loop = asyncio.get_running_loop()

    # 启动后短暂延迟，让 daemon 完成模型加载
    try:
        await asyncio.wait_for(stop_event.wait(), timeout=10)
        logger.info("auto-summary 后台循环：启动延迟期间收到停止信号，退出")
        return
    except asyncio.TimeoutError:
        pass

    while not stop_event.is_set():
        cfg = get_global_config_manager().get_auto_summary_config()
        interval_sec = max(60, cfg.interval_minutes * 60)

        if cfg.enabled:
            try:
                summary = await loop.run_in_executor(None, _tick_once)
                logger.info("auto-summary tick: %s", summary)
            except Exception as e:
                logger.exception("auto-summary tick 异常: %s", e)
        else:
            logger.debug("auto-summary 处于禁用状态，等待下一轮")

        try:
            await asyncio.wait_for(stop_event.wait(), timeout=interval_sec)
            break  # stop_event 已 set
        except asyncio.TimeoutError:
            continue

    logger.info("auto-summary 后台循环已退出")
