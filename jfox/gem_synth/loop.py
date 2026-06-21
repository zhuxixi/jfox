"""daemon 后台循环：每 interval_minutes 处理一批未合成锚点。

提供：
- gem_synth_loop(stop_event, interval_minutes): async task body
- _tick_once(stop_event): 同步 wrapper（在 executor 中执行）
"""

from __future__ import annotations

import asyncio
import logging
import threading

from ..global_config import get_global_config_manager
from .anchors import find_anchors
from .store import SynthesisLog
from .synthesizer import synthesize_anchor

logger = logging.getLogger(__name__)


def _tick_once(stop_event: threading.Event) -> str:
    """同步执行一轮：找未处理锚点 → 逐个合成。返回简短日志行。"""
    gm = get_global_config_manager()
    gm.reload()
    cfg = gm.get_gem_synthesis_config()
    if not cfg.enabled:
        return "gem-synth 已禁用，跳过本轮"

    log = SynthesisLog()
    try:
        try:
            from jfox.fragment.store import default_db_path

            anchors = find_anchors(
                fragments_db=default_db_path(),
                log=log,
                anchor_types=cfg.anchor_types,
            )
        except Exception as e:
            logger.exception("gem-synth 找锚点失败: %s", e)
            return f"找锚点异常: {e}"

        if not anchors:
            return "无待合成锚点"

        success = 0
        for anchor in anchors:
            if stop_event.is_set():
                break
            try:
                result = synthesize_anchor(anchor, log=log, cfg=cfg, kb=cfg.target_kb)
                if result is not None:
                    success += 1
            except Exception as e:
                logger.exception("gem-synth 合成锚点 #%s 异常: %s", anchor.get("fragment_id"), e)

        return f"待合成 {len(anchors)}, 成功 {success}"
    finally:
        log.close()


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
