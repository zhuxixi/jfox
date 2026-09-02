"""CLI 子命令组：jfox candidates list / show / promote / reject。

从 gem_synth/cli.py 原样迁移（#399：candidate 与合成进度解耦），命令名、
参数、输出行为完全不变。
"""

from __future__ import annotations

import json as _json
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

# 表格/错误用带颜色的 console；JSON 用 typer.echo 直接输出（避免 Rich 对 \n 二次转义）
console = Console(legacy_windows=False)

candidates_app = typer.Typer(
    name="candidates",
    help="查看候选知识宝石（待 L5 审阅）",
    no_args_is_help=True,
)


@candidates_app.command("show")
def show_cmd(
    note_id: str = typer.Argument(..., help="candidate 笔记 ID"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    output_format: str = typer.Option(
        "markdown", "--format", "-f", help="输出格式: markdown, json"
    ),
) -> None:
    """查看 candidate 笔记详情（完整 frontmatter + 正文，不截断）"""
    from ..config import use_kb
    from ..note import load_note_by_id

    with use_kb(kb):
        try:
            note = load_note_by_id(note_id)
        except Exception as e:
            # --format json 时输出结构化错误（AGENTS.md 约定），否则打印红色提示
            if output_format == "json":
                typer.echo(_json.dumps({"success": False, "error": str(e)}, ensure_ascii=False))
            else:
                console.print(f"[red]读取 candidate 失败：{e}[/red]")
            raise typer.Exit(code=1)
        if note is None:
            if output_format == "json":
                typer.echo(
                    _json.dumps(
                        {"success": False, "error": f"找不到笔记 ID={note_id}"},
                        ensure_ascii=False,
                    )
                )
            else:
                console.print(f"[red]找不到笔记 ID={note_id}[/red]")
            raise typer.Exit(code=1)

        if output_format == "json":
            # content 字段用纯正文（note.content），不含 frontmatter（避免与 top-level
            # 字段重复）。to_dict() 会把 content 截断到 200 字符，这里用完整正文覆盖。
            data = note.to_dict()
            data["content"] = note.content
            typer.echo(_json.dumps(data, ensure_ascii=False, indent=2))
            return

        # 默认输出完整原始 markdown（与 jfox show 一致）。
        # 用 typer.echo 而非 console.print：Rich 会解析正文中的 [xxx] 标记当成
        # markup/颜色标签，导致输出错乱或丢失字面量。
        try:
            typer.echo(note.filepath.read_text(encoding="utf-8"))
        except Exception as e:
            console.print(f"[yellow]读取文件失败，使用内存表示：{e}[/yellow]")
            typer.echo(note.to_markdown())


@candidates_app.command("list")
def list_cmd(
    status: str = typer.Option(
        "pending",
        "--status",
        help="按 status 过滤 (pending/rejected/all；promoted 笔记已转 permanent，"
        "用 list --type permanent 查看)",
    ),
    min_confidence: float = typer.Option(0.0, "--min-confidence", help="最低置信度"),
    limit: int = typer.Option(50, "--limit", "-n"),
    output_format: str = typer.Option("table", "--format", "-f", help="table, json"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
) -> None:
    """列出 candidate 笔记"""
    from ..config import use_kb
    from .service import list_candidates

    with use_kb(kb):
        try:
            rows = list_candidates(status=status, min_confidence=min_confidence, limit=limit)
        except Exception as e:
            # 未初始化/空库应返回空列表而非抛错；真正读取失败才报错退出
            if output_format == "json":
                typer.echo(_json.dumps({"success": False, "error": str(e)}, ensure_ascii=False))
            else:
                console.print(f"[red]读取 candidate 失败：{e}[/red]")
            raise typer.Exit(code=1)

        if output_format == "json":
            typer.echo(
                _json.dumps({"candidates": rows, "total": len(rows)}, ensure_ascii=False, indent=2)
            )
            return

        table = Table(title=f"候选宝石（共 {len(rows)} 条）")
        for col in ("ID", "标题", "置信度", "类型", "状态", "等级"):
            table.add_column(col)
        for r in rows:
            table.add_row(
                r["id"],
                r["title"],
                f"{r['confidence']:.2f}",
                r["knowledge_type"],
                r["status"],
                r["gem_level"],
            )
        console.print(table)


@candidates_app.command("promote")
def promote_cmd(
    note_id: str = typer.Argument(..., help="candidate 笔记 ID"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    output_format: str = typer.Option("table", "--format", "-f", help="table, json"),
) -> None:
    """晋升 candidate → permanent（改 type + 移文件 + 回填 backlinks）"""
    from ..config import use_kb
    from ..note import promote_note

    with use_kb(kb):
        try:
            ok = promote_note(note_id)
        except Exception as e:
            # 索引损坏/IO 等异常：结构化错误（AGENTS.md 约定），不崩 traceback
            if output_format == "json":
                typer.echo(
                    _json.dumps(
                        {"promoted": note_id, "success": False, "error": str(e)},
                        ensure_ascii=False,
                    )
                )
            else:
                console.print(f"[red]✗ 晋升异常：{e}[/red]")
            raise typer.Exit(code=1)
        if output_format == "json":
            typer.echo(_json.dumps({"promoted": note_id, "success": ok}, ensure_ascii=False))
        elif ok:
            console.print(f"[green]✓[/green] 晋升 {note_id} → permanent")
        else:
            console.print(f"[red]✗ 晋升失败：{note_id}（非 candidate 或不存在）[/red]")
        if not ok:
            raise typer.Exit(code=1)


@candidates_app.command("reject")
def reject_cmd(
    note_id: str = typer.Argument(..., help="candidate 笔记 ID"),
    reason: Optional[str] = typer.Option(
        None, "--reason", "-r", help="拒绝原因（记入 frontmatter）"
    ),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    output_format: str = typer.Option("table", "--format", "-f", help="table, json"),
) -> None:
    """拒绝 candidate（归档丢弃，可记原因，可 jfox unarchive 恢复）"""
    from ..config import use_kb
    from ..note import reject_note

    with use_kb(kb):
        try:
            ok = reject_note(note_id, reason=reason)
        except Exception as e:
            if output_format == "json":
                typer.echo(
                    _json.dumps(
                        {"rejected": note_id, "success": False, "error": str(e)},
                        ensure_ascii=False,
                    )
                )
            else:
                console.print(f"[red]✗ 拒绝异常：{e}[/red]")
            raise typer.Exit(code=1)
        if output_format == "json":
            typer.echo(_json.dumps({"rejected": note_id, "success": ok}, ensure_ascii=False))
        elif ok:
            console.print(f"[green]✓[/green] 拒绝 {note_id}（已归档）")
        else:
            console.print(f"[red]✗ 拒绝失败：{note_id} 不存在[/red]")
        if not ok:
            raise typer.Exit(code=1)


__all__ = ["candidates_app"]
