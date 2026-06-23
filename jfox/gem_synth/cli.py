"""CLI 子命令组：jfox candidates list / show"""

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
    help="查看 L3 合成的候选知识宝石（破损级，待 L5 审阅）",
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
            console.print(f"[red]读取 candidate 失败：{e}[/red]")
            raise typer.Exit(code=1)
        if note is None:
            console.print(f"[red]找不到笔记 ID={note_id}[/red]")
            raise typer.Exit(code=1)

        if output_format == "json":
            # to_dict() 会把 content 截断到 200 字符，这里用完整 markdown 覆盖
            data = note.to_dict()
            data["content"] = note.to_markdown()
            # 用 typer.echo 直接输出，避免 Rich console 对 \n 二次转义（破坏 JSON）
            typer.echo(_json.dumps(data, ensure_ascii=False, indent=2))
            return

        # 默认输出完整原始 markdown（与 jfox show 一致）
        try:
            console.print(note.filepath.read_text(encoding="utf-8"))
        except Exception as e:
            # 文件读取失败时回退到内存中的 markdown 表示
            console.print(f"[yellow]读取文件失败，使用内存表示：{e}[/yellow]")
            console.print(note.to_markdown())


@candidates_app.command("list")
def list_cmd(
    status: str = typer.Option(
        "pending", "--status", help="按 status 过滤 (pending/promoted/rejected/all)"
    ),
    min_confidence: float = typer.Option(0.0, "--min-confidence", help="最低置信度"),
    limit: int = typer.Option(50, "--limit", "-n"),
    output_format: str = typer.Option("table", "--format", "-f", help="table, json"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
) -> None:
    """列出 candidate 笔记"""
    from ..config import use_kb
    from ..models import NoteType
    from ..note import list_notes

    with use_kb(kb):
        # 多取一些再在内存里按 status/confidence 过滤（这些字段在 frontmatter，索引层不过滤）
        fetch_limit = limit * 3 if limit > 0 else limit
        try:
            notes = list_notes(note_type=NoteType.CANDIDATE, limit=fetch_limit)
        except Exception as e:
            # 未初始化/空库应返回空列表而非抛错；真正读取失败才报错退出
            console.print(f"[red]读取 candidate 失败：{e}[/red]")
            raise typer.Exit(code=1)

        rows = []
        for n in notes:
            nstatus = getattr(n, "status", None) or ""
            if status != "all" and nstatus != status:
                continue
            conf = getattr(n, "confidence", None) or 0.0
            if conf < min_confidence:
                continue
            rows.append(
                {
                    "id": n.id,
                    "title": n.title,
                    "confidence": conf,
                    "knowledge_type": getattr(n, "knowledge_type", "") or "",
                    "status": nstatus,
                    "gem_level": getattr(n, "gem_level", "") or "",
                }
            )
            if len(rows) >= limit:
                break

        if output_format == "json":
            # 用 typer.echo 直接输出，避免 Rich console 对 \n 二次转义（破坏 JSON）
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


__all__ = ["candidates_app"]
