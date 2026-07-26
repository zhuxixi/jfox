"""CLI subapp: jfox backup / jfox restore

子命令：
- run [--quiet]               立即手动备份（不停 daemon，靠崩溃一致；定时备份由
                              daemon loop 跑、有 quiesce 加持更干净）
- enable [--time] [--retain]  开启 daemon 定时调度
- disable                     关闭 daemon 定时调度
- status                      配置 + last_run + 快照数
- list                        列快照
- verify <snapshot>           校验快照完整性
- restore <snapshot> [--yes]  从快照恢复（独立进程，会停 daemon 拿干净快照）

设计说明：此模块子命令未采用主 cli.py 的 @app.command() → _impl() 拆分模式，
与 auto_summary/cli.py 同理——子命令简短，紧凑可读比形式统一更重要。
"""

from __future__ import annotations

import json as _json
from pathlib import Path

import typer
from rich.console import Console
from rich.table import Table

from ..global_config import DEFAULT_KB_PATH, get_global_config_manager

console = Console(legacy_windows=False)

backup_app = typer.Typer(
    name="backup",
    help="KB 滚动备份/恢复：daemon 定时备份 + 手动 run/restore",
    no_args_is_help=True,
)


def _cfg():
    return get_global_config_manager().get_backup_config()


def _backup_root() -> Path:
    cfg = _cfg()
    return Path(cfg.backup_root) if cfg.backup_root else Path.home() / ".jfox-backup"


def _make_mgr():
    from .manager import BackupManager

    cfg = _cfg()
    return BackupManager(
        backup_root=_backup_root(),
        kb_root=DEFAULT_KB_PATH,
        config_path=Path.home() / ".zk_config.json",
        retain=cfg.retain,
    )


@backup_app.command("status")
def status():
    """显示备份配置与上次运行情况"""
    cfg = _cfg()
    t = Table(title="JFox Backup")
    t.add_column("属性")
    t.add_column("值")
    t.add_row("enabled", "是" if cfg.enabled else "否")
    t.add_row("schedule_time", cfg.schedule_time)
    t.add_row("retain", str(cfg.retain))
    t.add_row("backup_root", str(_backup_root()))
    state_p = _backup_root() / "state.json"
    if state_p.exists():
        st = _json.loads(state_p.read_text(encoding="utf-8"))
        t.add_row("last_run", st.get("last_run", "-"))
        t.add_row("last_ok", "成功" if st.get("last_ok") else "失败")
    else:
        t.add_row("last_run", "-（尚未运行）")
    console.print(t)


@backup_app.command("enable")
def enable(
    time: str = typer.Option("08:00", "--time", help="每日备份时刻 HH:MM"),
    retain: int = typer.Option(7, "--retain", help="滚动保留份数"),
):
    """开启 daemon 定时备份调度（daemon 每 tick reload，下个 tick 生效）"""
    get_global_config_manager().update_backup_config(
        enabled=True, schedule_time=time, retain=retain
    )
    console.print(f"[green]已启用[/green] backup：每天 {time}，保留 {retain} 份")
    console.print("[dim]提示：daemon 每 tick reload 配置，新调度下个 tick 生效（≤5min）[/dim]")


@backup_app.command("disable")
def disable():
    """关闭 daemon 定时备份"""
    get_global_config_manager().update_backup_config(enabled=False)
    console.print("[green]已禁用[/green] backup 定时调度")


@backup_app.command("run")
def run(
    quiet: bool = typer.Option(False, "--quiet", help="成功时不打印"),
):
    """立即手动备份一份（不停 daemon，靠崩溃一致）"""
    mgr = _make_mgr()
    archive = mgr.backup()
    if not quiet:
        console.print(f"[green]备份成功[/green]：{archive}")


@backup_app.command("list")
def list_cmd():
    """列出已有快照"""
    snaps = _make_mgr().list_snapshots()
    if not snaps:
        console.print("[dim]无快照[/dim]")
        return
    t = Table(title="Snapshots")
    t.add_column("archive")
    t.add_column("size")
    t.add_column("ok")
    for s in snaps:
        t.add_row(s["archive"], str(s["size"]), "✓" if s["ok"] else "✗")
    console.print(t)


@backup_app.command("verify")
def verify_cmd(
    snapshot: str = typer.Argument(..., help="快照文件名（daily/ 下）或绝对路径"),
):
    """校验快照完整性（sha256 + tar）"""
    p = Path(snapshot)
    if not p.is_absolute():
        p = _backup_root() / "daily" / snapshot
    ok = _make_mgr().verify(p)
    console.print("[green]校验通过[/green]" if ok else "[red]校验失败[/red]")
    raise typer.Exit(0 if ok else 1)


@backup_app.command("restore")
def restore_cmd(
    snapshot: str = typer.Argument(..., help="快照文件名或绝对路径"),
    yes: bool = typer.Option(False, "--yes", help="跳过确认"),
):
    """从快照恢复 KB（可逆：当前态自动 rename 旁置为 .pre-restore-*）"""
    p = Path(snapshot)
    if not p.is_absolute():
        p = _backup_root() / "daily" / snapshot
    if not yes:
        console.print(f"[yellow]将用 {p} 恢复 ~/.zettelkasten + ~/.zk_config.json[/yellow]")
        console.print("[dim]当前态会 rename 旁置为 .pre-restore-*（安全可逆）[/dim]")
        if not typer.confirm("确认恢复？", default=False):
            raise typer.Abort()
    _make_mgr().restore(p, yes=True)
    console.print(f"[green]恢复完成[/green]：{p}")
