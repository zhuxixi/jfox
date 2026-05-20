"""模型下载器 - 支持内网自动降级下载"""

import logging
import os
import shutil
import subprocess
from pathlib import Path
from urllib.parse import quote
from urllib.request import urlopen

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


def _safe_model_name(model_name: str) -> str:
    """将模型名转换为安全的目录名，防止路径遍历"""
    return model_name.replace("/", "--").replace("\\", "--").replace("..", "--")


def _get_local_model_path_for_name(model_name: str) -> Path:
    """获取指定模型名的本地目录路径"""
    return _LOCAL_MODEL_DIR / _safe_model_name(model_name)


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
        safe_name = _safe_model_name(model_name)
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

        # Step 2: ModelScope HTTP 下载
        logger.info("步骤 2: 使用 ModelScope HTTP 下载...")
        if self._try_modelscope_http():
            logger.info("步骤 2 成功，模型已缓存")
            return True
        logger.warning("步骤 2 失败，进入步骤 3")

        # Step 3: curl 子进程下载
        logger.info("步骤 3: 使用 curl 从 ModelScope 下载...")
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
        return _get_local_model_path_for_name(self.model_name)

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
                    logger.warning(f"权重文件 {candidate} 尝试失败 ({e})，尝试下一个")
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

    def _try_modelscope_http(self) -> bool:
        """
        使用 urllib.request 从 ModelScope HTTP 下载模型文件到本地目录。
        """
        mirror = os.environ.get("JFOX_MODEL_MIRROR", _DEFAULT_MIRROR).rstrip("/")
        local_path = self._get_local_model_path()
        local_path.mkdir(parents=True, exist_ok=True)

        # 按优先级尝试下载权重文件（先写入临时文件，成功后重命名）
        weight_downloaded = False
        for candidate in _WEIGHT_FILE_CANDIDATES:
            url = _MODELSCOPE_API_TEMPLATE.format(
                mirror=mirror,
                model_id=quote(self.model_name, safe=""),
                file_path=quote(candidate, safe=""),
            )
            dest = local_path / candidate
            tmp_dest = local_path / f".{candidate}.tmp"
            logger.info(f"试用权重文件 {candidate}...")
            try:
                with urlopen(url, timeout=60) as resp:
                    with open(tmp_dest, "wb") as f:
                        f.write(resp.read())
                if tmp_dest.exists() and tmp_dest.stat().st_size > 0:
                    tmp_dest.replace(dest)
                    logger.info(f"权重文件 {candidate} 下载成功")
                    weight_downloaded = True
                    break
                else:
                    logger.warning(f"权重文件 {candidate} 下载后为空，尝试下一个")
                    tmp_dest.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"权重文件 {candidate} 下载失败 ({e})，尝试下一个")
                tmp_dest.unlink(missing_ok=True)
                continue

        if not weight_downloaded:
            logger.warning("所有权重文件候选均下载失败")
            self._cleanup_partial(local_path)
            return False

        # 下载其他必需文件（config.json 必须成功）
        for fname in _REQUIRED_FILES:
            url = _MODELSCOPE_API_TEMPLATE.format(
                mirror=mirror,
                model_id=quote(self.model_name, safe=""),
                file_path=quote(fname, safe=""),
            )
            dest = local_path / fname
            tmp_dest = local_path / f".{fname}.tmp"
            try:
                with urlopen(url, timeout=60) as resp:
                    with open(tmp_dest, "wb") as f:
                        f.write(resp.read())
                if tmp_dest.exists() and tmp_dest.stat().st_size > 0:
                    tmp_dest.replace(dest)
                else:
                    logger.warning(f"{fname} 下载后为空，跳过")
                    tmp_dest.unlink(missing_ok=True)
            except Exception as e:
                logger.warning(f"{fname} 下载失败 ({e})，跳过")
                tmp_dest.unlink(missing_ok=True)

        # 验证 config.json 存在（SentenceTransformer 必需）
        if not (local_path / "config.json").exists():
            logger.error("config.json 下载失败，模型不完整")
            self._cleanup_partial(local_path)
            return False

        return True

    def _try_curl_download(self) -> bool:
        """
        使用 curl 子进程从 ModelScope API 下载模型文件到本地目录。
        """
        if not shutil.which("curl"):
            logger.warning("系统未安装 curl，跳过步骤 3")
            return False

        mirror = os.environ.get("JFOX_MODEL_MIRROR", _DEFAULT_MIRROR).rstrip("/")
        local_path = self._get_local_model_path()
        local_path.mkdir(parents=True, exist_ok=True)

        # 按优先级尝试下载权重文件
        weight_downloaded = False
        for candidate in _WEIGHT_FILE_CANDIDATES:
            url = _MODELSCOPE_API_TEMPLATE.format(
                mirror=mirror,
                model_id=quote(self.model_name, safe=""),
                file_path=quote(candidate, safe=""),
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
            logger.error("所有权重文件候选下载失败，步骤 3 未完成")
            self._cleanup_partial(local_path)
            return False

        # 下载非权重必需文件
        for fname in _REQUIRED_FILES:
            url = _MODELSCOPE_API_TEMPLATE.format(
                mirror=mirror,
                model_id=quote(self.model_name, safe=""),
                file_path=quote(fname, safe=""),
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
                    pass  # 下载成功
                else:
                    logger.warning(f"{fname} 下载失败或为空，跳过")
            except (OSError, subprocess.TimeoutExpired) as e:
                logger.warning(f"{fname} 下载异常: {e}")

        # 验证 config.json 存在
        if not (local_path / "config.json").exists():
            logger.error("config.json 下载失败，模型不完整")
            self._cleanup_partial(local_path)
            return False

        return True

    def _cleanup_partial(self, local_path: Path):
        """下载失败时清理残留文件和空目录"""
        try:
            # 清理临时文件
            for tmp in local_path.glob(".*.tmp"):
                tmp.unlink(missing_ok=True)
            # 如果目录为空则删除
            if local_path.exists() and not any(local_path.iterdir()):
                local_path.rmdir()
        except OSError:
            pass

    def get_manual_instructions(self) -> str:
        """获取手动下载说明"""
        mirror = os.environ.get("JFOX_MODEL_MIRROR", _DEFAULT_MIRROR).rstrip("/")
        candidates = " / ".join(_WEIGHT_FILE_CANDIDATES)
        local_path = self._get_local_model_path()
        return (
            f"自动下载失败。请手动下载模型:\n"
            f"  1. 访问 {mirror}/models/{self.model_name}\n"
            f"  2. 下载权重文件（{candidates}）和 config.json\n"
            f"  3. 放置到 {local_path}/\n"
            f"  或设置环境变量 JFOX_MODEL_MIRROR 使用其他镜像"
        )
