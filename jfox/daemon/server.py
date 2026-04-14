"""
嵌入模型 HTTP 守护进程 - 服务端

常驻后台，加载 sentence-transformers 模型，通过 HTTP API 提供 embedding 编码服务。
入口：python -m jfox.daemon.server --port 18700
"""

import argparse
import logging
import os
from typing import List

from fastapi import FastAPI
from pydantic import BaseModel

logger = logging.getLogger(__name__)

app = FastAPI(title="JFox Embedding Daemon")

# 全局 embedding 后端（模型加载后常驻内存）
_backend = None


@app.on_event("startup")
def _load_model():
    """启动时加载模型（标记为 daemon 进程，防止自引用）"""
    global _backend
    os.environ["JFOX_DAEMON_PROCESS"] = "1"
    from ..embedding_backend import EmbeddingBackend

    _backend = EmbeddingBackend()
    _backend.load()
    logger.info(f"Daemon: 模型已加载 ({_backend.model_name})")


# =============================================================================
# 请求/响应模型
# =============================================================================


class HealthResponse(BaseModel):
    status: str
    model: str
    dimension: int
    pid: int


class EncodeRequest(BaseModel):
    texts: List[str]
    batch_size: int = 32


class EncodeResponse(BaseModel):
    embeddings: List[List[float]]
    dimension: int


class EncodeSingleRequest(BaseModel):
    text: str


class EncodeSingleResponse(BaseModel):
    embedding: List[float]
    dimension: int


# =============================================================================
# API 端点
# =============================================================================


@app.get("/health", response_model=HealthResponse)
def health():
    """健康检查"""
    return HealthResponse(
        status="ok",
        model=_backend.model_name,
        dimension=_backend.dimension,
        pid=os.getpid(),
    )


@app.post("/encode", response_model=EncodeResponse)
def encode(req: EncodeRequest):
    """批量文本编码"""
    embeddings = _backend.encode(req.texts, batch_size=req.batch_size)
    return EncodeResponse(
        embeddings=embeddings.tolist(),
        dimension=_backend.dimension,
    )


@app.post("/encode_single", response_model=EncodeSingleResponse)
def encode_single(req: EncodeSingleRequest):
    """单文本编码"""
    embedding = _backend.encode_single(req.text)
    return EncodeSingleResponse(
        embedding=embedding.tolist(),
        dimension=_backend.dimension,
    )


# =============================================================================
# 入口
# =============================================================================


def main():
    from . import DEFAULT_HOST, DEFAULT_PORT

    parser = argparse.ArgumentParser(description="JFox Embedding Daemon")
    parser.add_argument("--host", default=DEFAULT_HOST, help="监听地址")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="监听端口")
    args = parser.parse_args()

    import uvicorn

    uvicorn.run(app, host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
