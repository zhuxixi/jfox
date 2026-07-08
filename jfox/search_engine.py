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

        # 若 BM25 索引是从 v1 迁移而来，需要全量重建以回填 doc_types
        if self.bm25_index.needs_rebuild:
            if self.rebuild_bm25_index():
                self.bm25_index.needs_rebuild = False
            else:
                logger.warning(
                    "Failed to rebuild BM25 index after v1 migration, will retry next time"
                )

    @staticmethod
    def _filter_archived_results(
        results: List[Dict[str, Any]], include_archived: bool
    ) -> List[Dict[str, Any]]:
        """根据归档状态过滤搜索结果"""
        if include_archived:
            return results

        from .note_index import get_note_index

        idx = get_note_index()
        filtered = []
        for r in results:
            note_id = r.get("id") or r.get("note_id")
            if not note_id:
                continue
            meta = idx.find_by_id(note_id)
            # 如果索引中不存在，保守保留；如果存在且已归档，则排除
            if meta is not None and meta.archived:
                continue
            filtered.append(r)
        return filtered

    def search(
        self,
        query: str,
        top_k: int = 5,
        mode: SearchMode = SearchMode.HYBRID,
        note_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        include_archived: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        执行搜索

        Args:
            query: 搜索查询
            top_k: 返回结果数量
            mode: 搜索模式
            note_type: 笔记类型筛选
            tags: 标签筛选
            include_archived: 是否包含已归档笔记，默认排除

        Returns:
            搜索结果列表
        """
        if mode == SearchMode.SEMANTIC:
            return self._semantic_search(
                query, top_k, note_type, tags, include_archived=include_archived
            )
        elif mode == SearchMode.KEYWORD:
            return self._keyword_search(
                query, top_k, note_type, tags, include_archived=include_archived
            )
        else:  # HYBRID
            return self._hybrid_search(
                query, top_k, note_type, tags, include_archived=include_archived
            )

    def _semantic_search(
        self,
        query: str,
        top_k: int,
        note_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        include_archived: bool = False,
    ) -> List[Dict[str, Any]]:
        """纯语义搜索"""
        try:
            # 默认排除归档时需要多取一些结果，过滤后再截断
            search_k = top_k if include_archived else max(top_k * 5, 20)
            results = self.vector_store.search(
                query, top_k=search_k, note_type=note_type, tags=tags
            )
            # 添加搜索模式标记
            for r in results:
                r["search_mode"] = "semantic"
            filtered = self._filter_archived_results(results, include_archived)

            # 高密度归档场景下，初次过滤结果可能不足 top_k，二次扩大检索回填
            if not include_archived and len(filtered) < top_k:
                search_k = max(top_k * 10, 50)
                results = self.vector_store.search(
                    query, top_k=search_k, note_type=note_type, tags=tags
                )
                for r in results:
                    r["search_mode"] = "semantic"
                filtered = self._filter_archived_results(results, include_archived)

            return filtered[:top_k]
        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            return []

    def _keyword_search(
        self,
        query: str,
        top_k: int,
        note_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        include_archived: bool = False,
    ) -> List[Dict[str, Any]]:
        """纯关键词搜索 (BM25)"""
        try:
            # 请求更多结果以补偿标签/归档过滤后的数量损失（note_type 已在 BM25 层过滤）
            if tags or not include_archived:
                search_k = max(top_k * 5, 20)
            else:
                search_k = top_k
            bm25_results = self.bm25_index.search(query, top_k=search_k, note_type=note_type)

            results = self._build_keyword_results(bm25_results, tags, include_archived)

            # 高密度归档场景下，初次过滤结果可能不足 top_k，二次扩大检索回填
            if not include_archived and len(results) < top_k:
                search_k = max(top_k * 10, 50)
                bm25_results = self.bm25_index.search(query, top_k=search_k, note_type=note_type)
                results = self._build_keyword_results(bm25_results, tags, include_archived)

            return results[:top_k]
        except Exception as e:
            logger.error(f"Keyword search failed: {e}")
            return []

    def _build_keyword_results(
        self,
        bm25_results: List[Dict[str, Any]],
        tags: Optional[List[str]] = None,
        include_archived: bool = False,
    ) -> List[Dict[str, Any]]:
        """将 BM25 搜索结果转换为统一格式并过滤归档/标签"""
        results = []
        for r in bm25_results:
            from . import note as note_module

            note = note_module.load_note_by_id(r["note_id"])
            if note:
                # 默认排除归档笔记
                if not include_archived and note.archived:
                    continue
                # 如果有标签筛选，检查是否匹配所有标签
                if tags and not all(t in note.tags for t in tags):
                    continue
                results.append(
                    {
                        "id": r["note_id"],
                        "document": (
                            note.content[:300] + "..." if len(note.content) > 300 else note.content
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

    def _hybrid_search_with_k(
        self,
        query: str,
        top_k: int,
        search_k: int,
        note_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        include_archived: bool = False,
    ) -> List[Dict[str, Any]]:
        """使用指定 search_k 执行一次混合搜索（RRF 融合）"""
        semantic_results = []
        bm25_results = []

        try:
            semantic_results = self.vector_store.search(
                query, top_k=search_k, note_type=note_type, tags=tags
            )
        except Exception as e:
            logger.warning(f"Semantic search failed in hybrid mode: {e}")

        try:
            bm25_results = self.bm25_index.search(query, top_k=search_k, note_type=note_type)
        except Exception as e:
            logger.warning(f"BM25 search failed in hybrid mode: {e}")

        # 对 BM25 结果做 tags / 归档过滤
        bm25_notes_cache: Dict[str, Any] = {}
        if bm25_results and (tags or not include_archived):
            from . import note as note_module

            filtered = []
            for r in bm25_results:
                note = note_module.load_note_by_id(r["note_id"])
                if note:
                    bm25_notes_cache[r["note_id"]] = note
                    if not include_archived and note.archived:
                        continue
                    if tags and not all(t in note.tags for t in tags):
                        continue
                    filtered.append(r)
            bm25_results = filtered

        # 如果一种搜索失败，回退到另一种
        if not semantic_results and not bm25_results:
            return []
        elif not semantic_results:
            return self._keyword_search(
                query, top_k, note_type, tags, include_archived=include_archived
            )
        elif not bm25_results:
            filtered = self._filter_archived_results(semantic_results, include_archived)
            for r in filtered[:top_k]:
                r["search_mode"] = "semantic"
            return filtered[:top_k]

        # RRF 融合
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

        # 排序并过滤归档后返回 top_k
        sorted_ids = sorted(fused_scores.keys(), key=lambda x: fused_scores[x], reverse=True)

        from .note_index import get_note_index

        idx = get_note_index()
        results = []
        for note_id in sorted_ids:
            if not include_archived:
                meta = idx.find_by_id(note_id)
                if meta is not None and meta.archived:
                    continue
            data = result_data.get(note_id, {})
            data["score"] = fused_scores[note_id]
            data["search_mode"] = "hybrid"
            results.append(data)
            if len(results) >= top_k:
                break

        return results

    def _hybrid_search(
        self,
        query: str,
        top_k: int,
        note_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
        include_archived: bool = False,
    ) -> List[Dict[str, Any]]:
        """
        混合搜索：RRF 融合

        公式: score = Σ 1 / (k + rank)
        """
        if include_archived:
            search_k = max(top_k * 2, 10)
            return self._hybrid_search_with_k(
                query, top_k, search_k, note_type, tags, include_archived
            )

        # 默认排除归档时，先按 5 倍 over-fetch；结果不足则二次扩大到 10 倍
        search_k = max(top_k * 5, 20)
        results = self._hybrid_search_with_k(
            query, top_k, search_k, note_type, tags, include_archived
        )
        if len(results) < top_k:
            search_k = max(top_k * 10, 50)
            results = self._hybrid_search_with_k(
                query, top_k, search_k, note_type, tags, include_archived
            )
        return results

    def rebuild_bm25_index(self) -> bool:
        """
        重建 BM25 索引

        Returns:
            是否成功重建
        """
        try:
            from . import note as note_module

            # 重建时包含归档笔记，搜索时再通过归档状态过滤
            notes = note_module.list_notes(limit=10000, include_archived=True)
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
