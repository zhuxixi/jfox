"""daemon 后台循环：每 5 分钟检查是否到 schedule_time，到点备份一次。

镜像 auto_summary/loop.py 的结构：async loop + 同步 _tick_once（executor 里跑）+
stop_event 协作退出。每 tick reload 全局配置，使运行中改 backup 配置即时生效。
"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..global_config import DEFAULT_KB_PATH, get_global_config_manager
from ..utils import atomic_write_json
from .manager import BackupManager
from .schedule import should_run_now

logger = logging.getLogger(__name__)

_TICK_SECONDS = 300  # 5 分钟检查一次是否到点


def _state_path(backup_root: Path) -> Path:
    return Path(backup_root) / "state.json"


def _read_last_run(backup_root: Path) -> Optional[str]:
    p = _state_path(backup_root)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("last_run")
    except Exception:
        return None


def _write_last_run(backup_root: Path, ts: str, ok: bool, archive: Optional[str]) -> None:
    p = _state_path(backup_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(p, {"last_run": ts, "last_ok": ok, "last_archive": archive})


def _resolve_backup_root(cfg) -> Path:
    return Path(cfg.backup_root) if cfg.backup_root else Path.home() / ".jfox-backup"


def _tick_once() -> str:
    """同步执行一轮检查+备份，返回简短日志行。"""
    gm = get_global_config_manager()
    gm.reload()
    cfg = gm.get_backup_config()
    if not cfg.enabled:
        return "backup 未启用，跳过"

    backup_root = _resolve_backup_root(cfg)
    last = _read_last_run(backup_root)
    if not should_run_now(cfg.schedule_time, last):
        return "未到点或今日已备份，跳过"

    mgr = BackupManager(
        backup_root=backup_root,
        kb_root=DEFAULT_KB_PATH,
        config_path=Path.home() / ".zk_config.json",
        retain=cfg.retain,
    )
    try:
        archive = mgr.backup()
        # ts 取于备份成功之后（跨午夜场景避免 last_run 记前一日 → 当日二次备份）
        _write_last_run(backup_root, datetime.now().isoformat(), True, archive.name)
        return f"备份成功: {archive.name}"
    except Exception as e:
        logger.exception("backup_loop 备份失败: %s", e)
        _write_last_run(backup_root, datetime.now().isoformat(), False, None)
        return f"备份失败: {e}"


async def backup_loop(stop_event: threading.Event) -> None:
    """后台循环主体。stop_event.set() 后 ~_TICK_SECONDS 内退出。

    用 threading.Event（非 asyncio.Event）：run_in_executor 里的同步 _tick_once
    无法查 asyncio 状态；改在每轮间隙用 stop_event.wait 做可中断睡眠。
    """
    logger.info("backup 后台循环已启动")
    loop = asyncio.get_running_loop()

    # 启动后短暂延迟，让 daemon 完成模型加载
    try:
        await loop.run_in_executor(None, lambda: stop_event.wait(timeout=10))
    except RuntimeError as e:
        logger.warning("backup 启动延迟等待异常: %s", e)

    while not stop_event.is_set():
        try:
            msg = await loop.run_in_executor(None, _tick_once)
            if "成功" in msg or "失败" in msg or "跳过" not in msg:
                logger.info("backup tick: %s", msg)
            else:
                logger.debug("backup tick: %s", msg)
        except Exception as e:
            logger.exception("backup tick 异常: %s", e)

        # 可中断睡眠
        try:
            await loop.run_in_executor(None, lambda: stop_event.wait(timeout=_TICK_SECONDS))
        except RuntimeError:
            break
