"""Embedding Backend - 支持 daemon 加速 + GPU (CUDA)"""

import logging
import os
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)

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
        except Exception:
            # ImportError: torch 未安装; 其他: CUDA 驱动异常等
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
        # daemon 模式下从 daemon client 获取维度
        if self._daemon_client is not None:
            return self._daemon_client.dimension
        # 未加载时：如果 model_name 已确定，估算维度
        if self.model_name and self.model_name != "auto":
            if "bge-m3" in self.model_name or "bge-large" in self.model_name:
                return 1024
        return 384  # 默认 MiniLM 维度

    @property
    def resolved_device(self) -> str:
        """实际使用的设备（auto 解析后）"""
        return self._resolved_device or "unknown"


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
