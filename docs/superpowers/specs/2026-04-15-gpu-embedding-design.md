# GPU 加速 Embedding 设计

> Issue: #155
> 日期: 2026-04-15

## 目标

打通 `config.py` 中已有的 `device`/`embedding_model` 配置到 `EmbeddingBackend`，让 GPU（CUDA）自动生效，并支持更大的 embedding 模型。

## 背景

- `config.py` 已定义 `device`, `embedding_model`, `embedding_dimension` 字段，但 `EmbeddingBackend` 从未读取
- `get_backend()` 硬编码 `EmbeddingBackend()` 不传任何配置
- `dimension` 硬编码 384，换模型会崩溃
- 用户硬件：RTX 4000 SFF Ada 20GB + 2x 2080 Ti 22G SLI

## 硬件与模型选择

| 场景 | 模型 | 维度 | VRAM | device |
|------|------|------|------|--------|
| GPU 可用（默认） | `BAAI/bge-m3` | 1024 | ~2.3GB | cuda |
| GPU 不可用（后备） | `sentence-transformers/all-MiniLM-L6-v2` | 384 | ~0.3GB | cpu |

向量数据库保持 ChromaDB 不变 — 个人知识库万级文档无需 GPU 向量检索。

## 设计

### 1. Device 检测与模型选择

**自动检测逻辑**（`config.device = "auto"` 时）：

1. 首次加载 embedding 模型时调用 `torch.cuda.is_available()`
2. GPU 可用 → `device="cuda"`, 默认模型 `BAAI/bge-m3`
3. GPU 不可用 → `device="cpu"`, 默认模型 `sentence-transformers/all-MiniLM-L6-v2`
4. 用户手动指定 `device: "cpu"/"cuda"` 时跳过自动检测

**模型选择优先级**：
- `config.embedding_model` 设为具体值 → 使用该模型，不论 device
- `config.embedding_model = "auto"` → 根据 device 自动选默认模型

**日志示例**：
```
INFO  检测到 CUDA 可用 (NVIDIA RTX 4000 SFF Ada), 使用 GPU
INFO  模型已加载: BAAI/bge-m3 (device=cuda, dimension=1024)
```

```
INFO  CUDA 不可用, 使用 CPU
INFO  模型已加载: sentence-transformers/all-MiniLM-L6-v2 (device=cpu, dimension=384)
```

### 2. EmbeddingBackend 改造

**构造函数**：

```python
class EmbeddingBackend:
    def __init__(self, model_name: str | None = None, device: str = "auto"):
        self.model_name = model_name  # None/"auto" 表示由 device 自动决定
        self.device = device
        self.model = None
        self._resolved_device: str | None = None
        self._resolved_dim: int | None = None
```

**`load()` 流程**：

1. 解析 device：`"auto"` → `torch.cuda.is_available()` → `"cuda"` 或 `"cpu"`
2. 解析 model_name：`None`/`"auto"` 时根据 device 选默认模型
3. `SentenceTransformer(model_name, device=resolved_device)`
4. 缓存 `_resolved_device` 和 `_resolved_dim`

**`dimension` 属性**：

```python
@property
def dimension(self) -> int:
    if self._resolved_dim is not None:
        return self._resolved_dim
    if self.model is not None:
        return self.model.get_sentence_embedding_dimension()
    # 未加载时从 config 读取
    from .config import config
    return config.embedding_dimension
```

**`get_backend()` 改造**：

```python
def get_backend() -> EmbeddingBackend:
    global _backend
    if _backend is None:
        from .config import config
        model_name = config.embedding_model
        if model_name == "auto":
            model_name = None  # 交给 EmbeddingBackend 根据 device 自动决定
        _backend = EmbeddingBackend(model_name=model_name, device=config.device)
    return _backend
```

### 3. CLI `config set` 命令

```
jfox config set device cuda
jfox config set device auto
jfox config set embedding_model BAAI/bge-m3
jfox config set embedding_model auto
```

**行为**：

1. 修改 `config.yaml` 对应字段
2. 重置全局 backend 单例（`reset_backend()`），下次操作时用新配置重建
3. 如果修改了 `embedding_model`，检查新维度与旧索引是否匹配：
   - 维度相同 → 静默完成
   - 维度不同 → 打印警告：

```
⚠ 模型已更改为 BAAI/bge-m3 (维度 384 → 1024)
  现有向量索引已失效，请运行: jfox index rebuild
```

重建索引使用已有的 `jfox index rebuild` 命令。

**`jfox status` 改造**：

把 `cli.py:590` 硬编码的 `"type": "CPU"` 改为动态读取：

```python
"backend": {
    "type": backend._resolved_device or "未加载",
    "model": backend.model_name,
    "dimension": backend.dimension,
}
```

### 4. Daemon 改造

**`/health` 增强**：

```python
class HealthResponse(BaseModel):
    status: str
    model: str
    dimension: int
    device: str      # 新增：实际使用的设备
    pid: int
```

**启动时读 config**：

```python
from ..config import config
model_name = config.embedding_model if config.embedding_model != "auto" else None
_backend = EmbeddingBackend(device=config.device, model_name=model_name)
```

启动日志报告 device：
```
INFO  Daemon: 模型已加载 BAAI/bge-m3 (device=cuda, dimension=1024)
```

**不做 daemon hot-reload**。切换模型时 `jfox daemon stop && jfox daemon start` 即可。

### 5. Config 默认值变更

| 字段 | 旧默认值 | 新默认值 | 原因 |
|------|---------|---------|------|
| `embedding_model` | `"sentence-transformers/all-MiniLM-L6-v2"` | `"auto"` | 由 device 自动决定 |
| `embedding_dimension` | `384` | `0` | 不再硬编码，0 表示动态 |
| `device` | `"auto"` | `"auto"` | 不变 |

**向后兼容**：旧 config.yaml 写死了 `embedding_model: sentence-transformers/all-MiniLM-L6-v2` 时，升级后继续用该模型，不会自动切换。只有 `"auto"` 才触发自动选择。

## 改动文件清单

| 文件 | 改动 |
|------|------|
| `embedding_backend.py` | 构造函数加 `device`，`load()` 传 device，`dimension` 动态化 |
| `config.py` | 默认值变更，`get_backend()` 读 config |
| `cli.py` | 新增 `config set` 命令，`status` 显示实际 device |
| `daemon/server.py` | `/health` 加 device，启动读 config |
| `tests/conftest.py` | `MockEmbeddingBackend` 适配新接口 |

## 不在范围内

- Daemon hot-reload（`POST /reload`）
- 向量数据库替换（Milvus/Qdrant）
- 抽象向量存储接口
- 多 GPU / SLI 感知（PyTorch 自行处理）
