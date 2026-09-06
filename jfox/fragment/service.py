"""碎片摄入编排：event → classify → store.insert，Stop 时生成本轮摘要。

纯函数式（依赖注入 store/config），daemon 路由与单测都直接调用，不加载 embedding 模型。
"""

import logging
from typing import Any, Dict, Optional

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
    store: Any = None,  # 兼容旧调用点，忽略
    config: Any = None,  # 兼容旧调用点，忽略
) -> Dict[str, Any]:
    """已退役（#399）：旧分类采集不再执行，返回 retired。

    保留函数签名兼容历史调用点；daemon /api/fragment 对未知事件走本路径。
    """
    hook_event = event.get("hook_event_name") if isinstance(event, dict) else None
    return {"status": "retired", "reason": f"{hook_event or 'unknown'} capture is retired"}
