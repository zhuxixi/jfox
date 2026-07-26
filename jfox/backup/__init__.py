"""KB 滚动备份/恢复（daemon 调度 + CLI）。

- manager.py：BackupManager（tar+sha256+轮转+可逆恢复）+ BackupCoordinator（quiesce 标志）
- loop.py：daemon backup_loop 定时调度
- schedule.py：每日定点判断
- cli.py：jfox backup / jfox restore 子命令
"""

from .manager import BackupCoordinator, BackupManager

__all__ = ["BackupCoordinator", "BackupManager"]
