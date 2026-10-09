"""索引状态持久层（#539）：.zk/index_state.json 的读与原子写。

`index status` 的 last_rebuild 事实来源；`index rebuild` / `rebuild-bm25`
成功路径写入。纯文件 IO，无索引/模型依赖。
"""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Optional

from .config import ZKConfig, config

STATE_FILENAME = "index_state.json"


def _state_path(cfg: Optional[ZKConfig] = None) -> Path:
    use_cfg = cfg or config
    return use_cfg.zk_dir / STATE_FILENAME


def load_index_state(cfg: Optional[ZKConfig] = None) -> Optional[dict]:
    """读取索引状态；无文件、损坏 JSON 或非 dict 一律返回 None（容错不抛）。"""
    path = _state_path(cfg)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def save_index_state(state: dict, cfg: Optional[ZKConfig] = None) -> bool:
    """原子写入索引状态（temp + os.replace）；返回是否成功。"""
    path = _state_path(cfg)
    tmp: Optional[str] = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False, indent=2)
        os.replace(tmp, path)
        return True
    except OSError:
        return False
    finally:
        if tmp is not None and os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except OSError:
                pass


def build_rebuild_state(semantic: bool, notes: int, now: Optional[datetime] = None) -> dict:
    """构造一次成功 rebuild 的状态记录（纯函数，now 可注入便于测试）。"""
    ts = now or datetime.now()
    return {"last_rebuild": ts.isoformat(), "semantic": semantic, "notes": notes}
