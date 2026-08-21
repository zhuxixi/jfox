"""ChromaDB 向量存储封装"""

import logging
import re
import shutil
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import chromadb  # type: ignore[import-not-found]
import numpy as np
from chromadb.config import Settings  # type: ignore[import-not-found]

from .config import config
from .models import Note

logger = logging.getLogger(__name__)

# 活跃数据库快照只做有限次尝试，避免写入持续进行时长时间阻塞命令。
_READ_ONLY_SNAPSHOT_ATTEMPTS = 3


class VectorStoreReadError(RuntimeError):
    """读取现有向量集合失败。"""


class VectorStore:
    """向量存储封装"""

    def __init__(self, persist_directory: Optional[Path] = None):
        if persist_directory is None:
            persist_directory = config.chroma_dir

        self.persist_directory = persist_directory
        self.client: Any = None
        self.collection: Any = None
        self._read_only_tempdir: Optional[tempfile.TemporaryDirectory[str]] = None
        self._read_only_snapshot: Optional[Path] = None

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
            collection = self.collection
            assert collection is not None
            collection.add(
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
                dim_match = re.search(r"dimension of (\d+).*got (\d+)", error_msg, re.IGNORECASE)
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
        self,
        query: str,
        top_k: int = 5,
        note_type: Optional[str] = None,
        tags: Optional[List[str]] = None,
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

            if tags:
                tag_clauses = [{"tags": {"$contains": t}} for t in tags]
                if where:
                    # 已有 note_type 条件，合并到 $and
                    combined = [where] + tag_clauses
                    where = {"$and": combined}
                elif len(tag_clauses) > 1:
                    where = {"$and": tag_clauses}
                else:
                    where = tag_clauses[0]

            # 搜索
            collection = self.collection
            assert collection is not None
            results = collection.query(
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
            collection = self.collection
            assert collection is not None
            collection.delete(ids=[note_id])
            logger.debug(f"Deleted note {note_id} from vector store")
            return True
        except Exception as e:
            logger.error(f"Failed to delete note {note_id}: {e}")
            return False

    def add_or_update_note(self, note: Note) -> bool:
        """添加或更新笔记（如果已存在则更新）"""
        # 先尝试删除旧的（如果存在）
        try:
            collection = self.collection
            assert collection is not None
            collection.delete(ids=[note.id])
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
            collection = self.collection
            assert collection is not None
            result = collection.get(include=[])
            return result.get("ids", [])
        except Exception as e:
            logger.error(f"Failed to get all IDs: {e}")
            return []

    def _recursive_file_manifest(self) -> Tuple[Tuple[str, int, int], ...]:
        """读取数据库目录的递归文件清单，用于检测复制期间的变化。"""
        entries = []
        for path in self.persist_directory.rglob("*"):
            if not path.is_file():
                continue
            stat = path.stat()
            entries.append(
                (
                    path.relative_to(self.persist_directory).as_posix(),
                    stat.st_size,
                    stat.st_mtime_ns,
                )
            )
        return tuple(sorted(entries))

    def _discard_read_only_snapshot(self) -> None:
        """清理未完成或不可用的只读快照。"""
        self._read_only_snapshot = None
        if self._read_only_tempdir is not None:
            self._read_only_tempdir.cleanup()
            self._read_only_tempdir = None

    def _create_consistent_snapshot(self) -> Path:
        """在复制前后清单稳定时返回只读快照，否则有限重试。"""
        last_error: Optional[BaseException] = None
        for _attempt in range(_READ_ONLY_SNAPSHOT_ATTEMPTS):
            self._discard_read_only_snapshot()
            self._read_only_tempdir = tempfile.TemporaryDirectory(prefix="jfox-moc-chroma-")
            snapshot = Path(self._read_only_tempdir.name) / "chroma_db"
            try:
                manifest_before = self._recursive_file_manifest()
                shutil.copytree(self.persist_directory, snapshot)
                manifest_after = self._recursive_file_manifest()
                if manifest_before != manifest_after:
                    last_error = RuntimeError("数据库文件清单在复制期间发生变化")
                    continue
                self._read_only_snapshot = snapshot
                return snapshot
            except (OSError, RuntimeError) as exc:
                last_error = exc

        self._discard_read_only_snapshot()
        raise VectorStoreReadError(
            f"无法为 {self.persist_directory} 创建一致的向量库只读快照：{last_error}。"
            "可能有 daemon/indexer 正在写入，请稍后重试。"
        ) from last_error

    def _get_existing_collection(self):
        """通过只读快照打开现有 Chroma 集合，不创建或修改原始数据库。"""
        if self.collection is not None:
            return self.collection
        database_path = self.persist_directory / "chroma.sqlite3"
        if not database_path.is_file():
            raise VectorStoreReadError(f"Vector database does not exist: {database_path}")
        try:
            if self.client is None:
                # Chroma 即使只读集合也会写 SQLite，因此只打开清单稳定的快照。
                snapshot = self._create_consistent_snapshot()
                self.client = chromadb.PersistentClient(
                    path=str(snapshot),
                    settings=Settings(anonymized_telemetry=False, allow_reset=True),
                )
            self.collection = self.client.get_collection(name="notes")
            return self.collection
        except VectorStoreReadError:
            raise
        except Exception as exc:
            self.client = None
            self.collection = None
            self._discard_read_only_snapshot()
            raise VectorStoreReadError(
                f"Unable to read vector collection at {self.persist_directory}: {exc}"
            ) from exc

    def get_all_embeddings(
        self, note_type: Optional[str] = None
    ) -> Tuple[List[str], List[Optional[Dict[str, Any]]], np.ndarray]:
        """通过严格不创建数据的读取路径返回已存向量。"""
        collection = self._get_existing_collection()
        kwargs: Dict[str, Any] = {"include": ["embeddings", "metadatas"]}
        if note_type is not None:
            kwargs["where"] = {"type": note_type}

        try:
            result = collection.get(**kwargs)
        except Exception as exc:
            raise VectorStoreReadError(f"Unable to read vector embeddings: {exc}") from exc
        ids = list(result.get("ids") or [])
        metadatas = list(result.get("metadatas") or [])
        raw_embeddings = result.get("embeddings")
        if raw_embeddings is None or len(raw_embeddings) == 0:
            return ids, metadatas, np.empty((0, 0), dtype=np.float32)
        try:
            embeddings = np.asarray(raw_embeddings, dtype=np.float32)
        except (TypeError, ValueError) as exc:
            raise VectorStoreReadError(f"Invalid vector embeddings: {exc}") from exc
        return ids, metadatas, embeddings

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        if self.collection is None:
            self.init()

        try:
            collection = self.collection
            assert collection is not None
            count = collection.count()
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
            collection = self.collection
            assert collection is not None
            result = collection.get(include=[])
            ids = result.get("ids", [])
            if ids:
                collection.delete(ids=ids)
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
            client = self.client
            assert client is not None
            client.delete_collection("notes")
            logger.info("Deleted old collection 'notes'")
        except ValueError:
            # ChromaDB 对不存在的 collection 抛 ValueError，这是正常情况
            logger.debug("Collection 'notes' did not exist, skipping delete")

        try:
            client = self.client
            assert client is not None
            self.collection = client.get_or_create_collection(
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
