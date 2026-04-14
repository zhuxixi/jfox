"""Embedding Backend - 支持 daemon 加速"""

import logging
import os
from typing import List, Optional

import numpy as np

logger = logging.getLogger(__name__)


class EmbeddingBackend:
    """嵌入模型后端（支持 daemon 代理）"""

    def __init__(self, model_name: str = "sentence-transformers/all-MiniLM-L6-v2"):
        self.model_name = model_name
        self.model = None
        self._daemon_client = None  # 延迟初始化
        self._use_daemon: Optional[bool] = None  # None=未检测

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
        """加载模型"""
        if self.model is not None:
            return
        if self._check_daemon():
            return  # daemon 已持有模型，无需本地加载

        try:
            from sentence_transformers import SentenceTransformer

            self.model = SentenceTransformer(self.model_name)
            logger.info(f"模型已加载: {self.model_name}")
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
        """返回嵌入维度"""
        return 384


# Global backend instance
_backend: Optional[EmbeddingBackend] = None


def get_backend() -> EmbeddingBackend:
    """获取全局 embedding 后端实例"""
    global _backend
    if _backend is None:
        _backend = EmbeddingBackend()
    return _backend


def reset_backend():
    """重置全局 embedding 后端（用于测试或特殊场景）"""
    global _backend
    _backend = None
