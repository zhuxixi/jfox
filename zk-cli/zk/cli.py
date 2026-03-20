"""CLI 主程序"""

import json
import logging
from pathlib import Path
from typing import Optional, List
from datetime import datetime, timedelta

import typer
from rich.console import Console
from rich.table import Table
from rich.tree import Tree
from rich.panel import Panel

from .models import NoteType
from .config import config, ZKConfig
from . import note
from .embedding_backend import get_backend
from .graph import KnowledgeGraph
from .indexer import Indexer
from .vector_store import get_vector_store

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


def extract_wiki_links(content: str) -> List[str]:
    """从内容中提取 [[...]] 格式的维基链接"""
    import re
    pattern = r'\[\[(.*?)\]\]'
    matches = re.findall(pattern, content)
    return [m.strip() for m in matches]


def find_note_id_by_title_or_id(title_or_id: str) -> Optional[str]:
    """通过标题或ID查找笔记"""
    all_notes = note.list_notes()
    
    # 首先尝试精确匹配 ID
    for n in all_notes:
        if n.id == title_or_id:
            return n.id
    
    # 然后尝试标题包含匹配
    for n in all_notes:
        if title_or_id.lower() in n.title.lower():
            return n.id
    
    # 最后尝试模糊匹配（标题相近）
    for n in all_notes:
        if n.title.lower() == title_or_id.lower():
            return n.id
    
    return None


@app.command()
def add(
    content: str = typer.Argument(..., help="笔记内容（支持 [[笔记标题]] 格式链接）"),
    title: Optional[str] = typer.Option(None, "--title", "-t", help="笔记标题"),
    note_type: str = typer.Option("fleeting", "--type", help="笔记类型 (fleeting/literature/permanent)"),
    tags: Optional[List[str]] = typer.Option(None, "--tag", help="标签（可多次使用）"),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="来源（文献笔记）"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="JSON 输出"),
):
    """添加新笔记（内容中可用 [[笔记标题]] 引用其他笔记）"""
    try:
        # 解析类型
        try:
            nt = NoteType(note_type.lower())
        except ValueError:
            raise ValueError(f"Invalid note type: {note_type}. Use: fleeting, literature, permanent")
        
        # 从内容中提取维基链接
        wiki_links = extract_wiki_links(content)
        resolved_links = []
        unresolved = []
        
        for link_text in wiki_links:
            target_id = find_note_id_by_title_or_id(link_text)
            if target_id:
                resolved_links.append(target_id)
            else:
                unresolved.append(link_text)
        
        # 创建笔记
        new_note = note.create_note(
            content=content,
            title=title,
            note_type=nt,
            tags=tags or [],
            links=resolved_links,
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
                    "links": resolved_links,
                },
            }
            
            if unresolved:
                result["warnings"] = f"Unresolved links: {', '.join(unresolved)}"
            
            if json_output:
                console.print(output_json(result))
            else:
                console.print(f"[green]✓[/green] Note created: {new_note.title}")
                console.print(f"  ID: {new_note.id}")
                console.print(f"  Path: {new_note.filepath}")
                if resolved_links:
                    console.print(f"  Links: {len(resolved_links)} connection(s)")
                if unresolved:
                    console.print(f"  [yellow]Warning: Unresolved links - {', '.join(unresolved)}[/yellow]")
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
            table.add_row("Backend", "CPU")
            table.add_row("Model", backend.model_name)
            
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


@app.command()
def refs(
    note_id: Optional[str] = typer.Option(None, "--note", "-n", help="查看特定笔记的引用关系"),
    search: Optional[str] = typer.Option(None, "--search", "-s", help="搜索笔记标题"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="JSON 输出"),
):
    """查看笔记引用关系（反向链接）"""
    try:
        if search:
            # 搜索笔记
            all_notes = note.list_notes()
            matches = [n for n in all_notes if search.lower() in n.title.lower()]
            
            result = {
                "query": search,
                "matches": [
                    {"id": n.id, "title": n.title, "type": n.type.value}
                    for n in matches
                ]
            }
            
            if json_output:
                console.print(output_json(result))
            else:
                console.print(f"[bold]Search:[/bold] '{search}'\n")
                if matches:
                    for n in matches:
                        console.print(f"• [{n.type.value}] {n.title}")
                        console.print(f"  ID: {n.id}")
                        console.print(f"  引用此笔记: {len(n.backlinks)} 处")
                        console.print()
                else:
                    console.print("[dim]No matches found[/dim]")
        
        elif note_id:
            # 查看特定笔记的引用关系
            n = note.load_note_by_id(note_id)
            if not n:
                console.print(f"[red]Note not found: {note_id}[/red]")
                raise typer.Exit(1)
            
            # 获取链接到的笔记
            forward_links = []
            for link_id in n.links:
                link_note = note.load_note_by_id(link_id)
                if link_note:
                    forward_links.append({
                        "id": link_id,
                        "title": link_note.title,
                        "type": link_note.type.value
                    })
            
            # 获取反向链接
            backward_links = []
            for back_id in n.backlinks:
                back_note = note.load_note_by_id(back_id)
                if back_note:
                    backward_links.append({
                        "id": back_id,
                        "title": back_note.title,
                        "type": back_note.type.value
                    })
            
            result = {
                "note": {
                    "id": n.id,
                    "title": n.title,
                    "type": n.type.value,
                },
                "forward_links": forward_links,
                "backward_links": backward_links,
            }
            
            if json_output:
                console.print(output_json(result))
            else:
                console.print(f"[bold]{n.title}[/bold]\n")
                
                if forward_links:
                    console.print("[cyan]→ Links to:[/cyan]")
                    for link in forward_links:
                        console.print(f"  • [{link['type']}] {link['title']}")
                    console.print()
                
                if backward_links:
                    console.print("[green]← Linked by:[/green]")
                    for link in backward_links:
                        console.print(f"  • [{link['type']}] {link['title']}")
                    console.print()
                
                if not forward_links and not backward_links:
                    console.print("[dim]No connections yet[/dim]")
        
        else:
            # 显示所有笔记及其链接统计
            all_notes = note.list_notes()
            notes_with_links = []
            for n in all_notes:
                notes_with_links.append({
                    "id": n.id,
                    "title": n.title,
                    "type": n.type.value,
                    "outgoing": len(n.links),
                    "incoming": len(n.backlinks),
                })
            
            result = {"notes": notes_with_links}
            
            if json_output:
                console.print(output_json(result))
            else:
                table = Table(title="Note References")
                table.add_column("ID", style="dim")
                table.add_column("Title", style="cyan")
                table.add_column("Type", style="green")
                table.add_column("Out", justify="right")
                table.add_column("In", justify="right")
                
                for n in notes_with_links:
                    table.add_row(
                        n["id"][:14],
                        n["title"][:40],
                        n["type"],
                        str(n["outgoing"]),
                        str(n["incoming"])
                    )
                
                console.print(table)
    
    except Exception as e:
        result = {"success": False, "error": str(e)}
        if json_output:
            console.print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def delete(
    note_id: str = typer.Argument(..., help="笔记 ID"),
    force: bool = typer.Option(False, "--force", "-f", help="强制删除不确认"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="JSON 输出"),
):
    """删除笔记"""
    try:
        # 先查找笔记
        n = note.load_note_by_id(note_id)
        if not n:
            console.print(f"[red]Note not found: {note_id}[/red]")
            raise typer.Exit(1)
        
        # 确认删除
        if not force:
            if json_output:
                console.print(f"Use --force to delete: {n.title}")
                raise typer.Exit(1)
            else:
                console.print(f"Note: {n.title}")
                confirm = input("Delete? (y/N): ")
                if confirm.lower() != "y":
                    console.print("Cancelled")
                    raise typer.Exit(0)
        
        # 执行删除
        if note.delete_note(note_id):
            result = {
                "success": True,
                "deleted": note_id,
                "title": n.title,
            }
            
            if json_output:
                console.print(output_json(result))
            else:
                console.print(f"[green]✓[/green] Deleted: {n.title}")
        else:
            raise Exception("Failed to delete note")
            
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
def query(
    query_str: str = typer.Argument(..., help="搜索查询"),
    top: int = typer.Option(5, "--top", "-n", help="返回结果数量"),
    graph_depth: int = typer.Option(2, "--depth", "-d", help="图谱遍历深度"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="JSON 输出"),
):
    """语义搜索 + 知识图谱联合查询"""
    try:
        # 1. 语义搜索
        vector_results = note.search_notes(query_str, top_k=top)
        
        # 2. 构建知识图谱并查找相关笔记
        graph = KnowledgeGraph(config).build()
        
        # 3. 为每个搜索结果查找图谱关联
        enriched_results = []
        for r in vector_results:
            note_id = r["id"]
            related = graph.get_related(note_id, depth=graph_depth)
            
            # 获取相关笔记详情
            related_notes = []
            for depth_key, note_ids in related.items():
                depth = int(depth_key.split("_")[1])
                for nid in note_ids[:3]:  # 限制每层的数量
                    n = note.load_note_by_id(nid)
                    if n:
                        related_notes.append({
                            "id": nid,
                            "title": n.title,
                            "type": n.type.value,
                            "depth": depth,
                        })
            
            enriched_results.append({
                **r,
                "related_notes": related_notes,
                "graph_stats": {
                    "neighbors": len(graph.get_neighbors(note_id)),
                }
            })
        
        result = {
            "query": query_str,
            "semantic_results": len(vector_results),
            "results": enriched_results,
        }
        
        if json_output:
            console.print(output_json(result))
        else:
            console.print(f"[bold]Query:[/bold] {query_str}")
            console.print(f"[bold]Results:[/bold] {len(enriched_results)}\n")
            
            for i, r in enumerate(enriched_results, 1):
                score = r.get("score", 0)
                panel_content = f"[cyan]{r['document'][:150]}...[/cyan]"
                
                if r["related_notes"]:
                    panel_content += "\n\n[dim]Related:[/dim]"
                    for rel in r["related_notes"][:3]:
                        panel_content += f"\n  • [{rel['type']}] {rel['title']}"
                
                console.print(Panel(
                    panel_content,
                    title=f"{i}. [{score:.2f}] {r['metadata'].get('title', 'Untitled')}",
                    border_style="blue"
                ))
        
    except Exception as e:
        result = {"success": False, "error": str(e)}
        if json_output:
            console.print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def graph(
    note_id: Optional[str] = typer.Option(None, "--note", "-n", help="查看特定笔记的图谱"),
    depth: int = typer.Option(2, "--depth", "-d", help="遍历深度"),
    stats: bool = typer.Option(False, "--stats", "-s", help="显示统计信息"),
    orphans: bool = typer.Option(False, "--orphans", "-o", help="显示孤立笔记"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="JSON 输出"),
):
    """知识图谱可视化和分析"""
    try:
        kg = KnowledgeGraph(config).build()
        
        if stats:
            # 显示统计信息
            graph_stats = kg.get_stats()
            result = {
                "total_nodes": graph_stats.total_nodes,
                "total_edges": graph_stats.total_edges,
                "avg_degree": round(graph_stats.avg_degree, 2),
                "isolated_nodes": graph_stats.isolated_nodes,
                "clusters": graph_stats.clusters,
                "top_hubs": [
                    {"id": nid, "title": kg.graph.nodes[nid].get("title", ""), "degree": deg}
                    for nid, deg in graph_stats.hubs[:10]
                ],
            }
            
            if json_output:
                console.print(output_json(result))
            else:
                table = Table(title="Knowledge Graph Statistics")
                table.add_column("Metric", style="cyan")
                table.add_column("Value", style="green")
                table.add_row("Total Notes", str(graph_stats.total_nodes))
                table.add_row("Total Links", str(graph_stats.total_edges))
                table.add_row("Average Degree", f"{graph_stats.avg_degree:.2f}")
                table.add_row("Isolated Notes", str(graph_stats.isolated_nodes))
                table.add_row("Clusters", str(graph_stats.clusters))
                console.print(table)
                
                console.print("\n[bold]Top Connected Notes:[/bold]")
                for nid, deg in graph_stats.hubs[:10]:
                    title = kg.graph.nodes[nid].get("title", "Untitled")
                    console.print(f"  • {nid}: {title} ({deg} connections)")
        
        elif orphans:
            # 显示孤立笔记
            orphan_ids = kg.get_orphan_notes()
            orphans_list = []
            for oid in orphan_ids:
                n = note.load_note_by_id(oid)
                if n:
                    orphans_list.append({"id": oid, "title": n.title, "type": n.type.value})
            
            result = {"orphans": orphans_list}
            
            if json_output:
                console.print(output_json(result))
            else:
                console.print(f"[bold]Orphan Notes ({len(orphans_list)}):[/bold]\n")
                for o in orphans_list:
                    console.print(f"  • [{o['type']}] {o['title']} ({o['id']})")
        
        elif note_id:
            # 显示特定笔记的图谱
            if note_id not in kg.graph:
                console.print(f"[red]Note not found: {note_id}[/red]")
                raise typer.Exit(1)
            
            related = kg.get_related(note_id, depth=depth)
            n = note.load_note_by_id(note_id)
            
            result = {
                "note_id": note_id,
                "title": n.title if n else "",
                "related": related,
            }
            
            if json_output:
                console.print(output_json(result))
            else:
                tree = Tree(f"[bold]{n.title}[/bold] ({note_id})")
                
                for depth_key, note_ids in related.items():
                    depth_num = depth_key.split("_")[1]
                    level = tree.add(f"[dim]Depth {depth_num}[/dim]")
                    for nid in note_ids[:10]:  # 限制显示数量
                        rel_note = note.load_note_by_id(nid)
                        if rel_note:
                            level.add(f"[{rel_note.type.value}] {rel_note.title}")
                
                console.print(tree)
        
        else:
            # 显示整体图谱文本可视化
            viz = kg.visualize_text()
            console.print(viz)
    
    except Exception as e:
        result = {"success": False, "error": str(e)}
        if json_output:
            console.print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def daily(
    date: Optional[str] = typer.Option(None, "--date", "-d", help="日期 (YYYY-MM-DD, 默认今天)"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="JSON 输出"),
):
    """查看某天的笔记（默认今天）"""
    try:
        if date:
            target_date = datetime.strptime(date, "%Y-%m-%d")
        else:
            target_date = datetime.now()
        
        date_str = target_date.strftime("%Y%m%d")
        
        # 查找当天的笔记
        all_notes = note.list_notes()
        daily_notes = [n for n in all_notes if n.id.startswith(date_str)]
        
        result = {
            "date": target_date.strftime("%Y-%m-%d"),
            "total": len(daily_notes),
            "notes": [
                {
                    "id": n.id,
                    "title": n.title,
                    "type": n.type.value,
                    "created": n.created.isoformat() if n.created else None,
                }
                for n in daily_notes
            ],
        }
        
        if json_output:
            console.print(output_json(result))
        else:
            console.print(f"[bold]Notes for {target_date.strftime('%Y-%m-%d')}:[/bold]\n")
            if daily_notes:
                for n in daily_notes:
                    console.print(f"• [{n.type.value}] {n.title}")
            else:
                console.print("[dim]No notes found for this date.[/dim]")
    
    except Exception as e:
        result = {"success": False, "error": str(e)}
        if json_output:
            console.print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def inbox(
    limit: int = typer.Option(20, "--limit", "-n", help="显示数量"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="JSON 输出"),
):
    """查看临时笔记 (Fleeting Notes)"""
    try:
        fleeting_notes = note.list_notes(note_type=NoteType.FLEETING, limit=limit)
        
        result = {
            "total": len(fleeting_notes),
            "notes": [
                {
                    "id": n.id,
                    "title": n.title,
                    "created": n.created.isoformat() if n.created else None,
                    "filepath": str(n.filepath) if n.filepath else None,
                }
                for n in fleeting_notes
            ],
        }
        
        if json_output:
            console.print(output_json(result))
        else:
            console.print(f"[bold]Fleeting Notes ({len(fleeting_notes)}):[/bold]\n")
            for n in fleeting_notes:
                time_str = n.created.strftime("%H:%M") if n.created else ""
                console.print(f"• [{time_str}] {n.title}")
    
    except Exception as e:
        result = {"success": False, "error": str(e)}
        if json_output:
            console.print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def index(
    action: str = typer.Argument("status", help="操作: status, rebuild, verify"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="JSON 输出"),
):
    """索引管理：查看状态、重建索引、验证完整性"""
    try:
        vector_store = get_vector_store()
        indexer = Indexer(config, vector_store)
        
        if action == "status":
            stats = indexer.get_stats()
            vs_stats = vector_store.get_stats()
            
            result = {
                "total_indexed": stats.total_indexed,
                "last_indexed": stats.last_indexed.isoformat() if stats.last_indexed else None,
                "pending_changes": stats.pending_changes,
                "vector_store": vs_stats,
            }
            
            if json_output:
                console.print(output_json(result))
            else:
                table = Table(title="Index Status")
                table.add_column("Property", style="cyan")
                table.add_column("Value", style="green")
                table.add_row("Total Indexed", str(stats.total_indexed))
                table.add_row("Last Indexed", str(stats.last_indexed or "Never"))
                table.add_row("Pending Changes", str(stats.pending_changes))
                table.add_row("Vector Store Notes", str(vs_stats.get("total_notes", 0)))
                console.print(table)
                
                if stats.errors:
                    console.print("\n[yellow]Recent Errors:[/yellow]")
                    for err in stats.errors[-5:]:
                        console.print(f"  • {err}")
        
        elif action == "rebuild":
            console.print("[yellow]Rebuilding index...[/yellow]")
            count = indexer.index_all()
            
            result = {
                "success": True,
                "indexed": count,
            }
            
            if json_output:
                console.print(output_json(result))
            else:
                console.print(f"[green]✓[/green] Indexed {count} notes")
        
        elif action == "verify":
            verification = indexer.verify_index()
            
            result = verification
            
            if json_output:
                console.print(output_json(result))
            else:
                if verification["healthy"]:
                    console.print("[green]✓[/green] Index is healthy")
                else:
                    console.print("[yellow]⚠[/yellow] Index has issues")
                
                console.print(f"  Files: {verification['total_files']}")
                console.print(f"  Indexed: {verification['total_indexed']}")
                
                if verification["missing_from_index"]:
                    console.print(f"\n[yellow]Missing from index ({len(verification['missing_from_index'])}):[/yellow]")
                    for nid in verification["missing_from_index"][:5]:
                        console.print(f"  • {nid}")
                
                if verification["orphaned_in_index"]:
                    console.print(f"\n[yellow]Orphaned in index ({len(verification['orphaned_in_index'])}):[/yellow]")
                    for nid in verification["orphaned_in_index"][:5]:
                        console.print(f"  • {nid}")
        
        else:
            console.print(f"[red]Unknown action: {action}. Use: status, rebuild, verify[/red]")
            raise typer.Exit(1)
    
    except Exception as e:
        result = {"success": False, "error": str(e)}
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
