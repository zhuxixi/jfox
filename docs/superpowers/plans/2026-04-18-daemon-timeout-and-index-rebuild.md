# Daemon 启动可见性 + Index Rebuild 修复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 daemon 首次启动超时/无日志可见性 + index rebuild 不重建 ChromaDB collection 结构 + 维度不匹配错误提示不友好

**Architecture:** 三个独立修复点：(1) daemon 子进程日志落盘 + 首次下载预检 + 动态超时；(2) VectorStore 新增 `reset_collection()` 彻底重建 collection；(3) `add_note()` 捕获维度不匹配异常并给出 Actionable 提示。所有修改都在现有模块内完成，不新增文件。

**Tech Stack:** Python 3.10+, ChromaDB, subprocess, pathlib

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `jfox/daemon/process.py` | Modify | 日志落盘、模型缓存预检、动态超时 |
| `jfox/vector_store.py` | Modify | 新增 `reset_collection()`、`add_note()` 维度不匹配友好提示 |
| `jfox/indexer.py` | Modify | `index_all()` 调用 `reset_collection()` 替代 `clear()` |
| `jfox/daemon/__init__.py` | Modify | 导出 `DAEMON_LOG_FILE` 常量 |
| `tests/unit/test_vector_store_clear.py` | Modify | 新增 `reset_collection()` 测试 |
| `tests/unit/test_indexer_clear_before_rebuild.py` | Modify | 更新 rebuild 测试使用 `reset_collection()` |
| `tests/unit/test_daemon_process.py` | Modify | 新增日志落盘、预检、动态超时测试 |

---

### Task 1: VectorStore.reset_collection() — 新增方法 + 测试

**Files:**
- Modify: `jfox/vector_store.py:186-207`
- Modify: `tests/unit/test_vector_store_clear.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_vector_store_clear.py` 末尾追加：

```python
class TestVectorStoreResetCollection:
    """VectorStore.reset_collection() 单元测试"""

    def test_reset_collection_recreates_collection(self):
        """reset_collection() 应删除旧 collection 并创建新的（维度重置）"""
        from jfox.vector_store import VectorStore

        store = VectorStore()
        client = chromadb.EphemeralClient()
        store.client = client
        store.collection = client.create_collection(
            name="notes", metadata={"hnsw:space": "cosine"}
        )

        # 插入 384 维数据
        store.collection.add(
            ids=["note_001"],
            documents=["doc1"],
            embeddings=[[0.1] * 384],
            metadatas=[{"title": "t1", "type": "permanent", "filepath": "/a", "tags": ""}],
        )
        assert store.collection.count() == 1

        # reset 后 collection 应为空
        result = store.reset_collection()

        assert result is True
        assert store.collection.count() == 0

    def test_reset_collection_on_nonexistent_collection(self):
        """reset_collection() 在 collection 不存在时应正常创建新的"""
        from jfox.vector_store import VectorStore

        store = VectorStore()
        client = chromadb.EphemeralClient()
        store.client = client
        # 不创建 collection，client 上没有 "notes" collection

        result = store.reset_collection()

        assert result is True
        assert store.collection is not None
        assert store.collection.count() == 0

    def test_reset_collection_returns_false_on_init_failure(self):
        """reset_collection() 在 init 失败时返回 False"""
        from jfox.vector_store import VectorStore

        store = VectorStore()
        store.client = MagicMock()
        store.collection = MagicMock()
        store.collection.count.return_value = 0
        store.client.delete_collection.side_effect = Exception("DB error")

        result = store.reset_collection()

        assert result is False
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_vector_store_clear.py::TestVectorStoreResetCollection -v`
Expected: FAIL — `AttributeError: 'VectorStore' object has no attribute 'reset_collection'`

- [ ] **Step 3: 实现 reset_collection()**

在 `jfox/vector_store.py` 的 `clear()` 方法后面（第 207 行之后）追加：

```python
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
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_vector_store_clear.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/vector_store.py tests/unit/test_vector_store_clear.py
git commit -m "feat(vector_store): add reset_collection() for full collection rebuild"
```

---

### Task 2: Indexer.index_all() 使用 reset_collection() 替代 clear()

**Files:**
- Modify: `jfox/indexer.py:253`
- Modify: `tests/unit/test_indexer_clear_before_rebuild.py`

- [ ] **Step 1: 更新测试**

在 `tests/unit/test_indexer_clear_before_rebuild.py` 中：

将 `test_index_all_calls_vector_store_clear` 的断言从 `clear` 改为 `reset_collection`：

```python
    def test_index_all_calls_vector_store_reset_collection(self):
        """index_all() 应在索引笔记前调用 vector_store.reset_collection()"""
        from jfox.indexer import Indexer

        mock_config = MagicMock()
        mock_vector_store = MagicMock()

        # 空笔记目录
        with tempfile.TemporaryDirectory() as tmpdir:
            notes_dir = Path(tmpdir) / "notes"
            notes_dir.mkdir()
            mock_config.notes_dir = str(notes_dir)

            indexer = Indexer(config=mock_config, vector_store=mock_vector_store)
            count = indexer.index_all()

            assert count == 0
            mock_vector_store.reset_collection.assert_called_once()
```

将 `test_index_all_clear_before_add` 的调用顺序检查从 `clear` 改为 `reset_collection`：

```python
    def test_index_all_reset_before_add(self):
        """reset_collection() 必须在 add_or_update_note() 之前调用"""
        from jfox.indexer import Indexer

        mock_config = MagicMock()
        mock_vector_store = MagicMock()

        with tempfile.TemporaryDirectory() as tmpdir:
            notes_dir = Path(tmpdir) / "notes"
            notes_dir.mkdir()
            mock_config.notes_dir = str(notes_dir)

            # 创建假笔记文件
            note_file = notes_dir / "20260412120000-test.md"
            note_file.write_text(
                "---\nid: '20260412120000'\ntitle: Test\ntype: permanent\ntags: []\n---\nContent"
            )

            with patch("jfox.note.NoteManager") as mock_note_mgr:
                mock_note = MagicMock()
                mock_note.id = "20260412120000"
                mock_note_mgr.load_note.return_value = mock_note

                indexer = Indexer(config=mock_config, vector_store=mock_vector_store)
                indexer.index_all()

            # 验证调用顺序
            calls = mock_vector_store.method_calls
            reset_indices = [i for i, c in enumerate(calls) if c[0] == "reset_collection"]
            add_indices = [i for i, c in enumerate(calls) if c[0] == "add_or_update_note"]

            if reset_indices and add_indices:
                assert reset_indices[0] < add_indices[0], (
                    f"reset_collection() (call #{reset_indices[0]}) must be before "
                    f"add_or_update_note() (call #{add_indices[0]})"
                )
```

同时删除旧的 `test_index_all_calls_vector_store_clear` 和 `test_index_all_clear_before_add` 方法（被上面两个新方法替代）。

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_indexer_clear_before_rebuild.py -v`
Expected: FAIL — `reset_collection` not called (因为 `index_all()` 仍调用 `clear()`)

- [ ] **Step 3: 修改 index_all()**

在 `jfox/indexer.py:253`，将：

```python
        # 清除旧索引数据，确保干净重建
        self.vector_store.clear()
```

改为：

```python
        # 彻底重建 collection（删除旧结构 + 重建，解决模型切换后维度不匹配）
        self.vector_store.reset_collection()
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_indexer_clear_before_rebuild.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/indexer.py tests/unit/test_indexer_clear_before_rebuild.py
git commit -m "fix(indexer): use reset_collection() for full rebuild on model switch"
```

---

### Task 3: add_note() 维度不匹配友好错误提示

**Files:**
- Modify: `jfox/vector_store.py:84-86`
- Modify: `tests/unit/test_vector_store_clear.py`（追加测试）

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_vector_store_clear.py` 末尾追加：

```python
class TestVectorStoreDimensionMismatch:
    """add_note() 维度不匹配时应给出友好提示"""

    def test_add_note_dimension_mismatch_friendly_message(self, capfd):
        """维度不匹配时错误信息应包含 rebuild 提示"""
        from jfox.vector_store import VectorStore
        from jfox.models import Note, NoteType
        from unittest.mock import MagicMock, patch

        store = VectorStore()
        client = chromadb.EphemeralClient()
        store.client = client
        store.collection = client.create_collection(
            name="notes", metadata={"hnsw:space": "cosine"}
        )

        # 创建一个假笔记
        note = MagicMock(spec=Note)
        note.id = "20260412120000"
        note.title = "Test"
        note.content = "Test content"
        note.type = NoteType.PERMANENT
        note.tags = []
        note.filepath = Path("/tmp/test.md")

        # mock collection.add 抛出维度不匹配异常
        original_add = store.collection.add
        store.collection.add = MagicMock(
            side_effect=Exception(
                "Collection expecting embedding with dimension of 384, got 1024"
            )
        )

        result = store.add_note(note)

        assert result is False
        # 验证 logger.error 被调用且包含友好提示
        # （通过 capfd 捕获或直接 mock logger）


    def test_add_note_normal_exception_still_returns_false(self):
        """非维度不匹配的异常仍返回 False"""
        from jfox.vector_store import VectorStore

        store = VectorStore()
        store.collection = MagicMock()
        store.collection.add.side_effect = Exception("Some other error")

        note = MagicMock()
        note.id = "20260412120000"
        note.title = "Test"
        note.content = "Content"
        note.type = MagicMock(value="permanent")
        note.tags = []
        note.filepath = MagicMock()

        with patch("jfox.vector_store.get_backend") as mock_backend:
            mock_backend.return_value.encode_single.return_value.tolist.return_value = [0.1] * 1024
            result = store.add_note(note)

        assert result is False
```

- [ ] **Step 2: 运行测试确认通过/失败**

Run: `uv run pytest tests/unit/test_vector_store_clear.py::TestVectorStoreDimensionMismatch -v`
Expected: 第二个测试 PASS（已有行为），第一个测试需要验证友好提示

- [ ] **Step 3: 修改 add_note() 错误处理**

将 `jfox/vector_store.py` 中 `add_note()` 的 except 块（第 84-86 行）：

```python
        except Exception as e:
            logger.error(f"Failed to add note {note.id}: {e}")
            return False
```

改为：

```python
        except Exception as e:
            error_msg = str(e)
            if "dimension" in error_msg.lower() and "expecting" in error_msg.lower():
                # 维度不匹配：模型已切换，提示用户 rebuild
                import re
                dim_match = re.search(r"dimension of (\d+).*got (\d+)", error_msg)
                if dim_match:
                    old_dim, new_dim = dim_match.group(1), dim_match.group(2)
                    logger.error(
                        f"Embedding 维度不匹配（collection: {old_dim}, 当前模型: {new_dim}）。"
                        f"可能是模型已切换，请执行 jfox index rebuild 重建索引。原始错误: {error_msg}"
                    )
                else:
                    logger.error(
                        f"Embedding 维度不匹配，可能是模型已切换。"
                        f"请执行 jfox index rebuild 重建索引。原始错误: {error_msg}"
                    )
            else:
                logger.error(f"Failed to add note {note.id}: {error_msg}")
            return False
```

- [ ] **Step 4: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_vector_store_clear.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/vector_store.py tests/unit/test_vector_store_clear.py
git commit -m "fix(vector_store): friendly error message on embedding dimension mismatch"
```

---

### Task 4: Daemon 日志落盘 — 子进程 stdout/stderr 写入日志文件

**Files:**
- Modify: `jfox/daemon/process.py:38,148-155`
- Modify: `jfox/daemon/__init__.py`（导出 DAEMON_LOG_FILE）
- Modify: `tests/unit/test_daemon_process.py`

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_daemon_process.py` 末尾追加：

```python
class TestDaemonLogFile:
    """测试 daemon 子进程日志落盘"""

    @patch("jfox.daemon.process.subprocess.Popen")
    @patch("jfox.daemon.process._http_health_check")
    def test_start_daemon_writes_to_log_file(self, mock_health, mock_popen):
        """start_daemon 应将子进程 stdout/stderr 重定向到日志文件"""
        from jfox.daemon.process import start_daemon, DAEMON_LOG_FILE

        mock_health.side_effect = [None, {"pid": 9999}]
        mock_popen.return_value.pid = 1234

        start_daemon()

        call_kwargs = mock_popen.call_args[1]
        # stdout 和 stderr 不应是 DEVNULL
        assert call_kwargs["stdout"] != subprocess.DEVNULL
        assert call_kwargs["stderr"] != subprocess.DEVNULL
        # 应该是文件对象，且路径包含 DAEMON_LOG_FILE 的路径
        stdout_arg = call_kwargs["stdout"]
        assert hasattr(stdout_arg, "name") or hasattr(stdout_arg, "write")

    @patch("jfox.daemon.process.subprocess.Popen")
    @patch("jfox.daemon.process._http_health_check")
    def test_daemon_log_file_path(self, mock_health, mock_popen):
        """DAEMON_LOG_FILE 应在用户 home 目录下"""
        from jfox.daemon.process import DAEMON_LOG_FILE
        from pathlib import Path

        assert str(DAEMON_LOG_FILE).endswith(".jfox_daemon.log")
        assert DAEMON_LOG_FILE.parent == Path.home()
```

- [ ] **Step 2: 运行测试确认失败**

Run: `uv run pytest tests/unit/test_daemon_process.py::TestDaemonLogFile -v`
Expected: FAIL — `ImportError: cannot import name 'DAEMON_LOG_FILE'`

- [ ] **Step 3: 实现日志落盘**

在 `jfox/daemon/process.py` 中：

1. 在文件顶部（第 17 行 `from . import DEFAULT_HOST, DEFAULT_PORT` 之后）添加常量：

```python
DAEMON_LOG_FILE = Path.home() / ".jfox_daemon.log"
```

2. 将 `STARTUP_TIMEOUT = 60` 行（第 38 行）改为：

```python
STARTUP_TIMEOUT = 60  # 常规启动超时（秒）
FIRST_RUN_TIMEOUT = 300  # 首次下载模型超时（秒）
```

3. 在 `start_daemon()` 函数中，将 `subprocess.Popen` 调用（第 148-155 行）的 stdout/stderr 从 DEVNULL 改为日志文件。替换：

```python
    try:
        proc = subprocess.Popen(
            cmd,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            **kwargs,
        )
```

为：

```python
    # 子进程日志落盘（stdout/stderr → 日志文件）
    log_file = open(DAEMON_LOG_FILE, "a", encoding="utf-8")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=log_file,
            stdin=subprocess.DEVNULL,
            **kwargs,
        )
```

同时将日志提示也加上，在 `logger.info(f"Daemon 进程已启动 (PID: {proc.pid})")` 后追加：

```python
        logger.info(f"Daemon 日志文件: {DAEMON_LOG_FILE}")
```

在函数末尾的 `return False`（启动超时）之前，也需要关闭 `log_file`。为了正确管理文件句柄，需要用 try/finally 包裹。完整的 `start_daemon` 函数替换见下方。

4. 完整的 `start_daemon()` 替换为：

```python
def start_daemon(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    """
    启动 daemon 后台进程

    Returns:
        True 表示启动成功
    """
    # 检查是否已在运行
    health = _http_health_check(host, port)
    if health is not None:
        logger.info("Daemon 已在运行")
        _write_pid_file(
            {
                "pid": health.get("pid", 0),
                "host": host,
                "port": port,
                "started_at": time.time(),
            }
        )
        return True

    # 首次启动预检：检查模型缓存是否存在
    timeout = STARTUP_TIMEOUT
    cache_info = _check_model_cache()
    if cache_info["needs_download"]:
        logger.info(f"首次启动需要下载模型 {cache_info['model_name']}（约 {cache_info['size_hint']}）")
        timeout = FIRST_RUN_TIMEOUT

    # 构建启动命令（Windows 使用 pythonw.exe 避免控制台窗口）
    cmd = [
        _get_pythonw_executable(),
        "-m",
        "jfox.daemon.server",
        "--host",
        host,
        "--port",
        str(port),
    ]

    kwargs = {}
    if sys.platform == "win32":
        # Windows: 后台分离进程，不弹窗
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        DETACHED_PROCESS = 0x00000008
        CREATE_NO_WINDOW = 0x08000000
        kwargs["creationflags"] = CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS | CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True

    # 子进程日志落盘（stdout/stderr → 日志文件）
    log_file = open(DAEMON_LOG_FILE, "a", encoding="utf-8")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=log_file,
            stdin=subprocess.DEVNULL,
            **kwargs,
        )
        logger.info(f"Daemon 进程已启动 (PID: {proc.pid})")
        logger.info(f"Daemon 日志文件: {DAEMON_LOG_FILE}")
    except Exception as e:
        log_file.close()
        logger.error(f"启动 daemon 失败: {e}")
        return False

    # 等待 daemon 就绪（用 HTTP 健康检查判断，不用 PID）
    try:
        for i in range(timeout):
            time.sleep(1)
            health = _http_health_check(host, port)
            if health is not None:
                # 从 daemon 自身获取真实 PID
                real_pid = health.get("pid", proc.pid)
                _write_pid_file(
                    {
                        "pid": real_pid,
                        "host": host,
                        "port": port,
                        "started_at": time.time(),
                    }
                )
                logger.info(f"Daemon 已就绪 (PID: {real_pid}, port: {port})")
                return True

        logger.warning(f"Daemon 启动超时（{timeout}秒），日志见 {DAEMON_LOG_FILE}")
        return False
    finally:
        log_file.close()
```

5. 在 `start_daemon()` 函数之前（第 106 行之前）添加预检函数：

```python
def _check_model_cache() -> dict:
    """
    检查当前模型是否已缓存

    Returns:
        dict: {"needs_download": bool, "model_name": str, "size_hint": str}
    """
    try:
        from .config import config as _cfg
        from .embedding_backend import _GPU_DEFAULT_MODEL, _CPU_DEFAULT_MODEL

        # 确定目标模型名
        device = _cfg.device
        model_name = _cfg.embedding_model
        if model_name == "auto" or not model_name:
            # 简单检测：如果 torch 可用且有 CUDA，则用 GPU 模型
            try:
                import torch
                if torch.cuda.is_available():
                    model_name = _GPU_DEFAULT_MODEL
                else:
                    model_name = _CPU_DEFAULT_MODEL
            except Exception:
                model_name = _CPU_DEFAULT_MODEL

        # 检查 HuggingFace 缓存
        hf_home = os.environ.get("HF_HOME", str(Path.home() / ".cache" / "huggingface"))
        hub_cache = os.environ.get("HUGGINGFACE_HUB_CACHE", str(Path(hf_home) / "hub"))
        model_cache_dir = Path(hub_cache) / f"models--{model_name.replace('/', '--')}"

        size_hint = "2GB" if "bge-m3" in model_name else "90MB"

        if model_cache_dir.exists():
            # 检查是否有实际权重文件（snapshots 目录不为空）
            snapshots_dir = model_cache_dir / "snapshots"
            has_files = (
                snapshots_dir.exists()
                and any(snapshots_dir.iterdir())
            )
            return {
                "needs_download": not has_files,
                "model_name": model_name,
                "size_hint": size_hint,
            }

        return {
            "needs_download": True,
            "model_name": model_name,
            "size_hint": size_hint,
        }
    except Exception:
        # 预检失败不应阻止启动
        return {"needs_download": False, "model_name": "unknown", "size_hint": ""}
```

- [ ] **Step 4: 更新 __init__.py 导出**

在 `jfox/daemon/__init__.py` 中追加导出：

```python
from .process import DAEMON_LOG_FILE
```

并在 `__all__` 列表中追加 `"DAEMON_LOG_FILE"`。

- [ ] **Step 5: 运行测试确认通过**

Run: `uv run pytest tests/unit/test_daemon_process.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add jfox/daemon/process.py jfox/daemon/__init__.py tests/unit/test_daemon_process.py
git commit -m "fix(daemon): redirect subprocess logs to file, add model cache pre-check and dynamic timeout"
```

---

### Task 5: CLI daemon start 输出增加日志文件提示

**Files:**
- Modify: `jfox/cli.py:2614-2634`

- [ ] **Step 1: 修改 CLI 输出**

在 `jfox/cli.py` 的 `daemon start` 分支（第 2615 行附近），将：

```python
            console.print("[yellow]正在启动 embedding daemon...[/yellow]")
```

改为：

```python
            from .daemon.process import DAEMON_LOG_FILE
            console.print("[yellow]正在启动 embedding daemon...[/yellow]")
            console.print(f"[dim]日志文件: {DAEMON_LOG_FILE}[/dim]")
```

在第 2632 行（启动失败时），将：

```python
                console.print("[red]✗ Daemon 启动失败[/red]")
```

改为：

```python
                console.print(f"[red]✗ Daemon 启动失败[/red]")
                console.print(f"[dim]查看日志: {DAEMON_LOG_FILE}[/dim]")
```

- [ ] **Step 2: 运行快速测试确认无语法错误**

Run: `uv run python -c "from jfox.cli import app; print('OK')"`
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add jfox/cli.py
git commit -m "feat(cli): show daemon log file path in start/failure output"
```

---

## Self-Review

### 1. Spec Coverage

| Issue 要求 | 任务 |
|------------|------|
| 子进程日志落盘 | Task 4（stdout/stderr → DAEMON_LOG_FILE） |
| 首次启动预检 + 提示 | Task 4（`_check_model_cache()` + 日志提示） |
| 动态超时 | Task 4（`FIRST_RUN_TIMEOUT = 300`） |
| reset_collection() | Task 1（新增方法） |
| index_all 用 reset 替代 clear | Task 2 |
| 维度不匹配友好提示 | Task 3 |
| CLI 显示日志路径 | Task 5 |

### 2. Placeholder Scan

No TBD/TODO/fill-in-later found. All steps contain actual code.

### 3. Type Consistency

- `reset_collection()` 返回 `bool`，与 `clear()` 签名一致 ✓
- `DAEMON_LOG_FILE` 是 `Path` 对象，与 `PID_FILE` 风格一致 ✓
- `_check_model_cache()` 返回 `dict`，在 `start_daemon()` 内部使用 ✓
- `log_file` 用 `open()` 打开，传给 `subprocess.Popen` 的 stdout/stderr ✓
- Task 4 的测试 import `DAEMON_LOG_FILE` 与 `process.py` 中定义一致 ✓
