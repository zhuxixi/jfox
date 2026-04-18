"""
Daemon 进程管理

负责启动、停止、查询 daemon 后台进程。
PID 文件存储在 ~/.jfox_daemon.pid。
"""

import json
import logging
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

from . import DEFAULT_HOST, DEFAULT_PORT


def _get_pythonw_executable() -> str:
    """获取 pythonw.exe 路径（Windows 无控制台入口）

    Windows 上优先使用 pythonw.exe 避免 daemon 子进程弹出控制台窗口。
    如果 pythonw.exe 不存在则回退到 sys.executable。
    非 Windows 平台直接返回 sys.executable。
    """
    if sys.platform != "win32":
        return sys.executable

    pythonw = sys.executable.replace("python.exe", "pythonw.exe")
    if pythonw != sys.executable and Path(pythonw).exists():
        return pythonw
    return sys.executable


logger = logging.getLogger(__name__)

STARTUP_TIMEOUT = 60  # 模型加载可能较慢
FIRST_RUN_TIMEOUT = 300  # 首次下载模型超时（秒）
DAEMON_LOG_FILE = Path.home() / ".jfox_daemon.log"
PID_FILE = Path.home() / ".jfox_daemon.pid"


def _read_pid_file() -> Optional[dict]:
    """读取 PID 文件"""
    if not PID_FILE.exists():
        return None
    try:
        return json.loads(PID_FILE.read_text(encoding="utf-8"))
    except Exception:
        return None


def _write_pid_file(data: dict):
    """写入 PID 文件"""
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    logger.debug(f"PID 文件已写入: {PID_FILE}")


def _remove_pid_file():
    """删除 PID 文件"""
    try:
        PID_FILE.unlink()
    except OSError:
        pass


def _get_daemon_url(data: Optional[dict] = None) -> str:
    """获取 daemon URL"""
    if data is None:
        data = _read_pid_file()
    if data is None:
        return f"http://{DEFAULT_HOST}:{DEFAULT_PORT}"
    host = data.get("host", DEFAULT_HOST)
    port = data.get("port", DEFAULT_PORT)
    return f"http://{host}:{port}"


def _http_health_check(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> Optional[dict]:
    """HTTP 健康检查，返回健康信息或 None"""
    try:
        import urllib.request

        resp = urllib.request.urlopen(f"http://{host}:{port}/health", timeout=2)
        return json.loads(resp.read().decode("utf-8"))
    except Exception:
        return None


def is_daemon_running() -> bool:
    """检查 daemon 是否在运行（以 HTTP 健康检查为准）"""
    # 先尝试 PID 文件记录的地址
    data = _read_pid_file()
    if data is not None:
        host = data.get("host", DEFAULT_HOST)
        port = data.get("port", DEFAULT_PORT)
        if _http_health_check(host, port) is not None:
            return True

    # 再尝试默认地址
    if _http_health_check() is not None:
        return True

    return False


def _check_model_cache() -> dict:
    """
    检查当前模型是否已缓存

    Returns:
        dict: {"needs_download": bool, "model_name": str, "size_hint": str}
    """
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
            except Exception:
                model_name = _CPU_DEFAULT_MODEL

        # 检查 HuggingFace 缓存
        hf_home = os.environ.get("HF_HOME", str(Path.home() / ".cache" / "huggingface"))
        hub_cache = os.environ.get("HUGGINGFACE_HUB_CACHE", str(Path(hf_home) / "hub"))
        model_cache_dir = Path(hub_cache) / f"models--{model_name.replace('/', '--')}"

        size_hint = "2GB" if "bge-m3" in model_name else "90MB"

        if model_cache_dir.exists():
            snapshots_dir = model_cache_dir / "snapshots"
            has_files = snapshots_dir.exists() and any(snapshots_dir.iterdir())
            return {
                "needs_download": not has_files,
                "model_name": model_name,
                "size_hint": size_hint,
            }

        return {
            "needs_download": True,
            "model_name": model_name,
            "size_hint": size_hint,
        }
    except Exception as e:
        logger.debug(f"Model cache check failed, assuming download needed: {e}")
        return {"needs_download": True, "model_name": "unknown", "size_hint": ""}


def start_daemon(host: str = DEFAULT_HOST, port: int = DEFAULT_PORT) -> bool:
    """
    启动 daemon 后台进程

    Returns:
        True 表示启动成功
    """
    # 检查是否已在运行
    health = _http_health_check(host, port)
    if health is not None:
        logger.info("Daemon 已在运行")
        _write_pid_file(
            {
                "pid": health.get("pid", 0),
                "host": host,
                "port": port,
                "started_at": time.time(),
            }
        )
        return True

    # 首次启动预检：检查模型缓存是否存在
    timeout = STARTUP_TIMEOUT
    cache_info = _check_model_cache()
    if cache_info["needs_download"]:
        logger.info(
            f"首次启动需要下载模型 {cache_info['model_name']}" f"（约 {cache_info['size_hint']}）"
        )
        timeout = FIRST_RUN_TIMEOUT

    # 构建启动命令（Windows 使用 pythonw.exe 避免控制台窗口）
    cmd = [
        _get_pythonw_executable(),
        "-m",
        "jfox.daemon.server",
        "--host",
        host,
        "--port",
        str(port),
    ]

    kwargs = {}
    if sys.platform == "win32":
        CREATE_NEW_PROCESS_GROUP = 0x00000200
        DETACHED_PROCESS = 0x00000008
        CREATE_NO_WINDOW = 0x08000000
        kwargs["creationflags"] = CREATE_NEW_PROCESS_GROUP | DETACHED_PROCESS | CREATE_NO_WINDOW
    else:
        kwargs["start_new_session"] = True

    # 子进程日志落盘（stdout/stderr → 日志文件）
    log_file = open(DAEMON_LOG_FILE, "a", encoding="utf-8")

    try:
        proc = subprocess.Popen(
            cmd,
            stdout=log_file,
            stderr=log_file,
            stdin=subprocess.DEVNULL,
            **kwargs,
        )
        logger.info(f"Daemon 进程已启动 (PID: {proc.pid})")
        logger.info(f"Daemon 日志文件: {DAEMON_LOG_FILE}")
    except Exception as e:
        log_file.close()
        logger.error(f"启动 daemon 失败: {e}")
        return False

    # 等待 daemon 就绪（用 HTTP 健康检查判断，不用 PID）
    try:
        for i in range(timeout):
            time.sleep(1)
            health = _http_health_check(host, port)
            if health is not None:
                real_pid = health.get("pid", proc.pid)
                _write_pid_file(
                    {
                        "pid": real_pid,
                        "host": host,
                        "port": port,
                        "started_at": time.time(),
                    }
                )
                logger.info(f"Daemon 已就绪 (PID: {real_pid}, port: {port})")
                return True

        logger.warning(f"Daemon 启动超时（{timeout}秒），日志见 {DAEMON_LOG_FILE}")
        return False
    finally:
        log_file.close()


def stop_daemon() -> bool:
    """
    停止 daemon 进程

    Returns:
        True 表示停止成功
    """
    data = _read_pid_file()
    host = DEFAULT_HOST
    port = DEFAULT_PORT
    pid = 0

    if data is not None:
        pid = data.get("pid", 0)
        host = data.get("host", DEFAULT_HOST)
        port = data.get("port", DEFAULT_PORT)

    # 先检查是否真的在跑
    if _http_health_check(host, port) is None:
        _remove_pid_file()
        return True

    # 尝试停止
    if pid > 0:
        try:
            if sys.platform == "win32":
                subprocess.run(
                    ["taskkill", "/PID", str(pid), "/T", "/F"],
                    capture_output=True,
                    timeout=10,
                )
            else:
                os.kill(pid, 15)  # SIGTERM
        except Exception as e:
            logger.warning(f"停止 daemon 失败: {e}")

    # 等待进程退出
    for _ in range(10):
        if _http_health_check(host, port) is None:
            _remove_pid_file()
            logger.info(f"Daemon 已停止 (PID: {pid})")
            return True
        time.sleep(0.5)

    # 超时未退出
    logger.warning(f"Daemon 停止超时 (PID: {pid})")
    _remove_pid_file()
    return False


def get_daemon_status() -> Optional[dict]:
    """获取 daemon 状态信息（含健康检查）"""
    data = _read_pid_file()
    host = data.get("host", DEFAULT_HOST) if data else DEFAULT_HOST
    port = data.get("port", DEFAULT_PORT) if data else DEFAULT_PORT

    health = _http_health_check(host, port)
    if health is None:
        _remove_pid_file()
        return None

    return {
        "pid": health.get("pid", 0),
        "host": host,
        "port": port,
        "model": health.get("model", "unknown"),
        "dimension": health.get("dimension", 384),
        "device": health.get("device", "unknown"),
        "started_at": data.get("started_at") if data else None,
    }
