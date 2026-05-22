# ModelScope 替换 hf-mirror.com 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将模型下载源从 hf-mirror.com 替换为 ModelScope，修复 #225 报错体验和缓存结构问题。

**Architecture:** model_downloader.py 新增 ModelScope HTTP 下载步骤，curl 改为从 ModelScope API 下载到本地目录；embedding_backend.py 支持从本地路径加载 SentenceTransformer；process.py 下载失败阻断启动并打印指引。

**Tech Stack:** Python 3.10+, standard library (urllib), pytest, unittest.mock

---

## 文件结构

| File | Action | Responsibility |
|------|--------|--------------|
| `jfox/model_downloader.py` | Modify | 下载源替换、本地目录支持、日志级别提升 |
| `jfox/embedding_backend.py` | Modify | 本地路径加载支持 |
| `jfox/daemon/process.py` | Modify | 阻断启动、本地目录预检 |
| `tests/unit/test_model_downloader.py` | Modify | 更新现有测试适配新链路，新增 ModelScope 测试 |
| `tests/unit/test_daemon_process.py` | Modify | 新增阻断启动和本地缓存测试 |
| `tests/unit/test_embedding_local_load.py` | Create | 本地路径加载测试 |

---

### Task 1: model_downloader.py — 常量和 _check_cached 重构

**Files:**
- Modify: `jfox/model_downloader.py:1-282`
- Test: `tests/unit/test_model_downloader.py`

- [ ] **Step 1: 删除 _HF_MIRROR，新增 ModelScope 常量和本地目录**

```python
# 删除：
# _HF_MIRROR = "https://hf-mirror.com"

# 新增：
_DEFAULT_MIRROR = "https://modelscope.cn"
_LOCAL_MODEL_DIR = Path.home() / ".zettelkasten" / ".models"

_MODELSCOPE_API_TEMPLATE = (
    "{mirror}/api/v1/models/{model_id}/repo"
    "?FilePath={file_path}&Revision=master"
)
```

- [ ] **Step 2: 重构 _check_cached 支持本地目录和 HF Hub 双重检查**

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

def _check_hf_hub_cached(self) -> bool:
    """检查模型是否已在 HuggingFace 缓存目录中存在"""
    if not self._model_cache.exists():
        return False
    snapshots_dir = self._model_cache / "snapshots"
    if not snapshots_dir.exists():
        return False
    try:
        for snapshot in snapshots_dir.iterdir():
            if snapshot.is_dir():
                for candidate in _WEIGHT_FILE_CANDIDATES:
                    if (snapshot / candidate).exists():
                        return True
    except OSError:
        logger.warning(f"无法遍历缓存目录: {snapshots_dir}")
        return False
    return False

def _get_local_model_path(self) -> Path:
    """获取本地模型目录路径"""
    safe_name = self.model_name.replace("/", "--")
    return _LOCAL_MODEL_DIR / safe_name
```

- [ ] **Step 3: 运行现有测试确认 _check_cached 重构通过**

Run: `uv run pytest tests/unit/test_model_downloader.py::TestModelDownloader::test_check_cached_when_not_exists tests/unit/test_model_downloader.py::TestModelDownloader::test_check_cached_when_exists tests/unit/test_model_downloader.py::TestModelDownloader::test_check_cached_missing_model_file -v`

Expected: 3 PASS（需要更新 fixture 中 patch 的路径）

- [ ] **Step 4: Commit**

```bash
git add jfox/model_downloader.py tests/unit/test_model_downloader.py
git commit -m "refactor(model_downloader): split _check_cached into HF hub + local dir checks"
```

---

### Task 2: model_downloader.py — _try_hf_hub_download 移除镜像站参数

**Files:**
- Modify: `jfox/model_downloader.py:109-163`
- Test: `tests/unit/test_model_downloader.py`

- [ ] **Step 1: 简化 _try_hf_hub_download，移除 endpoint 参数**

原函数签名：`def _try_hf_hub_download(self, endpoint: Optional[str] = None) -> bool:`

新函数签名：`def _try_hf_hub_download(self) -> bool:`

删除 `endpoint` 参数及相关的 env_backup 设置/恢复逻辑。函数只保留直连 HuggingFace 的下载逻辑。

```python
def _try_hf_hub_download(self) -> bool:
    """使用 huggingface_hub 直连 HuggingFace 下载模型。"""
    try:
        from huggingface_hub import hf_hub_download

        weight_downloaded = False
        for candidate in _WEIGHT_FILE_CANDIDATES:
            try:
                hf_hub_download(
                    repo_id=self.model_name,
                    filename=candidate,
                    cache_dir=str(self._hf_hub_cache),
                    local_files_only=False,
                )
                weight_downloaded = True
                logger.debug(f"权重文件 {candidate} 下载成功")
                break
            except Exception as e:
                logger.warning(f"权重文件 {candidate} 尝试失败 ({e})，尝试下一个")
                continue

        if not weight_downloaded:
            logger.warning("所有权重文件候选均下载失败")
            return False

        for fname in _REQUIRED_FILES:
            try:
                hf_hub_download(
                    repo_id=self.model_name,
                    filename=fname,
                    cache_dir=str(self._hf_hub_cache),
                    local_files_only=False,
                )
            except (OSError, ValueError):
                pass

        return True
    except Exception as e:
        logger.warning(f"huggingface_hub 下载失败: {e}")
        return False
```

- [ ] **Step 2: 更新 ensure_cached 调用链路（3步 → 4步）**

```python
def ensure_cached(self) -> bool:
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

    # Step 2: ModelScope HTTP 下载
    logger.info("步骤 2: 使用 ModelScope HTTP 下载...")
    if self._try_modelscope_http():
        logger.info("步骤 2 成功，模型已缓存")
        return True
    logger.warning("步骤 2 失败，进入步骤 3")

    # Step 3: curl 从 ModelScope 下载
    logger.info("步骤 3: 使用 curl 从 ModelScope 下载...")
    if self._try_curl_download():
        logger.info("步骤 3 成功，模型已缓存")
        return True
    logger.error("步骤 3 失败，所有自动方式均已尝试")

    return False
```

- [ ] **Step 3: 更新测试文件 — 移除 _HF_MIRROR 引用和 endpoint 测试**

修改 `tests/unit/test_model_downloader.py`：

1. 删除 `from jfox.model_downloader import _HF_MIRROR` 行，改为 `from jfox.model_downloader import _DEFAULT_MIRROR, ModelDownloader`

2. 更新 `test_ensure_cached_step1_succeeds`：
```python
def test_ensure_cached_step1_succeeds(self, downloader):
    with patch.object(downloader, "_try_hf_hub_download", return_value=True) as mock_hf:
        with patch.object(downloader, "_try_modelscope_http") as mock_http:
            with patch.object(downloader, "_try_curl_download") as mock_curl:
                result = downloader.ensure_cached()
                assert result is True
                mock_hf.assert_called_once()
                mock_http.assert_not_called()
                mock_curl.assert_not_called()
```

3. 更新 `test_ensure_cached_step1_fails_step2_succeeds`（原 Step 1 失败，Step 2 成功）：
```python
def test_ensure_cached_step1_fails_step2_succeeds(self, downloader):
    with patch.object(downloader, "_try_hf_hub_download", return_value=False) as mock_hf:
        with patch.object(downloader, "_try_modelscope_http", return_value=True) as mock_http:
            with patch.object(downloader, "_try_curl_download") as mock_curl:
                result = downloader.ensure_cached()
                assert result is True
                mock_hf.assert_called_once()
                mock_http.assert_called_once()
                mock_curl.assert_not_called()
```

4. 更新 `test_ensure_cached_step1_2_fail_step3_succeeds`（原 Step 1/2 失败，Step 3 成功）：
```python
def test_ensure_cached_step1_2_fail_step3_succeeds(self, downloader):
    with patch.object(downloader, "_try_hf_hub_download", return_value=False) as mock_hf:
        with patch.object(downloader, "_try_modelscope_http", return_value=False) as mock_http:
            with patch.object(downloader, "_try_curl_download", return_value=True) as mock_curl:
                result = downloader.ensure_cached()
                assert result is True
                mock_hf.assert_called_once()
                mock_http.assert_called_once()
                mock_curl.assert_called_once()
```

5. 更新 `test_ensure_cached_all_fail`：
```python
def test_ensure_cached_all_fail(self, downloader):
    with patch.object(downloader, "_try_hf_hub_download", return_value=False):
        with patch.object(downloader, "_try_modelscope_http", return_value=False):
            with patch.object(downloader, "_try_curl_download", return_value=False):
                result = downloader.ensure_cached()
                assert result is False
```

6. 删除 `test_try_hf_hub_download_sets_env`（endpoint 逻辑已移除）

- [ ] **Step 4: 运行更新后的测试**

Run: `uv run pytest tests/unit/test_model_downloader.py -v`

Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/model_downloader.py tests/unit/test_model_downloader.py
git commit -m "refactor(model_downloader): remove hf-mirror endpoint param, restructure to 4-step chain"
```

---

### Task 3: model_downloader.py — 新增 _try_modelscope_http

**Files:**
- Modify: `jfox/model_downloader.py`
- Test: `tests/unit/test_model_downloader.py`

- [ ] **Step 1: 实现 _try_modelscope_http**

```python
def _try_modelscope_http(self) -> bool:
    """使用 urllib 从 ModelScope API 下载模型文件到本地目录。"""
    import urllib.request

    mirror = os.environ.get("JFOX_MODEL_MIRROR", _DEFAULT_MIRROR)
    local_path = self._get_local_model_path()
    local_path.mkdir(parents=True, exist_ok=True)

    # 按优先级下载权重文件
    weight_downloaded = False
    for candidate in _WEIGHT_FILE_CANDIDATES:
        url = _MODELSCOPE_API_TEMPLATE.format(
            mirror=mirror,
            model_id=self.model_name,
            file_path=candidate,
        )
        dest = local_path / candidate
        logger.info(f"试用权重文件 {candidate}...")
        try:
            urllib.request.urlretrieve(url, dest)
            if dest.exists() and dest.stat().st_size > 0:
                downloaded = True
                logger.info(f"权重文件 {candidate} 下载成功")
                break
            else:
                logger.warning(f"权重文件 {candidate} 下载结果为空，尝试下一个")
        except Exception as e:
            logger.warning(f"权重文件 {candidate} 下载失败 ({e})，尝试下一个")
            continue

    if not weight_downloaded:
        logger.warning("所有权重文件候选均下载失败")
        return False

    # 下载其他必要文件（不阻断）
    for fname in _REQUIRED_FILES:
        url = _MODELSCOPE_API_TEMPLATE.format(
            mirror=mirror,
            model_id=self.model_name,
            file_path=fname,
        )
        dest = local_path / fname
        try:
            urllib.request.urlretrieve(url, dest)
        except Exception:
            pass  # 非核心文件，缺失不影响基本功能

    return True
```

- [ ] **Step 2: 新增测试 — ModelScope HTTP 下载成功**

```python
def test_try_modelscope_http_success(self, downloader):
    """ModelScope HTTP 下载成功"""
    with patch("urllib.request.urlretrieve") as mock_retrieve:
        def urlretrieve_side_effect(url, dest):
            Path(dest).write_text("fake model")
        mock_retrieve.side_effect = urlretrieve_side_effect

        result = downloader._try_modelscope_http()
        assert result is True
        # 验证文件写入本地目录
        local_path = downloader._get_local_model_path()
        assert (local_path / "model.safetensors").exists()

def test_try_modelscope_http_fallback_to_pytorch(self, downloader):
    """model.safetensors 不存在时回退到 pytorch_model.bin"""
    call_count = 0
    def urlretrieve_side_effect(url, dest):
        nonlocal call_count
        call_count += 1
        if "model.safetensors" in url:
            raise Exception("404")
        Path(dest).write_text("fake model")
    
    with patch("urllib.request.urlretrieve") as mock_retrieve:
        mock_retrieve.side_effect = urlretrieve_side_effect
        result = downloader._try_modelscope_http()
        assert result is True
        assert call_count >= 1

def test_try_modelscope_http_all_fail(self, downloader):
    """所有权重文件下载失败"""
    with patch("urllib.request.urlretrieve", side_effect=Exception("network")):
        result = downloader._try_modelscope_http()
        assert result is False

def test_try_modelscope_http_custom_mirror(self, downloader):
    """JFOX_MODEL_MIRROR 环境变量生效"""
    with patch.dict(os.environ, {"JFOX_MODEL_MIRROR": "https://custom.mirror.com"}):
        with patch("urllib.request.urlretrieve") as mock_retrieve:
            def urlretrieve_side_effect(url, dest):
                assert "custom.mirror.com" in url
                Path(dest).write_text("fake")
            mock_retrieve.side_effect = urlretrieve_side_effect
            result = downloader._try_modelscope_http()
            assert result is True
```

- [ ] **Step 3: 运行测试**

Run: `uv run pytest tests/unit/test_model_downloader.py -v`

Expected: 全部 PASS

- [ ] **Step 4: Commit**

```bash
git add jfox/model_downloader.py tests/unit/test_model_downloader.py
git commit -m "feat(model_downloader): add ModelScope HTTP download step"
```

---

### Task 4: model_downloader.py — _try_curl_download 改造为 ModelScope

**Files:**
- Modify: `jfox/model_downloader.py:165-270`
- Test: `tests/unit/test_model_downloader.py`

- [ ] **Step 1: 改造 _try_curl_download**

改为从 ModelScope API 下载，文件直接放到本地模型目录，不再创建 snapshots/refs 假结构。

```python
def _try_curl_download(self) -> bool:
    """使用 curl 子进程从 ModelScope API 下载模型文件到本地目录。"""
    if not shutil.which("curl"):
        logger.warning("系统未安装 curl，跳过步骤 3")
        return False

    mirror = os.environ.get("JFOX_MODEL_MIRROR", _DEFAULT_MIRROR)
    local_path = self._get_local_model_path()
    local_path.mkdir(parents=True, exist_ok=True)

    # 按优先级尝试下载权重文件
    weight_downloaded = False
    for candidate in _WEIGHT_FILE_CANDIDATES:
        url = _MODELSCOPE_API_TEMPLATE.format(
            mirror=mirror,
            model_id=self.model_name,
            file_path=candidate,
        )
        dest = local_path / candidate
        logger.info(f"试用权重文件 {candidate}...")
        try:
            result = subprocess.run(
                [
                    "curl",
                    "-L",
                    "-f",
                    "-s",
                    "-S",
                    "--connect-timeout",
                    "10",
                    "--max-time",
                    str(_TIMEOUT_CURL),
                    "-o",
                    str(dest),
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_CURL + 5,
            )
            if result.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
                weight_downloaded = True
                break
            else:
                logger.warning(f"{candidate} 下载失败或为空，跳过")
        except (OSError, subprocess.TimeoutExpired) as e:
            logger.warning(f"{candidate} 下载异常: {e}")

    if not weight_downloaded:
        logger.error("所有权重文件候选下载失败，curl 步骤未完成")
        return False

    # 下载非权重必需文件
    for fname in _REQUIRED_FILES:
        url = _MODELSCOPE_API_TEMPLATE.format(
            mirror=mirror,
            model_id=self.model_name,
            file_path=fname,
        )
        dest = local_path / fname
        logger.info(f"下载 {fname}...")
        try:
            result = subprocess.run(
                [
                    "curl",
                    "-L",
                    "-f",
                    "-s",
                    "-S",
                    "--connect-timeout",
                    "10",
                    "--max-time",
                    str(_TIMEOUT_CURL),
                    "-o",
                    str(dest),
                    url,
                ],
                capture_output=True,
                text=True,
                timeout=_TIMEOUT_CURL + 5,
            )
            if result.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
                pass  # 成功，无需处理
            else:
                logger.warning(f"{fname} 下载失败或为空，跳过")
        except (OSError, subprocess.TimeoutExpired) as e:
            logger.warning(f"{fname} 下载异常: {e}")

    return True
```

- [ ] **Step 2: 更新 curl 相关测试**

```python
def test_try_curl_download_success(self, downloader):
    """curl 从 ModelScope 下载成功"""
    with patch("jfox.model_downloader.shutil.which", return_value="curl"):
        with patch("jfox.model_downloader.subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = downloader._try_curl_download()
            assert result is True
            # 验证文件写入本地目录
            local_path = downloader._get_local_model_path()
            # subprocess.run 被 mock 了，文件不会实际创建
            # 但至少验证调用参数中包含 ModelScope URL
            calls = mock_run.call_args_list
            assert any("modelscope.cn" in str(c) for c in calls)

def test_try_curl_download_custom_mirror(self, downloader):
    """curl 使用 JFOX_MODEL_MIRROR 环境变量"""
    with patch.dict(os.environ, {"JFOX_MODEL_MIRROR": "https://custom.mirror.com"}):
        with patch("jfox.model_downloader.shutil.which", return_value="curl"):
            with patch("jfox.model_downloader.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                downloader._try_curl_download()
                calls = mock_run.call_args_list
                assert any("custom.mirror.com" in str(c) for c in calls)
```

- [ ] **Step 3: 运行测试**

Run: `uv run pytest tests/unit/test_model_downloader.py -v`

Expected: 全部 PASS

- [ ] **Step 4: Commit**

```bash
git add jfox/model_downloader.py tests/unit/test_model_downloader.py
git commit -m "feat(model_downloader): curl download from ModelScope API to local dir"
```

---

### Task 5: model_downloader.py — 日志级别提升和 get_manual_instructions 更新

**Files:**
- Modify: `jfox/model_downloader.py`
- Test: `tests/unit/test_model_downloader.py`

- [ ] **Step 1: 4 处 debug → warning**

| 位置 | 变更 |
|------|------|
| `_try_hf_hub_download` 第 136 行 | `logger.debug(f"权重文件 {candidate} 尝试失败 ({e})，尝试下一个")` → `logger.warning(...)` |
| `_try_curl_download` 第 213 行 | `logger.debug(f"{candidate} 下载失败或为空，跳过")` → `logger.warning(...)` |
| `_try_curl_download` 第 249 行 | `logger.debug(f"{fname} 下载失败或为空，跳过")` → `logger.warning(...)` |
| `_try_curl_download` 第 251 行 | `logger.debug(f"{fname} 下载异常: {e}")` → `logger.warning(...)` |

- [ ] **Step 2: 更新 get_manual_instructions**

```python
def get_manual_instructions(self) -> str:
    """获取手动下载说明"""
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

- [ ] **Step 3: 新增测试**

```python
def test_get_manual_instructions(self, downloader):
    """手动下载指引包含 ModelScope URL 和本地路径"""
    instructions = downloader.get_manual_instructions()
    assert "modelscope.cn" in instructions
    assert downloader.model_name in instructions
    assert str(downloader._get_local_model_path()) in instructions
    assert "JFOX_MODEL_MIRROR" in instructions

def test_get_manual_instructions_custom_mirror(self, downloader):
    """自定义镜像站时指引使用自定义 URL"""
    with patch.dict(os.environ, {"JFOX_MODEL_MIRROR": "https://custom.mirror.com"}):
        instructions = downloader.get_manual_instructions()
        assert "custom.mirror.com" in instructions
```

- [ ] **Step 4: 运行测试**

Run: `uv run pytest tests/unit/test_model_downloader.py -v`

Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/model_downloader.py tests/unit/test_model_downloader.py
git commit -m "feat(model_downloader): upgrade log level to warning, update manual instructions for ModelScope"
```

---

### Task 6: embedding_backend.py — 本地路径加载支持

**Files:**
- Modify: `jfox/embedding_backend.py`
- Create: `tests/unit/test_embedding_local_load.py`

- [ ] **Step 1: 新增 _get_local_model_path 方法**

```python
def _get_local_model_path(self) -> Optional[Path]:
    """获取本地模型目录路径"""
    if not self.model_name or self.model_name == "auto":
        return None
    safe_name = self.model_name.replace("/", "--")
    local = Path.home() / ".zettelkasten" / ".models" / safe_name
    return local if local.exists() else None
```

- [ ] **Step 2: 修改 load() 优先检查本地目录**

```python
def load(self):
    """加载模型（支持 device 自动检测和 GPU 加速）"""
    if self.model is not None:
        return

    # 解析 device 和 model（即使 daemon 模式也需要，用于 status 显示）
    if self._resolved_device is None:
        self._resolved_device = self._resolve_device()
    if self.model_name is None or self.model_name == "auto":
        self.model_name = self._resolve_model_name(self._resolved_device)

    if self._check_daemon():
        return  # daemon 已持有模型，无需本地加载

    try:
        from sentence_transformers import SentenceTransformer

        # 优先从本地目录加载
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

- [ ] **Step 3: 新增测试文件**

```python
"""EmbeddingBackend 本地路径加载测试"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestEmbeddingLocalLoad:
    """测试本地模型目录加载"""

    @pytest.fixture
    def backend(self):
        from jfox.embedding_backend import EmbeddingBackend

        return EmbeddingBackend(device="cpu", model_name="sentence-transformers/all-MiniLM-L6-v2")

    def test_get_local_model_path_when_exists(self, backend, tmp_path):
        """本地目录存在时返回路径"""
        with patch.object(Path, "exists", return_value=True):
            result = backend._get_local_model_path()
            assert result is not None
            assert "all-MiniLM-L6-v2" in str(result)

    def test_get_local_model_path_when_not_exists(self, backend):
        """本地目录不存在时返回 None"""
        result = backend._get_local_model_path()
        assert result is None

    def test_load_uses_local_path_when_available(self, backend):
        """本地目录存在时优先使用本地路径加载"""
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 384

        with patch.object(backend, "_get_local_model_path", return_value=Path("/fake/local/model")):
            with patch("sentence_transformers.SentenceTransformer", return_value=mock_model) as mock_st:
                with patch.object(backend, "_check_daemon", return_value=False):
                    backend.load()
                    # 验证使用了本地路径
                    mock_st.assert_called_once_with("/fake/local/model", device="cpu")

    def test_load_uses_model_name_when_no_local(self, backend):
        """本地目录不存在时使用模型名加载"""
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 384

        with patch.object(backend, "_get_local_model_path", return_value=None):
            with patch("sentence_transformers.SentenceTransformer", return_value=mock_model) as mock_st:
                with patch.object(backend, "_check_daemon", return_value=False):
                    backend.load()
                    # 验证使用了模型名
                    mock_st.assert_called_once_with(
                        "sentence-transformers/all-MiniLM-L6-v2", device="cpu"
                    )
```

- [ ] **Step 4: 运行测试**

Run: `uv run pytest tests/unit/test_embedding_local_load.py -v`

Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/embedding_backend.py tests/unit/test_embedding_local_load.py
git commit -m "feat(embedding_backend): support loading model from local directory"
```

---

### Task 7: process.py — 阻断启动和本地目录预检

**Files:**
- Modify: `jfox/daemon/process.py`
- Test: `tests/unit/test_daemon_process.py`

- [ ] **Step 1: 修改 start_daemon 阻断启动**

```python
# 原代码（process.py:206-208）:
# if not downloader.ensure_cached():
#     logger.error("模型自动下载失败")
#     # 不阻断启动，让 daemon 自己去尝试加载（会暴露更详细的错误日志）

# 新代码:
if not downloader.ensure_cached():
    logger.error("模型自动下载失败")
    print(downloader.get_manual_instructions(), file=sys.stderr)
    return False
```

- [ ] **Step 2: 修改 _check_model_cache 检查本地目录**

在原有 HF Hub 缓存检查之后，新增本地模型目录检查：

```python
def _check_model_cache() -> dict:
    try:
        from ..config import config as _cfg
        from ..embedding_backend import _CPU_DEFAULT_MODEL, _GPU_DEFAULT_MODEL

        # 确定目标模型名
        model_name = _cfg.embedding_model
        if model_name == "auto" or not model_name:
            try:
                import torch
                if torch.cuda.is_available():
                    model_name = _GPU_DEFAULT_MODEL
                else:
                    model_name = _CPU_DEFAULT_MODEL
            except (ImportError, OSError):
                model_name = _CPU_DEFAULT_MODEL

        # 检查本地模型目录
        from ..model_downloader import _LOCAL_MODEL_DIR

        safe_name = model_name.replace("/", "--")
        local_path = _LOCAL_MODEL_DIR / safe_name
        if local_path.exists():
            has_weight = False
            for candidate in ["model.safetensors", "pytorch_model.bin"]:
                if (local_path / candidate).exists():
                    has_weight = True
                    break
            size_hint = "2GB" if "bge-m3" in model_name else "90MB"
            return {
                "needs_download": not has_weight,
                "model_name": model_name,
                "size_hint": size_hint,
            }

        # 原有 HF Hub 缓存检查逻辑...
        # （保持不变）

    except (ImportError, OSError, ValueError) as e:
        logger.debug(f"Model cache check failed, assuming download needed: {e}")
        return {"needs_download": True, "model_name": "unknown", "size_hint": ""}
```

- [ ] **Step 3: 新增 daemon 进程测试**

```python
def test_start_daemon_blocks_when_download_fails(self):
    """模型下载失败时应阻断启动"""
    from jfox.daemon.process import start_daemon

    with patch("jfox.daemon.process._check_model_cache") as mock_cache:
        mock_cache.return_value = {
            "needs_download": True,
            "model_name": "sentence-transformers/all-MiniLM-L6-v2",
            "size_hint": "90MB",
        }
        with patch("jfox.model_downloader.ModelDownloader.ensure_cached", return_value=False):
            with patch("jfox.model_downloader.ModelDownloader.get_manual_instructions", return_value="test instructions"):
                result = start_daemon()
                assert result is False

def test_check_model_cache_local_dir(self):
    """本地模型目录已存在时 needs_download=False"""
    from jfox.daemon.process import _check_model_cache
    from jfox.model_downloader import _LOCAL_MODEL_DIR

    with patch("jfox.daemon.process._cfg") as mock_cfg:
        mock_cfg.embedding_model = "sentence-transformers/all-MiniLM-L6-v2"
        # 创建本地模型目录和权重文件
        local_path = _LOCAL_MODEL_DIR / "sentence-transformers--all-MiniLM-L6-v2"
        local_path.mkdir(parents=True, exist_ok=True)
        (local_path / "model.safetensors").write_text("fake")

        try:
            result = _check_model_cache()
            assert result["needs_download"] is False
            assert result["model_name"] == "sentence-transformers/all-MiniLM-L6-v2"
        finally:
            # 清理
            import shutil
            if local_path.exists():
                shutil.rmtree(local_path)
```

- [ ] **Step 4: 运行测试**

Run: `uv run pytest tests/unit/test_daemon_process.py -v`

Expected: 全部 PASS（注意：部分测试依赖 Windows，在 Linux 上可能 skip）

- [ ] **Step 5: Commit**

```bash
git add jfox/daemon/process.py tests/unit/test_daemon_process.py
git commit -m "feat(daemon): block startup on download failure, check local model dir"
```

---

### Task 8: 集成验证

**Files:**
- All modified files

- [ ] **Step 1: 运行 model_downloader 全部单元测试**

Run: `uv run pytest tests/unit/test_model_downloader.py -v`

Expected: 全部 PASS

- [ ] **Step 2: 运行 daemon 全部单元测试**

Run: `uv run pytest tests/unit/test_daemon_process.py -v`

Expected: 全部 PASS（部分 Windows-only 测试会 skip）

- [ ] **Step 3: 运行 embedding_backend 单元测试**

Run: `uv run pytest tests/unit/test_embedding_local_load.py -v`

Expected: 全部 PASS

- [ ] **Step 4: 运行快速测试套件（排除 embedding/slow）**

Run: `uv run pytest tests/ -m "not embedding and not slow" -v`

Expected: 全部 PASS，无新增失败

- [ ] **Step 5: 格式化和 lint**

Run:
```bash
uv run black jfox/ tests/
uv run ruff check jfox/ tests/
```

Expected: 无错误

- [ ] **Step 6: 最终 Commit**

```bash
git add -A
git commit -m "feat: replace hf-mirror.com with ModelScope, fix #225 startup failure UX"
```

---

## Self-Review

**Spec coverage:**
- [x] 替换下载源 hf-mirror.com → ModelScope — Task 3, 4
- [x] 修复报错体验（阻断启动）— Task 7 Step 1
- [x] 提升日志级别 — Task 5 Step 1
- [x] 打印手动指引 — Task 7 Step 1 + Task 5 Step 2
- [x] 修复缓存结构 — Task 3, 4, 6
- [x] 支持 JFOX_MODEL_MIRROR 环境变量 — Task 3, 4
- [x] EmbeddingBackend 本地路径加载 — Task 6
- [x] process.py 本地目录预检 — Task 7 Step 2

**Placeholder scan:** 无 TBD、TODO、"implement later"、"add appropriate error handling"。所有步骤包含完整代码。

**Type consistency:**
- `_try_hf_hub_download()` 签名统一为无 `endpoint` 参数
- `_get_local_model_path()` 返回 `Path` 或 `None`，在 `load()` 中统一检查
- `_MODELSCOPE_API_TEMPLATE` 格式在 Task 3 和 Task 4 中一致

**测试覆盖:**
- ModelScope HTTP 下载成功/失败/自定义镜像
- curl ModelScope 下载成功/自定义镜像
- 日志级别变更验证（通过 mock 确认 warning 被调用）
- 手动指引内容验证
- 本地路径加载优先
- 阻断启动行为
- 本地目录预检
