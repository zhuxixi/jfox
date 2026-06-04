"""
CLI subapp: jfox auto-summary

子命令：
- run [--dry-run] [--verbose]    手动触发一轮扫描+总结
- scan                           列出当前会被处理的 session（dry-run 视图）
- status                         显示配置 + ledger 统计
- enable [--interval] [--kb]     启用 auto-summary（可同时改若干字段）
- disable                        禁用 auto-summary
- forget <session_id>            从 ledger 中移除一条，使其下次重跑
- prune [--days N]               清理 ledger 中早于 N 天的条目
"""

from __future__ import annotations

import json as _json
from datetime import datetime
from typing import Any, Optional

import typer
from rich.console import Console
from rich.table import Table

from ..global_config import get_global_config_manager
from . import ledger as ledger_module
from .ledger import Ledger
from .runner import run_once, scan_pending

# 设计说明：此模块的子命令未采用主 cli.py 的 `@app.command() → _xxx_impl()` 拆分模式。
# 原因：(1) 每个子命令仅 20-40 行，拆分无复用价值；
#       (2) 作为独立子模块，不与主 cli.py 共享 _impl 函数；
#       (3) 保持紧凑可读比形式统一更重要。


def _fmt(table: Optional[Table] = None, json_data: Any = None, fmt: str = "table") -> None:
    """统一的输出路由：fmt=json 时输出 JSON 字符串，否则渲染 Table"""
    if fmt == "json":
        console.print(_json.dumps(json_data, ensure_ascii=False, indent=2))
    elif table is not None:
        console.print(table)


console = Console(legacy_windows=False)

auto_summary_app = typer.Typer(
    name="auto-summary",
    help="Claude Code 会话自动总结：定时扫描 ~/.claude/projects 并写入知识库",
    no_args_is_help=True,
)


def _config():
    return get_global_config_manager().get_auto_summary_config()


@auto_summary_app.command("status")
def status(
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: table, json"),
) -> None:
    """显示 auto-summary 配置和 ledger 统计"""
    cfg = _config()
    led = Ledger()
    stats = led.stats()

    if output_format == "json":
        _fmt(
            json_data={
                "config": cfg.to_dict(),
                "ledger_file": str(ledger_module.DEFAULT_LEDGER_PATH),
                "ledger_stats": stats,
            },
            fmt="json",
        )
        return

    table = Table(title="auto-summary 配置", show_header=False)
    table.add_column("项", style="cyan", no_wrap=True)
    table.add_column("值", style="green")
    table.add_row("enabled", "[green]是[/green]" if cfg.enabled else "[dim]否[/dim]")
    table.add_row("扫描间隔", f"{cfg.interval_minutes} 分钟")
    table.add_row("结束判定阈值", f"{cfg.idle_threshold_minutes} 分钟（mtime 静默）")
    table.add_row("目标知识库", cfg.target_kb or "(default)")
    table.add_row("单轮最多处理", str(cfg.max_per_tick))
    table.add_row("最大 session 大小", f"{cfg.max_session_size_mb} MB")
    table.add_row("最小 session 大小", f"{cfg.min_session_size_kb} KB")
    table.add_row("跳过过旧 session 阈值", f"{cfg.skip_after_days} 天")
    table.add_row("claude -p 超时", f"{cfg.claude_timeout_seconds} 秒")
    table.add_row("claude 路径", cfg.claude_binary or "(从 PATH 解析)")
    table.add_row("ledger 文件", str(ledger_module.DEFAULT_LEDGER_PATH))
    console.print(table)

    stat_table = Table(title="ledger 状态分布")
    stat_table.add_column("状态", style="cyan")
    stat_table.add_column("数量", style="green", justify="right")
    for k, v in stats.items():
        stat_table.add_row(k, str(v))
    console.print(stat_table)


@auto_summary_app.command("enable")
def enable(
    interval: Optional[int] = typer.Option(None, "--interval", help="扫描间隔（分钟，>=1）"),
    idle_threshold: Optional[int] = typer.Option(
        None, "--idle-threshold", help="session 结束判定的静默阈值（分钟）"
    ),
    kb: Optional[str] = typer.Option(None, "--kb", help="写入哪个知识库（默认 default）"),
    max_per_tick: Optional[int] = typer.Option(
        None, "--max-per-tick", help="每轮最多处理几个 session"
    ),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: table, json"),
) -> None:
    """启用 auto-summary，可同时调整其他字段"""
    changes: dict = {"enabled": True}
    if interval is not None:
        if interval < 1:
            console.print("[red]✗[/red] interval 必须 >= 1")
            raise typer.Exit(1)
        changes["interval_minutes"] = interval
    if idle_threshold is not None:
        if idle_threshold < 1:
            console.print("[red]✗[/red] idle-threshold 必须 >= 1")
            raise typer.Exit(1)
        changes["idle_threshold_minutes"] = idle_threshold
    if kb is not None:
        changes["target_kb"] = kb or None
    if max_per_tick is not None:
        if max_per_tick < 1:
            console.print("[red]✗[/red] max-per-tick 必须 >= 1")
            raise typer.Exit(1)
        changes["max_per_tick"] = max_per_tick

    if get_global_config_manager().update_auto_summary_config(**changes):
        if output_format == "json":
            _fmt(json_data={"success": True, "message": "auto-summary 已启用"}, fmt="json")
            console.print(
                "[yellow]⚠ 隐私声明：auto-summary 会将 Claude Code 会话记录通过 `claude -p` 发送至"
                " Anthropic API 以生成摘要。仅传输会话文本，不传输额外数据。[/yellow]"
            )
            return
        console.print("[green]✓[/green] auto-summary 已启用")
        console.print(
            "[dim]提示：daemon 启动后才会真正在后台运行；CLI 仍可手动 jfox auto-summary run[/dim]"
        )
        console.print(
            "[yellow]⚠ 隐私声明：auto-summary 会将 Claude Code 会话记录通过 `claude -p` 发送至"
            " Anthropic API 以生成摘要。仅传输会话文本，不传输额外数据。[/yellow]"
        )
    else:
        if output_format == "json":
            _fmt(json_data={"success": False, "error": "写入配置失败"}, fmt="json")
            raise typer.Exit(1)
        console.print("[red]✗[/red] 写入配置失败")
        raise typer.Exit(1)


@auto_summary_app.command("disable")
def disable(
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: table, json"),
) -> None:
    """禁用 auto-summary（daemon 将停止后台循环；ledger 不会被清空）"""
    if get_global_config_manager().update_auto_summary_config(enabled=False):
        if output_format == "json":
            _fmt(json_data={"success": True, "message": "auto-summary 已禁用"}, fmt="json")
            return
        console.print("[yellow]auto-summary 已禁用[/yellow]")
    else:
        if output_format == "json":
            _fmt(json_data={"success": False, "error": "写入配置失败"}, fmt="json")
            raise typer.Exit(1)
        console.print("[red]✗[/red] 写入配置失败")
        raise typer.Exit(1)


@auto_summary_app.command("scan")
def scan(
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: table, json"),
) -> None:
    """列出当前会被处理的 session（dry-run）"""
    pending = scan_pending()
    if not pending:
        if output_format == "json":
            _fmt(json_data={"pending": []}, fmt="json")
        else:
            console.print("[dim]无待处理 session[/dim]")
        return

    if output_format == "json":
        _fmt(
            json_data={
                "pending": [
                    {
                        "session_id": sf.session_id,
                        "project": sf.project_dir_name,
                        "size_bytes": sf.size_bytes,
                        "mtime": sf.mtime,
                        "age_minutes": sf.age_seconds / 60,
                    }
                    for sf in pending
                ]
            },
            fmt="json",
        )
        return

    table = Table(title=f"待处理 session ({len(pending)})")
    table.add_column("project", style="cyan", overflow="fold")
    table.add_column("session_id", style="yellow")
    table.add_column("size", justify="right")
    table.add_column("mtime", style="dim")
    table.add_column("age", justify="right", style="dim")

    for sf in pending:
        mtime_str = datetime.fromtimestamp(sf.mtime).strftime("%Y-%m-%d %H:%M")
        age_min = sf.age_seconds / 60
        if age_min < 60:
            age_str = f"{age_min:.0f}m"
        elif age_min < 60 * 24:
            age_str = f"{age_min / 60:.1f}h"
        else:
            age_str = f"{age_min / 60 / 24:.1f}d"
        size_kb = sf.size_bytes / 1024
        size_str = f"{size_kb:.0f} KB" if size_kb < 1024 else f"{size_kb / 1024:.1f} MB"
        table.add_row(sf.project_dir_name, sf.session_id[:8], size_str, mtime_str, age_str)

    console.print(table)


@auto_summary_app.command("run")
def run(
    dry_run: bool = typer.Option(False, "--dry-run", help="只扫描不实际调用 claude 和写入"),
    verbose: bool = typer.Option(False, "--verbose", "-v", help="详细输出每条结果"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: table, json"),
) -> None:
    """手动触发一轮 auto-summary（不依赖 daemon）"""
    if not _config().enabled and not dry_run:
        console.print(
            "[yellow]提示：auto-summary 当前处于禁用状态[/yellow]，"
            "本次手动 run 仍会执行，但 daemon 不会自动调度。"
        )

    report = run_once(dry_run=dry_run)

    if output_format == "json":
        _fmt(
            json_data={
                "scanned": report.scanned,
                "processed": report.processed,
                "success": report.success,
                "skipped": report.skipped,
                "failed": report.failed,
                "items": [
                    {
                        "session_id": it.session_id,
                        "outcome": it.outcome.value,
                        "note_id": it.note_id,
                        "title": it.title,
                        "reason": it.reason,
                        "error": it.error,
                    }
                    for it in report.items
                ],
            },
            fmt="json",
        )
        return

    console.print(
        f"扫描 {report.scanned}, 处理 {report.processed}, "
        f"[green]成功 {report.success}[/green], "
        f"[yellow]跳过 {report.skipped}[/yellow], "
        f"[red]失败 {report.failed}[/red]"
    )

    if verbose or report.failed > 0:
        for item in report.items:
            line = f"  [{item.outcome.value}] {item.session_id[:8]}"
            if item.title:
                line += f" — {item.title}"
            if item.note_id:
                line += f" → {item.note_id}"
            if item.reason:
                line += f"  ({item.reason})"
            if item.error:
                line += f"  ERROR: {item.error}"
            console.print(line)


@auto_summary_app.command("forget")
def forget(
    session_id: str = typer.Argument(..., help="要从 ledger 移除的 session_id（支持完整或前缀）"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: table, json"),
) -> None:
    """从 ledger 中移除一条，使其下次扫描时被重新处理"""
    led = Ledger()
    matches = [sid for sid in led.all_entries() if sid.startswith(session_id)]
    if not matches:
        if output_format == "json":
            _fmt(
                json_data={"success": False, "error": f"ledger 中没有匹配 '{session_id}' 的条目"},
                fmt="json",
            )
            raise typer.Exit(1)
        console.print(f"[red]✗[/red] ledger 中没有匹配 '{session_id}' 的条目")
        raise typer.Exit(1)
    if len(matches) > 1:
        if output_format == "json":
            _fmt(
                json_data={
                    "success": False,
                    "error": f"前缀 '{session_id}' 命中 {len(matches)} 条，请输入更长的前缀",
                    "matches": matches[:10],
                },
                fmt="json",
            )
            raise typer.Exit(1)
        console.print(f"[red]✗[/red] 前缀 '{session_id}' 命中 {len(matches)} 条，请输入更长的前缀")
        for m in matches[:10]:
            console.print(f"  - {m}")
        raise typer.Exit(1)

    target = matches[0]
    if led.forget(target):
        if output_format == "json":
            _fmt(json_data={"success": True, "removed": target}, fmt="json")
            return
        console.print(f"[green]✓[/green] 已从 ledger 移除 {target}")
    else:
        if output_format == "json":
            _fmt(json_data={"success": False, "error": "移除失败"}, fmt="json")
            raise typer.Exit(1)
        console.print("[red]✗[/red] 移除失败")
        raise typer.Exit(1)


@auto_summary_app.command("prune")
def prune(
    days: int = typer.Option(30, "--days", help="删除 ledger 中早于 N 天的条目"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: table, json"),
) -> None:
    """清理 ledger 中过旧的条目（不影响知识库笔记）"""
    if days <= 0:
        if output_format == "json":
            _fmt(json_data={"success": False, "error": "days 必须 > 0"}, fmt="json")
            raise typer.Exit(1)
        console.print("[red]✗[/red] days 必须 > 0")
        raise typer.Exit(1)
    led = Ledger()
    n = led.prune_older_than(days)
    if output_format == "json":
        _fmt(json_data={"success": True, "pruned": n, "older_than_days": days}, fmt="json")
        return
    console.print(f"[green]✓[/green] 已清理 {n} 条早于 {days} 天的 ledger 条目")


__all__ = ["auto_summary_app"]
