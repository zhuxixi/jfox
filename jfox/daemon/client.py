"""
嵌入模型 HTTP 客户端

通过 HTTP 调用 daemon 获取 embedding，接口与 EmbeddingBackend 一致。
"""

import json
import time
from typing import List, Optional

import numpy as np

# 健康检查结果缓存时间（秒）
_HEALTH_CACHE_TTL = 30.0

# HTTP 请求超时（秒）
_REQUEST_TIMEOUT = 120.0
_HEALTH_TIMEOUT = 2.0


class DaemonClient:
    """HTTP 客户端，代理 embedding 请求到 daemon"""

    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")
        self._health_cache_time: float = 0.0
        self._health_cache_result: Optional[bool] = None
        self._dimension: int = 384

    @property
    def available(self) -> bool:
        """检查 daemon 是否可用（带缓存）"""
        now = time.time()
        cached = self._health_cache_result
        if cached is not None and (now - self._health_cache_time) < _HEALTH_CACHE_TTL:
            return cached

        try:
            import urllib.request

            resp = urllib.request.urlopen(f"{self.base_url}/health", timeout=_HEALTH_TIMEOUT)
            data = json.loads(resp.read().decode("utf-8"))
            self._dimension = data.get("dimension", 384)
            self._health_cache_result = True
        except Exception:
            self._health_cache_result = False

        self._health_cache_time = now
        return self._health_cache_result

    def encode(self, texts: List[str], batch_size: int = 32) -> np.ndarray:
        """批量文本编码"""
        import urllib.request

        payload = json.dumps({"texts": texts, "batch_size": batch_size}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/encode",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        resp = urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT)
        result = json.loads(resp.read().decode("utf-8"))

        return np.array(result["embeddings"], dtype=np.float32)

    def encode_single(self, text: str) -> np.ndarray:
        """单文本编码"""
        import urllib.request

        payload = json.dumps({"text": text}).encode("utf-8")
        req = urllib.request.Request(
            f"{self.base_url}/encode_single",
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )

        resp = urllib.request.urlopen(req, timeout=_REQUEST_TIMEOUT)
        result = json.loads(resp.read().decode("utf-8"))

        return np.array(result["embedding"], dtype=np.float32)

    @property
    def model_name(self) -> str:
        """获取模型名称"""
        try:
            import urllib.request

            resp = urllib.request.urlopen(f"{self.base_url}/health", timeout=_HEALTH_TIMEOUT)
            data = json.loads(resp.read().decode("utf-8"))
            return data.get("model", "unknown")
        except Exception:
            return "daemon"

    @property
    def dimension(self) -> int:
        return self._dimension
