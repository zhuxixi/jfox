"""嵌入模型守护进程"""

DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 18700

from .process import DAEMON_LOG_FILE, get_daemon_status, is_daemon_running, start_daemon, stop_daemon

__all__ = [
    "DAEMON_LOG_FILE",
    "DEFAULT_HOST",
    "DEFAULT_PORT",
    "start_daemon",
    "stop_daemon",
    "is_daemon_running",
    "get_daemon_status",
]
