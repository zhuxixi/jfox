# BM25 索引并发写损坏修复（#391）Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 BM25Index 加乐观并发控制（write_version + 增量重放）、文件锁、原子写盘与读路径 stale 检测，根治 daemon 长进程旧内存快照覆盖磁盘导致的索引回滚。

**Architecture:** 单点改造 `jfox/bm25_index.py`：`_save()` 重写为「拿文件锁 → 比对磁盘 write_version → 必要时 reload + 重放 `_pending_ops` → 原子写 pkl（tmp+os.replace）→ 原子写 metadata（commit point）」。`jfox/search_engine.py` 构造引擎时调 `check_stale_and_reload()` 刷新长驻进程的旧单例。

**Tech Stack:** Python 3.10+, filelock（已是传递依赖，本 plan 显式声明）, rank_bm25, pytest。

**Spec:** `docs/superpowers/specs/2026-08-16-bm25-concurrent-write-race-design.md`

## Global Constraints

- 行长度 100（black/ruff 配置，E501 可忽略但保持整洁）
- 失败路径一律**不写盘**：锁超时、reload 失败 → `_save()` 返回 False，磁盘保持原状
- 不引入除 filelock 外的新依赖；filelock 显式声明进 `pyproject.toml`
- 所有新增/修改的公开行为必须有测试；测试放 `tests/unit/test_bm25_concurrency.py`
- 中文注释，conventional commits，按文件 stage（不用 `git add -A`）
- 不改动 `add_document`/`remove_document`/`rebuild_from_notes`/`search` 的对外签名与语义

---

### Task 1: `_save` 重写——文件锁 + 原子写 + write_version + 日志

**Files:**

- Modify: `jfox/bm25_index.py`（`_save`、`_load`、`__init__`、新增 `_read_disk_write_version` / `_atomic_write_bytes` / `_atomic_write_text`）
- Modify: `pyproject.toml`（dependencies 加 `filelock>=3.12`）
- Test: `tests/unit/test_bm25_concurrency.py`（新建）

**Interfaces:**

- Produces:
  - `BM25Index._loaded_write_version: int`（实例属性，load 后 = 磁盘版本）
  - `BM25Index._read_disk_write_version() -> int`
  - metadata.json 新字段 `write_version: int`

- [ ] **Step 1: 写失败测试**

新建 `tests/unit/test_bm25_concurrency.py`：

```python
"""
BM25Index 并发写防护（#391）单元测试

用两个共享同一索引目录的 BM25Index 实例模拟 CLI 与 daemon 两个进程的交错写。
"""

import json
import pickle
from pathlib import Path
from unittest.mock import patch

import pytest
from filelock import Timeout

from jfox.bm25_index import BM25Index


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
        meta = json.loads(
            (tmp_path / BM25Index.METADATA_FILENAME).read_text(encoding="utf-8")
        )
        assert meta["doc_count"] == 2
        assert meta["write_version"] == 2

    def test_legacy_metadata_without_version(self, tmp_path):
        idx = BM25Index(index_dir=tmp_path)
        assert idx.add_document("a", "hello world", "session")
        # 抹掉 write_version 模拟旧格式文件
        meta_path = tmp_path / BM25Index.METADATA_FILENAME
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        meta.pop("write_version", None)
        meta_path.write_text(json.dumps(meta), encoding="utf-8")
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd <worktree> && uv run pytest tests/unit/test_bm25_concurrency.py -v`
Expected: FAIL（`_loaded_write_version` 属性不存在 / FileLock 未导入）

- [ ] **Step 3: 实现**

`jfox/bm25_index.py` 顶部 import 区加：

```python
import os

from filelock import FileLock, Timeout
```

`BM25Index` 类常量区加 `LOCK_FILENAME = "bm25_index.lock"`；`__init__` 中 `self._load()` 之前初始化：

```python
        self._loaded_write_version: int = 0  # load 时记录的磁盘写入版本（乐观锁令牌）
        self._pending_ops: List[Tuple[str, str, str, Optional[str]]] = []  # 未落盘的增量操作
        self._dirty_full_rebuild: bool = False  # rebuild 后 save 走覆盖语义
```

`_load()` 在读完 metadata 后记录版本（`metadata = json.load(f)` 之后）：

```python
            self._loaded_write_version = int(metadata.get("write_version") or 0)
```

新增工具方法与 `_save` 重写（整体替换现有 `_save`）：

```python
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
        """
        try:
            with FileLock(str(self.index_dir / self.LOCK_FILENAME), timeout=5):
                disk_version = self._read_disk_write_version()
                if disk_version > self._loaded_write_version and not self._dirty_full_rebuild:
                    if not self._load():
                        logger.error(
                            "BM25 磁盘版本较新但 reload 失败，放弃本次 save（不写盘）"
                        )
                        return False
                    self._replay_pending_ops()
                elif disk_version < self._loaded_write_version:
                    logger.warning(
                        f"BM25 磁盘版本 {disk_version} 比本地 {self._loaded_write_version} 旧，按本地覆盖"
                    )

                new_version = max(disk_version, self._loaded_write_version) + 1
                prev_version = self._loaded_write_version

                # 先写 pkl（数据本体），后写 metadata（commit point）
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
```

`_replay_pending_ops` 在 Task 2 才实现，本 Task 先放桩（保证 self._pending_ops 恒为空时行为正确）：

```python
    def _replay_pending_ops(self) -> None:
        """重放本地未落盘的增量操作（Task 2 实现合并逻辑）"""
```

`pyproject.toml` dependencies 加 `"filelock>=3.12"`，然后 `uv lock`。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_bm25_concurrency.py -v`
Expected: 3 个测试 PASS

- [ ] **Step 5: 回归现有 BM25 测试**

Run: `uv run pytest tests/unit/test_bm25_batch.py tests/unit/test_indexer_verify.py -v`
Expected: 全绿（`_save` 签名/行为对外不变）

- [ ] **Step 6: Commit**

```bash
git add jfox/bm25_index.py pyproject.toml uv.lock tests/unit/test_bm25_concurrency.py
git commit -m "feat(bm25): 索引写入加文件锁+原子写+write_version 乐观锁令牌（#391）"
```

---

### Task 2: 增量操作跟踪与重放合并（乐观锁核心）

**Files:**

- Modify: `jfox/bm25_index.py`（`add_document`/`remove_document`/`add_documents_batch` 拆出纯内存 helper，记录 `_pending_ops`；实现 `_replay_pending_ops`）
- Test: `tests/unit/test_bm25_concurrency.py`

**Interfaces:**

- Consumes: Task 1 的 `_save` 新流程、`_pending_ops`、`_loaded_write_version`
- Produces:
  - `BM25Index._add_document_local(note_id, content, note_type) -> bool`（纯内存，不 save 不记 pending）
  - `BM25Index._remove_document_local(note_id) -> bool`（纯内存）
  - `BM25Index._replay_pending_ops() -> None`（同 id 合并后按序重放）

- [ ] **Step 1: 写失败测试（追加到同文件）**

```python
class TestOptimisticMerge:
    """双实例模拟双进程：磁盘较新时 reload + 重放本地增量"""

    def test_concurrent_add_replay(self, tmp_path):
        a = BM25Index(index_dir=tmp_path)  # 模拟 daemon：先 load 旧状态
        b = BM25Index(index_dir=tmp_path)  # 模拟 CLI
        assert b.add_document("note-cli", "cli 写入 hello", "session")  # v1
        assert a.add_document("note-daemon", "daemon 写入 world", "session")  # 触发 merge → v2
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_bm25_concurrency.py::TestOptimisticMerge -v`
Expected: FAIL（`_add_document_local` 不存在 / merge 不生效）

- [ ] **Step 3: 实现**

拆出纯内存 helper（不含 `_rebuild_index`/`_save`/pending 记录）：

```python
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
```

`add_document` 主体改为（语义不变：空 tokens 静默成功；已存在先移除）：

```python
        try:
            if not self._add_document_local(note_id, content, note_type):
                return False
            self._pending_ops.append(("add", note_id, content, note_type))
            self._rebuild_index()
            self._save()
            return True
        except Exception as e:
            logger.error(f"Failed to add document {note_id}: {e}")
            return False
```

`remove_document` 主体改为（不存在则直接返回 True、不记 pending 不 save，保持原语义）：

```python
        try:
            if note_id not in self.doc_mapping:
                return True
            self._remove_document_local(note_id)
            self._pending_ops.append(("remove", note_id, "", None))
            self._rebuild_index()
            self._save()
            return True
        except Exception as e:
            logger.error(f"Failed to remove document {note_id}: {e}")
            return False
```

实现 `_replay_pending_ops`（替换 Task 1 的桩）：

```python
    def _replay_pending_ops(self) -> None:
        """重放本地未落盘的增量操作：同 id 合并（只留最后 op）后按序 apply"""
        if not self._pending_ops:
            return
        merged: Dict[str, Tuple[str, str, Optional[str]]] = {}
        for op, nid, content, ntype in self._pending_ops:
            merged[nid] = (op, content, ntype)
        logger.warning(
            f"BM25 merge: 磁盘版本较新，重放 {len(merged)} 条本地操作后合并写入"
        )
        for nid, (op, content, ntype) in merged.items():
            if op == "remove":
                self._remove_document_local(nid)
            else:
                self._add_document_local(nid, content, ntype)
        self._rebuild_index()
```

`add_documents_batch` 内部若直接操作列表：改为逐条 `_add_document_local` 并把每条 append 进 `_pending_ops`（batch 场景 pending 条数=batch 大小，可接受；重放时按 id 合并去重）。

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_bm25_concurrency.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/bm25_index.py tests/unit/test_bm25_concurrency.py
git commit -m "feat(bm25): 写前乐观检测+增量重放合并，根治旧快照覆盖（#391）"
```

---

### Task 3: rebuild 覆盖语义

**Files:**

- Modify: `jfox/bm25_index.py`（`rebuild_from_notes` 置 `_dirty_full_rebuild`）
- Test: `tests/unit/test_bm25_concurrency.py`

**Interfaces:**

- Consumes: Task 1/2 的 `_save`、`_dirty_full_rebuild`

- [ ] **Step 1: 写失败测试**

```python
from datetime import datetime

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


class TestRebuildSemantics:
    def test_rebuild_overwrites_stale_disk(self, tmp_path):
        a = BM25Index(index_dir=tmp_path)
        b = BM25Index(index_dir=tmp_path)
        assert b.add_document("old", "old note", "session")  # v1
        # a 内存是旧状态，但 rebuild 语义=以我的快照为准：直接覆盖，不 merge
        assert a.rebuild_from_notes([_note("n1"), _note("n2")])
        assert set(_load_disk_ids(tmp_path)) == {"n1", "n2"}
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_bm25_concurrency.py::TestRebuildSemantics -v`
Expected: FAIL（当前 rebuild 后 `_dirty_full_rebuild` 未置位，走 merge 分支会保留 "old"）

- [ ] **Step 3: 实现**

`rebuild_from_notes` 原子替换当前状态成功后、调 `_save()` 之前：

```python
            # rebuild 语义=以本次快照为准：save 时即便磁盘较新也直接覆盖，不做 merge
            self._dirty_full_rebuild = True
            self._pending_ops.clear()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_bm25_concurrency.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/bm25_index.py tests/unit/test_bm25_concurrency.py
git commit -m "feat(bm25): rebuild 采用覆盖语义（stale 时不 merge）（#391）"
```

---

### Task 4: 读路径 stale 检测（daemon 搜索不滞后）

**Files:**

- Modify: `jfox/bm25_index.py`（新增 `check_stale_and_reload`）
- Modify: `jfox/search_engine.py`（`HybridSearchEngine.__init__` 接线）
- Test: `tests/unit/test_bm25_concurrency.py`

**Interfaces:**

- Produces: `BM25Index.check_stale_and_reload() -> None`（磁盘版本较新则 reload，失败静默兜底）

- [ ] **Step 1: 写失败测试**

```python
class TestStaleDetection:
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/test_bm25_concurrency.py::TestStaleDetection -v`
Expected: FAIL（`check_stale_and_reload` 不存在）

- [ ] **Step 3: 实现**

`jfox/bm25_index.py` 新增：

```python
    def check_stale_and_reload(self) -> None:
        """轻量 stale 检查：磁盘 write_version 比内存新就 reload。

        用于长驻进程（daemon）的查询路径，避免搜索长期基于过期快照。
        失败静默兜底（用内存快照），不阻塞查询。
        """
        try:
            if self._read_disk_write_version() > self._loaded_write_version:
                self._load()
        except Exception:
            pass
```

`jfox/search_engine.py` 的 `HybridSearchEngine.__init__`，在 `self.bm25_index = bm25_index or get_bm25_index()` 之后、needs_rebuild 检查之前插入：

```python
        # 长驻进程（daemon）的查询路径：磁盘被别的进程写过时自动刷新单例，
        # 避免 hybrid 搜索长期基于过期快照（#391）
        self.bm25_index.check_stale_and_reload()
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/test_bm25_concurrency.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/bm25_index.py jfox/search_engine.py tests/unit/test_bm25_concurrency.py
git commit -m "feat(search): 引擎构造时检测 BM25 磁盘版本并自动刷新（#391）"
```

---

### Task 5: 回归与收尾

**Files:**

- Modify: 无新代码

- [ ] **Step 1: 全量快速测试回归**

Run: `uv run pytest tests/unit/ -m "not embedding and not slow" -x -q`
Expected: 全绿。重点关注：`test_bm25_batch.py`、`test_indexer_verify.py`、search 相关测试。

- [ ] **Step 2: ruff + black**

Run: `uv run ruff check jfox/bm25_index.py jfox/search_engine.py tests/unit/test_bm25_concurrency.py && uv run black --check jfox/bm25_index.py jfox/search_engine.py tests/unit/test_bm25_concurrency.py`
Expected: 无错误（black 有差异则 `uv run black <files>` 后重跑测试）

- [ ] **Step 3: Commit（如有格式修正）**

```bash
git add jfox/bm25_index.py jfox/search_engine.py tests/unit/test_bm25_concurrency.py
git commit -m "chore(bm25): ruff/black 格式修正（#391）"
```
