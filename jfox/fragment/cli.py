"""CLI 子命令组：jfox fragments list / show"""

from __future__ import annotations

import json as _json
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from .store import FragmentStore

# 表格输出用带颜色的 console；JSON 用 _json_console（无 ANSI，配 soft_wrap 防折行破坏 JSON），便于机器解析
console = Console(legacy_windows=False)
_json_console = Console(legacy_windows=False, highlight=False, markup=False, no_color=True)

fragments_app = typer.Typer(
    name="fragments",
    help="查看 Hook 采集的 session 碎片（纠正/决策/工具调用）",
    no_args_is_help=True,
)


@fragments_app.command("list")
def list_cmd(
    session: Optional[str] = typer.Option(None, "--session", help="按 CC session_id 过滤"),
    type: Optional[str] = typer.Option(None, "--type", "-t", help="按 fragment_type 过滤"),
    limit: int = typer.Option(20, "--limit", "-n", help="返回条数"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: table, json"),
) -> None:
    """列出碎片（最新在前）"""
    store = FragmentStore()
    try:
        rows = store.query(session_id=session, fragment_type=type, limit=limit)
    except Exception as e:
        if output_format == "json":
            _json_console.print(
                _json.dumps(
                    {"success": False, "error": f"读取碎片失败：{e}"},
                    ensure_ascii=False,
                    indent=2,
                ),
                soft_wrap=True,
            )
        else:
            console.print(f"[red]读取碎片失败：{e}[/red]")
        raise typer.Exit(code=1)
    finally:
        store.close()

    if output_format == "json":
        _json_console.print(
            _json.dumps(
                {"success": True, "fragments": rows, "total": len(rows)},
                ensure_ascii=False,
                indent=2,
            ),
            soft_wrap=True,
        )
        return

    table = Table(title=f"碎片（共 {len(rows)} 条）")
    for col in ("ID", "时间", "类型", "来源事件", "内容预览"):
        table.add_column(col)
    for r in rows:
        preview = (r.get("content") or "")[:40].replace("\n", " ")
        table.add_row(
            str(r["fragment_id"]),
            str(r.get("timestamp", "")),
            r["fragment_type"],
            r.get("source_event", ""),
            preview,
        )
    console.print(table)


@fragments_app.command("show")
def show_cmd(
    fragment_id: int = typer.Argument(..., help="碎片 ID"),
) -> None:
    """查看碎片详情（含完整原始事件）"""
    store = FragmentStore()
    try:
        row = store.get(fragment_id)
    except Exception as e:
        # show 是纯 JSON 命令：错误分支也必须输出 JSON（#502 C2b）
        _json_console.print(
            _json.dumps(
                {"success": False, "error": f"读取碎片失败：{e}"},
                ensure_ascii=False,
                indent=2,
            ),
            soft_wrap=True,
        )
        raise typer.Exit(code=1)
    finally:
        store.close()
    if row is None:
        _json_console.print(
            _json.dumps(
                {"success": False, "error": f"找不到碎片 ID={fragment_id}"},
                ensure_ascii=False,
                indent=2,
            ),
            soft_wrap=True,
        )
        raise typer.Exit(code=1)
    _json_console.print(
        _json.dumps({"success": True, **row}, ensure_ascii=False, indent=2),
        soft_wrap=True,
    )


__all__ = ["fragments_app"]
