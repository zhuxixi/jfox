"""检索 permanent 笔记 top-K，作为合成基准（防幻觉佐证）。"""

import logging
from typing import Dict, List, Optional

from ..search_engine import HybridSearchEngine, SearchMode

logger = logging.getLogger(__name__)


def fetch_grounding(query: str, top_k: int = 5, kb: Optional[str] = None) -> List[Dict]:
    """返回 [{title, content, id, score}]，仅 permanent 笔记。空查询或异常返回 []。

    结果字典结构适配 search_engine 实际返回（顶层 id/document/metadata.title/score），
    同时兼容 mock 中使用的顶层 title/content。

    注：kb 参数保留以维持 API 稳定，但此处不再 use_kb——调用方（daemon loop 的
    _tick_once 外层已 use_kb(cfg.target_kb)）负责 KB 上下文。此处再 use_kb 会每锚点
    _reset_singletons（重载 embedding 模型 30-60s）。独立调用方需自行 use_kb 包裹。
    """
    if not (query or "").strip():
        return []
    # 不在此处 use_kb：调用方（daemon loop 的 _tick_once 外层已 use_kb(target_kb)）负责 KB 上下文。
    # 此处再 use_kb 会每锚点 _reset_singletons（重载 embedding 模型 30-60s）。
    try:
        engine = HybridSearchEngine()
        results = engine.search(
            query=query, mode=SearchMode.HYBRID, note_type="permanent", top_k=top_k
        )
    except Exception as e:
        logger.exception("grounding 检索失败: %s", e)
        return []
    grounding: List[Dict] = []
    for r in results:
        meta = r.get("metadata") or {}
        # post-filter: HybridSearchEngine 的 BM25 路径不过滤 note_type，此处兜底只留 permanent。
        # 不保留 None（缺失 type 可能是 fleeting/literature 元数据不全，不应混入合成基准）。
        if meta.get("type") != "permanent":
            continue
        grounding.append(
            {
                "title": r.get("title") or meta.get("title", ""),
                "content": (r.get("content") or r.get("document") or "")[:500],
                "id": r.get("id") or meta.get("id", ""),
                "score": r.get("score"),
            }
        )
    return grounding


__all__ = ["fetch_grounding"]
