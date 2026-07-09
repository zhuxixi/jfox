"""碎片摄入编排：event → classify → store.insert，Stop 时生成本轮摘要。

纯函数式（依赖注入 store/config），daemon 路由与单测都直接调用，不加载 embedding 模型。
"""

import logging
from typing import Any, Dict, Optional

from ..global_config import FragmentCaptureConfig, get_global_config_manager
from .detector import classify
from .internal_sources import INTERNAL_SOURCES
from .store import FragmentStore

logger = logging.getLogger(__name__)

# daemon 常驻的 store 单例（lifespan 初始化时设置；此处不懒创建，避免并发竞态与连接泄漏）
_default_store: Optional[FragmentStore] = None


def _get_event_source(event: Dict[str, Any]) -> Optional[str]:
    """从事件中提取来源标记（供 hook 或内部调用方显式声明）。

    对外部输入做防御：event 本身、metadata 均可能不是字典。
    """
    if not isinstance(event, dict):
        return None
    raw = event.get("source")
    if isinstance(raw, str) and raw:
        return raw
    metadata = event.get("metadata")
    if isinstance(metadata, dict):
        raw = metadata.get("source")
        if isinstance(raw, str) and raw:
            return raw
    return None


def set_default_store(store: Optional[FragmentStore]) -> None:
    """daemon lifespan 启动/关闭时调用，注入或清空常驻 store。"""
    global _default_store
    _default_store = store


def get_default_store() -> Optional[FragmentStore]:
    """读取 daemon 常驻的 store 单例（供 daemon 关闭路径对称访问，避免引用私有变量）。"""
    return _default_store


def _summary_message(counts: Dict[str, int]) -> str:
    # 排除历史 session_summary 行，避免同一 session 多次 Stop 时计数虚高
    total = sum(v for k, v in counts.items() if k != "session_summary")
    parts = []
    label_map = {
        "correction": "纠正",
        "decision": "决策",
        "tool_call": "工具",
        "user_input": "输入",
    }
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
      {fragment_id, fragment_type, message}              正常写入
      {status: "skipped"}                                配置禁用
      {status: "skipped", reason: "ignored internal source: ..."}  内部来源跳过
      {status: "error", message}                         输入异常 / store 不可用 / 写入异常
    """
    if config is None:
        config = get_global_config_manager().get_fragment_capture_config()
    if not config.enabled:
        return {"status": "skipped"}

    if not isinstance(event, dict):
        return {"status": "error", "message": "event must be a JSON object"}

    session_id = event.get("session_id")
    if not session_id:
        return {"status": "error", "message": "missing session_id in event"}

    source = _get_event_source(event)
    if source in INTERNAL_SOURCES:
        logger.debug("ingest_event: 跳过 JFox 内部 session 来源: %s", source)
        return {"status": "skipped", "reason": f"ignored internal source: {source}"}

    # store 由 daemon lifespan 单点初始化；此处不懒创建，避免并发竞态、连接泄漏，
    # 以及绕过 daemon 初始化失败时的「采集不可用」决策。
    if store is None:
        store = _default_store
    if store is None:
        return {"status": "error", "message": "fragment store unavailable (daemon not initialized)"}

    try:
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
    except Exception as e:
        # classify 与 store 操作都在此 try 内；用中性消息，避免把分类失败误报为 store error
        logger.exception("ingest_event: 处理失败: %s", e)
        return {"status": "error", "message": f"ingest error: {e}"}

    message = content if ftype == "session_summary" else "ok"
    return {"fragment_id": fid, "fragment_type": ftype, "message": message}


__all__ = ["ingest_event", "set_default_store", "get_default_store"]
