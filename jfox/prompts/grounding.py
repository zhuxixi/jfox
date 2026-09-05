"""strict permanent grounding + unresolved evidence + prompt history。

与旧 gem_synth/grounding.py 的区别：
- 排除 unresolved-problems 标签的聚合清单（不是已解决知识）；
- 区分"无命中"（合法空）与"搜索异常"（unavailable）；
- 返回 note ID 而非标题列表，供 runner 的 matched_note_ids 校验。
"""

import logging
from typing import Any, Dict, List, Optional

from ..search_engine import HybridSearchEngine, SearchMode

logger = logging.getLogger(__name__)

# 默认 grounding 正文片段上限
DEFAULT_MAX_GROUNDING_CHARS = 4000

# unresolved 清单排除标签
UNRESOLVED_TAG = "unresolved-problems"


class GroundingResult:
    """grounding 查询结果：evidence 列表 + 可用性标记。"""

    def __init__(
        self,
        evidence: List[Dict[str, Any]],
        unavailable: bool = False,
        error: Optional[str] = None,
    ):
        self.evidence = evidence
        self.unavailable = unavailable
        self.error = error


def fetch_judgment_grounding(
    query: str,
    top_k: int = 8,
    max_chars: int = DEFAULT_MAX_GROUNDING_CHARS,
) -> GroundingResult:
    """检索当前 KB 未归档 permanent 笔记作为已解决知识证据。

    - 只留 permanent 类型；
    - 排除带 unresolved-problems 标签的清单笔记；
    - 无命中是合法空证据（unavailable=False）；
    - 搜索/索引异常返回 unavailable=True（调用方使 item failed，不调用 runner）。
    """
    if not (query or "").strip():
        return GroundingResult(evidence=[], unavailable=False)

    try:
        engine = HybridSearchEngine()
        results = engine.search(
            query=query, mode=SearchMode.HYBRID, note_type="permanent", top_k=top_k
        )
    except Exception as e:
        logger.exception("judgment grounding 检索失败: %s", e)
        return GroundingResult(evidence=[], unavailable=True, error=str(e))

    evidence: List[Dict[str, Any]] = []
    for r in results:
        meta = r.get("metadata") or {}
        # 只留 permanent
        if meta.get("type") != "permanent":
            continue
        # 排除 unresolved 清单
        tags = meta.get("tags") or []
        if isinstance(tags, str):
            tags = [tags]
        if UNRESOLVED_TAG in tags:
            continue
        content = (r.get("content") or r.get("document") or "")[:max_chars]
        evidence.append(
            {
                "id": r.get("id") or meta.get("id", ""),
                "title": r.get("title") or meta.get("title", ""),
                "content": content,
                "score": r.get("score"),
            }
        )
    return GroundingResult(evidence=evidence, unavailable=False)


def fetch_unresolved_evidence(store, kb_name: str) -> List[Dict[str, Any]]:
    """读取当前 KB 的 active unresolved 条目（独立 evidence 通道）。"""
    try:
        items = store.list_unresolved(kb_name, state="active")
        return [
            {
                "prompt_id": item["prompt_id"],
                "note_id": item.get("note_id", ""),
                "last_seen": item.get("last_seen", ""),
            }
            for item in items
        ]
    except Exception as e:
        logger.warning("fetch_unresolved_evidence 失败: %s", e)
        return []


def build_prompt_history(
    store,
    prompt_id: int,
    session_id: str,
    limit: int = 20,
    kb_name: str = "default",
) -> List[Dict[str, Any]]:
    """为目标 prompt 构建有界历史证据。

    - 当前 session 中该 prompt 之前的有序 prompt；
    - 全局按 prompt_hash 匹配的其他 session 相同/规范化相同 prompt；
    - 包含 ID、session、时间与已有 disposition（如果有）。
    """
    target = store.get_prompt(prompt_id)
    if target is None:
        return []

    prompt_hash = target["prompt_hash"]
    history: List[Dict[str, Any]] = []
    seen_ids = {prompt_id}

    # 1) 当前 session 中该 prompt 之前的 prompt
    session_prompts = store.list_prompts(session_id=session_id, limit=500)
    for row in session_prompts:
        if row["prompt_id"] >= prompt_id:
            break  # 只取之前的（list 按 prompt_id 升序）
        if row["prompt_id"] in seen_ids:
            continue
        seen_ids.add(row["prompt_id"])
        history.append(_history_item(row, store, kb_name))
        if len(history) >= limit:
            return history

    # 2) 全局按 hash 匹配（其他 session 的相同/规范化相同）
    # PromptStore 目前没有 hash 查询方法，遍历最近 prompt 匹配
    all_recent = store.list_prompts(limit=500)
    for row in all_recent:
        if row["prompt_id"] in seen_ids:
            continue
        if row["prompt_hash"] != prompt_hash:
            continue
        seen_ids.add(row["prompt_id"])
        history.append(_history_item(row, store, kb_name))
        if len(history) >= limit:
            break

    return history


def _history_item(row: Dict[str, Any], store, kb_name: str = "default") -> Dict[str, Any]:
    """构造一条历史证据 dict（含已有 judgment disposition，如果有）。"""
    item = {
        "id": row["prompt_id"],
        "session_id": row["session_id"],
        "prompt": row["prompt"],
        "captured_at": row.get("captured_at", ""),
        "disposition": None,
    }
    # 查已有 judgment 的 disposition（按 (kb_name, prompt_id) 复合键，调用方传真实 KB）
    try:
        j = store.get_judgment(kb_name, row["prompt_id"])
        if j and j.get("disposition"):
            item["disposition"] = j["disposition"]
    except Exception:
        pass
    return item


__all__ = [
    "GroundingResult",
    "fetch_judgment_grounding",
    "fetch_unresolved_evidence",
    "build_prompt_history",
    "UNRESOLVED_TAG",
]
