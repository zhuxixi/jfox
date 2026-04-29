# 内网模型自动下载设计 (#172)

## 问题描述

在公司内网（有代理/防火墙限制）环境中，`huggingface_hub` 无法连接 HuggingFace 官方服务器，导致 `jfox daemon start` 首次启动时模型下载失败，卡在加载阶段。

具体表现：
- `sentence-transformers` 从 `huggingface.co` 下载超时或 SSL 握手失败
- 即使设置 `HF_HUB_OFFLINE=1` 或 `HF_ENDPOINT=https://hf-mirror.com`，某些内网代理环境仍无法工作

## 目标

1. **全自动降级**：daemon 启动前自动检测模型缓存，未命中时按重试链逐层降级下载
2. **透明日志**：每步操作都有清晰的 INFO/WARN/ERROR 日志
3. **独立命令**：新增 `jfox model download` 子命令，也可手动调用
4. **无感知**：前 3 步全自动，用户无感知；只有全部失败时才提示手动操作

## 架构设计

### 重试链

```
Step 1: huggingface_hub 正常下载（全自动）
  → 失败 →
Step 2: 切换 HF_ENDPOINT=hf-mirror.com 重试（全自动）
  → 失败 →
Step 3: 代码自动执行 curl 子进程下载到 HF 缓存目录（全自动）
  → 失败 →
报错，提示用户运行独立脚本（需用户操作）
```

任何一步成功立即终止重试链，启动 daemon。

### 新增模块

```
jfox/model_downloader.py         # ModelDownloader 类
scripts/download-model-intranet.sh  # 降级兜底脚本
```

### 修改模块

```
jfox/daemon/process.py           # start_daemon() 启动前调用下载检查
jfox/cli.py                      # 新增 model download 子命令
```

## 详细设计

### ModelDownloader 类

```python
class ModelDownloader:
    def __init__(self, model_name: str):
        self.model_name = model_name
        self.cache_dir = Path(huggingface_hub.constants.HUGGINGFACE_HUB_CACHE)
        self.model_cache = self.cache_dir / f"models--{model_name.replace('/', '--')}"

    def ensure_cached(self) -> bool:
        """
        确保模型已缓存。按重试链逐层降级。
        返回 True 表示成功（无论哪一步成功）。
        返回 False 表示全部失败。
        """

    def _check_cached(self) -> bool:
        """检查模型是否已在 HuggingFace 缓存目录中存在"""

    def _try_hf_hub_download(self, endpoint: Optional[str] = None) -> bool:
        """
        Step 1/2: 使用 huggingface_hub 下载。
        endpoint=None 为正常模式；endpoint="https://hf-mirror.com" 为镜像模式。
        """

    def _try_curl_download(self) -> bool:
        """
        Step 3: 代码自动执行 curl 子进程下载到 HF 缓存目录。
        按 HF 缓存目录结构放置文件，使 sentence-transformers 认为"模型已缓存"。
        """
        # 下载文件列表：
        # - model.safetensors
        # - config.json
        # - tokenizer.json
        # - tokenizer_config.json
        # - sentence_bert_config.json（如存在）

    def _cleanup_partial(self):
        """清理部分下载残留，防止损坏缓存"""
```

### 日志策略

| 场景 | 日志级别 | 示例 |
|------|---------|------|
| 每步开始 | INFO | `[INFO] 步骤 1: 使用 huggingface_hub 正常下载...` |
| 每步成功 | INFO | `[INFO] 步骤 1 成功，模型已缓存` |
| 每步失败 | WARN | `[WARN] 步骤 1 失败: HTTPSConnectionPool timeout` |
| 全部失败 | ERROR | `[ERROR] 模型下载失败，所有自动方式均已尝试` |
| 最终提示 | INFO | `建议手动下载: jfox model download --manual` |

完整日志示例：

```
[INFO] 检查模型缓存: sentence-transformers/all-MiniLM-L6-v2
[INFO] 缓存未命中，开始下载
[INFO] 步骤 1: 使用 huggingface_hub 正常下载...
[WARN] 步骤 1 失败: HTTPSConnectionPool timeout
[INFO] 步骤 2: 切换 HF_ENDPOINT=hf-mirror.com 重试...
[WARN] 步骤 2 失败: SSL handshake failed
[INFO] 步骤 3: 使用 curl 子进程从镜像站下载...
[INFO] 下载 model.safetensors (87MB)...
[INFO] 下载 config.json...
[INFO] 步骤 3 成功，模型已缓存
[INFO] 启动 daemon...
```

### CLI 集成

**新增命令：`jfox model download`**

```bash
jfox model download [--model MODEL] [--force]

选项:
  --model   指定模型名（默认从配置读取，auto 则按 device 自动选择）
  --force   强制重新下载（覆盖已有缓存）
  --manual  显示手动下载脚本说明（全部自动方式失败后的兜底）
```

**daemon start 自动调用：**

在 `process.py` 的 `start_daemon()` 中，启动子进程前插入：

```python
def start_daemon(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    # 1. 确定目标模型名
    model_name = resolve_model_name()  # 复用现有逻辑

    # 2. 确保模型已缓存
    downloader = ModelDownloader(model_name)
    if not downloader.ensure_cached():
        # 前 3 步全自动都失败了
        logger.error("模型下载失败，所有自动方式均已尝试")
        console.print("[red]模型下载失败[/red]")
        console.print("建议: jfox model download --manual")
        return False

    # 3. 继续原有 daemon 启动逻辑
    ...
```

**注意：** 如果 daemon 已在运行，跳过下载检查（因为已有模型在内存中）。

### 超时策略

| 步骤 | 超时 |
|------|------|
| Step 1 (hf_hub 正常) | 60 秒 |
| Step 2 (hf_hub 镜像) | 60 秒 |
| Step 3 (curl 下载) | 120 秒（模型文件较大） |

### 部分下载清理

任何步骤开始后，如果下载中断（超时、进程被杀、异常退出），`_cleanup_partial()` 自动清理不完整的文件：
- 删除 `.part` 临时文件
- 删除不完整的 snapshot 目录
- 确保下次加载时不会读到损坏的缓存

## 错误处理

```
daemon start
  │
  ▼
检查模型缓存（_check_cached）
  │ 已缓存？ → 跳过下载，直接启动 daemon
  │ 未缓存？ → 进入重试链
  ▼
Step 1: huggingface_hub 正常下载（60s 超时）
  │ 成功 → 记录 [INFO]，启动 daemon
  │ 失败 → 记录 [WARN]，进入 Step 2
  ▼
Step 2: 设置 HF_ENDPOINT，huggingface_hub 重试（60s 超时）
  │ 成功 → 记录 [INFO]，启动 daemon
  │ 失败 → 记录 [WARN]，进入 Step 3
  ▼
Step 3: curl 子进程下载到 HF 缓存目录（120s 超时）
  │ 成功 → 记录 [INFO]，启动 daemon
  │ 失败 → 记录 [ERROR]，提示手动方案
  ▼
全部失败 → CLI 报错，daemon 不启动
```

## 测试方案

### 单元测试：`tests/unit/test_model_downloader.py`

```python
class TestModelDownloader:
    """ModelDownloader 单元测试"""

    def test_check_cached_when_exists(self):
        """缓存已存在时返回 True"""

    def test_check_cached_when_not_exists(self):
        """缓存不存在时返回 False"""

    def test_try_hf_hub_download_success(self):
        """mock hf_hub_download 成功"""

    def test_try_hf_hub_download_failure(self):
        """mock hf_hub_download 抛出异常"""

    def test_try_mirror_download_sets_env(self):
        """验证设置了 HF_ENDPOINT 环境变量"""

    def test_try_curl_download_executes_subprocess(self):
        """mock subprocess.run，验证 curl 命令参数"""

    def test_ensure_cached_early_return_when_cached(self):
        """已缓存时直接返回，不走重试链"""

    def test_ensure_cached_retry_chain_order(self):
        """验证重试链按 1→2→3 顺序执行"""

    def test_cleanup_partial_removes_temp_files(self):
        """验证部分下载残留被清理"""
```

### 集成测试：`tests/integration/test_model_download.py`

```python
class TestModelDownloadRetryChain:
    """mock 网络层，验证完整重试链按顺序执行"""

    def test_full_chain_step1_succeeds(self):
        """Step 1 成功，后续步骤不执行"""

    def test_full_chain_step1_fails_step2_succeeds(self):
        """Step 1 失败，Step 2 成功"""

    def test_full_chain_step1_2_fail_step3_succeeds(self):
        """Step 1/2 失败，Step 3 成功"""

    def test_full_chain_all_fail(self):
        """全部失败，返回 False"""

    def test_daemon_start_calls_downloader(self):
        """验证 daemon start 启动前调用下载检查"""

    def test_cli_model_download_command(self):
        """验证 CLI model download 命令正确调用 downloader"""
```

## 新增/修改文件清单

| 文件 | 类型 | 说明 |
|------|------|------|
| `jfox/model_downloader.py` | 新增 | ModelDownloader 类 |
| `scripts/download-model-intranet.sh` | 新增 | 降级兜底脚本（curl 方案参考实现） |
| `jfox/cli.py` | 修改 | 新增 `model download` 子命令 |
| `jfox/daemon/process.py` | 修改 | `start_daemon()` 启动前调用下载检查 |
| `tests/unit/test_model_downloader.py` | 新增 | 单元测试 |
| `tests/integration/test_model_download.py` | 新增 | 集成测试 |

## 依赖

- **无新增 Python 依赖**
- `curl`：系统命令（Step 3 使用）
- `huggingface_hub`：已存在（Step 1/2 使用）

## 风险

| 风险 | 缓解 |
|------|------|
| curl 不可用 | Step 3 前检查 `shutil.which("curl")`，不存在则跳过 |
| curl 下载中途被杀 | 部分下载清理 + 断点续传（curl `-C -`） |
| HF 缓存目录结构变更 | 使用 `huggingface_hub.constants` 获取路径，不硬编码 |
| 并发下载冲突 | PID 文件锁或临时目录隔离 |

## 关联

- #172 — 原始问题（公司内网模型下载失败）
- #117 — daemon 模式已解决重复加载，但首次下载仍需联网
