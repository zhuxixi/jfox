"""CLI 主程序"""

import json
import logging
from pathlib import Path
from typing import Optional, List

import typer
from rich.console import Console
from rich.table import Table

from .models import NoteType
from .config import config, ZKConfig
from . import note
from .embedding_backend import get_backend

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# 创建应用
app = typer.Typer(
    name="zk",
    help="Zettelkasten 知识管理 CLI",
    add_completion=False,
)

console = Console()


def output_json(data: dict) -> str:
    """输出 JSON 格式"""
    return json.dumps(data, ensure_ascii=False, indent=2)


@app.command()
def init(
    path: Optional[str] = typer.Option(None, "--path", "-p", help="知识库路径"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="JSON 输出"),
):
    """初始化知识库"""
    try:
        # 使用指定路径或默认路径
        if path:
            config.base_dir = Path(path).expanduser().resolve()
            # 重新计算派生路径
            config.notes_dir = config.base_dir / "notes"
            config.zk_dir = config.base_dir / ".zk"
            config.chroma_dir = config.zk_dir / "chroma_db"
        
        # 创建目录
        config.ensure_dirs()
        
        # 保存配置
        config.save()
        
        result = {
            "success": True,
            "message": "Knowledge base initialized successfully",
            "path": str(config.base_dir),
            "notes_dir": str(config.notes_dir),
        }
        
        if json_output:
            console.print(output_json(result))
        else:
            console.print(f"[green]✓[/green] Knowledge base initialized at: {config.base_dir}")
        
    except Exception as e:
        result = {
            "success": False,
            "error": str(e),
        }
        if json_output:
            console.print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def add(
    content: str = typer.Argument(..., help="笔记内容"),
    title: Optional[str] = typer.Option(None, "--title", "-t", help="笔记标题"),
    note_type: str = typer.Option("fleeting", "--type", help="笔记类型 (fleeting/literature/permanent)"),
    tags: Optional[List[str]] = typer.Option(None, "--tag", help="标签（可多次使用）"),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="来源（文献笔记）"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="JSON 输出"),
):
    """添加新笔记"""
    try:
        # 解析类型
        try:
            nt = NoteType(note_type.lower())
        except ValueError:
            raise ValueError(f"Invalid note type: {note_type}. Use: fleeting, literature, permanent")
        
        # 创建笔记
        new_note = note.create_note(
            content=content,
            title=title,
            note_type=nt,
            tags=tags or [],
            source=source,
        )
        
        # 保存笔记
        if note.save_note(new_note):
            result = {
                "success": True,
                "note": {
                    "id": new_note.id,
                    "title": new_note.title,
                    "type": new_note.type.value,
                    "filepath": str(new_note.filepath),
                },
            }
            
            if json_output:
                console.print(output_json(result))
            else:
                console.print(f"[green]✓[/green] Note created: {new_note.title}")
                console.print(f"  Path: {new_note.filepath}")
        else:
            raise Exception("Failed to save note")
            
    except Exception as e:
        result = {
            "success": False,
            "error": str(e),
        }
        if json_output:
            console.print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def search(
    query: str = typer.Argument(..., help="搜索查询"),
    top: int = typer.Option(5, "--top", "-n", help="返回结果数量"),
    note_type: Optional[str] = typer.Option(None, "--type", "-t", help="筛选笔记类型"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="JSON 输出"),
):
    """语义搜索笔记"""
    try:
        results = note.search_notes(query, top_k=top, note_type=note_type)
        
        result = {
            "query": query,
            "total": len(results),
            "results": results,
        }
        
        if json_output:
            console.print(output_json(result))
        else:
            console.print(f"[bold]Query:[/bold] {query}")
            console.print(f"[bold]Results:[/bold] {len(results)}\n")
            
            for i, r in enumerate(results, 1):
                score = r.get("score", 0)
                console.print(f"{i}. [{score:.2f}] {r['metadata'].get('title', 'Untitled')}")
                console.print(f"   {r['document'][:100]}...")
                console.print()
        
    except Exception as e:
        result = {
            "success": False,
            "error": str(e),
        }
        if json_output:
            console.print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def status(
    json_output: bool = typer.Option(True, "--json/--no-json", help="JSON 输出"),
):
    """查看知识库状态"""
    try:
        stats = note.get_stats()
        
        # 获取 NPU 状态
        backend = get_backend()
        
        result = {
            "knowledge_base": {
                "path": str(config.base_dir),
                "exists": config.base_dir.exists(),
            },
            "stats": stats,
            "backend": {
                "type": "CPU",
                "model": backend.model_name if backend.model else "not loaded",
            },
        }
        
        if json_output:
            console.print(output_json(result))
        else:
            # 打印表格
            table = Table(title="Knowledge Base Status")
            table.add_column("Property", style="cyan")
            table.add_column("Value", style="green")
            
            table.add_row("Base Path", str(config.base_dir))
            table.add_row("Total Notes", str(stats["total"]))
            table.add_row("Fleeting", str(stats["by_type"].get("fleeting", 0)))
            table.add_row("Literature", str(stats["by_type"].get("literature", 0)))
            table.add_row("Permanent", str(stats["by_type"].get("permanent", 0)))
            table.add_row("NPU Available", "Yes" if npu_health["openvino_available"] else "No")
            table.add_row("NPU Device", npu_health["selected_device"] or "N/A")
            
            console.print(table)
        
    except Exception as e:
        result = {
            "success": False,
            "error": str(e),
        }
        if json_output:
            console.print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def list(
    note_type: Optional[str] = typer.Option(None, "--type", "-t", help="筛选笔记类型"),
    limit: int = typer.Option(10, "--limit", "-n", help="显示数量"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="JSON 输出"),
):
    """列出笔记"""
    try:
        # 解析类型
        nt = None
        if note_type:
            try:
                nt = NoteType(note_type.lower())
            except ValueError:
                raise ValueError(f"Invalid note type: {note_type}")
        
        notes = note.list_notes(note_type=nt, limit=limit)
        
        result = {
            "total": len(notes),
            "notes": [n.to_dict() for n in notes],
        }
        
        if json_output:
            console.print(output_json(result))
        else:
            console.print(f"[bold]Total:[/bold] {len(notes)} notes\n")
            for n in notes:
                console.print(f"• [{n.type.value}] {n.title}")
                console.print(f"  {n.filepath}")
                console.print()
        
    except Exception as e:
        result = {
            "success": False,
            "error": str(e),
        }
        if json_output:
            console.print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


# 入口点
def main():
    """CLI 入口点"""
    app()


if __name__ == "__main__":
    main()
