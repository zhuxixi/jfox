"""gem_synth 默认路径。"""

import os
from pathlib import Path


def default_synthesis_db_path() -> Path:
    """合成记账库路径，可被 JFOX_SYNTHESIS_DB 覆盖（测试用）。"""
    env = os.environ.get("JFOX_SYNTHESIS_DB")
    if env:
        return Path(env).expanduser().resolve()
    return Path.home() / ".zettelkasten" / "synthesis_log.db"
