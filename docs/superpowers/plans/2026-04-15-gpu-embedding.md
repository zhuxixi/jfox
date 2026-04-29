# GPU 加速 Embedding 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 打通 config.py 的 device/embedding_model 配置到 EmbeddingBackend，让 GPU 自动生效并支持更大的 embedding 模型。

**Architecture:** EmbeddingBackend 新增 device 参数和自动检测逻辑，get_backend() 从 config 读取配置传入。CLI 新增 `config set` 命令，daemon/server.py 启动时读 config 并在 /health 报告 device。

**Tech Stack:** Python 3.10+, sentence-transformers, torch (CUDA), Typer, ChromaDB

---

## File Structure

| File | Action | Responsibility |
|------|--------|----------------|
| `jfox/embedding_backend.py` | Modify | 构造函数加 device，load() 传 device，dimension 动态化 |
| `jfox/config.py` | Modify | 默认值变更（embedding_model → "auto", embedding_dimension → 0） |
| `jfox/cli.py` | Modify | 新增 config set 命令，status 显示实际 device |
| `jfox/daemon/server.py` | Modify | /health 加 device 字段，启动读 config |
| `jfox/daemon/client.py` | Modify | dimension 从 /health 动态获取（已做，确认兼容） |
| `jfox/daemon/process.py` | Modify | get_daemon_status() 透传 device 字段 |
| `tests/test_embedding_device.py` | Create | device 检测和模型选择的单元测试 |
| `tests/test_config_unit.py` | Modify | 更新默认值断言 |
| `tests/conftest.py` | Modify | MockEmbeddingBackend 适配新接口 |

---

### Task 1: EmbeddingBackend 构造函数和 device 解析

**Files:**
- Modify: `jfox/embedding_backend.py:12-18` (EmbeddingBackend class)
- Create: `tests/test_embedding_device.py`

- [ ] **Step 1: Write failing tests for device resolution**

Create `tests/test_embedding_device.py`:

```python
"""Tests for EmbeddingBackend device detection and model selection"""
from unittest.mock import MagicMock, patch

import pytest

from jfox.embedding_backend import EmbeddingBackend


class TestDeviceResolution:
    """测试 device 解析逻辑"""

    @patch("jfox.embedding_backend.torch", create=True)
    def test_auto_resolves_to_cuda_when_available(self, mock_torch_module):
        """auto 模式下，CUDA 可用时解析为 cuda"""
        # 在 load() 中 import torch，所以 mock torch.cuda.is_available
        with patch("torch.cuda.is_available", return_value=True):
            with patch("torch.cuda.get_device_name", return_value="NVIDIA RTX 4000"):
                backend = EmbeddingBackend(device="auto")
                # 不实际加载模型，只测 device 解析
                resolved = backend._resolve_device()
                assert resolved == "cuda"

    def test_auto_resolves_to_cpu_when_no_cuda(self):
        """auto 模式下，CUDA 不可用时解析为 cpu"""
        with patch("torch.cuda.is_available", return_value=False):
            backend = EmbeddingBackend(device="auto")
            resolved = backend._resolve_device()
            assert resolved == "cpu"

    def test_explicit_cuda_skips_detection(self):
        """手动指定 cuda 时跳过自动检测"""
        backend = EmbeddingBackend(device="cuda")
        resolved = backend._resolve_device()
        assert resolved == "cuda"

    def test_explicit_cpu_skips_detection(self):
        """手动指定 cpu 时跳过自动检测"""
        backend = EmbeddingBackend(device="cpu")
        resolved = backend._resolve_device()
        assert resolved == "cpu"


class TestModelSelection:
    """测试模型自动选择"""

    def test_none_model_with_cuda_selects_bge_m3(self):
        """model_name=None + device=cuda → 选择 bge-m3"""
        with patch("torch.cuda.is_available", return_value=True):
            with patch("torch.cuda.get_device_name", return_value="NVIDIA RTX 4000"):
                backend = EmbeddingBackend(model_name=None, device="cuda")
                resolved_model = backend._resolve_model_name("cuda")
                assert resolved_model == "BAAI/bge-m3"

    def test_none_model_with_cpu_selects_minilm(self):
        """model_name=None + device=cpu → 选择 MiniLM"""
        backend = EmbeddingBackend(model_name=None, device="cpu")
        resolved_model = backend._resolve_model_name("cpu")
        assert resolved_model == "sentence-transformers/all-MiniLM-L6-v2"

    def test_explicit_model_overrides_auto(self):
        """手动指定模型时优先使用手动值"""
        backend = EmbeddingBackend(
            model_name="BAAI/bge-large-zh-v1.5", device="cpu"
        )
        resolved_model = backend._resolve_model_name("cpu")
        assert resolved_model == "BAAI/bge-large-zh-v1.5"

    def test_auto_model_string_selects_by_device(self):
        """model_name='auto' 等同于 None，根据 device 选模型"""
        with patch("torch.cuda.is_available", return_value=True):
            with patch("torch.cuda.get_device_name", return_value="NVIDIA RTX 4000"):
                backend = EmbeddingBackend(model_name="auto", device="cuda")
                resolved_model = backend._resolve_model_name("cuda")
                assert resolved_model == "BAAI/bge-m3"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_embedding_device.py -v`
Expected: FAIL — `EmbeddingBackend` has no `_resolve_device()` or `_resolve_model_name()` methods.

- [ ] **Step 3: Implement device resolution and model selection in EmbeddingBackend**

Replace the `EmbeddingBackend` class in `jfox/embedding_backend.py` with:

```python
# 默认模型
_GPU_DEFAULT_MODEL = "BAAI/bge-m3"
_CPU_DEFAULT_MODEL = "sentence-transformers/all-MiniLM-L6-v2"


class EmbeddingBackend:
    """嵌入模型后端（支持 daemon 代理 + GPU 加速）"""

    def __init__(self, model_name: Optional[str] = None, device: str = "auto"):
        self.model_name = model_name  # None/"auto" 表示由 device 自动决定
        self.device = device
        self.model = None
        self._daemon_client = None  # 延迟初始化
        self._use_daemon: Optional[bool] = None  # None=未检测
        self._resolved_device: Optional[str] = None  # 实际解析后的设备
        self._resolved_dim: Optional[int] = None  # 实际嵌入维度

    def _resolve_device(self) -> str:
        """解析 device 字符串为实际设备名"""
        if self.device != "auto":
            return self.device
        try:
            import torch

            if torch.cuda.is_available():
                device_name = torch.cuda.get_device_name(0)
                logger.info(f"检测到 CUDA 可用 ({device_name}), 使用 GPU")
                return "cuda"
        except ImportError:
            pass
        logger.info("CUDA 不可用, 使用 CPU")
        return "cpu"

    def _resolve_model_name(self, resolved_device: str) -> str:
        """根据 device 和用户配置决定使用哪个模型"""
        if self.model_name is not None and self.model_name != "auto":
            return self.model_name
        return _GPU_DEFAULT_MODEL if resolved_device == "cuda" else _CPU_DEFAULT_MODEL

    def _check_daemon(self) -> bool:
        """检测是否使用 daemon（仅检测一次，缓存结果）"""
        if self._use_daemon is not None:
            return self._use_daemon

        # daemon 进程内不应连接自己
        if os.environ.get("JFOX_DAEMON_PROCESS"):
            self._use_daemon = False
            return False

        try:
            from .daemon.process import _get_daemon_url, is_daemon_running

            if is_daemon_running():
                from .daemon.client import DaemonClient

                url = _get_daemon_url()
                client = DaemonClient(url)
                if client.available:
                    self._daemon_client = client
                    self._use_daemon = True
                    logger.info("使用远程 embedding daemon")
                    return True
        except Exception:
            pass

        self._use_daemon = False
        return False

    def load(self):
        """加载模型（支持 device 自动检测和 GPU 加速）"""
        if self.model is not None:
            return
        if self._check_daemon():
            return  # daemon 已持有模型，无需本地加载

        # 解析 device 和 model
        self._resolved_device = self._resolve_device()
        actual_model_name = self._resolve_model_name(self._resolved_device)
        self.model_name = actual_model_name  # 更新为实际模型名

        try:
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer(actual_model_name, device=self._resolved_device)
            self._resolved_dim = self.model.get_sentence_embedding_dimension()
            logger.info(
                f"模型已加载: {actual_model_name} "
                f"(device={self._resolved_device}, dimension={self._resolved_dim})"
            )
        except Exception as e:
            logger.error(f"加载模型失败: {e}")
            raise

    def encode(self, texts: List[str], batch_size: int = 32) -> np.ndarray:
        """文本编码（优先使用 daemon）"""
        # 优先使用 daemon
        if self._check_daemon() and self._daemon_client is not None:
            try:
                return self._daemon_client.encode(texts, batch_size=batch_size)
            except Exception as e:
                logger.warning(f"Daemon 编码失败，回退到本地: {e}")
                self._use_daemon = False

        if self.model is None:
            self.load()

        try:
            return self.model.encode(
                texts, batch_size=batch_size, show_progress_bar=False, convert_to_numpy=True
            )
        except Exception as e:
            logger.error(f"编码失败: {e}")
            raise

    def encode_single(self, text: str) -> np.ndarray:
        """单文本编码"""
        return self.encode([text])[0]

    @property
    def dimension(self) -> int:
        """返回嵌入维度（动态读取）"""
        if self._resolved_dim is not None:
            return self._resolved_dim
        if self.model is not None:
            return self.model.get_sentence_embedding_dimension()
        # 未加载时：如果 model_name 已确定，估算维度
        if self.model_name and self.model_name != "auto":
            if "bge-m3" in self.model_name or "bge-large" in self.model_name:
                return 1024
        return 384  # 默认 MiniLM 维度


# Global backend instance
_backend: Optional[EmbeddingBackend] = None


def get_backend() -> EmbeddingBackend:
    """获取全局 embedding 后端实例（从 config 读取配置）"""
    global _backend
    if _backend is None:
        from .config import config

        model_name = config.embedding_model
        if model_name == "auto":
            model_name = None  # 交给 EmbeddingBackend 根据 device 自动决定
        _backend = EmbeddingBackend(model_name=model_name, device=config.device)
    return _backend


def reset_backend():
    """重置全局 embedding 后端（用于测试或特殊场景）"""
    global _backend
    _backend = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_embedding_device.py -v`
Expected: All 8 tests PASS.

- [ ] **Step 5: Commit**

```bash
git add jfox/embedding_backend.py tests/test_embedding_device.py
git commit -m "feat: add device auto-detection and model selection to EmbeddingBackend

- _resolve_device() auto-detects CUDA availability
- _resolve_model_name() selects bge-m3 for GPU, MiniLM for CPU
- dimension property is now dynamic (reads from model)
- get_backend() reads config.embedding_model and config.device"
```

---

### Task 2: Config 默认值变更

**Files:**
- Modify: `jfox/config.py:32-33` (ZKConfig default values)
- Modify: `tests/test_config_unit.py:49-51,94,124,147` (update assertions)

- [ ] **Step 1: Update config defaults and fix test assertions**

In `jfox/config.py`, change lines 32-33:

```python
    # NPU 配置
    embedding_model: str = "auto"
    embedding_dimension: int = 0  # 0 表示动态，由模型决定
```

In `tests/test_config_unit.py`, update `test_default_values` (line 49-50):

```python
        assert config.embedding_model == "auto"
        assert config.embedding_dimension == 0
```

Update `test_save_writes_yaml` (line 94):

```python
        assert data["embedding_model"] == "auto"
```

Update `test_load_returns_default_if_file_not_exists` (line 147):

```python
        assert config.embedding_model == "auto"
```

- [ ] **Step 2: Run config tests to verify**

Run: `uv run pytest tests/test_config_unit.py -v`
Expected: All tests PASS.

- [ ] **Step 3: Commit**

```bash
git add jfox/config.py tests/test_config_unit.py
git commit -m "refactor: change config defaults to 'auto' for embedding model selection

- embedding_model default: 'auto' (device-driven selection)
- embedding_dimension default: 0 (dynamic, read from model)
- Update test assertions to match new defaults"
```

---

### Task 3: MockEmbeddingBackend 适配 + get_backend 测试

**Files:**
- Modify: `tests/conftest.py:64-80` (MockEmbeddingBackend)
- Modify: `tests/test_embedding_device.py` (add get_backend tests)

- [ ] **Step 1: Update MockEmbeddingBackend in conftest.py**

Replace `MockEmbeddingBackend` class (lines 64-80) with:

```python
    class MockEmbeddingBackend:
        """Mock embedding backend - 返回随机向量（适配新接口）"""

        def __init__(self):
            self.model_name = "mock-model"
            self.device = "cpu"
            self._resolved_device = "cpu"
            self._resolved_dim = 384
            self.dimension = 384

        def encode(self, texts, **kwargs):
            """返回随机向量"""
            if isinstance(texts, str):
                texts = [texts]
            return np.random.rand(len(texts), self.dimension).astype("float32")

        def encode_batch(self, texts, batch_size=32):
            """批量编码"""
            return self.encode(texts)

        def _resolve_device(self):
            return "cpu"

        def _resolve_model_name(self, resolved_device):
            return "mock-model"
```

- [ ] **Step 2: Add get_backend tests to test_embedding_device.py**

Append to `tests/test_embedding_device.py`:

```python
class TestGetBackend:
    """测试 get_backend() 从 config 读取配置"""

    def test_reads_config_device(self):
        """get_backend() 从 config.device 读取"""
        from jfox.embedding_backend import _backend, get_backend, reset_backend

        reset_backend()
        with patch("jfox.config.config") as mock_config:
            mock_config.embedding_model = "BAAI/bge-m3"
            mock_config.device = "cuda"
            backend = get_backend()
            assert backend.device == "cuda"
            assert backend.model_name == "BAAI/bge-m3"
        reset_backend()

    def test_auto_model_resolves_to_none(self):
        """config.embedding_model='auto' 传 None 给 EmbeddingBackend"""
        from jfox.embedding_backend import reset_backend

        reset_backend()
        with patch("jfox.config.config") as mock_config:
            mock_config.embedding_model = "auto"
            mock_config.device = "cpu"
            from jfox.embedding_backend import get_backend

            backend = get_backend()
            assert backend.model_name is None  # None = auto-select
        reset_backend()

    def test_reset_backend_clears_singleton(self):
        """reset_backend() 清除全局单例"""
        from jfox.embedding_backend import _backend, reset_backend

        reset_backend()
        from jfox.embedding_backend import _backend as check1

        assert check1 is None
```

- [ ] **Step 3: Run all embedding device tests**

Run: `uv run pytest tests/test_embedding_device.py -v`
Expected: All tests PASS.

- [ ] **Step 4: Commit**

```bash
git add tests/conftest.py tests/test_embedding_device.py
git commit -m "test: add get_backend config tests and update MockEmbeddingBackend

- MockEmbeddingBackend now has _resolved_device, _resolved_dim attributes
- Test get_backend() reads config.embedding_model and config.device
- Test reset_backend() clears singleton"
```

---

### Task 4: CLI `config set` 命令

**Files:**
- Modify: `jfox/cli.py` (add config command)
- Create: `tests/test_config_set_unit.py`

- [ ] **Step 1: Write failing tests for config set**

Create `tests/test_config_set_unit.py`:

```python
"""Unit tests for 'jfox config set' command"""
from pathlib import Path
from unittest.mock import Mock, patch

import pytest
import yaml


class TestConfigSet:
    """测试 jfox config set 命令"""

    def test_set_device_writes_to_yaml(self, tmp_path):
        """config set device cuda 写入 config.yaml"""
        from jfox.cli import _config_set_impl

        zk_dir = tmp_path / ".zk"
        zk_dir.mkdir(parents=True)
        config_file = zk_dir / "config.yaml"

        with patch("jfox.cli.config") as mock_config:
            mock_config.zk_dir = zk_dir
            mock_config.device = "auto"
            mock_config.embedding_model = "auto"
            _config_set_impl("device", "cuda")

        with open(config_file) as f:
            data = yaml.safe_load(f)
        assert data["device"] == "cuda"

    def test_set_embedding_model_writes_to_yaml(self, tmp_path):
        """config set embedding_model BAAI/bge-m3 写入 config.yaml"""
        from jfox.cli import _config_set_impl

        zk_dir = tmp_path / ".zk"
        zk_dir.mkdir(parents=True)
        config_file = zk_dir / "config.yaml"

        with patch("jfox.cli.config") as mock_config:
            mock_config.zk_dir = zk_dir
            mock_config.device = "auto"
            mock_config.embedding_model = "auto"
            _config_set_impl("embedding_model", "BAAI/bge-m3")

        with open(config_file) as f:
            data = yaml.safe_load(f)
        assert data["embedding_model"] == "BAAI/bge-m3"

    def test_set_invalid_key_raises(self):
        """config set invalid_key 抛出错误"""
        from jfox.cli import _config_set_impl

        with pytest.raises(ValueError, match="不支持的配置项"):
            _config_set_impl("invalid_key", "value")

    def test_set_resets_backend_singleton(self, tmp_path):
        """config set 后重置 backend 单例"""
        from jfox.cli import _config_set_impl

        zk_dir = tmp_path / ".zk"
        zk_dir.mkdir(parents=True)
        config_file = zk_dir / "config.yaml"

        with (
            patch("jfox.cli.config") as mock_config,
            patch("jfox.embedding_backend.reset_backend") as mock_reset,
        ):
            mock_config.zk_dir = zk_dir
            mock_config.device = "auto"
            mock_config.embedding_model = "auto"
            _config_set_impl("device", "cuda")
            mock_reset.assert_called_once()

    def test_valid_config_keys(self):
        """验证所有合法的配置键"""
        from jfox.cli import _VALID_CONFIG_KEYS

        assert "device" in _VALID_CONFIG_KEYS
        assert "embedding_model" in _VALID_CONFIG_KEYS
        assert "batch_size" in _VALID_CONFIG_KEYS
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config_set_unit.py -v`
Expected: FAIL — `_config_set_impl` and `_VALID_CONFIG_KEYS` not defined.

- [ ] **Step 3: Implement config set in cli.py**

Add near the top of `cli.py` (after imports, around line 54):

```python
# config set 允许的配置键及其验证
_VALID_CONFIG_KEYS = {"device", "embedding_model", "batch_size"}
```

Add the `_config_set_impl` function (place it before the `status` command, around line 571):

```python
def _config_set_impl(key: str, value: str):
    """设置配置项的内部实现"""
    if key not in _VALID_CONFIG_KEYS:
        raise ValueError(f"不支持的配置项: {key} (可选: {', '.join(sorted(_VALID_CONFIG_KEYS))})")

    # 读取现有配置（或使用默认值）
    config_data = {}
    config_file = config.zk_dir / "config.yaml"
    if config_file.exists():
        with open(config_file, "r", encoding="utf-8") as f:
            config_data = yaml.safe_load(f) or {}

    # 更新配置值
    config_data[key] = value

    # 写回文件
    config_file.parent.mkdir(parents=True, exist_ok=True)
    with open(config_file, "w", encoding="utf-8") as f:
        yaml.dump(config_data, f, allow_unicode=True, sort_keys=False)

    # 重置 backend 单例，下次操作时用新配置
    from .embedding_backend import reset_backend

    reset_backend()

    console.print(f"[green]✓[/green] {key} = {value}")

    # 如果修改了 embedding_model，检查维度变化
    if key == "embedding_model":
        _warn_dimension_change(value)


def _warn_dimension_change(new_model: str):
    """检查新模型维度是否与旧索引匹配"""
    try:
        old_dim = None
        chroma_dir = config.chroma_dir
        if chroma_dir.exists():
            import chromadb
            from chromadb.config import Settings

            client = chromadb.PersistentClient(
                path=str(chroma_dir),
                settings=Settings(anonymized_telemetry=False, allow_reset=True),
            )
            try:
                collection = client.get_collection("notes")
                old_dim = collection.metadata.get("dimension") if collection.metadata else None
            except Exception:
                pass

        # 估算新模型维度
        new_dim = 1024 if ("bge-m3" in new_model or "bge-large" in new_model) else 384

        if old_dim is not None and old_dim != new_dim:
            console.print(
                f"[yellow]⚠ 模型已更改为 {new_model} (维度 {old_dim} → {new_dim})[/yellow]"
            )
            console.print("  现有向量索引已失效，请运行: [cyan]jfox index rebuild[/cyan]")
    except Exception:
        pass  # 检查失败不影响主流程
```

Add the CLI command (place near other commands, around line 2300):

```python
@app.command(name="config")
def config_cmd(
    action: str = typer.Argument(..., help="操作: set"),
    key: str = typer.Argument(None, help="配置项名称"),
    value: str = typer.Argument(None, help="配置值"),
):
    """
    查看/修改知识库配置

    示例:

        jfox config set device cuda          # 使用 GPU
        jfox config set device auto          # 自动检测
        jfox config set embedding_model BAAI/bge-m3  # 切换模型
        jfox config set embedding_model auto          # 自动选择模型
    """
    try:
        if action == "set":
            if key is None or value is None:
                console.print("[red]用法: jfox config set <key> <value>[/red]")
                raise typer.Exit(1)
            _config_set_impl(key, value)
        else:
            console.print(f"[red]未知操作: {action}[/red]")
            console.print("可用操作: set")
            raise typer.Exit(1)
    except ValueError as e:
        console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]✗[/red] 错误: {e}")
        raise typer.Exit(1)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config_set_unit.py -v`
Expected: All tests PASS.

- [ ] **Step 5: Commit**

```bash
git add jfox/cli.py tests/test_config_set_unit.py
git commit -m "feat: add 'jfox config set' command for device/model configuration

- jfox config set device cuda/auto/cpu
- jfox config set embedding_model <name>/auto
- Warns on dimension change when switching models
- Resets backend singleton after config change"
```

---

### Task 5: CLI `status` 显示实际设备信息

**Files:**
- Modify: `jfox/cli.py:572-621` (_status_impl function)

- [ ] **Step 1: Update _status_impl to show actual device info**

Replace lines 588-593 (the `"backend"` dict in `_status_impl`):

```python
        "backend": {
            "type": backend._resolved_device or "未加载",
            "model": backend.model_name or "auto (未加载)",
            "dimension": backend.dimension,
        },
```

Replace line 615 (table row for Backend):

```python
        table.add_row("Backend", backend._resolved_device or "未加载")
```

Replace line 616 (table row for Model):

```python
        table.add_row("Model", backend.model_name or "auto (未加载)")
```

Add after the Model row:

```python
        table.add_row("Dimension", str(backend.dimension))
```

- [ ] **Step 2: Verify status output manually**

Run: `uv run jfox status --format json`
Expected: JSON output with `"type": "cpu"` or `"cuda"` (depending on machine).

- [ ] **Step 3: Commit**

```bash
git add jfox/cli.py
git commit -m "fix: show actual device info in jfox status instead of hardcoded CPU

- backend.type now shows resolved device (cpu/cuda)
- Shows model name and dimension dynamically"
```

---

### Task 6: Daemon 改造 — 读 config + /health 报告设备

**Files:**
- Modify: `jfox/daemon/server.py:24-37,45-49,76-84`
- Modify: `jfox/daemon/process.py:208-226` (get_daemon_status)

- [ ] **Step 1: Update daemon server to read config and report device**

In `jfox/daemon/server.py`, replace `HealthResponse` class (lines 45-49):

```python
class HealthResponse(BaseModel):
    status: str
    model: str
    dimension: int
    device: str  # 实际使用的设备
    pid: int
```

Replace `_load_model` function (lines 24-37):

```python
@app.on_event("startup")
def _load_model():
    """启动时加载模型（标记为 daemon 进程，防止自引用）"""
    global _backend
    os.environ["JFOX_DAEMON_PROCESS"] = "1"
    from ..config import config
    from ..embedding_backend import EmbeddingBackend

    model_name = config.embedding_model if config.embedding_model != "auto" else None
    _backend = EmbeddingBackend(device=config.device, model_name=model_name)
    try:
        _backend.load()
        logger.info(
            f"Daemon: 模型已加载 {_backend.model_name} "
            f"(device={_backend._resolved_device}, dimension={_backend._resolved_dim})"
        )
    except Exception as e:
        logger.error(f"Daemon: 模型加载失败，进程退出: {e}")
        os._exit(1)
```

Update `/health` endpoint (lines 76-84):

```python
@app.get("/health", response_model=HealthResponse)
def health():
    """健康检查"""
    return HealthResponse(
        status="ok",
        model=_backend.model_name,
        dimension=_backend.dimension,
        device=_backend._resolved_device or "unknown",
        pid=os.getpid(),
    )
```

- [ ] **Step 2: Update get_daemon_status to pass through device**

In `jfox/daemon/process.py`, update `get_daemon_status()` (lines 219-226):

```python
    return {
        "pid": health.get("pid", 0),
        "host": host,
        "port": port,
        "model": health.get("model", "unknown"),
        "dimension": health.get("dimension", 384),
        "device": health.get("device", "unknown"),
        "started_at": data.get("started_at") if data else None,
    }
```

- [ ] **Step 3: Update daemon status display in CLI**

In `jfox/cli.py`, in the daemon `status` action table (around line 2548), add after the dimension row:

```python
                    table.add_row("设备", info.get("device", "unknown"))
```

And in the daemon `start` action table (around line 2522), add after the dimension row:

```python
                    table.add_row("设备", info.get("device", "unknown"))
```

- [ ] **Step 4: Commit**

```bash
git add jfox/daemon/server.py jfox/daemon/process.py jfox/cli.py
git commit -m "feat: daemon reads config for device/model and reports device in /health

- daemon/server.py loads model using config.device and config.embedding_model
- /health endpoint includes device field
- get_daemon_status() passes through device info
- CLI daemon status/start shows device"
```

---

### Task 7: 确保现有快速测试通过

**Files:** No new files — validation only.

- [ ] **Step 1: Run fast unit tests**

Run: `uv run pytest tests/test_config_unit.py tests/test_config_set_unit.py tests/test_embedding_device.py -v`
Expected: All PASS.

- [ ] **Step 2: Run broader fast tests (no embedding, no slow)**

Run: `uv run pytest tests/ -m "not embedding and not slow" -v --timeout=120`
Expected: All PASS. If any fail due to the new EmbeddingBackend interface, fix them.

- [ ] **Step 3: Commit any fixes**

```bash
git add -A
git commit -m "fix: address test failures from EmbeddingBackend interface changes"
```

---

### Task 8: 集成验证

**Files:** No new files — manual verification.

- [ ] **Step 1: Verify CLI help includes new config command**

Run: `uv run jfox --help`
Expected: `config` command listed.

- [ ] **Step 2: Verify config set works end-to-end**

Run: `uv run jfox config set device cpu && uv run jfox status --format json`
Expected: device field shows `"cpu"`.

- [ ] **Step 3: Verify auto-detection works**

Run: `uv run jfox config set device auto && uv run jfox status --format json`
Expected: device field shows `"cuda"` or `"cpu"` depending on machine.

- [ ] **Step 4: Verify daemon status shows device**

Run: `uv run jfox daemon status`
Expected: Shows device info (or "Daemon 未运行" if not running).

- [ ] **Step 5: Final commit — bump version**

Update version in `jfox/__init__.py` and `pyproject.toml` to `0.4.0` (minor bump for new feature), then run `uv lock`.

```bash
git add jfox/__init__.py pyproject.toml uv.lock
git commit -m "chore: bump version to 0.4.0 for GPU embedding support"
```

---

## Self-Review Checklist

- [x] **Spec coverage:** Each section in the spec maps to a task:
  - Section 1 (Device detection) → Task 1
  - Section 2 (EmbeddingBackend) → Task 1
  - Section 3 (CLI config set) → Tasks 4, 5
  - Section 4 (Daemon) → Task 6
  - Section 5 (Config defaults) → Task 2
- [x] **Placeholder scan:** No TBD/TODO/vague steps. All code is concrete.
- [x] **Type consistency:** `_resolve_device()`, `_resolve_model_name()`, `_resolved_device`, `_resolved_dim`, `_VALID_CONFIG_KEYS` names are consistent across all tasks.
