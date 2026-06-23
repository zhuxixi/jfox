"""
嵌入模型 HTTP 守护进程 - 服务端

常驻后台，加载 sentence-transformers 模型，通过 HTTP API 提供 embedding 编码服务。
入口：python -m jfox.daemon.server --port 18700
"""

import argparse
import asyncio
import logging
import os
import threading
from contextlib import asynccontextmanager
from typing import List, Optional

from fastapi import FastAPI, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# 全局 embedding 后端（模型加载后常驻内存）
_backend = None

# uvicorn Server 实例（用于 graceful shutdown）
_server = None

# auto-summary 后台 task 与停止信号
_auto_summary_task: Optional[asyncio.Task] = None
_auto_summary_stop_event: Optional[threading.Event] = None

# gem-synthesis 后台 task 与停止信号
_gem_synth_task: Optional[asyncio.Task] = None
_gem_synth_stop_event: Optional[threading.Event] = None


def _load_model():
    """启动时加载模型（标记为 daemon 进程，防止自引用）"""
    global _backend
    os.environ["JFOX_DAEMON_PROCESS"] = "1"
    from ..config import config
    from ..embedding_backend import EmbeddingBackend

    model_name = config.embedding_model if config.embedding_model != "auto" else None
    _backend = EmbeddingBackend(device=config.device, model_name=model_name)
    try:
        _backend.load()
        logger.info(
            f"Daemon: 模型已加载 {_backend.model_name} "
            f"(device={_backend._resolved_device}, dimension={_backend._resolved_dim})"
        )
    except Exception as e:
        logger.error(f"Daemon: 模型加载失败，进程退出: {e}")
        os._exit(1)


def _maybe_init_fragment_store() -> None:
    """daemon 启动时按配置打开常驻 FragmentStore（热连接，单一写者）；禁用则跳过。"""
    from ..fragment import set_default_store
    from ..fragment.store import FragmentStore
    from ..global_config import get_global_config_manager

    try:
        cfg = get_global_config_manager().get_fragment_capture_config()
        if not cfg.enabled:
            logger.info("Daemon: fragment_capture 未启用，跳过 FragmentStore 初始化")
            set_default_store(None)
            return
        set_default_store(FragmentStore())
        logger.info("Daemon: FragmentStore 已初始化")
    except Exception as e:
        logger.exception("Daemon: 初始化 FragmentStore 失败（碎片采集不可用）: %s", e)
        set_default_store(None)


def _maybe_close_fragment_store() -> None:
    """daemon 关闭时释放 store 连接，确保全局引用被清空"""
    from ..fragment import set_default_store
    from ..fragment.service import get_default_store

    try:
        try:
            store = get_default_store()
            if store is not None:
                store.close()
        finally:
            set_default_store(None)
    except Exception as e:
        logger.warning("Daemon: 关闭 FragmentStore 时异常: %s", e)


def _maybe_start_auto_summary() -> None:
    """如果用户启用了 auto-summary，启动后台循环 task"""
    global _auto_summary_task, _auto_summary_stop_event
    try:
        from ..auto_summary.loop import auto_summary_loop
        from ..global_config import get_global_config_manager

        cfg = get_global_config_manager().get_auto_summary_config()
        if not cfg.enabled:
            logger.info("Daemon: auto-summary 未启用（config.auto_summary.enabled=false）")
            return

        _auto_summary_stop_event = threading.Event()
        _auto_summary_task = asyncio.create_task(auto_summary_loop(_auto_summary_stop_event))
        logger.info(
            "Daemon: auto-summary 后台循环已启动 (interval=%dm, idle_threshold=%dm)",
            cfg.interval_minutes,
            cfg.idle_threshold_minutes,
        )
    except Exception as e:
        logger.exception("Daemon: 启动 auto-summary 后台循环失败: %s", e)


async def _maybe_stop_auto_summary() -> None:
    """关闭 auto-summary 后台循环（lifespan shutdown 阶段调用）"""
    global _auto_summary_task, _auto_summary_stop_event
    if _auto_summary_stop_event is not None:
        _auto_summary_stop_event.set()
    if _auto_summary_task is not None:
        try:
            # stop_event 已 set，_run_claude 会在 ~1s 内终止子进程
            await asyncio.wait_for(_auto_summary_task, timeout=10)
        except asyncio.TimeoutError:
            logger.warning("Daemon: auto-summary task 10s 内未退出，取消之")
            _auto_summary_task.cancel()
            try:
                await asyncio.gather(_auto_summary_task, return_exceptions=True)
            except Exception as inner:
                logger.warning("Daemon: 等待 auto-summary 取消时异常: %s", inner)
        except Exception as e:
            logger.warning("Daemon: 等待 auto-summary 退出时异常: %s", e)
            _auto_summary_task.cancel()
            try:
                await asyncio.gather(_auto_summary_task, return_exceptions=True)
            except Exception:
                pass
    _auto_summary_task = None
    _auto_summary_stop_event = None


def _maybe_start_gem_synth() -> None:
    """如果用户启用了 gem-synthesis，启动后台循环 task"""
    global _gem_synth_task, _gem_synth_stop_event
    try:
        from ..gem_synth.loop import gem_synth_loop
        from ..global_config import get_global_config_manager

        cfg = get_global_config_manager().get_gem_synthesis_config()
        if not cfg.enabled:
            logger.info("Daemon: gem-synthesis 未启用（config.gem_synthesis.enabled=false）")
            return

        _gem_synth_stop_event = threading.Event()
        _gem_synth_task = asyncio.create_task(
            gem_synth_loop(_gem_synth_stop_event, cfg.interval_minutes)
        )
        logger.info("Daemon: gem-synthesis 后台循环已启动 (interval=%dm)", cfg.interval_minutes)
    except Exception as e:
        logger.exception("Daemon: 启动 gem-synthesis 后台循环失败: %s", e)


async def _maybe_stop_gem_synth() -> None:
    """关闭 gem-synthesis 后台循环（lifespan shutdown 阶段调用）"""
    global _gem_synth_task, _gem_synth_stop_event
    if _gem_synth_stop_event is not None:
        _gem_synth_stop_event.set()
    if _gem_synth_task is not None:
        try:
            await asyncio.wait_for(_gem_synth_task, timeout=10)
        except asyncio.TimeoutError:
            logger.warning("Daemon: gem-synthesis task 10s 内未退出，取消之")
            _gem_synth_task.cancel()
            try:
                await asyncio.gather(_gem_synth_task, return_exceptions=True)
            except Exception as inner:
                logger.warning("Daemon: 等待 gem-synthesis 取消时异常: %s", inner)
        except Exception as e:
            logger.warning("Daemon: 等待 gem-synthesis 退出时异常: %s", e)
            _gem_synth_task.cancel()
            # return_exceptions=True 时 gather 不抛异常，无需 try/except
            await asyncio.gather(_gem_synth_task, return_exceptions=True)
    _gem_synth_task = None
    _gem_synth_stop_event = None


@asynccontextmanager
async def lifespan(app):
    _load_model()
    _maybe_start_auto_summary()
    _maybe_start_gem_synth()
    _maybe_init_fragment_store()
    try:
        yield
    finally:
        await _maybe_stop_gem_synth()
        await _maybe_stop_auto_summary()
        _maybe_close_fragment_store()


app = FastAPI(title="JFox Embedding Daemon", lifespan=lifespan)


# =============================================================================
# 请求/响应模型
# =============================================================================


class HealthResponse(BaseModel):
    status: str
    model: str
    dimension: int
    device: str  # 实际使用的设备
    pid: int


class EncodeRequest(BaseModel):
    texts: List[str]
    batch_size: int = 32


class EncodeResponse(BaseModel):
    embeddings: List[List[float]]
    dimension: int


class EncodeSingleRequest(BaseModel):
    text: str


class ShutdownResponse(BaseModel):
    status: str


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
        device=_backend.resolved_device,
        pid=os.getpid(),
    )


@app.post("/shutdown", response_model=ShutdownResponse)
def shutdown():
    """请求 daemon 自行停止"""
    if _server:
        _server.should_exit = True
    return ShutdownResponse(status="shutting_down")


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


@app.get("/auto_summary/status")
def auto_summary_status():
    """auto-summary 后台循环状态（仅供调试观察）"""
    from ..auto_summary.ledger import Ledger
    from ..global_config import get_global_config_manager

    cfg = get_global_config_manager().get_auto_summary_config()
    running = _auto_summary_task is not None and not _auto_summary_task.done()
    try:
        ledger_stats = Ledger().stats()
    except Exception as e:
        ledger_stats = {"error": str(e)}

    return {
        "config": {
            "enabled": cfg.enabled,
            "interval_minutes": cfg.interval_minutes,
            "idle_threshold_minutes": cfg.idle_threshold_minutes,
            "max_per_tick": cfg.max_per_tick,
            "target_kb": cfg.target_kb,
        },
        "task_running": running,
        "ledger": ledger_stats,
    }


# =============================================================================
# 碎片采集（Phase 1：Hook → Daemon REST API）
# =============================================================================


@app.post("/api/fragment")
def capture_fragment(event: dict):
    """接收 CC hook POST 的原始事件 JSON，分类后写入 SQLite。

    请求体即 CC 事件的 stdin JSON（UserPromptSubmit / PostToolUse / Stop）。
    """
    from ..fragment import ingest_event

    return ingest_event(event)


@app.get("/api/fragments")
def list_fragments(
    session: Optional[str] = None,
    type: Optional[str] = None,
    limit: int = Query(default=20, ge=1, le=1000),
):
    """按 session / type 查询碎片（最新在前）。复用 daemon 常驻 store；未启用则返回空。"""
    from ..fragment.service import get_default_store

    store = get_default_store()
    if store is None:
        # 未启用（enabled=false）或 daemon 未初始化：不创建 store，返回空（尊重禁用决策，
        # 避免 enabled=false 时兜底创建 fragments.db）
        return {"fragments": [], "total": 0}
    try:
        rows = store.query(session_id=session, fragment_type=type, limit=limit)
    except Exception as e:
        # 含 shutdown 竞态：请求持有 store 引用后 lifespan 关闭了连接 → ProgrammingError
        logger.exception("list_fragments: 查询失败: %s", e)
        return {"fragments": [], "total": 0, "error": str(e)}
    return {"fragments": rows, "total": len(rows)}


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

    global _server
    config = uvicorn.Config(app, host=args.host, port=args.port, log_level="warning")
    _server = uvicorn.Server(config)
    _server.run()


if __name__ == "__main__":
    main()
