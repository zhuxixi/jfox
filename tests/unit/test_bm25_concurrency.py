"""
BM25Index 并发写防护（#391）单元测试

用两个共享同一索引目录的 BM25Index 实例模拟 CLI 与 daemon 两个进程的交错写。
"""

import json
import pickle
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from filelock import Timeout

from jfox.bm25_index import BM25Index
from jfox.models import Note, NoteType


def _note(nid: str, ntype: NoteType = NoteType.PERMANENT) -> Note:
    return Note(
        id=nid,
        title=f"title {nid}",
        type=ntype,
        content=f"content {nid}",
        created=datetime.now(),
        updated=datetime.now(),
    )


def _load_disk_ids(index_dir: Path) -> list:
    with open(index_dir / BM25Index.INDEX_FILENAME, "rb") as f:
        return pickle.load(f)["doc_ids"]


def _disk_version(index_dir: Path) -> int:
    with open(index_dir / BM25Index.METADATA_FILENAME, "r", encoding="utf-8") as f:
        return json.load(f).get("write_version", 0)


class TestWriteVersionAndLock:
    """write_version 元数据、原子写、文件锁"""

    def test_write_version_increments(self, tmp_path):
        idx = BM25Index(index_dir=tmp_path)
        assert idx.add_document("a", "hello world", "session")
        assert idx.add_document("b", "foo bar", "session")
        assert _disk_version(tmp_path) == 2
        meta = json.loads((tmp_path / BM25Index.METADATA_FILENAME).read_text(encoding="utf-8"))
        assert meta["doc_count"] == 2
        assert meta["write_version"] == 2

    def test_legacy_metadata_without_version(self, tmp_path):
        idx = BM25Index(index_dir=tmp_path)
        assert idx.add_document("a", "hello world", "session")
        # 抹掉 metadata 与 pkl 里的 write_version 模拟旧格式文件
        meta_path = tmp_path / BM25Index.METADATA_FILENAME
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta.pop("write_version", None)
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        pkl_path = tmp_path / BM25Index.INDEX_FILENAME
        data = pickle.loads(pkl_path.read_bytes())
        data.pop("write_version", None)
        pkl_path.write_bytes(pickle.dumps(data))
        idx2 = BM25Index(index_dir=tmp_path)
        assert idx2._loaded_write_version == 0
        assert "a" in idx2.doc_mapping
        assert idx2.add_document("b", "foo bar", "session")
        assert _disk_version(tmp_path) >= 1

    def test_lock_timeout_aborts_save_without_writing(self, tmp_path):
        idx = BM25Index(index_dir=tmp_path)
        with patch("jfox.bm25_index.FileLock") as mock_lock_cls:
            mock_lock_cls.return_value.__enter__.side_effect = Timeout("bm25_index.lock")
            ok = idx._save()
        assert ok is False
        assert not (tmp_path / BM25Index.INDEX_FILENAME).exists()


class TestOptimisticMerge:
    """双实例模拟双进程：磁盘较新时 reload + 重放本地增量"""

    def test_concurrent_add_replay(self, tmp_path):
        a = BM25Index(index_dir=tmp_path)  # 模拟 daemon：先 load 旧状态
        b = BM25Index(index_dir=tmp_path)  # 模拟 CLI
        assert b.add_document("note-cli", "cli 写入 hello", "session")  # v1
        assert a.add_document("note-daemon", "daemon 写入 world", "session")  # merge → v2
        ids = _load_disk_ids(tmp_path)
        assert "note-cli" in ids
        assert "note-daemon" in ids
        assert _disk_version(tmp_path) == 2

    def test_concurrent_remove_replay(self, tmp_path):
        a = BM25Index(index_dir=tmp_path)
        assert a.add_document("x", "hello x", "permanent")  # v1
        b = BM25Index(index_dir=tmp_path)  # b load v1（含 x）
        assert b.add_document("y", "hello y", "permanent")  # v2
        assert a.remove_document("x")  # a：reload v2 + 重放 remove x → v3
        ids = _load_disk_ids(tmp_path)
        assert "y" in ids
        assert "x" not in ids
        assert _disk_version(tmp_path) == 3

    def test_conflict_last_writer_wins(self, tmp_path):
        a = BM25Index(index_dir=tmp_path)
        assert a.add_document("x", "from a", "session")  # v1
        b = BM25Index(index_dir=tmp_path)
        assert b.add_document("x", "from b", "session")  # v2
        assert a.remove_document("x")  # v3：重放 remove 覆盖 b 的 add
        assert "x" not in _load_disk_ids(tmp_path)

    def test_reload_failure_aborts_save_without_writing(self, tmp_path):
        a = BM25Index(index_dir=tmp_path)
        b = BM25Index(index_dir=tmp_path)
        assert b.add_document("x", "hello x", "session")  # v1
        # a 内存里产生未落盘的增量，然后破坏磁盘 pkl 使 reload 失败
        a._add_document_local("y", "local change", "session")
        a._pending_ops.append(("add", "y", "local change", "session"))
        corrupted = b"corrupted-pkl"
        (tmp_path / BM25Index.INDEX_FILENAME).write_bytes(corrupted)
        assert a._save() is False
        assert (tmp_path / BM25Index.INDEX_FILENAME).read_bytes() == corrupted


class TestRebuildSemantics:
    """rebuild 覆盖语义（stale 时不 merge）"""

    def test_rebuild_overwrites_stale_disk(self, tmp_path):
        a = BM25Index(index_dir=tmp_path)
        b = BM25Index(index_dir=tmp_path)
        assert b.add_document("old", "old note", "session")  # v1
        # a 内存是旧状态，但 rebuild 语义=以我的快照为准：直接覆盖，不 merge
        assert a.rebuild_from_notes([_note("n1"), _note("n2")])
        assert set(_load_disk_ids(tmp_path)) == {"n1", "n2"}


class TestStaleDetection:
    """读路径 stale 检测与刷新"""

    def test_check_stale_and_reload(self, tmp_path):
        a = BM25Index(index_dir=tmp_path)
        b = BM25Index(index_dir=tmp_path)
        assert b.add_document("x", "hello x", "session")  # v1
        assert "x" not in a.doc_mapping  # a 仍是旧内存
        a.check_stale_and_reload()
        assert "x" in a.doc_mapping

    def test_check_stale_and_reload_noop_when_fresh(self, tmp_path):
        a = BM25Index(index_dir=tmp_path)
        assert a.add_document("x", "hello x", "session")
        docs_before = list(a.documents)
        a.check_stale_and_reload()
        assert a.documents == docs_before  # 未发生 reload


import logging


class TestFailureRecovery:
    """B1：reload 失败不得毒化实例；N1：rebuild 覆盖须记 warning"""

    def test_failed_reload_does_not_poison_instance(self, tmp_path):
        a = BM25Index(index_dir=tmp_path)
        b = BM25Index(index_dir=tmp_path)
        assert b.add_document("x", "hello x", "session")  # v1
        pkl_path = tmp_path / BM25Index.INDEX_FILENAME
        good_bytes = pkl_path.read_bytes()
        # 磁盘 pkl 损坏 → a 的 save 失败且不写盘，实例不得被毒化
        pkl_path.write_bytes(b"corrupted")
        assert a.add_document("y", "local y", "session") is False
        assert pkl_path.read_bytes() == b"corrupted"
        # 磁盘恢复后，下一次 save 必须 reload + 重放 pending，而不是用旧/空内存覆盖
        pkl_path.write_bytes(good_bytes)
        assert a.add_document("z", "local z", "session") is True
        ids = _load_disk_ids(tmp_path)
        assert "x" in ids
        assert "y" in ids
        assert "z" in ids

    def test_rebuild_overwrite_logs_warning(self, tmp_path, caplog):
        a = BM25Index(index_dir=tmp_path)
        b = BM25Index(index_dir=tmp_path)
        assert b.add_document("old", "old note", "session")  # v1
        with caplog.at_level(logging.WARNING, logger="jfox.bm25_index"):
            assert a.rebuild_from_notes([_note("n1")])
        assert any("覆盖" in r.message for r in caplog.records)


class TestCrRound1Fixes:
    """cc bot round-1 修复回归（#396）：令牌回退、半提交自愈、空内容语义、注入参数副作用"""

    def test_batch_rollback_restores_version_token(self, tmp_path):
        """issue-1：batch save 失败回滚必须恢复乐观锁令牌，否则下次 save 走快路径覆盖磁盘"""
        a = BM25Index(index_dir=tmp_path)
        b = BM25Index(index_dir=tmp_path)
        assert b.add_document("x", "hello x", "session")  # v1（磁盘较新）
        # merge 分支 reload 会把令牌推进到 1，随后写盘失败 → 回滚必须恢复令牌
        with patch.object(a, "_atomic_write_bytes", side_effect=OSError("disk full")):
            assert a.add_documents_batch([("y", "hello y", "session")]) is False
        assert a._loaded_write_version == 0  # 令牌已回退（bug 时 =1）
        # 磁盘恢复后，下一次 save 必须走 merge（reload），而不是快路径覆盖
        assert a.add_document("z", "hello z", "session") is True
        ids = _load_disk_ids(tmp_path)
        assert "x" in ids
        assert "z" in ids

    def test_half_commit_pkl_version_self_heals(self, tmp_path):
        """issue-5：metadata 替换失败的半提交（pkl 新、版本旧）由 pkl 内嵌版本自愈"""
        idx = BM25Index(index_dir=tmp_path)
        assert idx.add_document("x", "hello x", "session")  # v1
        assert idx.add_document("y", "hello y", "session")  # v2（pkl 内嵌 v2）
        # 模拟半提交：metadata 停留 v1（其 os.replace 失败场景）
        meta_path = tmp_path / BM25Index.METADATA_FILENAME
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["write_version"] = 1
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        # 新实例 load：以 pkl 内嵌版本为准，数据与版本一致
        fresh = BM25Index(index_dir=tmp_path)
        assert fresh._loaded_write_version == 2
        assert "y" in fresh.doc_mapping
        # 下次 save 自愈 metadata 版本
        assert fresh.add_document("z", "hello z", "session")
        assert _disk_version(tmp_path) == 3

    def test_add_empty_content_keeps_legacy_semantics(self, tmp_path):
        """issue-11：空内容 add 恢复旧语义——不存在 id 恒 True 不落盘；已存在 id 仅移除"""
        idx = BM25Index(index_dir=tmp_path)
        assert idx.add_document("a", "hello", "session")  # v1
        assert idx.add_document("new-id", "", "session") is True
        assert _disk_version(tmp_path) == 1  # 未落盘（版本未涨）
        assert "new-id" not in idx.doc_mapping
        # 已存在 id + 空内容 = 移除（旧语义）
        assert idx.add_document("a", "", "session") is True
        assert "a" not in idx.doc_mapping
        assert _disk_version(tmp_path) == 2  # remove 落盘了一次

    def test_explicit_bm25_index_not_reloaded(self, tmp_path):
        """issue-12：显式传入 bm25_index 时构造器不得对其产生隐式 reload 副作用"""
        from unittest.mock import MagicMock

        from jfox.search_engine import HybridSearchEngine

        a = BM25Index(index_dir=tmp_path)
        b = BM25Index(index_dir=tmp_path)
        assert b.add_document("x", "hello x", "session")  # 磁盘 v1 较新
        engine = HybridSearchEngine(vector_store=MagicMock(), bm25_index=a)
        assert engine.bm25_index is a
        assert "x" not in a.doc_mapping  # a 未被刷新


class TestCrRound2Fixes:
    """cc bot round-2 修复回归（#396）：孤儿 tmp 哨兵检测、空内容透传"""

    def test_orphan_pkl_detected_by_tmp_marker(self, tmp_path):
        """issue-4/16：pkl 已落盘、metadata 未提交的孤儿由 metadata.tmp 信号精确检测"""
        idx = BM25Index(index_dir=tmp_path)
        assert idx.add_document("x", "hello x", "session")  # v1
        assert idx.add_document("y", "hello y", "session")  # v2 全落盘
        # 构造孤儿：metadata 回滚到 v1 + 留下 metadata.tmp（模拟提交前中断）
        meta_path = tmp_path / BM25Index.METADATA_FILENAME
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["write_version"] = 1
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        (tmp_path / "bm25_metadata.json.tmp").write_text("{}", encoding="utf-8")
        # 长驻写者视角：令牌=1（写 metadata 失败后未推进），磁盘版本比较判定「相等」
        daemon_view = BM25Index(index_dir=tmp_path)
        assert daemon_view._loaded_write_version == 2  # _load 已 max 采纳
        daemon_view._loaded_write_version = 1  # 模拟 metadata 提交失败后的内存令牌
        # tmp 信号检测必须发现孤儿 → reload 采纳 v2
        daemon_view.check_stale_and_reload()
        assert daemon_view._loaded_write_version == 2
        assert "y" in daemon_view.doc_mapping

    def test_empty_content_add_transparent_remove_result(self, tmp_path):
        """issue-17：空内容+已存在 id 透传 remove 的落盘结果"""
        idx = BM25Index(index_dir=tmp_path)
        assert idx.add_document("a", "hello", "session")  # v1
        # remove 落盘失败（锁超时）→ add 必须返回 False 而不是恒 True
        with patch("jfox.bm25_index.FileLock") as mock_lock_cls:
            mock_lock_cls.return_value.__enter__.side_effect = Timeout("bm25_index.lock")
            assert idx.add_document("a", "", "session") is False


class TestCrPiRound2Fixes:
    """pi-cr round-2 修复回归（#396）：孤儿 tmp + clear 自愈"""

    def test_clear_after_orphan_tmp_residue(self, tmp_path):
        """issue-9：metadata.tmp 残留 + clear() 后 save 不得永久失败"""
        idx = BM25Index(index_dir=tmp_path)
        assert idx.add_document("x", "hello x", "session")  # v1
        # 模拟「tmp 已写、metadata 未提交」的中断残留
        (tmp_path / "bm25_metadata.json.tmp").write_text("{}", encoding="utf-8")
        assert idx.clear()
        # clear 后 save 必须能成功（孤儿 tmp 不应让 save 永久失败）
        assert idx.add_document("y", "hello y", "session") is True
        assert (tmp_path / BM25Index.METADATA_FILENAME).exists()
        assert "y" in _load_disk_ids(tmp_path)

    def test_orphan_tmp_residue_self_heals_without_clear(self, tmp_path):
        """issue-9：clear() 之外的孤儿 tmp 残留路径——reload 采纳；tmp 由读路径持锁消费（#401）"""
        idx = BM25Index(index_dir=tmp_path)
        assert idx.add_document("x", "hello x", "session")  # v1
        assert idx.add_document("y", "hello y", "session")  # v2
        # 孤儿：metadata 回滚 v1 + tmp 残留
        meta_path = tmp_path / BM25Index.METADATA_FILENAME
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta["write_version"] = 1
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        (tmp_path / "bm25_metadata.json.tmp").write_text("{}", encoding="utf-8")
        daemon_view = BM25Index(index_dir=tmp_path)
        daemon_view._loaded_write_version = 1
        daemon_view.check_stale_and_reload()
        assert daemon_view._loaded_write_version == 2
        assert "y" in daemon_view.doc_mapping

    def test_orphan_tmp_self_heal_branch_direct(self, tmp_path, caplog):
        """issue-11：自愈分支直接覆盖——loaded=0 实例 + tmp 残留 + 磁盘双文件缺失 → 清理 tmp 后按内存写入"""
        import logging

        # 构造磁盘状态：tmp 残留，index/metadata 均缺失（不经 clear()，直达自愈分支）
        (tmp_path / "bm25_metadata.json.tmp").write_text("{}", encoding="utf-8")
        a = BM25Index(index_dir=tmp_path)  # loaded=0，内存空
        # stale 判定：disk_version(0)==loaded(0) 且 orphan(tmp 存在) → 孤儿分支 →
        # _load 失败（文件缺失）→ 自愈清理 tmp → 按内存写入
        with caplog.at_level(logging.WARNING, logger="jfox.bm25_index"):
            assert a.add_document("x", "hello x", "session") is True
        # 判别力落在「自愈分支确实走过」（warning 日志），而非 tmp 消失的通用结果（#401 issue-25）
        assert any(
            "孤儿 tmp" in r.message and "按内存状态写入" in r.message for r in caplog.records
        )
        assert (tmp_path / BM25Index.METADATA_FILENAME).exists()
        assert "x" in _load_disk_ids(tmp_path)


class TestIssue401Followup:
    """#401：cc round-4 遗留——clear 快照化 / 单边态自愈 / tmp 只读消费"""

    def test_clear_writes_empty_snapshot(self, tmp_path):
        """issue-20：clear() 写空快照（版本递增），文件保留"""
        a = BM25Index(index_dir=tmp_path)
        b = BM25Index(index_dir=tmp_path)
        assert b.add_document("x", "hello x", "session")  # v1
        assert a.add_document("daemon-pending", "daemon 内容", "session") is True  # merge → v2
        assert a.clear()
        meta = json.loads((tmp_path / BM25Index.METADATA_FILENAME).read_text(encoding="utf-8"))
        assert meta["doc_count"] == 0
        assert meta["write_version"] == 3
        assert _load_disk_ids(tmp_path) == []
        assert (tmp_path / BM25Index.INDEX_FILENAME).exists()  # 不删文件

    def test_clear_not_resurrected_by_other_process(self, tmp_path):
        """issue-20(b)：clear 后他进程（持旧令牌）的 save 走 merge 采纳空索引，不复活旧数据"""
        a = BM25Index(index_dir=tmp_path)
        assert a.add_document("x", "hello x", "session")  # v1
        b = BM25Index(index_dir=tmp_path)  # b load v1（含 x）
        c = BM25Index(index_dir=tmp_path)
        assert c.clear()  # v2 空快照
        assert b.add_document("y", "hello y", "session") is True
        ids = _load_disk_ids(tmp_path)
        assert "x" not in ids
        assert "y" in ids

    def test_orphan_metadata_missing_pkl_present_self_heals(self, tmp_path):
        """issue-24：pkl 存在、metadata 缺失、tmp 残留的单边态不再僵死"""
        idx = BM25Index(index_dir=tmp_path)
        assert idx.add_document("x", "hello x", "session")  # v1
        (tmp_path / BM25Index.METADATA_FILENAME).unlink()
        (tmp_path / "bm25_metadata.json.tmp").write_text("{}", encoding="utf-8")
        fresh = BM25Index(index_dir=tmp_path)  # loaded=0 内存空（load 因 metadata 缺失返回 False）
        assert fresh.add_document("y", "hello y", "session") is True
        assert (tmp_path / BM25Index.METADATA_FILENAME).exists()
        assert not (tmp_path / "bm25_metadata.json.tmp").exists()

    def test_orphan_tmp_consumed_by_read_path(self, tmp_path):
        """issue-21：check_stale_and_reload 采纳孤儿后持锁消费 tmp（补完 commit）"""
        idx = BM25Index(index_dir=tmp_path)
        assert idx.add_document("x", "hello x", "session")  # v1
        assert idx.add_document("y", "hello y", "session")  # v2
        meta_path = tmp_path / BM25Index.METADATA_FILENAME
        meta_v2_text = meta_path.read_text(encoding="utf-8")
        # 孤儿：tmp 里是写者未提交的 v2 metadata，正式 metadata 被回滚到 v1
        tmp_marker = tmp_path / "bm25_metadata.json.tmp"
        tmp_marker.write_text(meta_v2_text, encoding="utf-8")
        meta = json.loads(meta_v2_text)
        meta["write_version"] = 1
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
        daemon_view = BM25Index(index_dir=tmp_path)
        daemon_view._loaded_write_version = 1
        daemon_view.check_stale_and_reload()
        assert daemon_view._loaded_write_version == 2
        assert "y" in daemon_view.doc_mapping
        # tmp 被读路径消费（replace 为正式 metadata），版本提交到 2
        assert not tmp_marker.exists()
        assert _disk_version(tmp_path) == 2
