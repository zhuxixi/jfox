# ModelScope 替换 hf-mirror.com 设计文档

## 背景

Issue #225 报告：`jfox daemon start` 在模型下载失败后仍继续启动，导致用户误导性等待 300 秒超时。根本原因是国内网络环境下 HuggingFace 不可达，而现有的三步降级（hf_hub → hf-mirror.com → curl hf-mirror.com）所有步骤都依赖同一个镜像站 `hf-mirror.com`，当该镜像站也不可用时全部失败。

## 目标

1. **替换下载源**：将 hf-mirror.com 完全替换为 ModelScope（`modelscope.cn`）
2. **修复报错体验**：下载失败阻断启动、提升日志级别、打印手动指引
3. **修复缓存结构**：不再伪造 HF Hub `snapshots/{fake_commit_hash}`，改为本地目录加载
4. **支持自定义镜像**：`JFOX_MODEL_MIRROR` 环境变量

## 非目标

- 不引入 modelscope SDK 等新依赖
- 不重构 ModelDownloader 的架构
- 不删除 HuggingFace 直连步骤（国外用户仍可用）

## 总体架构

### 新的下载链路

```
用户运行 jfox daemon start
    |
    v
process.py:start_daemon()
    |
    v
_check_model_cache() --> 检查 HF Hub 缓存 + 本地模型目录
    |
    v
ModelDownloader.ensure_cached()
    Step 1: _check_cached() --> 本地目录 / HF Hub 缓存
    Step 2: _try_hf_hub_download() --> 直连 HuggingFace
    Step 3: _try_modelscope_http() --> urllib 从 ModelScope API 下载到 ~/.zettelkasten/.models/
    Step 4: _try_curl_download() --> curl 从 ModelScope API 下载到 ~/.zettelkasten/.models/
    |
    v
if 全部失败:
    process.py 阻断启动（return False）
    打印 get_manual_instructions() --> ModelScope 手动下载指引
else:
    启动 daemon
    daemon: EmbeddingBackend.load() --> 优先从 ~/.zettelkasten/.models/ 加载
```

### 缓存策略（兼容现有用户）

| 场景 | 行为 |
|------|------|
| HF Hub 缓存已存在 | 正常使用，不改动 |
| 本地模型目录已存在 | 优先使用本地目录 |
| 都不存在 | 走下载链路，下载到本地模型目录 |
| 混合存在 | 优先 HF Hub 缓存（避免重复下载） |

## model_downloader.py 改动

### 常量变更

删除 `_HF_MIRROR`，新增：

```python
_DEFAULT_MIRROR = "https://modelscope.cn"
_LOCAL_MODEL_DIR = Path.home() / ".zettelkasten" / ".models"

_MODELSCOPE_API_TEMPLATE = (
    "{mirror}/api/v1/models/{model_id}/repo"
    "?FilePath={file_path}&Revision=master"
)
```

`JFOX_MODEL_MIRROR` 环境变量覆盖 `_DEFAULT_MIRROR`。

### _check_cached()

同时检查本地目录和 HF Hub 缓存：

```python
def _check_cached(self) -> bool:
    # 优先检查 HF Hub 缓存（现有用户）
    if self._check_hf_hub_cached():
        return True

    # 再检查本地模型目录（ModelScope 下载）
    local_path = self._get_local_model_path()
    if local_path.exists():
        for candidate in _WEIGHT_FILE_CANDIDATES:
            if (local_path / candidate).exists():
                return True
    return False
```

### _try_hf_hub_download()

移除 `endpoint` 参数（ModelScope 不支持 HF Hub 协议），只保留直连 HuggingFace。

### 新增 _try_modelscope_http()

使用标准库 `urllib.request` 从 ModelScope API 下载，无新增依赖：

```python
def _try_modelscope_http(self) -> bool:
    mirror = os.environ.get("JFOX_MODEL_MIRROR", _DEFAULT_MIRROR)
    local_path = self._get_local_model_path()
    local_path.mkdir(parents=True, exist_ok=True)

    # 按优先级下载权重文件
    for candidate in _WEIGHT_FILE_CANDIDATES:
        url = _MODELSCOPE_API_TEMPLATE.format(
            mirror=mirror,
            model_id=self.model_name,
            file_path=candidate,
        )
        try:
            urllib.request.urlretrieve(url, local_path / candidate)
            if (local_path / candidate).stat().st_size > 0:
                break
        except Exception as e:
            logger.warning(f"ModelScope HTTP 下载 {candidate} 失败: {e}")
            continue
    else:
        return False

    # 下载必需文件（不阻断）
    for fname in _REQUIRED_FILES:
        url = _MODELSCOPE_API_TEMPLATE.format(...)
        try:
            urllib.request.urlretrieve(url, local_path / fname)
        except Exception:
            pass

    return True
```

### _try_curl_download()

改为从 ModelScope API 下载，文件直接放到本地模型目录，**不再创建 snapshots/refs 假结构**。

### 日志级别提升

4 处 `logger.debug` 改为 `logger.warning`：

| 原行号 | 内容 |
|--------|------|
| 136 | `权重文件 {candidate} 尝试失败 ({e})，尝试下一个` |
| 213 | `{candidate} 下载失败或为空，跳过` |
| 249 | `{fname} 下载失败或为空，跳过` |
| 251 | `{fname} 下载异常: {e}` |

### get_manual_instructions()

更新为 ModelScope 指引：

```python
def get_manual_instructions(self) -> str:
    mirror = os.environ.get("JFOX_MODEL_MIRROR", _DEFAULT_MIRROR)
    candidates = " / ".join(_WEIGHT_FILE_CANDIDATES)
    local_path = self._get_local_model_path()
    return (
        f"自动下载失败。请手动下载模型:\n"
        f"  1. 访问 {mirror}/models/{self.model_name}\n"
        f"  2. 下载权重文件（{candidates}）和 config.json\n"
        f"  3. 放置到 {local_path}/\n"
        f"  或设置环境变量 JFOX_MODEL_MIRROR 使用其他镜像"
    )
```

## embedding_backend.py 改动

### 新增 _get_local_model_path()

```python
def _get_local_model_path(self) -> Optional[Path]:
    if not self.model_name or self.model_name == "auto":
        return None
    safe_name = self.model_name.replace("/", "--")
    local = Path.home() / ".zettelkasten" / ".models" / safe_name
    return local if local.exists() else None
```

### 修改 load()

优先从本地目录加载：

```python
def load(self):
    if self.model is not None:
        return

    # 解析 device 和 model（保持原有逻辑）
    if self._resolved_device is None:
        self._resolved_device = self._resolve_device()
    if self.model_name is None or self.model_name == "auto":
        self.model_name = self._resolve_model_name(self._resolved_device)

    if self._check_daemon():
        return

    try:
        from sentence_transformers import SentenceTransformer

        # 新增：优先从本地目录加载
        local_path = self._get_local_model_path()
        if local_path is not None:
            self.model = SentenceTransformer(
                str(local_path), device=self._resolved_device
            )
        else:
            self.model = SentenceTransformer(
                self.model_name, device=self._resolved_device
            )

        self._resolved_dim = self.model.get_sentence_embedding_dimension()
        logger.info(
            f"模型已加载: {self.model_name} "
            f"(device={self._resolved_device}, dimension={self._resolved_dim})"
        )
    except Exception as e:
        logger.error(f"加载模型失败: {e}")
        raise
```

## process.py 改动

### start_daemon() — 阻断启动

```python
downloader = ModelDownloader(cache_info["model_name"])
if not downloader.ensure_cached():
    logger.error("模型自动下载失败")
    print(downloader.get_manual_instructions(), file=sys.stderr)
    return False  # 阻断启动

# 删除原注释"不阻断启动，让 daemon 自己去尝试加载"
```

### _check_model_cache() — 检查本地目录

在原有 HF Hub 缓存检查之后，新增本地模型目录检查：

```python
local_dir = Path.home() / ".zettelkasten" / ".models"
safe_name = model_name.replace("/", "--")
local_path = local_dir / safe_name
if local_path.exists():
    has_weight = any(
        (local_path / c).exists() for c in _WEIGHT_FILE_CANDIDATES
    )
    return {
        "needs_download": not has_weight,
        "model_name": model_name,
        "size_hint": size_hint,
    }
```

## 错误处理变更总结

| 场景 | 当前行为 | 新行为 |
|------|---------|--------|
| 下载失败 | 继续启动，300 秒后超时 | **立即阻断**，打印手动指引 |
| 日志级别 | debug 隐藏失败原因 | **warning** 暴露具体原因 |
| 手动指引 | 从未打印 | **stderr 输出** |
| 缓存结构 | 伪造 HF Hub 结构 | **本地目录**，EmbeddingBackend 直接加载 |

## 测试策略

需要验证的场景：

1. ModelScope HTTP 下载成功（mock urllib）
2. ModelScope curl 下载成功（mock subprocess）
3. 三步全败时阻断启动（assert start_daemon() returns False）
4. 本地目录已存在时优先加载（mock Path.exists）
5. HF Hub 缓存已存在时不受影响
6. `JFOX_MODEL_MIRROR` 环境变量生效

## 兼容性

- **现有用户**：HF Hub 缓存不受影响，继续正常使用
- **新用户**：自动从 ModelScope 下载到本地目录
- **混合环境**：优先使用 HF Hub 缓存，避免重复下载
- **自定义镜像**：通过 `JFOX_MODEL_MIRROR` 环境变量支持企业内网镜像
