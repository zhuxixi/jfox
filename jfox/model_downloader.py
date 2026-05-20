"""模型下载器 - 支持内网自动降级下载"""

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
from urllib.parse import quote

logger = logging.getLogger(__name__)

# 重试超时（秒）
_TIMEOUT_HF_HUB = 60
_TIMEOUT_CURL = 120

# 默认镜像站
_DEFAULT_MIRROR = "https://modelscope.cn"

# 本地模型目录
_LOCAL_MODEL_DIR = Path.home() / ".zettelkasten" / ".models"

# ModelScope API 模板
_MODELSCOPE_API_TEMPLATE = (
    "{mirror}/api/v1/models/{model_id}/repo" "?FilePath={file_path}&Revision=master"
)

# 权重文件候选列表（按优先级排序：safetensors 优先，PyTorch 回退）
_WEIGHT_FILE_CANDIDATES = [
    "model.safetensors",
    "pytorch_model.bin",
]

# 非权重必需文件列表
_REQUIRED_FILES = [
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
        # 同时替换正反斜杠，防止路径遍历
        safe_name = model_name.replace("/", "--").replace("\\", "--")
        self._model_cache = self._hf_hub_cache / f"models--{safe_name}"

    def _get_hf_hub_cache(self) -> Path:
        """获取 HuggingFace Hub 缓存目录"""
        try:
            import huggingface_hub.constants

            return Path(huggingface_hub.constants.HUGGINGFACE_HUB_CACHE)
        except ImportError:
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

        # Step 2: 重试 huggingface_hub 下载
        logger.info("步骤 2: 重试 huggingface_hub 下载...")
        if self._try_hf_hub_download():
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
        """检查模型是否已缓存（HF Hub 缓存或本地目录）"""
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
        # 检查至少有一个 snapshot 且包含权重文件
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

    def _try_hf_hub_download(self) -> bool:
        """
        使用 huggingface_hub 直接下载模型。
        """
        try:
            from huggingface_hub import hf_hub_download

            # 按优先级尝试下载权重文件
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
                    logger.debug(f"权重文件 {candidate} 尝试失败 ({e})，尝试下一个")
                    continue

            if not weight_downloaded:
                logger.warning("所有权重文件候选均下载失败")
                return False

            # 尝试下载其他必要文件（不失败）
            for fname in _REQUIRED_FILES:
                try:
                    hf_hub_download(
                        repo_id=self.model_name,
                        filename=fname,
                        cache_dir=str(self._hf_hub_cache),
                        local_files_only=False,
                    )
                except (OSError, ValueError):
                    pass  # 非核心文件，缺失不影响基本功能

            return True
        except Exception as e:
            logger.warning(f"huggingface_hub 下载失败: {e}")
            return False

    def _try_curl_download(self) -> bool:
        """
        使用 curl 子进程下载模型文件到 HF 缓存目录。
        按 HF 缓存目录结构放置，使 sentence-transformers 认为"模型已缓存"。
        """
        if not shutil.which("curl"):
            logger.warning("系统未安装 curl，跳过步骤 3")
            return False

        # 构建镜像站 URL（对模型名进行 URL 编码，防止特殊字符破坏 URL）
        encoded_name = quote(self.model_name, safe="/")
        base_url = f"{_DEFAULT_MIRROR}/{encoded_name}/resolve/main"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            downloaded = []

            # 按优先级尝试下载权重文件
            weight_downloaded = False
            for candidate in _WEIGHT_FILE_CANDIDATES:
                url = f"{base_url}/{candidate}"
                dest = tmp_path / candidate
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
                        downloaded.append(candidate)
                        weight_downloaded = True
                        break
                    else:
                        logger.debug(f"{candidate} 下载失败或为空，跳过")
                except (OSError, subprocess.TimeoutExpired) as e:
                    logger.debug(f"{candidate} 下载异常: {e}")

            if not weight_downloaded:
                logger.error("所有权重文件候选下载失败，步骤 3 未完成")
                return False

            # 下载非权重必需文件
            for fname in _REQUIRED_FILES:
                url = f"{base_url}/{fname}"
                dest = tmp_path / fname
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
                        downloaded.append(fname)
                    else:
                        logger.debug(f"{fname} 下载失败或为空，跳过")
                except (OSError, subprocess.TimeoutExpired) as e:
                    logger.debug(f"{fname} 下载异常: {e}")

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
        candidates = " / ".join(_WEIGHT_FILE_CANDIDATES)
        return (
            f"自动下载失败。请手动下载模型:\n"
            f"  1. 访问 {_DEFAULT_MIRROR}/{self.model_name}\n"
            f"  2. 下载权重文件（{candidates}）和 config.json\n"
            f"  3. 放置到 {self._model_cache}/snapshots/\n"
            f"  或运行: bash scripts/download-model-intranet.sh"
        )
