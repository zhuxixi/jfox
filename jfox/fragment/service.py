"""碎片摄入编排：event → classify → store.insert，Stop 时生成本轮摘要。

纯函数式（依赖注入 store/config），daemon 路由与单测都直接调用，不加载 embedding 模型。
"""

from typing import Any, Dict, Optional

from ..global_config import FragmentCaptureConfig, get_global_config_manager
from .detector import classify
from .store import FragmentStore

# daemon 常驻的 store 单例（lifespan 初始化时设置）
_default_store: Optional[FragmentStore] = None


def set_default_store(store: Optional[FragmentStore]) -> None:
    """daemon lifespan 启动/关闭时调用，注入或清空常驻 store。"""
    global _default_store
    _default_store = store


def _summary_message(counts: Dict[str, int]) -> str:
    total = sum(counts.values())
    parts = []
    label_map = {"correction": "纠正", "decision": "决策", "tool_call": "工具", "user_input": "输入"}
    for k in ("correction", "decision", "tool_call", "user_input"):
        if counts.get(k):
            parts.append(f"{label_map[k]} {counts[k]}")
    detail = " / ".join(parts) if parts else "无"
    return f"本轮采集 {total} 碎片：{detail}"


def ingest_event(
    event: Dict[str, Any],
    store: Optional[FragmentStore] = None,
    config: Optional[FragmentCaptureConfig] = None,
) -> Dict[str, Any]:
    """处理一个 CC 事件，写入碎片，返回响应 dict。

    返回形如：
      {fragment_id, fragment_type, message}            正常写入
      {status: "skipped"}                              配置禁用
      {status: "error", message}                       输入异常（如缺 session_id）
    """
    if config is None:
        config = get_global_config_manager().get_fragment_capture_config()
    if not config.enabled:
        return {"status": "skipped"}

    session_id = event.get("session_id")
    if not session_id:
        return {"status": "error", "message": "missing session_id in event"}

    if store is None:
        if _default_store is None:
            set_default_store(FragmentStore())
        store = _default_store  # type: ignore[assignment]

    ftype, content = classify(event, config)

    if ftype == "session_summary":
        counts = store.counts_by_type(session_id)
        content = _summary_message(counts)

    fid = store.insert(
        session_id=session_id,
        fragment_type=ftype,
        source_event=event.get("hook_event_name", "Unknown"),
        content=content,
        metadata=event,
    )
    message = content if ftype == "session_summary" else "ok"
    return {"fragment_id": fid, "fragment_type": ftype, "message": message}


__all__ = ["ingest_event", "set_default_store"]
