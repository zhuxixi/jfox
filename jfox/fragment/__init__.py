"""JFox 碎片子包（历史只读，#399 采集退役）。

旧分类采集（correction/decision/tool_call/session_summary）已随自动合成退役；
session_fragments 表和历史 CLI（jfox fragments list/show）保留供回溯。
"""

from .service import get_default_store, set_default_store
from .store import FragmentStore

__all__ = ["set_default_store", "get_default_store", "FragmentStore"]
