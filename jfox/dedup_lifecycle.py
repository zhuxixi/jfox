"""dedup 表生命周期同步（接续旧 gem_synth/lifecycle.py 职责，#399 退役迁移）。

订阅 note.py 的 post_delete/archive/promote/reject 事件维护 dedup 表：
已删/归档/拒绝笔记清行，promote 改类型——否则残留 embedding 会让 `jfox add`
的 embedding 通道误拦重新添加已删除内容（#383 语义回归）。

dedup 延迟到回调体内 import：jfox 包 __init__ 只挂本模块回调引用，不触发
dedup→numpy eager 加载（否则每次 jfox 命令都付 ~70-100ms numpy 启动开销）。
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# 仅 candidate/permanent 有 dedup 行；其它类型早返回避免实例化 store
_DEDUP_NOTE_TYPES = ("candidate", "permanent")


def _note_type_name(note_type: Any) -> str:
    """NoteType 枚举或字符串统一转小写字符串（广播 payload 两种形态都可能出现）。"""
    return str(getattr(note_type, "value", note_type)).lower()


def _on_note_removed(note_id: str, note_type: Any = None, **_: Any) -> None:
    """deleted/archived/rejected 共用：清 dedup 行。"""
    if _note_type_name(note_type) not in _DEDUP_NOTE_TYPES:
        return
    try:
        from .dedup import _resolve_kb_name, delete_dedup

        delete_dedup(_resolve_kb_name(None), note_id)
    except Exception as e:  # noqa: BLE001 — 订阅器故障不得阻塞存储主流程
        logger.warning("dedup lifecycle delete 失败 note=%s: %s", note_id, e)


def _on_note_promoted(note_id: str, note_type: Any = None, **_: Any) -> None:
    """candidate → permanent：dedup 表 note_type 改 permanent（仍占位防重）。"""
    if _note_type_name(note_type) not in _DEDUP_NOTE_TYPES:
        return
    try:
        from .dedup import _resolve_kb_name, update_dedup_type

        update_dedup_type(_resolve_kb_name(None), note_id, "permanent")
    except Exception as e:  # noqa: BLE001
        logger.warning("dedup lifecycle promote 失败 note=%s: %s", note_id, e)


def register_lifecycle() -> None:
    """把 dedup 生命周期回调注册到 note.py（幂等）。"""
    from .note import register_lifecycle_hook

    register_lifecycle_hook("post_delete", _on_note_removed)
    register_lifecycle_hook("post_archive", _on_note_removed)
    register_lifecycle_hook("post_reject", _on_note_removed)
    register_lifecycle_hook("post_promote", _on_note_promoted)
