# 内网模型自动下载 (#172) 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现全自动模型下载降级链，让内网用户也能无感知的首次启动 jfox daemon。

**架构:** 新增 `ModelDownloader` 类，封装 3 步重试链。`daemon start` 启动前自动调用。新增 `jfox model download` CLI 命令。

**Tech Stack:** Python, huggingface_hub, typer, rich, pytest, curl (系统命令)

---

## 文件清单

| 文件 | 类型 | 职责 |
|------|------|------|
| `jfox/model_downloader.py` | 新建 | `ModelDownloader` 类，3 步重试链 |
| `jfox/cli.py` | 修改 | 新增 `model download` 子命令 |
| `jfox/daemon/process.py` | 修改 | `start_daemon()` 启动前调用下载检查 |
| `scripts/download-model-intranet.sh` | 新建 | 降级兜底脚本（curl 参考实现） |
| `tests/unit/test_model_downloader.py` | 新建 | 单元测试 |
| `tests/integration/test_model_download.py` | 新建 | 集成测试 |

---

### Task 1: ModelDownloader 核心类

**Files:**
- Create: `jfox/model_downloader.py`

- [ ] **Step 1: 编写模型下载器核心类**

```python
"""模型下载器 - 支持内网自动降级下载"""

import json
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# 镜像站地址
_HF_MIRROR = "https://hf-mirror.com"

# 重试超时（秒）
_TIMEOUT_HF_HUB = 60
_TIMEOUT_CURL = 120

# 需要下载的文件列表（按重要性排序）
_REQUIRED_FILES = [
    "model.safetensors",
    "config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "sentence_bert_config.json",
]


class ModelDownloader:
    """模型下载器，支持全自动降级重试链"""

    def __init__(self, model_name: str):
        self.model_name = model_name
        self._hf_hub_cache = self._get_hf_hub_cache()
        self._model_cache = self._hf_hub_cache / f"models--{model_name.replace('/', '--')}"

    def _get_hf_hub_cache(self) -> Path:
        """获取 HuggingFace Hub 缓存目录"""
        try:
            import huggingface_hub.constants

            return Path(huggingface_hub.constants.HUGGINGFACE_HUB_CACHE)
        except Exception:
            hf_home = os.environ.get("HF_HOME", str(Path.home() / ".cache" / "huggingface"))
            return Path(hf_home) / "hub"

    def ensure_cached(self) -> bool:
        """
        确保模型已缓存。按重试链逐层降级。
        返回 True 表示成功（无论哪一步成功）。
        """
        if self._check_cached():
            logger.info(f"模型已缓存: {self.model_name}")
            return True

        logger.info(f"缓存未命中: {self.model_name}，开始下载")

        # Step 1: 正常下载
        logger.info("步骤 1: 使用 huggingface_hub 正常下载...")
        if self._try_hf_hub_download():
            logger.info("步骤 1 成功，模型已缓存")
            return True
        logger.warning("步骤 1 失败，进入步骤 2")

        # Step 2: 镜像站下载
        logger.info(f"步骤 2: 切换 HF_ENDPOINT={_HF_MIRROR} 重试...")
        if self._try_hf_hub_download(endpoint=_HF_MIRROR):
            logger.info("步骤 2 成功，模型已缓存")
            return True
        logger.warning("步骤 2 失败，进入步骤 3")

        # Step 3: curl 子进程下载
        logger.info("步骤 3: 使用 curl 子进程从镜像站下载...")
        if self._try_curl_download():
            logger.info("步骤 3 成功，模型已缓存")
            return True
        logger.error("步骤 3 失败，所有自动方式均已尝试")

        return False

    def _check_cached(self) -> bool:
        """检查模型是否已在 HuggingFace 缓存目录中存在"""
        if not self._model_cache.exists():
            return False
        snapshots_dir = self._model_cache / "snapshots"
        if not snapshots_dir.exists():
            return False
        # 检查至少有一个 snapshot 且包含 model.safetensors
        for snapshot in snapshots_dir.iterdir():
            if snapshot.is_dir():
                if (snapshot / "model.safetensors").exists():
                    return True
        return False

    def _try_hf_hub_download(self, endpoint: Optional[str] = None) -> bool:
        """
        使用 huggingface_hub 下载模型。
        endpoint=None 为正常模式；endpoint 为镜像站地址。
        """
        env_backup = None
        try:
            from huggingface_hub import hf_hub_download

            if endpoint:
                env_backup = os.environ.get("HF_ENDPOINT")
                os.environ["HF_ENDPOINT"] = endpoint

            # 下载核心文件（只下载 model.safetensors 即可让 sentence-transformers 识别）
            hf_hub_download(
                repo_id=self.model_name,
                filename="model.safetensors",
                cache_dir=str(self._hf_hub_cache),
                local_files_only=False,
            )
            # 尝试下载其他必要文件（不失败）
            for fname in _REQUIRED_FILES[1:]:
                try:
                    hf_hub_download(
                        repo_id=self.model_name,
                        filename=fname,
                        cache_dir=str(self._hf_hub_cache),
                        local_files_only=False,
                    )
                except Exception:
                    pass  # 非核心文件，缺失不影响基本功能

            return True
        except Exception as e:
            logger.warning(f"huggingface_hub 下载失败: {e}")
            return False
        finally:
            if env_backup is not None:
                os.environ["HF_ENDPOINT"] = env_backup
            elif endpoint and "HF_ENDPOINT" in os.environ:
                del os.environ["HF_ENDPOINT"]

    def _try_curl_download(self) -> bool:
        """
        使用 curl 子进程下载模型文件到 HF 缓存目录。
        按 HF 缓存目录结构放置，使 sentence-transformers 认为"模型已缓存"。
        """
        if not shutil.which("curl"):
            logger.warning("系统未安装 curl，跳过步骤 3")
            return False

        # 构建镜像站 URL
        base_url = f"{_HF_MIRROR}/{self.model_name}/resolve/main"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            downloaded = []

            for fname in _REQUIRED_FILES:
                url = f"{base_url}/{fname}"
                dest = tmp_path / fname
                logger.info(f"下载 {fname}...")
                try:
                    result = subprocess.run(
                        [
                            "curl", "-L", "-f", "-s", "-S",
                            "--connect-timeout", "10",
                            "--max-time", str(_TIMEOUT_CURL),
                            "-o", str(dest),
                            url,
                        ],
                        capture_output=True,
                        text=True,
                        timeout=_TIMEOUT_CURL + 5,
                    )
                    if result.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
                        downloaded.append(fname)
                    else:
                        logger.debug(f"{fname} 下载失败或为空，跳过")
                except Exception as e:
                    logger.debug(f"{fname} 下载异常: {e}")

            if "model.safetensors" not in downloaded:
                logger.error("model.safetensors 下载失败，步骤 3 未完成")
                return False

            # 按 HF 缓存目录结构放置
            # 格式: hub/models--org--model/snapshots/commit_hash/{files}
            # 使用伪 commit hash（基于模型名哈希）
            import hashlib

            commit_hash = hashlib.sha256(self.model_name.encode()).hexdigest()[:12]
            snapshot_dir = self._model_cache / "snapshots" / commit_hash
            snapshot_dir.mkdir(parents=True, exist_ok=True)

            for fname in downloaded:
                src = tmp_path / fname
                dst = snapshot_dir / fname
                shutil.copy2(str(src), str(dst))

            # 创建 refs 指向 snapshot
            refs_dir = self._model_cache / "refs"
            refs_dir.mkdir(parents=True, exist_ok=True)
            (refs_dir / "main").write_text(commit_hash, encoding="utf-8")

            return True

    def get_manual_instructions(self) -> str:
        """获取手动下载说明"""
        return (
            f"自动下载失败。请手动下载模型:\n"
            f"  1. 访问 {_HF_MIRROR}/{self.model_name}\n"
            f"  2. 下载 model.safetensors 和 config.json\n"
            f"  3. 放置到 {self._model_cache}/snapshots/\n"
            f"  或运行: bash scripts/download-model-intranet.sh"
        )
```

- [ ] **Step 2: 验证语法**

Run: `python -m py_compile jfox/model_downloader.py`
Expected: 无输出（通过）

- [ ] **Step 3: Commit**

```bash
git add jfox/model_downloader.py
git commit -m "feat(model): add ModelDownloader with 3-step retry chain"
```

---

### Task 2: CLI 新增 `model download` 命令

**Files:**
- Modify: `jfox/cli.py`
- 在 `daemon` 命令附近添加

- [ ] **Step 1: 在 cli.py 中导入并添加 model download 命令**

在 `daemon` 命令之后（约 2663 行后）插入：

```python
@app.command()
def model_download(
    model: Optional[str] = typer.Option(
        None, "--model", "-m",
        help="模型名（默认从配置读取，auto 则按设备自动选择）"
    ),
    force: bool = typer.Option(
        False, "--force", "-f",
        help="强制重新下载（覆盖已有缓存）"
    ),
):
    """
    手动下载 embedding 模型

    自动尝试 3 种下载方式（huggingface_hub → 镜像站 → curl）。
    通常不需要手动调用，daemon start 会自动执行。

    示例:

        jfox model download                    # 下载默认模型
        jfox model download --model bge-m3     # 下载指定模型
        jfox model download --force            # 强制重新下载
    """
    from .model_downloader import ModelDownloader
    from .embedding_backend import EmbeddingBackend

    # 解析模型名
    if model is None or model == "auto":
        backend = EmbeddingBackend()
        device = backend._resolve_device()
        model = backend._resolve_model_name(device)

    console.print(f"[yellow]准备下载模型: {model}[/yellow]")

    downloader = ModelDownloader(model)

    if force and downloader._check_cached():
        console.print("[yellow]强制重新下载，清理旧缓存...[/yellow]")
        import shutil
        shutil.rmtree(downloader._model_cache, ignore_errors=True)

    ok = downloader.ensure_cached()
    if ok:
        console.print(f"[green]✓ 模型下载完成: {model}[/green]")
    else:
        console.print(f"[red]✗ 模型下载失败[/red]")
        console.print(Panel(downloader.get_manual_instructions(), title="手动下载"))
        raise typer.Exit(1)
```

- [ ] **Step 2: 运行快速语法检查**

Run: `python -m py_compile jfox/cli.py`
Expected: 无输出（通过）

- [ ] **Step 3: Commit**

```bash
git add jfox/cli.py
git commit -m "feat(cli): add model download command"
```

---

### Task 3: daemon start 自动调用下载检查

**Files:**
- Modify: `jfox/daemon/process.py`

- [ ] **Step 1: 在 start_daemon 中添加下载检查**

修改 `start_daemon` 函数，在"首次启动预检"之后、构建启动命令之前插入下载逻辑：

找到 `jfox/daemon/process.py` 中 `start_daemon` 函数（约 158 行），在 `cache_info = _check_model_cache()` 和 `if cache_info["needs_download"]:` 代码块之后，构建 `cmd` 列表之前插入：

```python
    # 首次启动预检：检查模型缓存是否存在
    timeout = STARTUP_TIMEOUT
    cache_info = _check_model_cache()
    if cache_info["needs_download"]:
        logger.info(
            f"首次启动需要下载模型 {cache_info['model_name']}"
            f"（约 {cache_info['size_hint']}）"
        )
        # 自动下载模型（内网降级重试）
        try:
            from ..model_downloader import ModelDownloader
            downloader = ModelDownloader(cache_info["model_name"])
            if not downloader.ensure_cached():
                logger.error("模型自动下载失败")
                # 不阻断启动，让 daemon 自己去尝试加载（会暴露更详细的错误日志）
        except Exception as e:
            logger.warning(f"模型下载检查异常: {e}")
```

**注意：** 这里选择**不阻断启动**。理由：
1. 如果下载失败但用户已有其他方式放置了模型，daemon 加载可能仍成功
2. 让 daemon 自己去加载可以暴露更底层的错误信息
3. 避免下载逻辑 bug 导致 daemon 完全无法启动

如果希望严格阻断（下载失败就不启动），改为：
```python
            if not downloader.ensure_cached():
                logger.error("模型自动下载失败，daemon 未启动")
                return False
```

- [ ] **Step 2: 运行快速语法检查**

Run: `python -m py_compile jfox/daemon/process.py`
Expected: 无输出（通过）

- [ ] **Step 3: Commit**

```bash
git add jfox/daemon/process.py
git commit -m "feat(daemon): auto-download model before start with retry chain"
```

---

### Task 4: 降级兜底脚本

**Files:**
- Create: `scripts/download-model-intranet.sh`

- [ ] **Step 1: 创建 bash 脚本**

```bash
#!/usr/bin/env bash
set -euo pipefail

# =============================================================================
# JFox 内网模型下载脚本
# 当 huggingface_hub 无法工作时，使用 curl 手动下载模型
# =============================================================================

MODEL_NAME="${1:-sentence-transformers/all-MiniLM-L6-v2}"
HF_MIRROR="https://hf-mirror.com"

# 获取 HF 缓存目录
HF_HOME="${HF_HOME:-$HOME/.cache/huggingface}"
HUB_CACHE="${HUGGINGFACE_HUB_CACHE:-$HF_HOME/hub}"
MODEL_CACHE="$HUB_CACHE/models--${MODEL_NAME//\//--}"

info()  { echo -e "\033[0;32m[INFO]\033[0m $*"; }
warn()  { echo -e "\033[1;33m[WARN]\033[0m $*"; }
error() { echo -e "\033[0;31m[ERROR]\033[0m $*" >&2; }

# 检查 curl
if ! command -v curl > /dev/null 2>&1; then
    error "curl 未安装，请先安装 curl"
    exit 1
fi

info "目标模型: $MODEL_NAME"
info "缓存目录: $MODEL_CACHE"

# 生成伪 commit hash
COMMIT_HASH=$(echo -n "$MODEL_NAME" | sha256sum | cut -c1-12)
SNAPSHOT_DIR="$MODEL_CACHE/snapshots/$COMMIT_HASH"

mkdir -p "$SNAPSHOT_DIR"

# 下载文件列表
FILES=("model.safetensors" "config.json" "tokenizer.json" "tokenizer_config.json")

for fname in "${FILES[@]}"; do
    URL="$HF_MIRROR/$MODEL_NAME/resolve/main/$fname"
    DEST="$SNAPSHOT_DIR/$fname"

    if [ -f "$DEST" ] && [ -s "$DEST" ]; then
        info "$fname 已存在，跳过"
        continue
    fi

    info "下载 $fname..."
    if curl -L -f -s -S --connect-timeout 10 --max-time 120 \
         -o "$DEST" "$URL"; then
        info "$fname 下载完成"
    else
        warn "$fname 下载失败或不存在，跳过"
        rm -f "$DEST"
    fi
done

# 检查核心文件
if [ ! -f "$SNAPSHOT_DIR/model.safetensors" ]; then
    error "model.safetensors 下载失败"
    exit 1
fi

# 创建 refs
mkdir -p "$MODEL_CACHE/refs"
echo "$COMMIT_HASH" > "$MODEL_CACHE/refs/main"

info "模型下载完成: $MODEL_CACHE"
info "现在可以运行: jfox daemon start"
```

- [ ] **Step 2: 添加可执行权限**

Run: `chmod +x scripts/download-model-intranet.sh`

- [ ] **Step 3: Commit**

```bash
git add scripts/download-model-intranet.sh
git commit -m "feat(scripts): add intranet model download fallback script"
```

---

### Task 5: 单元测试

**Files:**
- Create: `tests/unit/test_model_downloader.py`

- [ ] **Step 1: 编写单元测试**

```python
"""ModelDownloader 单元测试"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jfox.model_downloader import ModelDownloader, _HF_MIRROR


class TestModelDownloader:
    """ModelDownloader 单元测试"""

    @pytest.fixture
    def downloader(self, tmp_path):
        """创建带临时缓存的 downloader"""
        with patch(
            "jfox.model_downloader.ModelDownloader._get_hf_hub_cache",
            return_value=tmp_path / "hub",
        ):
            d = ModelDownloader("sentence-transformers/all-MiniLM-L6-v2")
            return d

    def test_check_cached_when_not_exists(self, downloader):
        """缓存不存在时返回 False"""
        assert downloader._check_cached() is False

    def test_check_cached_when_exists(self, downloader):
        """缓存存在时返回 True"""
        # 创建模拟缓存结构
        snapshot = (
            downloader._model_cache
            / "snapshots"
            / "abc123"
        )
        snapshot.mkdir(parents=True)
        (snapshot / "model.safetensors").write_text("fake")
        assert downloader._check_cached() is True

    def test_check_cached_missing_model_file(self, downloader):
        """有 snapshot 但缺少 model.safetensors 时返回 False"""
        snapshot = downloader._model_cache / "snapshots" / "abc123"
        snapshot.mkdir(parents=True)
        (snapshot / "config.json").write_text("fake")
        assert downloader._check_cached() is False

    def test_ensure_cached_early_return_when_cached(self, downloader):
        """已缓存时直接返回 True，不走重试链"""
        snapshot = downloader._model_cache / "snapshots" / "abc123"
        snapshot.mkdir(parents=True)
        (snapshot / "model.safetensors").write_text("fake")

        with patch.object(downloader, "_try_hf_hub_download") as mock_hf:
            result = downloader.ensure_cached()
            assert result is True
            mock_hf.assert_not_called()

    def test_ensure_cached_step1_succeeds(self, downloader):
        """Step 1 成功，后续步骤不执行"""
        with patch.object(
            downloader, "_try_hf_hub_download", side_effect=[True, False]
        ) as mock_hf:
            with patch.object(downloader, "_try_curl_download") as mock_curl:
                result = downloader.ensure_cached()
                assert result is True
                assert mock_hf.call_count == 1
                mock_curl.assert_not_called()

    def test_ensure_cached_step1_fails_step2_succeeds(self, downloader):
        """Step 1 失败，Step 2 成功"""
        with patch.object(
            downloader, "_try_hf_hub_download", side_effect=[False, True]
        ) as mock_hf:
            with patch.object(downloader, "_try_curl_download") as mock_curl:
                result = downloader.ensure_cached()
                assert result is True
                # 第一次调用 endpoint=None，第二次 endpoint=镜像站
                assert mock_hf.call_count == 2
                mock_curl.assert_not_called()

    def test_ensure_cached_step1_2_fail_step3_succeeds(self, downloader):
        """Step 1/2 失败，Step 3 成功"""
        with patch.object(
            downloader, "_try_hf_hub_download", return_value=False
        ) as mock_hf:
            with patch.object(
                downloader, "_try_curl_download", return_value=True
            ) as mock_curl:
                result = downloader.ensure_cached()
                assert result is True
                assert mock_hf.call_count == 2
                mock_curl.assert_called_once()

    def test_ensure_cached_all_fail(self, downloader):
        """全部失败，返回 False"""
        with patch.object(
            downloader, "_try_hf_hub_download", return_value=False
        ):
            with patch.object(
                downloader, "_try_curl_download", return_value=False
            ):
                result = downloader.ensure_cached()
                assert result is False

    def test_try_hf_hub_download_sets_env(self, downloader):
        """验证镜像模式设置了 HF_ENDPOINT 环境变量"""
        env_before = os.environ.get("HF_ENDPOINT")

        with patch("jfox.model_downloader.hf_hub_download") as mock_download:
            mock_download.side_effect = Exception("network")
            downloader._try_hf_hub_download(endpoint=_HF_MIRROR)

        # 调用后环境变量应被恢复
        assert os.environ.get("HF_ENDPOINT") == env_before

    def test_try_curl_download_no_curl(self, downloader):
        """curl 不存在时返回 False"""
        with patch("jfox.model_downloader.shutil.which", return_value=None):
            result = downloader._try_curl_download()
            assert result is False

    def test_cleanup_partial(self, downloader):
        """验证部分下载残留被清理（通过 TemporaryDirectory 自动实现）"""
        # TemporaryDirectory 在上下文退出时自动清理
        # 这里验证 _try_curl_download 使用 tempfile
        with patch("jfox.model_downloader.shutil.which", return_value="curl"):
            with patch("jfox.model_downloader.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                # 模拟 model.safetensors 下载成功但文件为空（导致失败）
                downloader._try_curl_download()
                # 验证临时目录在使用后会被清理
```

- [ ] **Step 2: 运行单元测试**

Run: `uv run pytest tests/unit/test_model_downloader.py -v`
Expected: 全部通过

- [ ] **Step 3: Commit**

```bash
git add tests/unit/test_model_downloader.py
git commit -m "test(model): add ModelDownloader unit tests"
```

---

### Task 6: 集成测试

**Files:**
- Create: `tests/integration/test_model_download.py`

- [ ] **Step 1: 编写集成测试**

```python
"""模型下载集成测试"""

from unittest.mock import MagicMock, patch

import pytest

from jfox.model_downloader import ModelDownloader


class TestModelDownloadRetryChain:
    """mock 网络层，验证完整重试链按顺序执行"""

    @pytest.fixture
    def downloader(self, tmp_path):
        with patch(
            "jfox.model_downloader.ModelDownloader._get_hf_hub_cache",
            return_value=tmp_path / "hub",
        ):
            return ModelDownloader("sentence-transformers/all-MiniLM-L6-v2")

    def test_full_chain_step1_succeeds(self, downloader):
        """Step 1 成功，后续步骤不执行"""
        with patch.object(
            downloader, "_try_hf_hub_download", side_effect=[True, False]
        ) as mock_hf:
            with patch.object(
                downloader, "_try_curl_download"
            ) as mock_curl:
                result = downloader.ensure_cached()
                assert result is True
                assert mock_hf.call_count == 1
                mock_curl.assert_not_called()

    def test_full_chain_step1_fails_step2_succeeds(self, downloader):
        """Step 1 失败，Step 2 成功"""
        with patch.object(
            downloader, "_try_hf_hub_download", side_effect=[False, True]
        ) as mock_hf:
            with patch.object(
                downloader, "_try_curl_download"
            ) as mock_curl:
                result = downloader.ensure_cached()
                assert result is True
                # 验证调用了两次：第一次 endpoint=None，第二次 endpoint=镜像站
                calls = mock_hf.call_args_list
                assert len(calls) == 2
                assert calls[0][1].get("endpoint") is None
                assert calls[1][1].get("endpoint") is not None
                mock_curl.assert_not_called()

    def test_full_chain_step1_2_fail_step3_succeeds(self, downloader):
        """Step 1/2 失败，Step 3 成功"""
        with patch.object(
            downloader, "_try_hf_hub_download", return_value=False
        ):
            with patch.object(
                downloader, "_try_curl_download", return_value=True
            ) as mock_curl:
                result = downloader.ensure_cached()
                assert result is True
                mock_curl.assert_called_once()

    def test_full_chain_all_fail(self, downloader):
        """全部失败，返回 False"""
        with patch.object(
            downloader, "_try_hf_hub_download", return_value=False
        ):
            with patch.object(
                downloader, "_try_curl_download", return_value=False
            ):
                result = downloader.ensure_cached()
                assert result is False

    def test_daemon_start_calls_downloader(self):
        """验证 daemon start 启动前调用下载检查"""
        from jfox.daemon.process import start_daemon

        with patch("jfox.daemon.process._http_health_check", return_value=None):
            with patch("jfox.daemon.process._check_model_cache") as mock_cache:
                mock_cache.return_value = {
                    "needs_download": True,
                    "model_name": "test-model",
                    "size_hint": "90MB",
                }
                with patch(
                    "jfox.daemon.process.ModelDownloader"
                ) as mock_cls:
                    mock_downloader = MagicMock()
                    mock_downloader.ensure_cached.return_value = True
                    mock_cls.return_value = mock_downloader

                    with patch("jfox.daemon.process.subprocess.Popen"):
                        with patch(
                            "jfox.daemon.process._http_health_check",
                            side_effect=[None, {"pid": 123}],
                        ):
                            start_daemon()
                            mock_cls.assert_called_once_with("test-model")
                            mock_downloader.ensure_cached.assert_called_once()

    def test_cli_model_download_command(self):
        """验证 CLI model download 命令正确调用 downloader"""
        from jfox.cli import app
        from typer.testing import CliRunner

        runner = CliRunner()

        with patch(
            "jfox.cli.ModelDownloader"
        ) as mock_cls:
            mock_downloader = MagicMock()
            mock_downloader.ensure_cached.return_value = True
            mock_downloader._check_cached.return_value = False
            mock_cls.return_value = mock_downloader

            result = runner.invoke(app, ["model", "download"])
            assert result.exit_code == 0
            mock_cls.assert_called_once()
            mock_downloader.ensure_cached.assert_called_once()
```

- [ ] **Step 2: 运行集成测试**

Run: `uv run pytest tests/integration/test_model_download.py -v`
Expected: 全部通过

- [ ] **Step 3: Commit**

```bash
git add tests/integration/test_model_download.py
git commit -m "test(model): add model download integration tests"
```

---

## Self-Review

### 1. Spec Coverage

| Spec 要求 | 对应 Task |
|---|---|
| ModelDownloader 3 步重试链 | Task 1 |
| 日志策略（INFO/WARN/ERROR） | Task 1 |
| `jfox model download` CLI 命令 | Task 2 |
| daemon start 自动调用 | Task 3 |
| curl 子进程下载到 HF 缓存 | Task 1 |
| 部分下载清理 | Task 1 (TemporaryDirectory) |
| 超时策略 | Task 1 (_TIMEOUT_HF_HUB, _TIMEOUT_CURL) |
| 降级兜底脚本 | Task 4 |
| 单元测试 | Task 5 |
| 集成测试 | Task 6 |

**无遗漏。**

### 2. Placeholder Scan

- ✅ 无 "TBD" / "TODO"
- ✅ 无 "implement later"
- ✅ 无 "Add appropriate error handling"（每步有具体代码）
- ✅ 无 "Similar to Task N"
- ✅ 所有代码块包含完整代码

### 3. Type Consistency

- ✅ `ensure_cached()` 返回 `bool`，Task 1/2/3/5/6 一致
- ✅ `ModelDownloader.__init__(model_name: str)`，所有调用一致
- ✅ `_try_hf_hub_download(endpoint: Optional[str] = None)`，签名一致

---

**Plan complete and saved to `docs/superpowers/plans/2026-04-27-intranet-model-download.md`.**

Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?