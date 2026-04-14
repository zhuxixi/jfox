"""嵌入模型守护进程"""

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18700

from .process import get_daemon_status, is_daemon_running, start_daemon, stop_daemon

__all__ = [
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "start_daemon",
    "stop_daemon",
    "is_daemon_running",
    "get_daemon_status",
]
