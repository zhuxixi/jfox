"""bookshelf CLI 子命令组：jfox bookshelf add/list/show/remove。"""

from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Any, Dict, Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from ..config import config, use_kb
from .store import (
    BookAlreadyExistsError,
    BookNotFoundError,
    BookShelf,
    InvalidBundleError,
)

console = Console(legacy_windows=False)
_json_console = Console(legacy_windows=False, highlight=False, markup=False, no_color=True)

bookshelf_app = typer.Typer(
    name="bookshelf",
    help="管理好书书架：PDF + 抽取 bundle + 元数据",
    no_args_is_help=True,
)


def _shelf() -> BookShelf:
    return BookShelf(config.base_dir)


def _emit_json(data: Any) -> None:
    # soft_wrap=True：禁止 rich 按 80 列折行，否则长 path（如 Windows 绝对路径）会在
    # JSON 字符串内部插入换行，破坏 json.loads（#336 windows CI 踩过）。
    _json_console.print(_json.dumps(data, ensure_ascii=False, indent=2), soft_wrap=True)


def _fail(message: str, output_format: str) -> None:
    if output_format == "json":
        _json_console.print(
            _json.dumps({"success": False, "error": message}, ensure_ascii=False), soft_wrap=True
        )
    else:
        console.print(f"[red]{escape(message)}[/red]")
    raise typer.Exit(code=1)


@bookshelf_app.command("add")
def add_cmd(
    folder: str = typer.Argument(..., help="书文件夹（含 bundle/ + 可选 meta.json + 原件）"),
    force: bool = typer.Option(False, "--force", help="同名 slug 覆盖重加"),
    move: bool = typer.Option(False, "--move", help="移动原件而非复制"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(False, "--json", help="JSON 输出（等同 --format json）"),
) -> None:
    """把一本书加进书架。"""
    if json_output:
        output_format = "json"
    try:
        with use_kb(kb):
            shelf = _shelf()
            meta = shelf.add(Path(folder), move=move, force=force)
            data = {
                "success": True,
                "slug": meta.slug,
                "title": meta.title,
                "page_count": meta.book.get("page_count", 0),
                "path": str(shelf.book_dir(meta.slug)),
            }
    except BookAlreadyExistsError as e:
        _fail(f"书 '{e}' 已存在；用 --force 覆盖重加", output_format)
        return
    except InvalidBundleError as e:
        _fail(str(e), output_format)
        return
    if not meta.source.get("original_file"):
        typer.echo("⚠️ 未找到原件文件（仅 bundle 入库，source.original_* 留空）", err=True)
    if output_format == "json":
        _emit_json(data)
    else:
        console.print(f"[green]已加入书架[/green] {escape(meta.title)}")
        console.print(f"  slug:  {escape(meta.slug)}")
        console.print(f"  页数:  {meta.book.get('page_count', 0)}")
        console.print(f"  路径:  {escape(str(shelf.book_dir(meta.slug)))}")


@bookshelf_app.command("list")
def list_cmd(
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(False, "--json", help="JSON 输出（等同 --format json）"),
) -> None:
    """列出书架上的书。"""
    if json_output:
        output_format = "json"
    with use_kb(kb):
        shelf = _shelf()
        rows = [
            {
                "slug": m.slug,
                "title": m.title,
                "page_count": m.book.get("page_count", 0),
                "added_at": m.added_at,
                "distill_status": (m.distill or {}).get("status", "none"),
            }
            for m in shelf.list_books()
        ]
    if output_format == "json":
        _emit_json({"books": rows, "total": len(rows)})
        return
    table = Table(title=f"书架（共 {len(rows)} 本）")
    for col in ("slug", "title", "page_count", "added_at", "distill"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            escape(r["slug"]),
            escape(r["title"]),
            str(r["page_count"]),
            r["added_at"],
            r["distill_status"],
        )
    console.print(table)


@bookshelf_app.command("show")
def show_cmd(
    slug: str = typer.Argument(..., help="书 slug"),
    page: Optional[int] = typer.Option(None, "--page", "-p", help="打印指定页的 md（页号，如 1）"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(False, "--json", help="JSON 输出（等同 --format json）"),
) -> None:
    """查看一本书的元数据或指定页内容。"""
    if json_output:
        output_format = "json"
    try:
        with use_kb(kb):
            shelf = _shelf()
            if page is not None:
                text = shelf.read_page(slug, page)
                if output_format == "json":
                    _emit_json({"slug": slug, "page": page, "content": text})
                else:
                    print(text)
                return
            meta = shelf.get(slug)
            bundle_manifest = shelf.read_bundle_manifest(slug)
            pages_summary = [
                {
                    "page": p.get("page"),
                    "chars": p.get("chars", 0),
                    "has_image": p.get("has_image", False),
                }
                for p in bundle_manifest.get("pages", [])
            ]
            data: Dict[str, Any] = meta.to_dict()
            data["path"] = str(shelf.book_dir(slug))
            data["pages"] = pages_summary
    except (BookNotFoundError, InvalidBundleError) as e:
        _fail(f"找不到书/页：{e}", output_format)
        return
    if output_format == "json":
        _emit_json(data)
    else:
        console.print(f"[bold]{escape(meta.title)}[/bold]  ({escape(meta.slug)})")
        console.print(f"页数: {meta.book.get('page_count', 0)}  添加于: {meta.added_at}")
        console.print(f"路径: {escape(str(shelf.book_dir(slug)))}")


@bookshelf_app.command("remove")
def remove_cmd(
    slug: str = typer.Argument(..., help="书 slug"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认直接删除"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(False, "--json", help="JSON 输出（等同 --format json）"),
) -> None:
    """从书架删除一本书（不可逆）。"""
    if json_output:
        output_format = "json"
    try:
        with use_kb(kb):
            shelf = _shelf()
            if not shelf.exists(slug):
                raise BookNotFoundError(slug)
            if not yes:
                meta = shelf.get(slug)
                confirmed = typer.confirm(
                    f"确认删除《{meta.title}》（{meta.book.get('page_count', 0)} 页）？不可逆。",
                    default=False,
                )
                if not confirmed:
                    if output_format == "json":
                        _emit_json({"slug": slug, "removed": False})
                    else:
                        console.print("[yellow]已取消[/yellow]")
                    return
            shelf.remove(slug)
            data = {"slug": slug, "removed": True}
    except (BookNotFoundError, InvalidBundleError) as e:
        _fail(f"找不到书：{e}", output_format)
        return
    if output_format == "json":
        _emit_json(data)
    else:
        console.print(f"[green]已删除[/green] {escape(slug)}")


__all__ = ["bookshelf_app"]
