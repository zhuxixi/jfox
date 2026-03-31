"""Template management CLI commands"""

import os
import subprocess
from pathlib import Path
from typing import Optional, List

import typer
from rich.console import Console
from rich.table import Table

from .config import config
from .template import TemplateManager, TemplateError, TemplateNotFoundError


console = Console()

# Create template subcommand app
template_app = typer.Typer(
    name="template",
    help="Manage note templates",
)


def get_template_manager() -> TemplateManager:
    """Get template manager instance for current knowledge base"""
    templates_dir = config.base_dir / ".zk" / "templates"
    return TemplateManager(templates_dir)


@template_app.command("list")
def list_templates(
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"),
):
    """列出所有可用模板"""
    try:
        from .config import use_kb
        
        # 处理 --json 快捷方式
        if json_output:
            output_format = "json"
        
        if kb:
            with use_kb(kb):
                manager = get_template_manager()
                templates = manager.list_templates()
        else:
            manager = get_template_manager()
            templates = manager.list_templates()
        
        # Separate built-in and custom templates
        builtin_templates = [t for t in templates if t.is_builtin]
        custom_templates = [t for t in templates if not t.is_builtin]
        
        if output_format == "json":
            import json
            result = {
                "builtin": [
                    {
                        "name": t.name,
                        "description": t.description,
                        "note_type": t.note_type,
                    }
                    for t in builtin_templates
                ],
                "custom": [
                    {
                        "name": t.name,
                        "description": t.description,
                        "note_type": t.note_type,
                    }
                    for t in custom_templates
                ],
            }
            console.print(json.dumps(result, ensure_ascii=False, indent=2))
        elif output_format == "table":
            if builtin_templates:
                console.print("[bold]Built-in Templates:[/bold]")
                table = Table()
                table.add_column("Name", style="cyan")
                table.add_column("Description", style="white")
                table.add_column("Type", style="green")
                
                for t in builtin_templates:
                    table.add_row(t.name, t.description, t.note_type)
                console.print(table)
                console.print()
            
            if custom_templates:
                console.print("[bold]Custom Templates:[/bold]")
                table = Table()
                table.add_column("Name", style="cyan")
                table.add_column("Description", style="white")
                table.add_column("Type", style="green")
                
                for t in custom_templates:
                    table.add_row(t.name, t.description, t.note_type)
                console.print(table)
            elif not builtin_templates:
                console.print("[dim]No templates found[/dim]")
        else:
            console.print(f"[red]Error:[/red] Unsupported format: {output_format}")
            raise typer.Exit(1)
                
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@template_app.command("show")
def show_template(
    name: str = typer.Argument(..., help="模板名称"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="JSON 输出"),
):
    """查看模板详情"""
    try:
        from .config import use_kb
        
        if kb:
            with use_kb(kb):
                manager = get_template_manager()
                template = manager.get_template(name)
        else:
            manager = get_template_manager()
            template = manager.get_template(name)
        
        if not template:
            available = manager.get_available_templates()
            console.print(f"[red]Template '{name}' not found[/red]")
            if available:
                console.print(f"[dim]Available: {', '.join(available)}[/dim]")
            raise typer.Exit(1)
        
        if json_output:
            import json
            result = {
                "name": template.name,
                "description": template.description,
                "note_type": template.note_type,
                "title_format": template.title_format,
                "content": template.content,
                "tags": template.tags,
                "is_builtin": template.is_builtin,
            }
            console.print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            builtin_tag = " (built-in)" if template.is_builtin else ""
            console.print(f"[bold]{template.name}{builtin_tag}[/bold]")
            console.print(f"[dim]{template.description}[/dim]")
            console.print()
            console.print(f"Type: {template.note_type}")
            console.print(f"Title Format: {template.title_format}")
            console.print(f"Tags: {', '.join(template.tags) if template.tags else 'none'}")
            console.print()
            console.print("[bold]Content:[/bold]")
            console.print(template.content)
            
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@template_app.command("create")
def create_template(
    name: str = typer.Argument(..., help="模板名称"),
    description: Optional[str] = typer.Option(None, "--description", "-d", help="模板描述"),
    note_type: str = typer.Option("fleeting", "--type", "-t", help="笔记类型 (fleeting/literature/permanent)"),
    title_format: str = typer.Option("{{date}}-{{title}}", "--title-format", help="标题格式"),
    content: Optional[str] = typer.Option(None, "--content", "-c", help="模板内容"),
    tags: Optional[List[str]] = typer.Option(None, "--tag", help="默认标签"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    force: bool = typer.Option(False, "--force", "-f", help="覆盖已存在模板"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="JSON 输出"),
):
    """创建新模板"""
    try:
        from .config import use_kb
        
        if kb:
            with use_kb(kb):
                manager = get_template_manager()
        else:
            manager = get_template_manager()
        
        # Check if template exists
        existing = manager.get_template(name)
        if existing and not force:
            console.print(f"[red]Template '{name}' already exists[/red]")
            console.print("[dim]Use --force to overwrite[/dim]")
            raise typer.Exit(1)
        
        # Interactive mode if not all required fields provided
        desc = description or typer.prompt("Description", default=f"Custom {name} template")
        content_str = content or typer.prompt(
            "Content (use {{variable}} for variables)",
            default="## {{title}}\n\n{{content}}"
        )
        
        # Validate note_type
        if note_type not in ["fleeting", "literature", "permanent"]:
            console.print(f"[red]Invalid note type: {note_type}[/red]")
            raise typer.Exit(1)
        
        template = manager.create_template(
            name=name,
            description=desc,
            note_type=note_type,
            title_format=title_format,
            content=content_str,
            tags=tags or [],
        )
        
        if json_output:
            import json
            result = {
                "success": True,
                "template": {
                    "name": template.name,
                    "description": template.description,
                    "note_type": template.note_type,
                },
            }
            console.print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            action = "updated" if existing else "created"
            console.print(f"[green]Template '{name}' {action} successfully[/green]")
            
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@template_app.command("edit")
def edit_template(
    name: str = typer.Argument(..., help="模板名称"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
):
    """编辑模板（使用系统默认编辑器）"""
    try:
        from .config import use_kb
        
        if kb:
            with use_kb(kb):
                manager = get_template_manager()
                template = manager.get_template(name)
        else:
            manager = get_template_manager()
            template = manager.get_template(name)
        
        if not template:
            console.print(f"[red]Template '{name}' not found[/red]")
            raise typer.Exit(1)
        
        if template.is_builtin:
            console.print(f"[red]Cannot edit built-in template '{name}'[/red]")
            console.print("[dim]Create a custom template instead[/dim]")
            raise typer.Exit(1)
        
        template_path = manager.get_template_path(name)
        if not template_path:
            console.print(f"[red]Template file not found[/red]")
            raise typer.Exit(1)
        
        # Get editor from environment
        editor = os.environ.get("EDITOR", "notepad" if os.name == "nt" else "vi")
        
        # Open editor
        subprocess.run([editor, str(template_path)], check=True)
        console.print(f"[green]Template '{name}' updated[/green]")
        
    except subprocess.CalledProcessError as e:
        console.print(f"[red]Editor failed: {e}[/red]")
        raise typer.Exit(1)
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)


@template_app.command("remove")
def remove_template(
    name: str = typer.Argument(..., help="模板名称"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="JSON 输出"),
):
    """删除自定义模板"""
    try:
        from .config import use_kb
        
        if kb:
            with use_kb(kb):
                manager = get_template_manager()
        else:
            manager = get_template_manager()
        
        template = manager.get_template(name)
        if not template:
            console.print(f"[red]Template '{name}' not found[/red]")
            raise typer.Exit(1)
        
        if template.is_builtin:
            console.print(f"[red]Cannot remove built-in template '{name}'[/red]")
            raise typer.Exit(1)
        
        # Confirm deletion
        if not yes:
            if not json_output:
                confirm = input(f"Delete template '{name}'? (y/N): ")
                if confirm.lower() != "y":
                    console.print("Cancelled")
                    raise typer.Exit(0)
        
        manager.delete_template(name)
        
        if json_output:
            import json
            result = {"success": True, "deleted": name}
            console.print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            console.print(f"[green]Template '{name}' deleted[/green]")
            
    except Exception as e:
        console.print(f"[red]Error: {e}[/red]")
        raise typer.Exit(1)
