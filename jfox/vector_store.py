"""ChromaDB 向量存储封装"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import chromadb
from chromadb.config import Settings

from .config import config
from .models import Note

logger = logging.getLogger(__name__)


class VectorStore:
    """向量存储封装"""

    def __init__(self, persist_directory: Optional[Path] = None):
        if persist_directory is None:
            persist_directory = config.chroma_dir

        self.persist_directory = persist_directory
        self.client = None
        self.collection = None

    def init(self):
        """初始化 ChromaDB"""
        if self.client is not None:
            return

        # 确保目录存在
        self.persist_directory.mkdir(parents=True, exist_ok=True)

        # 创建客户端
        self.client = chromadb.PersistentClient(
            path=str(self.persist_directory),
            settings=Settings(
                anonymized_telemetry=False,
                allow_reset=True,
            ),
        )

        # 获取或创建集合
        self.collection = self.client.get_or_create_collection(
            name="notes", metadata={"hnsw:space": "cosine"}
        )

        logger.info(f"VectorStore initialized at {self.persist_directory}")

    def add_note(self, note: Note) -> bool:
        """添加笔记到向量存储"""
        if self.collection is None:
            self.init()

        try:
            # 准备文档内容
            document = f"{note.title}\n{note.content}"

            # 获取 embedding
            from .embedding_backend import get_backend

            backend = get_backend()
            embedding = backend.encode_single(document).tolist()

            # 添加到 ChromaDB
            self.collection.add(
                ids=[note.id],
                documents=[document],
                embeddings=[embedding],
                metadatas=[
                    {
                        "title": note.title,
                        "type": note.type.value,
                        "filepath": str(note.filepath),
                        "tags": ",".join(note.tags),
                    }
                ],
            )

            logger.debug(f"Added note {note.id} to vector store")
            return True

        except Exception as e:
            error_msg = str(e)
            if "dimension" in error_msg.lower() and "expecting" in error_msg.lower():
                # 维度不匹配：模型已切换，提示用户 rebuild
                dim_match = re.search(
                    r"dimension of (\d+).*got (\d+)", error_msg
                )
                if dim_match:
                    old_dim, new_dim = dim_match.group(1), dim_match.group(2)
                    logger.error(
                        f"Embedding 维度不匹配（collection: {old_dim}, "
                        f"当前模型: {new_dim}）。"
                        f"可能是模型已切换，请执行 jfox index rebuild "
                        f"重建索引。原始错误: {error_msg}"
                    )
                else:
                    logger.error(
                        f"Embedding 维度不匹配，可能是模型已切换。"
                        f"请执行 jfox index rebuild 重建索引。"
                        f"原始错误: {error_msg}"
                    )
            else:
                logger.error(f"Failed to add note {note.id}: {error_msg}")
            return False

    def search(
        self, query: str, top_k: int = 5, note_type: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """语义搜索"""
        if self.collection is None:
            self.init()

        try:
            # 获取查询向量
            from .embedding_backend import get_backend

            backend = get_backend()
            query_embedding = backend.encode_single(query).tolist()

            # 构建过滤条件
            where = {}
            if note_type:
                where["type"] = note_type

            # 搜索
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=top_k,
                where=where if where else None,
                include=["documents", "metadatas", "distances"],
            )

            # 格式化结果
            formatted_results = []
            for i in range(len(results["ids"][0])):
                formatted_results.append(
                    {
                        "id": results["ids"][0][i],
                        "document": results["documents"][0][i],
                        "metadata": results["metadatas"][0][i],
                        "distance": results["distances"][0][i],
                        "score": 1 - results["distances"][0][i],  # 转换为相似度
                    }
                )

            return formatted_results

        except Exception as e:
            logger.error(f"Search failed: {e}")
            return []

    def delete_note(self, note_id: str) -> bool:
        """删除笔记"""
        if self.collection is None:
            self.init()

        try:
            self.collection.delete(ids=[note_id])
            logger.debug(f"Deleted note {note_id} from vector store")
            return True
        except Exception as e:
            logger.error(f"Failed to delete note {note_id}: {e}")
            return False

    def add_or_update_note(self, note: Note) -> bool:
        """添加或更新笔记（如果已存在则更新）"""
        # 先尝试删除旧的（如果存在）
        try:
            self.collection.delete(ids=[note.id])
        except Exception:
            pass  # 可能不存在，忽略错误

        # 添加新的
        return self.add_note(note)

    def get_all_ids(self) -> List[str]:
        """获取所有索引的笔记 ID"""
        if self.collection is None:
            self.init()

        try:
            # 获取所有数据
            result = self.collection.get(include=[])
            return result.get("ids", [])
        except Exception as e:
            logger.error(f"Failed to get all IDs: {e}")
            return []

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        if self.collection is None:
            self.init()

        try:
            count = self.collection.count()
            return {
                "total_notes": count,
                "persist_directory": str(self.persist_directory),
            }
        except Exception as e:
            logger.error(f"Failed to get stats: {e}")
            return {"total_notes": 0, "error": str(e)}

    def clear(self) -> bool:
        """
        清空向量存储中的所有数据

        用于 index rebuild 时先清除旧数据，确保干净重建。

        Returns:
            是否成功清空
        """
        if self.collection is None:
            self.init()

        try:
            result = self.collection.get(include=[])
            ids = result.get("ids", [])
            if ids:
                self.collection.delete(ids=ids)
            logger.info(f"Cleared vector store ({len(ids)} notes removed)")
            return True
        except Exception as e:
            logger.error(f"Failed to clear vector store: {e}")
            return False

    def reset_collection(self) -> bool:
        """
        彻底删除并重建 collection（用于 index rebuild）

        与 clear() 不同，reset_collection() 会删除整个 collection 结构再重建，
        确保 embedding dimension 等元信息也被重置。
        适用于切换模型后需要 rebuild 的场景。

        Returns:
            是否成功重建
        """
        if self.client is None:
            self.init()

        try:
            self.client.delete_collection("notes")
            logger.info("Deleted old collection 'notes'")
        except Exception:
            pass  # collection 可能不存在

        try:
            self.collection = self.client.get_or_create_collection(
                name="notes", metadata={"hnsw:space": "cosine"}
            )
            logger.info("Recreated collection 'notes'")
            return True
        except Exception as e:
            logger.error(f"Failed to recreate collection: {e}")
            return False


# 全局向量存储实例
_vector_store: Optional[VectorStore] = None


def get_vector_store() -> VectorStore:
    """获取全局向量存储实例"""
    global _vector_store
    if _vector_store is None:
        _vector_store = VectorStore()
    return _vector_store


def reset_vector_store():
    """重置全局向量存储实例（用于切换知识库时）"""
    global _vector_store
    _vector_store = None
