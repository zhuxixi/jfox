"""gem_synth 订阅 note.py 生命周期事件，同步 dedup 表。

把 dedup 生命周期同步从核心存储层（note.py）上移到特性层：note.py 只广播
post_delete/archive/promote/reject 事件，本模块订阅并复刻原 dedup 同步逻辑，
保持 note.py 零 gem_synth 依赖（分层约束见 KB 笔记 20260712223046-705752）。

类型守卫（仅 candidate/permanent 有 dedup 行）下移到本模块：note.py 无条件广播，
本模块按 note_type 早返回，避免给 fleeting/literature/session 实例化 DedupStore
（防未启用 gem-synth 用户产生 synthesis_log.db 污染）。
"""

from __future__ import annotations

from typing import Any

from ..models import NoteType
from .dedup import (
    _resolve_kb_name,
    delete_dedup,
    release_blocked_anchors,
    update_dedup_type,
)

# 仅 candidate/permanent 有 dedup 行；其它类型早返回避免实例化 store
_DEDUP_TYPES = (NoteType.CANDIDATE, NoteType.PERMANENT)


def _on_deleted(note_id: str, note_type: NoteType, **_: Any) -> None:
    """硬删 candidate/permanent：删 dedup 行 + 释放被该笔记阻断的锚点。

    残留 dedup 行会让未来 candidate 永久命中已删笔记；被阻断锚点不释放则知识
    永久丢失。失败由 note._dispatch 兜底 warning，不阻塞主流程。
    """
    if note_type not in _DEDUP_TYPES:
        return
    kb = _resolve_kb_name(None)
    delete_dedup(kb, note_id)
    release_blocked_anchors(note_id)


def _on_archived(note_id: str, note_type: NoteType, **_: Any) -> None:
    """归档与硬删的 dedup 同步动作一致（candidate/permanent 同样清行 + 释放锚点）。"""
    _on_deleted(note_id, note_type)


def _on_promoted(note_id: str, note_type: NoteType, **_: Any) -> None:
    """candidate → permanent：dedup 表 note_type 改 permanent（仍占位防重复合成）。"""
    if note_type not in _DEDUP_TYPES:
        return
    update_dedup_type(_resolve_kb_name(None), note_id, "permanent")


def _on_rejected(note_id: str, note_type: NoteType, **_: Any) -> None:
    """reject candidate：删 dedup 行 + 释放锚点（让该事实可被未来重新合成）。"""
    if note_type not in _DEDUP_TYPES:
        return
    kb = _resolve_kb_name(None)
    delete_dedup(kb, note_id)
    release_blocked_anchors(note_id)


_HOOKS = {
    "post_delete": _on_deleted,
    "post_archive": _on_archived,
    "post_promote": _on_promoted,
    "post_reject": _on_rejected,
}


def register() -> None:
    """把 dedup 生命周期回调注册到 note.py。

    幂等——register_lifecycle_hook 对同一 callback 去重，重复调用安全。
    由 jfox.cli 模块级调用一次，保证所有 CLI 命令路径订阅就位。
    """
    from ..note import register_lifecycle_hook  # lazy：避免顶层 import 循环

    for event, cb in _HOOKS.items():
        register_lifecycle_hook(event, cb)
