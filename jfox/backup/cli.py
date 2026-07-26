"""CLI subapp: jfox backup / jfox restore

子命令：
- run [--quiet]               立即手动备份（不停 daemon，靠崩溃一致；定时备份由
                              daemon loop 跑、有 quiesce 加持更干净）
- enable [--time] [--retain]  开启 daemon 定时调度（首次启用/改时间需重启 daemon）
- disable                     关闭 daemon 定时调度
- status [-f json]            配置 + last_run
- list  [-f json]             列快照
- verify <snapshot> [-f json] 校验快照完整性
- restore <snapshot> [--yes]  从快照恢复（独立进程，会停 daemon 拿干净快照）

设计说明：此模块子命令未采用主 cli.py 的 @app.command() → _impl() 拆分模式，
与 auto_summary/cli.py 同理——子命令简短，紧凑可读比形式统一更重要。
"""

from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Any, Optional

import typer
from rich.console import Console
from rich.table import Table

from ..global_config import DEFAULT_KB_PATH, get_global_config_manager
from .schedule import parse_time

console = Console(legacy_windows=False)

backup_app = typer.Typer(
    name="backup",
    help="KB 滚动备份/恢复：daemon 定时备份 + 手动 run/restore",
    no_args_is_help=True,
)


def _fmt(table: Optional[Table] = None, json_data: Any = None, fmt: str = "table") -> None:
    """统一输出路由：fmt=json 输出 JSON，否则渲染 Table"""
    if fmt == "json":
        console.print(_json.dumps(json_data, ensure_ascii=False, indent=2))
    elif table is not None:
        console.print(table)


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


def _resolve_snapshot(snapshot: str) -> Path:
    """展开 ~ + 相对路径解析到 backup_root/daily/；相对名不得逃逸 daily/（CR #4/#8）"""
    expanded = Path(snapshot).expanduser()
    if expanded.is_absolute():
        return expanded
    daily = (_backup_root() / "daily").resolve()
    resolved = (daily / snapshot).resolve()
    try:
        resolved.relative_to(daily)
    except ValueError:
        raise typer.BadParameter(f"快照名不得逃逸 daily/ 目录: {snapshot}")
    return resolved


@backup_app.command("status")
def status(
    format: str = typer.Option("table", "--format", "-f", help="输出格式 table|json"),
):
    """显示备份配置与上次运行情况"""
    cfg = _cfg()
    state_p = _backup_root() / "state.json"
    state = {}
    if state_p.exists():
        try:
            state = _json.loads(state_p.read_text(encoding="utf-8"))
        except (ValueError, OSError):
            state = {}
    data = {
        "enabled": cfg.enabled,
        "schedule_time": cfg.schedule_time,
        "retain": cfg.retain,
        "backup_root": str(_backup_root()),
        "last_run": state.get("last_run"),
        "last_ok": state.get("last_ok"),
    }
    if format == "json":
        _fmt(json_data=data, fmt="json")
        return
    t = Table(title="JFox Backup")
    t.add_column("属性")
    t.add_column("值")
    t.add_row("enabled", "是" if cfg.enabled else "否")
    t.add_row("schedule_time", cfg.schedule_time)
    t.add_row("retain", str(cfg.retain))
    t.add_row("backup_root", str(_backup_root()))
    t.add_row("last_run", data["last_run"] or "-（尚未运行）")
    t.add_row(
        "last_ok", "成功" if state.get("last_ok") else ("失败" if "last_ok" in state else "-")
    )
    _fmt(table=t, fmt=format)


@backup_app.command("enable")
def enable(
    time: str = typer.Option("08:00", "--time", help="每日备份时刻 HH:MM"),
    retain: int = typer.Option(7, "--retain", help="滚动保留份数"),
):
    """开启 daemon 定时备份调度（首次启用/改 schedule_time 需重启 daemon 生效）"""
    # 校验输入，拒绝非法值而非静默强改（CR #9）
    try:
        parse_time(time)
    except ValueError:
        raise typer.BadParameter(f"时间格式应为 HH:MM（如 08:00），得到: {time}")
    if retain < 1:
        raise typer.BadParameter(f"retain 必须 >= 1，得到: {retain}")

    get_global_config_manager().update_backup_config(
        enabled=True, schedule_time=time, retain=retain
    )
    actual = _cfg()  # 回显实际持久化（normalize 后）的值，避免回显失真
    console.print(
        f"[green]已启用[/green] backup：每天 {actual.schedule_time}，保留 {actual.retain} 份"
    )
    console.print(
        "[dim]提示：首次启用或改 schedule_time 需重启 daemon 生效"
        "（jfox daemon stop && jfox daemon start），与 auto-summary/gem-synth 一致[/dim]"
    )


@backup_app.command("disable")
def disable():
    """关闭 daemon 定时备份"""
    get_global_config_manager().update_backup_config(enabled=False)
    console.print("[green]已禁用[/green] backup 定时调度")


@backup_app.command("run")
def run(
    quiet: bool = typer.Option(False, "--quiet", help="成功时不打印"),
):
    """立即手动备份一份（停 daemon 拿干净快照，与 restore 同；写 state.json）"""
    from .loop import write_backup_state

    mgr = _make_mgr()
    try:
        was_running = mgr.prepare_clean_snapshot()
    except Exception as e:
        console.print(f"[red]无法停 daemon，取消备份：{e}[/red]")
        raise typer.Exit(1)
    try:
        archive = mgr.backup()
        write_backup_state(_backup_root(), True, archive.name)
    except Exception as e:
        write_backup_state(_backup_root(), False, None)
        console.print(f"[red]备份失败：{e}[/red]")
        raise typer.Exit(1)
    finally:
        mgr.restore_daemon(was_running)
    if not quiet:
        console.print(f"[green]备份成功[/green]：{archive}")


@backup_app.command("list")
def list_cmd(
    format: str = typer.Option("table", "--format", "-f", help="输出格式 table|json"),
):
    """列出已有快照"""
    snaps = _make_mgr().list_snapshots()
    if format == "json":
        _fmt(json_data=snaps, fmt="json")
        return
    if not snaps:
        console.print("[dim]无快照[/dim]")
        return
    t = Table(title="Snapshots")
    t.add_column("archive")
    t.add_column("size")
    t.add_column("ok")
    for s in snaps:
        t.add_row(s["archive"], str(s["size"]), "✓" if s["ok"] else "✗")
    _fmt(table=t, fmt=format)


@backup_app.command("verify")
def verify_cmd(
    snapshot: str = typer.Argument(..., help="快照文件名（daily/ 下）或绝对路径"),
    format: str = typer.Option("table", "--format", "-f", help="输出格式 table|json"),
):
    """校验快照完整性（sha256 + tar）"""
    p = _resolve_snapshot(snapshot)
    ok = _make_mgr().verify(p)
    if format == "json":
        _fmt(json_data={"snapshot": str(p), "ok": ok}, fmt="json")
    else:
        console.print("[green]校验通过[/green]" if ok else "[red]校验失败[/red]")
    raise typer.Exit(0 if ok else 1)


@backup_app.command("restore")
def restore_cmd(
    snapshot: str = typer.Argument(..., help="快照文件名或绝对路径"),
    yes: bool = typer.Option(False, "--yes", help="跳过确认"),
):
    """从快照恢复 KB（可逆：当前态自动 rename 旁置为 .pre-restore-*）"""
    p = _resolve_snapshot(snapshot)
    if not yes:
        console.print(f"[yellow]将用 {p} 恢复 ~/.zettelkasten + ~/.zk_config.json[/yellow]")
        console.print("[dim]当前态会 rename 旁置为 .pre-restore-*（安全可逆）[/dim]")
        if not typer.confirm("确认恢复？", default=False):
            raise typer.Abort()
    try:
        _make_mgr().restore(p, yes=True)
    except (FileNotFoundError, ValueError, RuntimeError) as e:
        console.print(f"[red]恢复失败：{e}[/red]")
        raise typer.Exit(1)
    console.print(f"[green]恢复完成[/green]：{p}")
