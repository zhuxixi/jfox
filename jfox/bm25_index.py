"""
BM25 索引模块

提供基于 BM25 算法的关键词搜索功能，支持索引持久化和增量更新。
"""

import json
import logging
import os
import pickle
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from filelock import FileLock, Timeout
from rank_bm25 import BM25Okapi

from .config import config

logger = logging.getLogger(__name__)


class BM25Index:
    """
    BM25 索引管理器

    负责构建、保存、加载和查询 BM25 索引。
    支持增量更新和全量重建，支持按笔记类型过滤。
    """

    INDEX_VERSION = 2
    INDEX_FILENAME = "bm25_index.pkl"
    METADATA_FILENAME = "bm25_metadata.json"
    LOCK_FILENAME = "bm25_index.lock"

    def __init__(self, index_dir: Optional[Path] = None):
        """
        初始化 BM25 索引

        Args:
            index_dir: 索引文件存放目录，默认为 config.zk_dir
        """
        self.index_dir = index_dir or config.zk_dir
        self.index_path = self.index_dir / self.INDEX_FILENAME
        self.metadata_path = self.index_dir / self.METADATA_FILENAME

        # 索引数据
        self.bm25: Optional[BM25Okapi] = None
        self.documents: List[str] = []  # 分词后的文档列表
        self.doc_ids: List[str] = []  # 文档 ID 列表
        self.doc_types: List[Optional[str]] = []  # 文档类型列表
        self.doc_mapping: Dict[str, int] = {}  # note_id -> index
        self.needs_rebuild: bool = False  # 是否需要全量重建以回填元数据
        self._loaded_write_version: int = 0  # load 时记录的磁盘写入版本（乐观锁令牌）
        self._pending_ops: List[Tuple[str, str, str, Optional[str]]] = []  # 未落盘的增量操作
        self._dirty_full_rebuild: bool = False  # rebuild 后 save 走覆盖语义

        # 加载已有索引
        self._load()

    def _tokenize(self, text: str) -> List[str]:
        """
        分词函数 - 适配中英文

        Args:
            text: 输入文本

        Returns:
            分词结果列表
        """
        if not text:
            return []

        # 转换为小写
        text = text.lower()

        # 提取中文字符串（2-10字）和英文单词
        # 中文按字符分割，英文按单词分割
        tokens = []

        # 匹配中文字符
        chinese_chars = re.findall(r"[\u4e00-\u9fff]", text)
        tokens.extend(chinese_chars)

        # 匹配英文单词（包括下划线连接的变量名）
        english_words = re.findall(r"[a-z][a-z0-9_]{0,20}", text)
        tokens.extend(english_words)

        # 匹配数字
        numbers = re.findall(r"\d+", text)
        tokens.extend(numbers)

        return tokens

    def _load(self) -> bool:
        """
        从磁盘加载索引

        Returns:
            是否成功加载
        """
        try:
            if not self.index_path.exists() or not self.metadata_path.exists():
                logger.info("BM25 index not found, will create new index")
                return False

            # 加载元数据
            with open(self.metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)

            # 记录磁盘写入版本（乐观锁令牌）；旧格式无此字段视为 0
            self._loaded_write_version = int(metadata.get("write_version") or 0)

            # 检查版本，支持从 v1 迁移到 v2
            version = metadata.get("version")
            if version not in (1, self.INDEX_VERSION):
                logger.warning(f"BM25 index version mismatch: {version} != {self.INDEX_VERSION}")
                return False

            # 加载索引
            with open(self.index_path, "rb") as f:
                index_data = pickle.load(f)

            self.bm25 = index_data["bm25"]
            self.documents = index_data["documents"]
            self.doc_ids = index_data["doc_ids"]
            self.doc_mapping = index_data["doc_mapping"]

            # v1/v2 索引若缺失 doc_types，需要全量重建来回填类型元数据
            loaded_doc_types = index_data.get("doc_types")
            needs_backfill = loaded_doc_types is None
            if needs_backfill:
                self.doc_types = [None] * len(self.doc_ids)
            else:
                # 校验 doc_types 必须是 list（支持 append 等可变操作）
                if not isinstance(loaded_doc_types, list):
                    logger.error(f"BM25 index doc_types is not a list: {type(loaded_doc_types)}")
                    self._reset()
                    return False
                self.doc_types = loaded_doc_types

            # 校验核心数据结构长度一致且映射有效，防止持久化损坏导致错位
            expected_len = len(self.doc_ids)
            if not (
                len(self.documents) == expected_len
                and len(self.doc_types) == expected_len
                and len(self.doc_mapping) == expected_len
            ):
                logger.error(
                    "BM25 index data length mismatch: "
                    f"documents={len(self.documents)}, doc_ids={expected_len}, "
                    f"doc_types={len(self.doc_types)}, doc_mapping={len(self.doc_mapping)}"
                )
                self._reset()
                return False

            # 校验 doc_mapping 与 doc_ids 一一对应，且索引值在有效范围内
            for idx, note_id in enumerate(self.doc_ids):
                if self.doc_mapping.get(note_id) != idx:
                    logger.error(
                        f"BM25 index mapping corrupted: note_id={note_id}, "
                        f"expected_idx={idx}, got={self.doc_mapping.get(note_id)}"
                    )
                    self._reset()
                    return False

            # 校验 doc_types 元素类型
            if not all(dt is None or isinstance(dt, str) for dt in self.doc_types):
                logger.error("BM25 index doc_types contains invalid element types")
                self._reset()
                return False

            # 校验 bm25 实例有效；若损坏则重置并返回 False
            if self.bm25 is None and expected_len > 0:
                logger.error("BM25 index corrupted: bm25 is None but documents exist")
                self._reset()
                return False

            # 缺失 doc_types 或 metadata 标记需要重建的索引，触发全量重建回填类型元数据
            if needs_backfill or metadata.get("needs_rebuild"):
                self.needs_rebuild = True
                logger.info("Loaded BM25 index needs rebuild to backfill doc_types")

            logger.info(f"Loaded BM25 index: {len(self.doc_ids)} documents")
            return True

        except Exception as e:
            logger.error(f"Failed to load BM25 index: {e}")
            self._reset()
            return False

    def _read_disk_write_version(self) -> int:
        """读磁盘 metadata 的 write_version；损坏/缺失视为 0"""
        try:
            with open(self.metadata_path, "r", encoding="utf-8") as f:
                return int(json.load(f).get("write_version") or 0)
        except Exception:
            return 0

    def _atomic_write_bytes(self, path: Path, data: bytes) -> None:
        """原子写：先写临时文件再 os.replace，读端永远只能读到完整文件"""
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)

    def _atomic_write_text(self, path: Path, text: str) -> None:
        """原子写文本（同 _atomic_write_bytes）"""
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)

    def _save(self) -> bool:
        """
        保存索引到磁盘（乐观并发控制版）

        流程：拿文件锁 → 比对磁盘 write_version → 磁盘较新则 reload+重放本地增量
        → 原子写 pkl → 原子写 metadata（commit point）。
        铁律：任何一步失败都不写盘，返回 False。

        Returns:
            是否成功保存
        """
        try:
            # 确保目录存在
            self.index_dir.mkdir(parents=True, exist_ok=True)

            with FileLock(str(self.index_dir / self.LOCK_FILENAME), timeout=5):
                disk_version = self._read_disk_write_version()
                if (
                    disk_version > self._loaded_write_version
                    and not self._dirty_full_rebuild
                ):
                    if not self._load():
                        logger.error("BM25 磁盘版本较新但 reload 失败，放弃本次 save（不写盘）")
                        return False
                    self._replay_pending_ops()
                elif disk_version < self._loaded_write_version:
                    logger.warning(
                        f"BM25 磁盘版本 {disk_version} 比本地 "
                        f"{self._loaded_write_version} 旧，按本地覆盖"
                    )

                new_version = max(disk_version, self._loaded_write_version) + 1
                prev_version = self._loaded_write_version

                # 先写 pkl（数据本体），后写 metadata（commit point）：
                # 版本号上涨一定意味着 pkl 已完整落盘
                index_data = {
                    "bm25": self.bm25,
                    "documents": self.documents,
                    "doc_ids": self.doc_ids,
                    "doc_types": self.doc_types,
                    "doc_mapping": self.doc_mapping,
                }
                self._atomic_write_bytes(self.index_path, pickle.dumps(index_data))
                metadata = {
                    "version": self.INDEX_VERSION,
                    "doc_count": len(self.doc_ids),
                    "needs_rebuild": self.needs_rebuild,
                    "write_version": new_version,
                }
                self._atomic_write_text(
                    self.metadata_path, json.dumps(metadata, ensure_ascii=False, indent=2)
                )

                self._loaded_write_version = new_version
                self._pending_ops.clear()
                self._dirty_full_rebuild = False
                logger.info(
                    f"Saved BM25 index: {len(self.doc_ids)} documents "
                    f"(write_version={new_version}, prev={prev_version})"
                )
                return True
        except Timeout:
            logger.error("BM25 save: 获取索引文件锁超时（5s），放弃写入")
            return False
        except Exception as e:
            logger.error(f"Failed to save BM25 index: {e}")
            return False

    def _reset(self):
        """重置索引状态"""
        self.bm25 = None
        self.documents = []
        self.doc_ids = []
        self.doc_types = []
        self.doc_mapping = {}
        self.needs_rebuild = False

    def _rebuild_index(self):
        """重新构建 BM25 索引"""
        if self.documents:
            self.bm25 = BM25Okapi(self.documents)
        else:
            self.bm25 = None

    @staticmethod
    def _normalize_note_type(note_type: Any) -> Optional[str]:
        """
        标准化笔记类型入参

        接受 str、None 或具有 .value 属性的枚举对象（如 NoteType），
        其他类型转换为 str 并记录警告。

        Args:
            note_type: 原始笔记类型

        Returns:
            标准化后的 str 或 None
        """
        if note_type is None:
            return None
        if isinstance(note_type, str):
            return note_type
        if hasattr(note_type, "value"):
            return str(note_type.value)
        logger.warning(f"Unexpected note_type type {type(note_type)}, converting to str")
        return str(note_type)

    def _add_document_local(self, note_id: str, content: str, note_type: Optional[str]) -> bool:
        """纯内存添加（不含索引重建/落盘/pending 记录）"""
        if note_id in self.doc_mapping:
            self._remove_document_local(note_id)
        tokens = self._tokenize(content)
        if not tokens:
            return True
        normalized_type = self._normalize_note_type(note_type)
        idx = len(self.documents)
        self.documents.append(tokens)
        self.doc_ids.append(note_id)
        self.doc_types.append(normalized_type)
        self.doc_mapping[note_id] = idx
        return True

    def _remove_document_local(self, note_id: str) -> bool:
        """纯内存移除"""
        if note_id not in self.doc_mapping:
            return True
        idx = self.doc_mapping[note_id]
        self.documents.pop(idx)
        self.doc_ids.pop(idx)
        self.doc_types.pop(idx)
        del self.doc_mapping[note_id]
        self.doc_mapping = {doc_id: i for i, doc_id in enumerate(self.doc_ids)}
        return True

    def _replay_pending_ops(self) -> None:
        """重放本地未落盘的增量操作：同 id 合并（只留最后 op）后按序 apply"""
        if not self._pending_ops:
            return
        merged: Dict[str, Tuple[str, str, Optional[str]]] = {}
        for op, nid, content, ntype in self._pending_ops:
            merged[nid] = (op, content, ntype)
        logger.warning(f"BM25 merge: 磁盘版本较新，重放 {len(merged)} 条本地操作后合并写入")
        for nid, (op, content, ntype) in merged.items():
            if op == "remove":
                self._remove_document_local(nid)
            else:
                self._add_document_local(nid, content, ntype)
        self._rebuild_index()

    def add_document(self, note_id: str, content: str, note_type: Optional[str] = None) -> bool:
        """
        添加文档到索引（增量更新）

        Args:
            note_id: 笔记 ID
            content: 笔记内容
            note_type: 笔记类型（可选）

        Returns:
            是否成功添加
        """
        try:
            if not self._add_document_local(note_id, content, note_type):
                return False
            self._pending_ops.append(("add", note_id, content, note_type))

            # 重建索引
            self._rebuild_index()

            # 保存
            self._save()

            return True

        except Exception as e:
            logger.error(f"Failed to add document {note_id}: {e}")
            return False

    def remove_document(self, note_id: str) -> bool:
        """
        从索引中移除文档

        Args:
            note_id: 笔记 ID

        Returns:
            是否成功移除
        """
        try:
            if note_id not in self.doc_mapping:
                return True

            self._remove_document_local(note_id)
            self._pending_ops.append(("remove", note_id, "", None))

            # 重建索引
            self._rebuild_index()

            # 保存
            self._save()

            return True

        except Exception as e:
            logger.error(f"Failed to remove document {note_id}: {e}")
            return False

    def add_documents_batch(
        self,
        documents: List[Union[Tuple[str, str], Tuple[str, str, Optional[str]]]],
    ) -> bool:
        """
        批量添加文档到索引（高效版本）

        与逐条调用 add_document() 不同，此方法收集所有文档后只执行一次索引重建和保存。
        适用于批量导入场景。

        Args:
            documents: [(note_id, content), ...] 或 [(note_id, content, note_type), ...] 列表

        Returns:
            是否成功添加
        """
        if not documents:
            return True

        # 快照当前状态，失败时恢复
        saved_docs = list(self.documents)
        saved_ids = list(self.doc_ids)
        saved_types = list(self.doc_types)
        saved_mapping = dict(self.doc_mapping)
        saved_bm25 = self.bm25
        saved_pending_len = len(self._pending_ops)

        try:
            for doc in documents:
                note_id = doc[0]
                content = doc[1]
                note_type = self._normalize_note_type(doc[2] if len(doc) >= 3 else None)

                # 如果已存在，先移除
                if note_id in self.doc_mapping:
                    # 内联移除逻辑，避免触发 rebuild/save
                    idx = self.doc_mapping[note_id]
                    self.documents.pop(idx)
                    self.doc_ids.pop(idx)
                    self.doc_types.pop(idx)
                    del self.doc_mapping[note_id]
                    # 更新后续索引
                    self.doc_mapping = {}
                    for i, doc_id in enumerate(self.doc_ids):
                        self.doc_mapping[doc_id] = i

                # 分词并添加
                tokens = self._tokenize(content)
                if not tokens:
                    continue  # 跳过分词结果为空的文档
                idx = len(self.documents)
                self.documents.append(tokens)
                self.doc_ids.append(note_id)
                self.doc_types.append(note_type)
                self.doc_mapping[note_id] = idx
                # 记录 pending（save 失败回滚时会截断）
                self._pending_ops.append(("add", note_id, content, note_type))

            # 一次性重建索引
            self._rebuild_index()

            # 一次性保存，失败时回滚
            if not self._save():
                self.documents = saved_docs
                self.doc_ids = saved_ids
                self.doc_types = saved_types
                self.doc_mapping = saved_mapping
                self.bm25 = saved_bm25
                del self._pending_ops[saved_pending_len:]
                logger.error("Failed to persist BM25 index after batch add, rolled back")
                return False

            logger.info(f"Batch added {len(documents)} documents to BM25 index")
            return True

        except Exception:
            # 恢复到批次前的状态
            self.documents = saved_docs
            self.doc_ids = saved_ids
            self.doc_types = saved_types
            self.doc_mapping = saved_mapping
            self.bm25 = saved_bm25
            del self._pending_ops[saved_pending_len:]
            logger.error(
                f"Failed to batch add {len(documents)} documents to BM25 index",
                exc_info=True,
            )
            return False

    def search(self, query: str, top_k: int = 5, note_type: Optional[str] = None) -> List[Dict]:
        """
        搜索文档

        Args:
            query: 搜索查询
            top_k: 返回结果数量
            note_type: 笔记类型筛选（可选）

        Returns:
            搜索结果列表，每项包含 note_id 和 score
        """
        if not self.bm25 or not self.documents:
            return []

        try:
            # 分词
            query_tokens = self._tokenize(query)
            if not query_tokens:
                return []

            # 确定候选文档范围：若指定类型，先按类型过滤
            candidate_indices = range(len(self.documents))
            if note_type:
                candidate_indices = [
                    i for i, doc_type in enumerate(self.doc_types) if doc_type == note_type
                ]
                if not candidate_indices:
                    return []

            # BM25 搜索（仅在候选文档范围内）
            scores = self.bm25.get_scores(query_tokens)

            # 获取 top_k 结果
            top_indices = sorted(
                candidate_indices,
                key=lambda i: scores[i],
                reverse=True,
            )[:top_k]

            results = []
            for idx in top_indices:
                # BM25 分数可能为负，只要大于最小值就返回
                if scores[idx] > -10:  # 使用合理的阈值
                    results.append(
                        {
                            "note_id": self.doc_ids[idx],
                            "score": float(scores[idx]),
                        }
                    )

            return results

        except Exception as e:
            logger.error(f"BM25 search failed: {e}")
            return []

    def rebuild_from_notes(self, notes: List) -> bool:
        """
        从笔记列表全量重建索引

        重建过程是原子的：先在临时变量中构建新索引，成功后再替换当前状态；
        任何步骤失败都会恢复到重建前的状态。

        Args:
            notes: Note 对象列表

        Returns:
            是否成功重建
        """
        # 快照当前状态，失败时恢复
        saved_bm25 = self.bm25
        saved_documents = list(self.documents)
        saved_ids = list(self.doc_ids)
        saved_types = list(self.doc_types)
        saved_mapping = dict(self.doc_mapping)
        saved_needs_rebuild = self.needs_rebuild
        saved_dirty_full_rebuild = self._dirty_full_rebuild

        try:
            # 在局部变量中构建新索引
            new_documents: List[str] = []
            new_ids: List[str] = []
            new_types: List[Optional[str]] = []
            new_mapping: Dict[str, int] = {}

            for note in notes:
                # 组合标题和内容
                content = f"{note.title} {note.content}"
                tokens = self._tokenize(content)

                if tokens:
                    idx = len(new_documents)
                    new_documents.append(tokens)
                    new_ids.append(note.id)
                    new_types.append(self._normalize_note_type(note.type))
                    new_mapping[note.id] = idx

            # 原子替换当前状态
            self.documents = new_documents
            self.doc_ids = new_ids
            self.doc_types = new_types
            self.doc_mapping = new_mapping
            if self.documents:
                self.bm25 = BM25Okapi(self.documents)
            else:
                self.bm25 = None

            # 重建成功，清除 needs_rebuild 标志后再保存
            self.needs_rebuild = False

            # rebuild 语义=以本次快照为准：save 时即便磁盘较新也直接覆盖，不做 merge
            self._dirty_full_rebuild = True
            self._pending_ops.clear()

            # 保存，失败则回滚
            if not self._save():
                raise RuntimeError("Failed to persist BM25 index after rebuild")

            logger.info(f"Rebuilt BM25 index from {len(notes)} notes")
            return True

        except Exception as e:
            logger.error(f"Failed to rebuild BM25 index: {e}")
            # 恢复到重建前的状态
            self.bm25 = saved_bm25
            self.documents = saved_documents
            self.doc_ids = saved_ids
            self.doc_types = saved_types
            self.doc_mapping = saved_mapping
            self.needs_rebuild = saved_needs_rebuild
            self._dirty_full_rebuild = saved_dirty_full_rebuild
            return False

    def get_stats(self) -> Dict:
        """
        获取索引统计信息

        Returns:
            统计信息字典
        """
        return {
            "indexed": len(self.doc_ids),
            "version": self.INDEX_VERSION,
            "index_path": str(self.index_path),
            "index_exists": self.index_path.exists(),
        }

    def clear(self) -> bool:
        """
        清空索引

        Returns:
            是否成功清空
        """
        try:
            self._reset()

            # 删除文件
            if self.index_path.exists():
                self.index_path.unlink()
            if self.metadata_path.exists():
                self.metadata_path.unlink()

            logger.info("Cleared BM25 index")
            return True

        except Exception as e:
            logger.error(f"Failed to clear BM25 index: {e}")
            return False


# 全局索引实例
_bm25_index: Optional[BM25Index] = None


def get_bm25_index() -> BM25Index:
    """
    获取 BM25 索引实例（单例模式）

    Returns:
        BM25Index 实例
    """
    global _bm25_index
    if _bm25_index is None:
        _bm25_index = BM25Index()
    return _bm25_index


def reset_bm25_index():
    """重置全局索引实例（用于切换知识库时）"""
    global _bm25_index
    _bm25_index = None
