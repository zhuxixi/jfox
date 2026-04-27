"""模型下载器 - 支持内网自动降级下载"""

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

            # 下载核心文件
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
