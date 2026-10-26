"""共享工具函数。"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path


def atomic_write_json(path: Path, data: dict, *, indent: int = 2) -> None:
    """原子写入 JSON 文件：写临时文件 → os.replace 覆盖。

    异常时自动清理临时文件。os.replace 在所有主流 OS 上是原子的。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=indent)
        os.replace(tmp_path, path)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def normalize_agent(value: str) -> str:
    """Trim the agent name and reject empty values; no enum restriction."""
    agent = (value or "").strip()
    if not agent:
        raise ValueError("--agent 不能为空")
    return agent


def resolve_session_path(value: str) -> str:
    """Expand ~ and require an absolute path; existence is not checked."""
    path = Path(value).expanduser()
    if not path.is_absolute():
        raise ValueError("--session-path 必须是绝对路径")
    return str(path)
