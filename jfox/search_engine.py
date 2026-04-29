"""
混合搜索引擎

结合 BM25 关键词搜索和语义搜索，使用 RRF (Reciprocal Rank Fusion) 融合结果。
"""

import logging
from enum import Enum
from typing import Any, Dict, List, Optional

from .bm25_index import BM25Index, get_bm25_index
from .vector_store import VectorStore, get_vector_store

logger = logging.getLogger(__name__)


class SearchMode(Enum):
    """搜索模式"""

    HYBRID = "hybrid"  # 混合搜索（默认）
    SEMANTIC = "semantic"  # 纯语义搜索
    KEYWORD = "keyword"  # 纯关键词搜索 (BM25)


class HybridSearchEngine:
    """
    混合搜索引擎

    结合 BM25 和语义搜索，使用 RRF 融合算法。
    支持错误回退机制。
    """

    def __init__(
        self,
        vector_store: Optional[VectorStore] = None,
        bm25_index: Optional[BM25Index] = None,
        rrf_k: int = 60,
    ):
        """
        初始化混合搜索引擎

        Args:
            vector_store: 向量存储实例
            bm25_index: BM25 索引实例
            rrf_k: RRF 融合常数
        """
        self.vector_store = vector_store or get_vector_store()
        self.bm25_index = bm25_index or get_bm25_index()
        self.rrf_k = rrf_k

    def search(
        self,
        query: str,
        top_k: int = 5,
        mode: SearchMode = SearchMode.HYBRID,
        note_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        执行搜索

        Args:
            query: 搜索查询
            top_k: 返回结果数量
            mode: 搜索模式
            note_type: 笔记类型筛选
            tags: 标签筛选

        Returns:
            搜索结果列表
        """
        if mode == SearchMode.SEMANTIC:
            return self._semantic_search(query, top_k, note_type, tags)
        elif mode == SearchMode.KEYWORD:
            return self._keyword_search(query, top_k, tags)
        else:  # HYBRID
            return self._hybrid_search(query, top_k, note_type, tags)

    def _semantic_search(
        self,
        query: str,
        top_k: int,
        note_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """纯语义搜索"""
        try:
            results = self.vector_store.search(query, top_k=top_k, note_type=note_type, tags=tags)
            # 添加搜索模式标记
            for r in results:
                r["search_mode"] = "semantic"
            return results
        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            return []

    def _keyword_search(
        self, query: str, top_k: int, tags: Optional[List[str]] = None
    ) -> List[Dict[str, Any]]:
        """纯关键词搜索 (BM25)"""
        try:
            # 请求更多结果以补偿标签过滤后的数量损失
            search_k = top_k * 3 if tags else top_k
            bm25_results = self.bm25_index.search(query, top_k=search_k)

            # 转换为与语义搜索一致的格式
            results = []
            for r in bm25_results:
                # 获取笔记详情
                from . import note as note_module

                note = note_module.load_note_by_id(r["note_id"])
                if note:
                    # 如果有标签筛选，检查是否匹配所有标签
                    if tags and not all(t in note.tags for t in tags):
                        continue
                    results.append(
                        {
                            "id": r["note_id"],
                            "document": (
                                note.content[:300] + "..."
                                if len(note.content) > 300
                                else note.content
                            ),
                            "metadata": {
                                "title": note.title,
                                "type": note.type.value,
                                "tags": ",".join(note.tags),
                            },
                            "score": r["score"],
                            "search_mode": "keyword",
                        }
                    )

            return results
        except Exception as e:
            logger.error(f"Keyword search failed: {e}")
            return []

    def _hybrid_search(
        self,
        query: str,
        top_k: int,
        note_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """
        混合搜索：RRF 融合

        公式: score = Σ 1 / (k + rank)
        """
        # 1. 执行两种搜索（获取更多结果用于融合）
        search_k = max(top_k * 2, 10)  # 获取足够多的结果

        semantic_results = []
        bm25_results = []

        try:
            semantic_results = self.vector_store.search(
                query, top_k=search_k, note_type=note_type, tags=tags
            )
        except Exception as e:
            logger.warning(f"Semantic search failed in hybrid mode: {e}")

        try:
            bm25_results = self.bm25_index.search(query, top_k=search_k)
        except Exception as e:
            logger.warning(f"BM25 search failed in hybrid mode: {e}")

        # 对 BM25 结果做 tags 过滤
        bm25_notes_cache: Dict[str, Any] = {}
        if tags and bm25_results:
            from . import note as note_module

            filtered = []
            for r in bm25_results:
                note = note_module.load_note_by_id(r["note_id"])
                if note:
                    bm25_notes_cache[r["note_id"]] = note
                    if all(t in note.tags for t in tags):
                        filtered.append(r)
            bm25_results = filtered

        # 如果一种搜索失败，回退到另一种
        if not semantic_results and not bm25_results:
            return []
        elif not semantic_results:
            return self._keyword_search(query, top_k, tags)
        elif not bm25_results:
            for r in semantic_results[:top_k]:
                r["search_mode"] = "semantic"
            return semantic_results[:top_k]

        # 2. RRF 融合
        fused_scores: Dict[str, float] = {}
        result_data: Dict[str, Dict] = {}

        # 处理语义搜索结果
        for rank, result in enumerate(semantic_results, start=1):
            note_id = result.get("id")
            if note_id:
                fused_scores[note_id] = fused_scores.get(note_id, 0) + 1 / (self.rrf_k + rank)
                result_data[note_id] = result

        # 处理 BM25 搜索结果
        for rank, result in enumerate(bm25_results, start=1):
            note_id = result.get("note_id")
            if note_id:
                fused_scores[note_id] = fused_scores.get(note_id, 0) + 1 / (self.rrf_k + rank)
                # 如果没有语义搜索结果，使用 BM25 的数据
                if note_id not in result_data:
                    note = bm25_notes_cache.get(note_id)
                    if note is None:
                        from . import note as note_module

                        note = note_module.load_note_by_id(note_id)
                    if note:
                        result_data[note_id] = {
                            "id": note_id,
                            "document": (
                                note.content[:300] + "..."
                                if len(note.content) > 300
                                else note.content
                            ),
                            "metadata": {
                                "title": note.title,
                                "type": note.type.value,
                                "tags": ",".join(note.tags),
                            },
                        }

        # 3. 排序并返回 top_k
        sorted_ids = sorted(fused_scores.keys(), key=lambda x: fused_scores[x], reverse=True)

        results = []
        for note_id in sorted_ids[:top_k]:
            data = result_data.get(note_id, {})
            data["score"] = fused_scores[note_id]
            data["search_mode"] = "hybrid"
            results.append(data)

        return results

    def rebuild_bm25_index(self) -> bool:
        """
        重建 BM25 索引

        Returns:
            是否成功重建
        """
        try:
            from . import note as note_module

            notes = note_module.list_notes(limit=10000)  # 获取所有笔记
            return self.bm25_index.rebuild_from_notes(notes)
        except Exception as e:
            logger.error(f"Failed to rebuild BM25 index: {e}")
            return False


# 全局搜索引擎实例
_search_engine: Optional[HybridSearchEngine] = None


def get_search_engine() -> HybridSearchEngine:
    """
    获取搜索引擎实例（单例模式）

    Returns:
        HybridSearchEngine 实例
    """
    global _search_engine
    if _search_engine is None:
        _search_engine = HybridSearchEngine()
    return _search_engine


def reset_search_engine():
    """重置全局搜索引擎实例（用于切换知识库时）"""
    global _search_engine
    _search_engine = None
