"""daemon 后台循环：每 interval_minutes 处理一批未合成锚点。

提供：
- gem_synth_loop(stop_event, interval_minutes): async task body
- _tick_once(stop_event): 同步 wrapper（在 executor 中执行）
"""

from __future__ import annotations

import asyncio
import logging
import threading
import time

from ..config import use_kb
from ..global_config import get_global_config_manager
from .anchors import find_anchors
from .store import SynthesisLog
from .synthesizer import synthesize_anchor

logger = logging.getLogger(__name__)


def _tick_once(stop_event: threading.Event) -> str:
    """同步执行一轮：时间预算内逐个合成锚点。

    每轮跑 cfg.interval_minutes（窗口），串行处理（一次取一个未处理锚点），
    直到窗口用完或无锚点。窗口跑满则下个 tick 立即接上 → 积压时连续跑。
    """
    gm = get_global_config_manager()
    gm.reload()
    cfg = gm.get_gem_synthesis_config()
    if not cfg.enabled:
        return "gem-synth 已禁用，跳过本轮"

    from jfox.fragment.store import default_db_path

    log = SynthesisLog()
    tick_start = time.monotonic()
    budget_seconds = cfg.interval_minutes * 60
    success = 0
    failed = 0
    find_error = False  # find_anchors 抛异常 → 与"无锚点"区分（return msg 不同）
    try:
        # 整轮只切一次 KB（避免每锚点 use_kb → _reset_singletons 重载模型）
        with use_kb(cfg.target_kb):
            while not stop_event.is_set():
                # 时间预算用完 → 停，留给下个 tick（back-to-back 连续跑）
                if time.monotonic() - tick_start >= budget_seconds:
                    break
                try:
                    anchors = find_anchors(
                        fragments_db=default_db_path(),
                        log=log,
                        anchor_types=cfg.anchor_types,
                        limit=1,  # 一次取一个，配合时间预算
                    )
                except Exception as e:
                    logger.exception("gem-synth 找锚点失败: %s", e)
                    find_error = True
                    break
                if not anchors:
                    break  # 无积压
                try:
                    result = synthesize_anchor(anchors[0], log=log, cfg=cfg, stop_event=stop_event)
                    if result is not None:
                        success += 1
                    else:
                        failed += 1
                except Exception as e:
                    logger.exception(
                        "gem-synth 合成锚点 #%s 异常: %s", anchors[0].get("fragment_id"), e
                    )
                    # 防止抛异常的锚点被反复取回 busy-loop：mark_failed 隔离它
                    try:
                        log.mark_failed(anchors[0]["fragment_id"], f"unhandled: {e}")
                    except Exception as me:
                        # mark_failed 自身失败（database locked / disk full / conn closed）
                        # → busy-loop 防护实际未生效。记 warning 便于排查，不再静默吞（cc R2#2）
                        logger.warning(
                            "gem-synth mark_failed 失败，锚点 #%s 可能被重试: %s",
                            anchors[0].get("fragment_id"),
                            me,
                        )
                    failed += 1
    finally:
        log.close()
    if find_error:
        return f"find_anchors 异常提前终止（已处理 success={success} failed={failed}）"
    return f"本轮 success={success} failed={failed}（预算 {cfg.interval_minutes}min）"


async def gem_synth_loop(stop_event: threading.Event, interval_minutes: int = 30) -> None:
    """async 循环：每 interval_minutes 跑一次 _tick_once（在 executor 中）。"""
    loop = asyncio.get_running_loop()
    sleep_secs = max(60, interval_minutes * 60)
    while not stop_event.is_set():
        try:
            msg = await loop.run_in_executor(None, _tick_once, stop_event)
            logger.info("gem-synth tick: %s", msg)
        except Exception as e:
            logger.exception("gem-synth tick 异常: %s", e)
        slept = 0
        while slept < sleep_secs and not stop_event.is_set():
            await asyncio.sleep(min(10, sleep_secs - slept))
            slept += 10


__all__ = ["gem_synth_loop", "_tick_once"]
