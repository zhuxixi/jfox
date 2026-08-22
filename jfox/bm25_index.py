"""
BM25 索引模块

提供基于 BM25 算法的关键词搜索功能，支持索引持久化和增量更新。
"""

import json
import logging
import os
import pickle
import re
import threading
import time
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
        self.documents: List[List[str]] = []  # 分词后的文档列表（每个文档为 token 列表）
        self.doc_ids: List[str] = []  # 文档 ID 列表
        self.doc_types: List[Optional[str]] = []  # 文档类型列表
        self.doc_mapping: Dict[str, int] = {}  # note_id -> index
        self.needs_rebuild: bool = False  # 是否需要全量重建以回填元数据
        self._loaded_write_version: int = 0  # load 时记录的磁盘写入版本（乐观锁令牌）
        self._pending_ops: List[Tuple[str, str, str, Optional[str]]] = []  # 未落盘的增量操作
        self._dirty_full_rebuild: bool = False  # rebuild 后 save 走覆盖语义
        self.load_status: str = "missing"
        self.load_error: Optional[str] = None
        self._mem_lock = threading.RLock()  # 进程内内存状态锁（filelock 只串行化进程间写）
        # 权衡：写路径全程持锁执行 _save（含文件锁等待+pickle+fsync，慢盘可达数秒），
        # 会阻塞同进程 search/get_stats——换取状态一致性；daemon 查询延迟尖峰属已知取舍（#396 issue-6）

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

    def _set_load_status(self, status: str, error: Optional[str] = None) -> None:
        """Record the last disk-load outcome for read-only diagnostics."""
        self.load_status = status
        self.load_error = error

    def _load(self) -> bool:
        """
        从磁盘加载索引（事务式）

        全部加载与校验先在局部变量完成，成功才提交到实例；任何一步失败
        self 保持不变（防止失败路径毒化实例后，后续 save 用空/旧状态覆盖磁盘）。

        Returns:
            是否成功加载
        """
        try:
            index_exists = self.index_path.exists()
            metadata_exists = self.metadata_path.exists()
            if not index_exists or not metadata_exists:
                status = "missing"
                error = "BM25 index files are missing"
                self._set_load_status(status, error)
                logger.info("BM25 index not found, will create new index")
                return False

            # 加载元数据
            with open(self.metadata_path, "r", encoding="utf-8") as f:
                metadata = json.load(f)

            # 磁盘写入版本（乐观锁令牌）；旧格式无此字段视为 0
            write_version = int(metadata.get("write_version") or 0)

            # 检查版本，支持从 v1 迁移到 v2
            version = metadata.get("version")
            if version not in (1, self.INDEX_VERSION):
                error = f"BM25 index version mismatch: {version} != {self.INDEX_VERSION}"
                self._set_load_status("invalid", error)
                logger.warning(error)
                return False

            # 加载索引
            with open(self.index_path, "rb") as f:
                index_data = pickle.load(f)

            bm25 = index_data["bm25"]
            documents = index_data["documents"]
            doc_ids = index_data["doc_ids"]
            doc_mapping = index_data["doc_mapping"]

            # pkl 内嵌写入版本（v1 起存在，与 metadata 中 write_version 同源）：
            # 用于半提交自愈——pkl 先写、metadata 后写，若 metadata 替换失败，
            # 磁盘上会出现「pkl 版本 > metadata 版本」的残留，以此检测并采纳新数据。
            pkl_write_version = int(index_data.get("write_version") or 0)

            # v1/v2 索引若缺失 doc_types，需要全量重建来回填类型元数据
            loaded_doc_types = index_data.get("doc_types")
            needs_backfill = loaded_doc_types is None
            if needs_backfill:
                doc_types: List[Optional[str]] = [None] * len(doc_ids)
            else:
                # 校验 doc_types 必须是 list（支持 append 等可变操作）
                if not isinstance(loaded_doc_types, list):
                    error = f"BM25 index doc_types is not a list: {type(loaded_doc_types)}"
                    self._set_load_status("invalid", error)
                    logger.error(error)
                    return False
                doc_types = loaded_doc_types

            # 校验核心数据结构长度一致且映射有效，防止持久化损坏导致错位
            expected_len = len(doc_ids)
            if not (
                len(documents) == expected_len
                and len(doc_types) == expected_len
                and len(doc_mapping) == expected_len
            ):
                error = (
                    "BM25 index data length mismatch: "
                    f"documents={len(documents)}, doc_ids={expected_len}, "
                    f"doc_types={len(doc_types)}, doc_mapping={len(doc_mapping)}"
                )
                self._set_load_status("invalid", error)
                logger.error(error)
                return False

            # 校验 doc_mapping 与 doc_ids 一一对应，且索引值在有效范围内
            for idx, note_id in enumerate(doc_ids):
                if doc_mapping.get(note_id) != idx:
                    error = (
                        f"BM25 index mapping corrupted: note_id={note_id}, "
                        f"expected_idx={idx}, got={doc_mapping.get(note_id)}"
                    )
                    self._set_load_status("invalid", error)
                    logger.error(error)
                    return False

            # 校验 doc_types 元素类型
            if not all(dt is None or isinstance(dt, str) for dt in doc_types):
                error = "BM25 index doc_types contains invalid element types"
                self._set_load_status("invalid", error)
                logger.error(error)
                return False

            # 校验 bm25 实例有效
            if bm25 is None and expected_len > 0:
                error = "BM25 index corrupted: bm25 is None but documents exist"
                self._set_load_status("invalid", error)
                logger.error(error)
                return False

            # 全部校验通过，一次性提交到实例
            self.bm25 = bm25
            self.documents = documents
            self.doc_ids = doc_ids
            self.doc_types = doc_types
            self.doc_mapping = doc_mapping
            # 以 pkl 与 metadata 中较新者为准：pkl 较新 = 上次写 metadata 的半提交残留，自愈采纳
            if pkl_write_version > write_version:
                logger.warning(
                    f"BM25 半提交自愈：pkl 版本 {pkl_write_version} > metadata 版本 "
                    f"{write_version}（上次写 metadata 失败），采纳 pkl 数据"
                )
            self._loaded_write_version = max(pkl_write_version, write_version)
            # 缺失 doc_types 或 metadata 标记需要重建的索引，触发全量重建回填类型元数据
            self.needs_rebuild = needs_backfill or bool(metadata.get("needs_rebuild"))
            if self.needs_rebuild:
                logger.info("Loaded BM25 index needs rebuild to backfill doc_types")

            self._set_load_status("loaded")
            logger.info(f"Loaded BM25 index: {len(self.doc_ids)} documents")
            return True

        except Exception as e:
            error = f"{type(e).__name__}: {e}"
            self._set_load_status("invalid", error)
            logger.error(f"Failed to load BM25 index: {e}")
            return False

    def _read_disk_write_version(self) -> int:
        """读磁盘 metadata 的 write_version；损坏/缺失视为 0（异常留痕便于追踪）"""
        try:
            with open(self.metadata_path, "r", encoding="utf-8") as f:
                return int(json.load(f).get("write_version") or 0)
        except (OSError, json.JSONDecodeError, ValueError, TypeError, AttributeError) as e:
            logger.warning(f"Failed to read BM25 metadata write_version ({e}), treat as 0")
            return 0

    def _read_pkl_write_version(self) -> int:
        """读 pkl 内嵌 write_version；失败视为 0。

        仅异常态使用（孤儿 tmp 无效时覆盖分支规避撞号），全量 unpickle 成本
        在罕见异常路径下可接受。不采纳数据，只取版本号（#403）。
        """
        try:
            with open(self.index_path, "rb") as f:
                return int(pickle.load(f).get("write_version") or 0)
        except (
            OSError,
            pickle.UnpicklingError,
            EOFError,
            AttributeError,
            TypeError,
            ValueError,
        ) as e:
            logger.warning(f"Failed to read BM25 pkl write_version: {e}")
            return 0

    @property
    def _metadata_tmp_path(self) -> Path:
        return self.metadata_path.with_suffix(self.metadata_path.suffix + ".tmp")

    def _disk_has_orphan_pkl(self) -> bool:
        """检测半提交孤儿：pkl 已原子落盘、metadata 提交未完成。

        写序设计为 metadata.tmp → pkl(replace) → metadata.tmp(replace)，
        故「metadata.tmp 存在」= 上次写在 pkl 落盘后、metadata 提交前中断。
        相比 mtime 启发式：零成本、旧格式文件不误判。
        注意并非绝对精确——tmp 写成功后、pkl 替换前中断同样残留 tmp（数据未落盘的
        假阳），但触发动作是保守 reload（幂等），代价可接受。
        """
        return self._metadata_tmp_path.exists()

    def _atomic_write_bytes(self, path: Path, data: bytes) -> None:
        """原子写：写临时文件 → fsync → os.replace，读端永远只能读到完整文件。

        写后 fsync 保证断电/内核崩溃下数据块先于 rename 持久化；os.replace 撞上
        Windows 读窗口的瞬时 sharing violation 时重试（读端短窗，毫秒级瞬态）。
        """
        tmp = path.with_suffix(path.suffix + ".tmp")
        try:
            with open(tmp, "wb") as f:
                f.write(data)
                f.flush()
                os.fsync(f.fileno())
            self._replace_with_retry(tmp, path)
        finally:
            if tmp.exists():
                try:
                    tmp.unlink()
                except OSError:
                    pass

    @staticmethod
    def _replace_with_retry(tmp: Path, path: Path) -> None:
        """os.replace 带重试：Windows 读端无锁短窗打开目标文件时 sharing violation 为瞬态。

        重试预算 ~3.75s（0.25/0.5/1/2）：覆盖读端 unpickle 大索引（万级笔记）的打开窗口。
        """
        last_exc: Optional[BaseException] = None
        delays = (0.25, 0.5, 1.0, 2.0)
        for delay in delays:
            try:
                os.replace(tmp, path)
                return
            except PermissionError as e:
                last_exc = e
                time.sleep(delay)
        raise last_exc  # type: ignore[misc]

    @staticmethod
    def _fsync_dir(path: Path) -> None:
        """对父目录 fsync：保证 os.replace 的目录项持久化（断电/内核崩溃）。

        不支持目录 fsync 的平台（Windows）静默降级。
        """
        try:
            fd = os.open(path, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass

    def _save(self) -> bool:
        """
        保存索引到磁盘（乐观并发控制版）

        流程：拿文件锁 → 比对磁盘 write_version（含半提交孤儿 tmp 哨兵检测）→
        磁盘较新则 reload+重放本地增量 → 原子写 pkl → 原子写 metadata（commit point）。
        铁律：任何一步失败都不写盘，返回 False。

        Returns:
            是否成功保存
        """
        try:
            # 确保目录存在
            self.index_dir.mkdir(parents=True, exist_ok=True)

            with FileLock(
                str(self.index_dir / self.LOCK_FILENAME), timeout=30
            ):  # 大索引 pickle+fsync 在慢盘上可达数秒，5s 会误伤合法慢写（#396 issue-8）
                disk_version = self._read_disk_write_version()
                orphan_pkl = self._disk_has_orphan_pkl()
                stale = disk_version > self._loaded_write_version or (
                    # 半提交孤儿：pkl 已先落盘、metadata 未提交（或提交失败回退旧版本）。
                    # metadata 版本相等或较旧时快路径都会用本地内存覆写孤儿数据
                    # （#396 issue-16；「较旧」分支的复活窗口见 #404 CR issue-1）
                    # → 强制 reload 采纳较新 pkl 并重放 pending，良性等价情形结果不变
                    disk_version <= self._loaded_write_version
                    and orphan_pkl
                )
                if stale and not self._dirty_full_rebuild:
                    if orphan_pkl and disk_version == self._loaded_write_version:
                        logger.warning(
                            "BM25 检测到半提交孤儿 pkl（metadata.tmp 残留），reload 采纳后合并写入"
                        )
                    if not self._load():
                        if not self.metadata_path.exists():
                            # metadata 缺失（首次建索引崩溃单边态）：先试恢复——tmp 里可能
                            # 正是与 pkl 匹配的完整 metadata（写者中断在 tmp→metadata 前），
                            # 持锁提升后可零成本恢复全部数据（#401 reviewer Note 2）；
                            # tmp 无效或无 tmp 时才放弃 pkl 单边数据按内存写（可 rebuild 恢复）
                            self._commit_orphan_tmp(_already_holding_lock=True)
                            if self._load():
                                logger.warning("BM25 单边态经 tmp 提升恢复，合并写入")
                                self._replay_pending_ops()
                            else:
                                logger.warning(
                                    "BM25 孤儿 tmp 残留且 metadata 缺失，清理 tmp 后按内存状态写入"
                                )
                                self._metadata_tmp_path.unlink(missing_ok=True)
                        else:
                            logger.error("BM25 磁盘版本较新但 reload 失败，放弃本次 save（不写盘）")
                            return False
                    else:
                        self._replay_pending_ops()
                elif self._dirty_full_rebuild and (
                    orphan_pkl or disk_version > self._loaded_write_version
                ):
                    # rebuild/clear 覆盖语义：以本地快照为准，覆盖较新的磁盘状态。
                    # 关键：覆盖前先消费孤儿 tmp 并重读磁盘版本——否则 new_version 按陈旧
                    # metadata 算出 N+1，恰与孤儿 pkl 未提交版本 N+1 撞号，已自愈加载孤儿
                    # 的进程会快路径写回旧数据（清空被复活，#402 pi-cr r1-A）
                    if orphan_pkl:
                        promoted = self._commit_orphan_tmp(_already_holding_lock=True)
                        disk_version = self._read_disk_write_version()
                        if not promoted:
                            # tmp 无效被丢弃（或 pkl 缺失不提升）：孤儿 pkl 内嵌版本
                            # 未纳入 metadata，new_version 会与其撞号（清空被复活，
                            # #403）→ 读 pkl 内嵌版本垫高基数，不采纳其数据
                            pkl_version = self._read_pkl_write_version()
                            disk_version = max(disk_version, pkl_version)
                    relation = (
                        "新"
                        if disk_version > self._loaded_write_version
                        else ("旧" if disk_version < self._loaded_write_version else "持平")
                    )
                    loss_note = (
                        "，其间其他进程的写入将丢失"
                        if relation == "新"
                        else "（孤儿 tmp 消费后版本持平/更旧，无其他进程写入丢失）"
                    )
                    logger.warning(
                        f"BM25 rebuild/clear 覆盖：磁盘版本 {disk_version} 比本地 "
                        f"{self._loaded_write_version} {relation}，按本地快照覆盖{loss_note}"
                    )
                elif disk_version < self._loaded_write_version:
                    logger.warning(
                        f"BM25 磁盘版本 {disk_version} 比本地 "
                        f"{self._loaded_write_version} 旧，按本地覆盖"
                    )

                new_version = max(disk_version, self._loaded_write_version) + 1
                prev_version = self._loaded_write_version

                # 写序：metadata.tmp（不 replace）→ pkl 原子替换 → metadata.tmp 替换。
                # metadata.tmp 的存在即「pkl 已写、metadata 未提交」的孤儿信号（精确判定）。
                # 版本号上涨一定意味着 pkl 已完整落盘（metadata 作 commit point）。
                metadata = {
                    "version": self.INDEX_VERSION,
                    "doc_count": len(self.doc_ids),
                    "needs_rebuild": self.needs_rebuild,
                    "write_version": new_version,
                }
                with open(self._metadata_tmp_path, "w", encoding="utf-8") as f:
                    f.write(json.dumps(metadata, ensure_ascii=False, indent=2))
                    f.flush()
                    os.fsync(f.fileno())
                index_data = {
                    "bm25": self.bm25,
                    "documents": self.documents,
                    "doc_ids": self.doc_ids,
                    "doc_types": self.doc_types,
                    "doc_mapping": self.doc_mapping,
                    "write_version": new_version,
                }
                self._atomic_write_bytes(self.index_path, pickle.dumps(index_data))
                self._replace_with_retry(self._metadata_tmp_path, self.metadata_path)
                # issue-5：父目录 fsync，保证两次 rename 的目录项断电持久化
                self._fsync_dir(self.index_dir)

                self._loaded_write_version = new_version
                self._pending_ops.clear()
                self._dirty_full_rebuild = False
                logger.info(
                    f"Saved BM25 index: {len(self.doc_ids)} documents "
                    f"(write_version={new_version}, prev={prev_version})"
                )
                return True
        except Timeout:
            logger.error("BM25 save: 获取索引文件锁超时（30s），放弃写入")
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
        """重放本地未落盘的增量操作：同 id 合并（只留最后 op）后按序 apply。

        注意 stale-replay 窗口（并发 CRUD 的 LWW 终局语义）：本进程若在 save 失败后
        长期持有过期内存，其 pending 中记录的内容可能已陈旧于其他进程在此期间提交的
        同 id 更新——重放会以陈旧内容覆盖较新磁盘数据。这是乐观并发下 last-writer-wins
        的固有取舍（见 spec §8 风险段），非数据损坏。
        """
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

        失败语义：返回 False 表示「本次修改未落盘」——内存变更与 pending 记录保留，
        待下次 save 重放兜底；成功返回 True 表示已落盘。

        Args:
            note_id: 笔记 ID
            content: 笔记内容
            note_type: 笔记类型（可选）

        Returns:
            是否成功添加（并落盘）
        """
        with self._mem_lock:
            try:
                if not self._tokenize(content):
                    # 空内容：不存在 id 静默成功；已存在 id 等价于移除（旧语义），
                    # 透传 remove 的落盘结果（锁超时/写失败时调用方能感知）
                    if note_id in self.doc_mapping:
                        return self.remove_document(note_id)
                    return True
                self._add_document_local(note_id, content, note_type)
                self._pending_ops.append(("add", note_id, content, note_type))

                # 重建索引
                self._rebuild_index()

                # 保存（透传结果：锁超时/写失败时调用方能感知索引未落盘）
                return self._save()

            except Exception as e:
                logger.error(f"Failed to add document {note_id}: {e}")
                return False

    def remove_document(self, note_id: str) -> bool:
        """
        从索引中移除文档

        失败语义同 add_document：False 表示未落盘（内存变更与 pending 保留待重放）。

        Args:
            note_id: 笔记 ID

        Returns:
            是否成功移除
        """
        with self._mem_lock:
            try:
                if note_id not in self.doc_mapping:
                    return True

                self._remove_document_local(note_id)
                self._pending_ops.append(("remove", note_id, "", None))

                # 重建索引
                self._rebuild_index()

                # 保存（透传结果）
                return self._save()

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

        失败语义与 add_document 不同：save 失败时**回滚**内存与 pending 到批次前快照
        （批量操作的半成品对调用方无意义）；add/remove 单条路径则保留待重放。
        极端 IO 失败下（pkl 已原子落盘、metadata 提交失败）磁盘可能残留孤儿 pkl，
        由版本自愈（tmp 哨兵检测 + max 采纳）接住，见 _save 与 check_stale_and_reload。

        Args:
            documents: [(note_id, content), ...] 或 [(note_id, content, note_type), ...] 列表

        Returns:
            是否成功添加
        """
        if not documents:
            return True

        with self._mem_lock:
            try:
                # 快照当前状态，失败时恢复（回滚必须在锁内执行，防半回滚状态被并发读）
                saved_docs = list(self.documents)
                saved_ids = list(self.doc_ids)
                saved_types = list(self.doc_types)
                saved_mapping = dict(self.doc_mapping)
                saved_bm25 = self.bm25
                saved_pending_len = len(self._pending_ops)
                saved_needs_rebuild = self.needs_rebuild
                saved_loaded_version = self._loaded_write_version

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
                        # 已存在 id 的内联移除已发生：记 pending 保持重放一致性
                        # （重放时 _add_document_local 对空 tokens 同样先移除后跳过）
                        self._pending_ops.append(("add", note_id, content, note_type))
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
                    raise RuntimeError("BM25 batch save failed")

                logger.info(f"Batch added {len(documents)} documents to BM25 index")
                return True

            except Exception:
                # 恢复到批次前的状态（锁内执行）
                self.documents = saved_docs
                self.doc_ids = saved_ids
                self.doc_types = saved_types
                self.doc_mapping = saved_mapping
                self.bm25 = saved_bm25
                self.needs_rebuild = saved_needs_rebuild
                # 乐观锁令牌一并回退：merge 分支的 _load 可能已把令牌推进到磁盘版本，
                # 不回退则下次 save 走「磁盘==本地」快路径，用旧内存覆盖磁盘（#396 issue-1）
                self._loaded_write_version = saved_loaded_version
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
        with self._mem_lock:
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
        with self._mem_lock:
            # 快照当前状态，失败时恢复（快照必须持锁读取，防与写路径交错）
            saved_bm25 = self.bm25
            saved_documents = list(self.documents)
            saved_ids = list(self.doc_ids)
            saved_types = list(self.doc_types)
            saved_mapping = dict(self.doc_mapping)
            saved_needs_rebuild = self.needs_rebuild
            saved_dirty_full_rebuild = self._dirty_full_rebuild
            saved_pending_ops = list(self._pending_ops)
            saved_loaded_version = self._loaded_write_version

            try:
                # 在局部变量中构建新索引
                new_documents: List[List[str]] = []
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
                # 恢复到重建前的状态（锁内执行）
                self.bm25 = saved_bm25
                self.documents = saved_documents
                self.doc_ids = saved_ids
                self.doc_types = saved_types
                self.doc_mapping = saved_mapping
                self.needs_rebuild = saved_needs_rebuild
                self._dirty_full_rebuild = saved_dirty_full_rebuild
                self._pending_ops = saved_pending_ops
                self._loaded_write_version = saved_loaded_version
                return False

    def _validate_metadata_tmp(self) -> bool:
        """校验孤儿 tmp 内容是否为可安全提升的完整 metadata。

        防「读路径污染」：tmp 截断/垃圾（写者崩溃在 fsync 前、磁盘满）时提升会把
        有效 metadata 覆盖为垃圾，导致索引不可读（#402 pi-cr r1-B）。
        """
        try:
            with open(self._metadata_tmp_path, "r", encoding="utf-8") as f:
                meta = json.load(f)
            return (
                isinstance(meta, dict)
                and meta.get("version") in (1, self.INDEX_VERSION)
                and isinstance(meta.get("write_version"), int)
                and meta["write_version"] >= 0
            )
        except (OSError, json.JSONDecodeError, ValueError):
            return False

    def _commit_orphan_tmp(self, *, _already_holding_lock: bool = False) -> bool:
        """只读路径消费孤儿 tmp：持 filelock 确认无在途写者后，把 tmp 提升为正式 metadata。

        写者的 commit 流程是 metadata.tmp → pkl(replace) → metadata.tmp(replace)，
        中断后 tmp 残留；读路径拿锁成功 = 无在途写者（否则锁被占用），可安全补完
        最后一步提交。timeout=0 纯尝试（拿不到 = 在途写者活跃的窗口期假阳，跳过）——
        不阻塞查询路径（#401 reviewer Note 3）。

        提升前两重防护（#402 pi-cr r1-B/D）：
        - tmp 内容校验：无效/截断的 tmp unlink 而非 replace（防污染 metadata）；
        - pkl 必须已落盘：写者崩在 pkl 替换前时提升会造成「metadata 在、pkl 缺」的
          永久失败态——此时不提升，留给写路径自愈。

        _already_holding_lock=True：调用方（_save）已持锁，自己就是在途写者，
        直接操作——同线程第二个 FileLock 实例永远拿不到锁（filelock 可重入仅限
        同一实例），不能在 _save 内走常规拿锁路径。

        Returns:
            是否成功提升（供调用方决定后续重读版本）
        """
        if not self._metadata_tmp_path.exists():
            return False

        def _promote_locked() -> bool:
            if not self.index_path.exists():
                # pkl 未落盘（写者崩在 pkl 替换前）：不提升，留给写路径自愈（#402 r1-D）
                logger.warning("BM25 孤儿 tmp 伴随 pkl 缺失，不提升（留给写路径自愈）")
                return False
            if not self._validate_metadata_tmp():
                # 无效 tmp：unlink 防读路径污染有效 metadata（#402 r1-B）
                logger.warning("BM25 孤儿 tmp 内容无效，丢弃（unlink）")
                try:
                    self._metadata_tmp_path.unlink()
                except OSError as e:
                    logger.warning(f"BM25 丢弃无效 tmp 失败: {e}")
                return False
            self._replace_with_retry(self._metadata_tmp_path, self.metadata_path)
            self._fsync_dir(self.index_dir)
            logger.info("BM25 孤儿 tmp 已提升为正式 metadata（消费）")
            return True

        if _already_holding_lock:
            try:
                return _promote_locked()
            except OSError as e:
                logger.warning(f"BM25 消费孤儿 tmp 失败: {e}")
                return False
        try:
            with FileLock(str(self.index_dir / self.LOCK_FILENAME), timeout=0):
                return _promote_locked()
        except Timeout:
            return False
        except OSError as e:
            logger.warning(f"BM25 消费孤儿 tmp 失败（下次重试）: {e}")
            return False

    def check_stale_and_reload(self) -> None:
        """轻量 stale 检查：磁盘 write_version 比内存新（或存在孤儿 tmp）就 reload。

        用于长驻进程（daemon）的查询路径，避免搜索长期基于过期快照。
        采纳孤儿 tmp 后会持 filelock 补完提交（消费 tmp），避免真孤儿期间每次检查
        都重复全量 unpickle。失败兜底（用内存快照继续服务），留 warning 便于诊断。
        """
        try:
            with self._mem_lock:
                if (
                    self._read_disk_write_version() > self._loaded_write_version
                    or self._disk_has_orphan_pkl()
                ):
                    if self._load() and self._pending_ops:
                        # reload 会整体替换内存：重放未落盘的本地增量，防止丢失
                        self._replay_pending_ops()
                    # 消费孤儿 tmp（持锁补完 commit），否则真孤儿期间每次检查都全量 reload（#401 issue-21）
                    self._commit_orphan_tmp()
        except Exception as e:
            logger.warning(f"BM25 stale 检查失败（用内存快照兜底）: {e}")

    def get_stats(self) -> Dict:
        """
        获取索引统计信息

        Returns:
            统计信息字典
        """
        with self._mem_lock:
            return {
                "indexed": len(self.doc_ids),
                "version": self.INDEX_VERSION,
                "index_path": str(self.index_path),
                "index_exists": self.index_path.exists(),
            }

    def clear(self) -> bool:
        """清空索引：写空快照并递增 write_version（纳入乐观锁体系）。

        相比删文件：其他进程后续 save 看到更高版本走 merge 采纳空索引，不会用
        旧内存复活已清空数据；无 unlink，无 Windows 占用导致的中间态。
        全程在 _mem_lock + _save 的 filelock 内执行（#401 issue-20）。
        失败语义：save 失败时回滚内存快照（同 rebuild_from_notes），防「内存已清
        + dirty 标志残留」导致后续 add 走覆盖分支静默抹掉他进程数据。

        Returns:
            是否成功清空
        """
        with self._mem_lock:
            # 快照当前状态，失败时恢复
            saved_bm25 = self.bm25
            saved_documents = list(self.documents)
            saved_ids = list(self.doc_ids)
            saved_types = list(self.doc_types)
            saved_mapping = dict(self.doc_mapping)
            saved_pending_ops = list(self._pending_ops)
            saved_dirty_full_rebuild = self._dirty_full_rebuild
            saved_needs_rebuild = self.needs_rebuild
            saved_loaded_version = self._loaded_write_version

            self._reset()
            self._pending_ops.clear()
            # 覆盖语义：clear 以本地空快照为准（stale 时直接覆盖并记 warning）
            self._dirty_full_rebuild = True
            if self._save():
                return True
            if self._disk_has_orphan_pkl():
                # save 半途而废但磁盘残留 clear 的半提交（空 pkl 高版本 + tmp）：
                # 不回滚内存——旧数据内存下次 save 会被孤儿采纳逻辑复活到空索引上
                # （实测复现，#402 pi-cr r1-E）；保持清空态 + dirty，下次 save 覆盖重写
                logger.error(
                    "BM25 clear: save 失败且磁盘残留半提交空快照，保持清空态待下次覆盖重写"
                )
                return False
            # save 失败且无磁盘残留：回滚内存快照，防「内存已清+dirty 残留」的静默覆盖路径
            self.bm25 = saved_bm25
            self.documents = saved_documents
            self.doc_ids = saved_ids
            self.doc_types = saved_types
            self.doc_mapping = saved_mapping
            self._pending_ops = saved_pending_ops
            self._dirty_full_rebuild = saved_dirty_full_rebuild
            self.needs_rebuild = saved_needs_rebuild
            self._loaded_write_version = saved_loaded_version
            logger.error("BM25 clear: save 失败，已回滚内存快照")
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
