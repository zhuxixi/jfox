# jfox/auto_summary/kimi_source.py（最小桩，Task 5/6 填充）
from __future__ import annotations
from pathlib import Path


class KimiCodeSource:
    name = "kimi"

    def __init__(self, kimi_dir: Path):
        self.kimi_dir = kimi_dir
