"""CLI 主程序"""

import json
import logging
import sys
import warnings
from datetime import datetime
from pathlib import Path
from typing import List, Optional

import yaml

# Windows 下强制 UTF-8 输出，避免中文乱码
if sys.platform == "win32":
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8")

# 过滤 networkx 的 backend 警告
warnings.filterwarnings(
    "ignore", category=RuntimeWarning, message="networkx backend defined more than once"
)

import typer
from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.tree import Tree

from . import __version__, note
from .config import config
from .kb_manager import get_kb_manager
from .models import NoteType
from .template import TemplateManager, TemplateNotFoundError, TemplateRenderError
from .template_cli import template_app

# 配置日志
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)

# 抑制第三方库的 INFO/DEBUG 日志，避免污染 CLI 输出
for _lib in (
    "sentence_transformers",
    "torch",
    "chromadb",
    "tqdm",
    "urllib3",
    "watchdog",
    "PIL",
):
    logging.getLogger(_lib).setLevel(logging.WARNING)

logger = logging.getLogger(__name__)

# config set 支持的配置项
_VALID_CONFIG_KEYS = {"device", "embedding_model", "batch_size"}

# 创建应用
app = typer.Typer(
    name="jfox",
    help="JFox - Zettelkasten 知识管理 CLI",
    add_completion=False,
)


def _version_callback(value: bool):
    if value:
        print(f"jfox {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        None,
        "--version",
        "-V",
        help="显示版本号",
        callback=_version_callback,
        is_eager=True,
    ),
):
    pass


# 添加子命令
app.add_typer(template_app, name="template", help="Manage note templates")

# Model 下载子命令
model_app = typer.Typer(name="model", help="模型管理")
app.add_typer(model_app, name="model", help="模型管理")

console = Console(legacy_windows=False)


def output_json(data: dict) -> str:
    """输出 JSON 格式"""
    return json.dumps(data, ensure_ascii=False, indent=2)


@app.command()
def init(
    name: Optional[str] = typer.Option(None, "--name", "-n", help="知识库名称（默认: default）"),
    path: Optional[str] = typer.Option(
        None, "--path", "-p", help="知识库路径（默认: ~/.zettelkasten/<name>/）"
    ),
    description: Optional[str] = typer.Option(None, "--desc", "-d", help="知识库描述"),
    set_default: bool = typer.Option(True, "--default/--no-default", help="设为默认知识库"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"
    ),
):
    """
    初始化知识库

    创建一个新的知识库并注册到全局配置。

    示例:
        jfox init                          # 初始化默认知识库（~/.zettelkasten/default/）
        jfox init --name work              # 创建名为 work 的知识库（~/.zettelkasten/work/）
        jfox init --name personal --desc "个人笔记"
    """
    try:
        # 向后兼容：--json 快捷方式
        if json_output:
            output_format = "json"

        kb_name = name or "default"
        manager = get_kb_manager()

        # 如果知识库已存在，提示错误
        if manager.config_manager.kb_exists(kb_name):
            result = {
                "success": False,
                "error": f"Knowledge base '{kb_name}' already exists. Use 'jfox kb list' to see all knowledge bases.",
            }
            if output_format == "json":
                print(output_json(result))
            else:
                console.print(f"[red]✗[/red] Knowledge base '{kb_name}' already exists")
                console.print("[dim]Use 'jfox kb list' to see all knowledge bases[/dim]")
            raise typer.Exit(1)

        # 确定路径
        path_obj = Path(path) if path else None

        # 用户显式指定路径时，验证必须在管理目录下
        if path_obj is not None:
            from jfox.global_config import DEFAULT_KB_PATH

            resolved = path_obj.expanduser().resolve()
            kb_root = DEFAULT_KB_PATH.resolve()
            try:
                resolved.relative_to(kb_root)
            except ValueError:
                result = {
                    "success": False,
                    "error": (
                        f"Path '{resolved}' is outside managed directory "
                        f"'{kb_root}'. All knowledge bases must be under {kb_root}/"
                    ),
                }
                if output_format == "json":
                    print(output_json(result))
                else:
                    console.print(f"[red]✗[/red] {result['error']}")
                raise typer.Exit(1)

        # 创建知识库
        success, message = manager.create(
            name=kb_name, path=path_obj, description=description, set_as_default=set_default
        )

        if success:
            result = {
                "success": True,
                "message": message,
                "name": kb_name,
            }

            if output_format == "json":
                print(output_json(result))
            else:
                _print_action_table(
                    "init",
                    {
                        "KB": kb_name,
                    },
                )
                if set_default:
                    console.print("[dim]  This is now your default knowledge base[/dim]")
        else:
            result = {
                "success": False,
                "error": message,
            }
            if output_format == "json":
                print(output_json(result))
            else:
                console.print(f"[red]✗[/red] {message}")
            raise typer.Exit(1)

    except typer.Exit:
        raise
    except Exception as e:
        result = {
            "success": False,
            "error": str(e),
        }
        if output_format == "json":
            print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


def _print_action_table(action: str, fields: dict):
    """打印紧凑的操作结果表格（单行）"""
    table = Table(show_header=True, box=None, padding=(0, 2))
    table.add_column("Action", style="green")
    for key in fields:
        table.add_column(key)
    table.add_row(action, *[str(v) for v in fields.values()])
    console.print(table)


def extract_wiki_links(content: str) -> List[str]:
    """从内容中提取 [[...]] 格式的维基链接"""
    import re

    pattern = r"\[\[(.*?)\]\]"
    matches = re.findall(pattern, content)
    return [m.strip() for m in matches]


def find_note_id_by_title_or_id(
    title_or_id: str, all_notes: Optional[list] = None
) -> Optional[str]:
    """通过标题或ID查找笔记

    匹配优先级：精确ID → 精确标题 → 标题包含
    """
    if all_notes is None:
        all_notes = note.list_notes()

    # 单次遍历，按优先级：精确ID → 精确标题 → 标题包含
    title_lower = title_or_id.lower()
    contains_match = None

    for n in all_notes:
        if n.id == title_or_id:
            return n.id
        if n.title.lower() == title_lower:
            return n.id
        if contains_match is None and title_lower in n.title.lower():
            contains_match = n.id

    return contains_match


def _add_note_impl(
    content: str,
    title: Optional[str],
    note_type: str,
    tags: Optional[List[str]],
    source: Optional[str],
    output_format: str,
    template: Optional[str] = None,
):
    """添加笔记的内部实现"""
    # 如果指定了模板，使用模板渲染
    if template:
        templates_dir = config.base_dir / ".zk" / "templates"
        template_manager = TemplateManager(templates_dir)

        try:
            # 准备模板变量
            template_vars = {
                "title": title or "",
                "content": content,
                "source": source or "",
            }

            # 渲染模板
            rendered = template_manager.render(template, template_vars)

            # 使用渲染结果
            content = rendered["content"]
            if rendered["title"]:
                title = rendered["title"]
            note_type = rendered["note_type"]
            # 合并模板的 tags 和用户提供的 tags
            template_tags = rendered["tags"]
            if tags:
                tags = list(set(template_tags + tags))
            else:
                tags = template_tags

        except TemplateNotFoundError as e:
            raise ValueError(str(e))
        except TemplateRenderError as e:
            raise ValueError(str(e))

    # 解析类型
    try:
        nt = NoteType(note_type.lower())
    except ValueError:
        raise ValueError(f"Invalid note type: {note_type}. Use: fleeting, literature, permanent")

    # 从内容中提取维基链接
    wiki_links = extract_wiki_links(content)
    resolved_links = []
    unresolved = []

    # 缓存笔记列表，避免每个链接重复加载
    all_notes = note.list_notes() if wiki_links else []

    for link_text in wiki_links:
        target_id = find_note_id_by_title_or_id(link_text, all_notes=all_notes)
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
        # 更新被链接笔记的反向链接
        backlink_updated = 0
        for target_id in resolved_links:
            target_note = note.load_note_by_id(target_id)
            if target_note:
                # 避免重复添加
                if new_note.id not in target_note.backlinks:
                    target_note.backlinks.append(new_note.id)
                    # 重新保存目标笔记
                    note.save_note(target_note, add_to_index=False)
                    backlink_updated += 1

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

        if output_format == "json":
            print(output_json(result))
        else:
            _print_action_table(
                "created",
                {
                    "ID": new_note.id,
                    "Title": new_note.title,
                    "Type": new_note.type.value,
                    "Links": str(len(resolved_links)),
                },
            )
            if backlink_updated > 0:
                console.print(f"[dim]  Backlinks updated: {backlink_updated} note(s)[/dim]")
            if unresolved:
                console.print(
                    f"  [yellow]Warning: Unresolved links - {', '.join(unresolved)}[/yellow]"
                )
    else:
        raise Exception("Failed to save note")


@app.command()
def add(
    content: Optional[str] = typer.Argument(None, help="笔记内容（支持 [[笔记标题]] 格式链接）"),
    title: Optional[str] = typer.Option(None, "--title", "-t", help="笔记标题"),
    note_type: str = typer.Option(
        "fleeting", "--type", help="笔记类型 (fleeting/literature/permanent)"
    ),
    tags: Optional[List[str]] = typer.Option(None, "--tag", help="标签（可多次使用）"),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="来源（文献笔记）"),
    template: Optional[str] = typer.Option(
        None, "--template", "-T", help="使用模板创建笔记 (quick/meeting/literature)"
    ),
    content_file: Optional[str] = typer.Option(
        None, "--content-file", help="从文件读取内容（用 - 表示 stdin）"
    ),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"
    ),
):
    """添加新笔记（内容中可用 [[笔记标题]] 引用其他笔记）"""
    try:
        # 向后兼容：--json 快捷方式
        if json_output:
            output_format = "json"

        # content 和 --content-file 互斥
        if content is not None and content_file is not None:
            raise ValueError("不能同时指定内容参数和 --content-file，请选择其一")

        # 从文件读取内容
        if content_file is not None:
            content = _read_content_file(content_file)

        # 至少提供一种内容来源
        if not content:
            raise ValueError("请提供笔记内容（位置参数或 --content-file）")

        # 如果指定了知识库，临时切换
        if kb:
            from .config import use_kb

            with use_kb(kb):
                _add_note_impl(content, title, note_type, tags, source, output_format, template)
        else:
            _add_note_impl(content, title, note_type, tags, source, output_format, template)

    except typer.Exit:
        raise
    except Exception as e:
        result = {
            "success": False,
            "error": str(e),
        }
        if output_format == "json":
            print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


def _search_impl(
    query: str,
    top: int,
    note_type: Optional[str],
    tags: Optional[List[str]],
    search_mode: str,
    output_format: str,
):
    """搜索笔记的内部实现"""
    from .formatters import OutputFormatter

    results = note.search_notes(query, top_k=top, note_type=note_type, tags=tags, mode=search_mode)

    result = {
        "query": query,
        "mode": search_mode,
        "total": len(results),
        "results": results,
    }

    if output_format == "json":
        print(OutputFormatter.to_json(result))
    elif output_format == "table":
        mode_display = {
            "hybrid": "Hybrid (BM25 + Semantic)",
            "semantic": "Semantic",
            "keyword": "Keyword (BM25)",
        }.get(search_mode, search_mode)

        console.print(f"[bold]Query:[/bold] {query}")
        console.print(f"[bold]Mode:[/bold] {mode_display}")
        console.print(f"[bold]Results:[/bold] {len(results)}\n")

        for i, r in enumerate(results, 1):
            score = r.get("score", 0)
            mode_badge = r.get("search_mode", "")
            badge = ""
            if mode_badge == "semantic":
                badge = " [cyan]S[/cyan]"
            elif mode_badge == "keyword":
                badge = " [yellow]K[/yellow]"

            console.print(f"{i}. [{score:.2f}]{badge} {r['metadata'].get('title', 'Untitled')}")
            console.print(f"   {r['document'][:100]}...")
            console.print()
    elif output_format == "csv":
        # 扁平化结果数据
        flat_results = []
        for r in results:
            flat_r = {
                "id": r.get("id", ""),
                "title": r.get("metadata", {}).get("title", ""),
                "type": r.get("metadata", {}).get("type", ""),
                "score": r.get("score", 0),
                "search_mode": r.get("search_mode", ""),
            }
            flat_results.append(flat_r)
        console.print(
            OutputFormatter.to_csv(
                flat_results, headers=["id", "title", "type", "score", "search_mode"]
            )
        )
    elif output_format == "yaml":
        print(OutputFormatter.to_yaml(result))
    elif output_format == "paths":
        # 从结果中提取文件路径
        from . import note as note_module

        paths = []
        for r in results:
            note_id = r.get("id")
            if note_id:
                n = note_module.load_note_by_id(note_id)
                if n and n.filepath:
                    paths.append({"filepath": n.filepath})
        console.print(OutputFormatter.to_paths(paths, key="filepath"))
    else:
        raise ValueError(f"Unsupported format: {output_format}")


@app.command()
def search(
    query: str = typer.Argument(..., help="搜索查询"),
    top: int = typer.Option(5, "--top", "-n", help="返回结果数量"),
    note_type: Optional[str] = typer.Option(None, "--type", "-t", help="筛选笔记类型"),
    tags: Optional[List[str]] = typer.Option(
        None, "--tag", help="按标签筛选（可多次使用，AND 逻辑）"
    ),
    search_mode: str = typer.Option(
        "hybrid", "--mode", "-m", help="搜索模式: hybrid, semantic, keyword"
    ),
    output_format: str = typer.Option(
        "table", "--format", "-f", help="输出格式: json, table, csv, yaml, paths"
    ),
    json_output: bool = typer.Option(False, "--json/--no-json", help="JSON 输出（向后兼容）"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
):
    """
    搜索笔记

    支持三种搜索模式：
    - hybrid: 混合搜索（BM25 + 语义），默认
    - semantic: 纯语义搜索
    - keyword: 纯关键词搜索 (BM25)

    示例:
        jfox search "Python" --mode hybrid
        jfox search "async await" --mode keyword --top 10
    """
    try:
        # 向后兼容：如果指定了 --json，使用 json 格式
        if json_output:
            output_format = "json"

        # 如果指定了知识库，临时切换
        if kb:
            from .config import use_kb

            with use_kb(kb):
                _search_impl(query, top, note_type, tags, search_mode, output_format)
        else:
            _search_impl(query, top, note_type, tags, search_mode, output_format)

    except Exception as e:
        result = {
            "success": False,
            "error": str(e),
        }
        if output_format == "json":
            print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


def _warn_dimension_change(new_model: str):
    """切换 embedding 模型时警告用户重建索引"""
    if new_model == "auto":
        return  # auto 模式不需要警告
    try:
        import chromadb

        chroma_path = config.chroma_dir
        if not chroma_path.exists():
            return
        client = chromadb.PersistentClient(path=str(chroma_path))
        collection = client.get_collection("notes")
        if collection.count() == 0:
            return  # 空索引，无需警告
    except Exception:
        return

    # 有已有索引 + 换了模型 = 需要重建
    console.print(
        f"\n[yellow]⚠ 模型已更改为 {new_model}[/yellow]\n"
        f"[yellow]  如果检索结果异常，请重建索引:[/yellow]\n"
        f"  jfox index rebuild\n"
    )


def _config_set_impl(key: str, value: str):
    """设置知识库配置项"""
    if key not in _VALID_CONFIG_KEYS:
        raise ValueError(f"不支持的配置项: {key}，可选值: {', '.join(sorted(_VALID_CONFIG_KEYS))}")

    config_path = config.zk_dir / "config.yaml"

    # 读取现有配置
    if config_path.exists():
        with open(config_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}

    # 类型转换
    if key == "batch_size":
        value = int(value)

    # 写入配置
    data[key] = value
    config_path.parent.mkdir(parents=True, exist_ok=True)
    with open(config_path, "w", encoding="utf-8") as f:
        yaml.dump(data, f, allow_unicode=True, sort_keys=False)

    # 同步更新内存中的 config 对象
    setattr(config, key, value if key != "batch_size" else int(value))

    # 重置 backend 单例，让新配置在下次使用时生效
    from .embedding_backend import reset_backend

    reset_backend()

    console.print(f"[green]✓ {key} = {value}[/green]")

    # 切换模型时检查维度
    if key == "embedding_model":
        _warn_dimension_change(value)


@app.command(name="config")
def config_cmd(
    action: str = typer.Argument(..., help="操作: set"),
    key: str = typer.Argument(None, help="配置项名称"),
    value: str = typer.Argument(None, help="配置值"),
):
    """
    查看/修改知识库配置

    示例:

        jfox config set device cuda
        jfox config set device auto
        jfox config set embedding_model BAAI/bge-m3
        jfox config set embedding_model auto
    """
    try:
        if action == "set":
            if key is None:
                console.print("[red]✗ 缺少配置项名称[/red]")
                raise typer.Exit(1)
            if value is None:
                console.print("[red]✗ 缺少配置值[/red]")
                raise typer.Exit(1)
            _config_set_impl(key, value)
        else:
            console.print(f"[red]✗ 未知操作: {action}[/red]")
            console.print("  可用操作: set")
            raise typer.Exit(1)
    except ValueError as e:
        console.print(f"[red]✗ {e}[/red]")
        raise typer.Exit(1)


def _status_impl(output_format: str, json_output: bool):
    """查看知识库状态的内部实现"""
    from .formatters import OutputFormatter

    stats = note.get_stats()

    # 获取 NPU 状态
    from .embedding_backend import get_backend

    backend = get_backend()

    result = {
        "knowledge_base": {
            "path": str(config.base_dir),
            "exists": config.base_dir.exists(),
        },
        "stats": stats,
        "backend": {
            "type": backend.resolved_device,
            "model": backend.model_name or "auto (未加载)",
            "dimension": backend.dimension,
        },
    }

    # 处理 --json 快捷方式
    if json_output:
        output_format = "json"

    # 根据格式输出
    if output_format == "json":
        print(OutputFormatter.to_json(result))
    elif output_format == "yaml":
        print(OutputFormatter.to_yaml(result))
    elif output_format == "table":
        # 打印表格
        table = Table(title="Knowledge Base Status")
        table.add_column("Property", style="cyan")
        table.add_column("Value", style="green")

        table.add_row("Base Path", str(config.base_dir))
        table.add_row("Total Notes", str(stats["total"]))
        table.add_row("Fleeting", str(stats["by_type"].get("fleeting", 0)))
        table.add_row("Literature", str(stats["by_type"].get("literature", 0)))
        table.add_row("Permanent", str(stats["by_type"].get("permanent", 0)))
        table.add_row("Backend", backend.resolved_device)
        table.add_row("Model", backend.model_name or "auto (未加载)")
        table.add_row("Dimension", str(backend.dimension))

        console.print(table)
    else:
        console.print(f"[red]Error:[/red] Unsupported format: {output_format}")
        raise typer.Exit(1)


@app.command()
def status(
    output_format: str = typer.Option(
        "table", "--format", "-f", help="输出格式: json, table, yaml"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"
    ),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
):
    """查看知识库状态"""
    try:
        # 如果指定了知识库，临时切换
        if kb:
            from .config import use_kb

            with use_kb(kb):
                _status_impl(output_format, json_output)
        else:
            _status_impl(output_format, json_output)

    except Exception as e:
        console.print(f"[red]Error:[/red] {e}")
        raise typer.Exit(1)


def _list_impl(
    note_type: Optional[str],
    tags: Optional[List[str]],
    limit: int,
    output_format: str,
):
    """列出笔记的内部实现"""
    from .formatters import OutputFormatter

    # 解析类型
    nt = None
    if note_type:
        try:
            nt = NoteType(note_type.lower())
        except ValueError:
            raise ValueError(f"Invalid note type: {note_type}")

    notes = note.list_notes(note_type=nt, tags=tags, limit=limit)
    data = [n.to_dict() for n in notes]

    result = {
        "total": len(notes),
        "notes": data,
    }

    if output_format == "json":
        print(OutputFormatter.to_json(result))
    elif output_format == "table":
        table = Table(title=f"Notes ({len(notes)} total)")
        table.add_column("ID", style="dim")
        table.add_column("Title", style="cyan")
        table.add_column("Type", style="green")
        table.add_column("Tags", style="yellow")
        table.add_column("Created", style="dim")

        for n in notes:
            created_str = n.created.strftime("%Y-%m-%d") if n.created else ""
            table.add_row(
                n.id, n.title[:40], n.type.value, ", ".join(n.tags) if n.tags else "", created_str
            )

        console.print(table)
    elif output_format == "tree":
        console.print(OutputFormatter.to_tree(data, group_by="type"))
    elif output_format in ["csv", "yaml", "paths"]:
        # 对于 csv, yaml, paths，只输出 notes 列表
        if output_format == "csv":
            console.print(
                OutputFormatter.to_csv(data, headers=["id", "title", "type", "tags", "created"])
            )
        elif output_format == "yaml":
            print(OutputFormatter.to_yaml(result))
        elif output_format == "paths":
            console.print(OutputFormatter.to_paths(data, key="filepath"))
    else:
        raise ValueError(f"Unsupported format: {output_format}")


@app.command()
def list(
    note_type: Optional[str] = typer.Option(None, "--type", "-t", help="筛选笔记类型"),
    tags: Optional[List[str]] = typer.Option(
        None, "--tag", help="按标签筛选（可多次使用，AND 逻辑）"
    ),
    limit: int = typer.Option(10, "--limit", "-n", help="显示数量"),
    output_format: str = typer.Option(
        "table", "--format", "-f", help="输出格式: json, table, csv, yaml, paths, tree"
    ),
    json_output: bool = typer.Option(False, "--json/--no-json", help="JSON 输出（向后兼容）"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
):
    """
    列出笔记

    支持多种输出格式：
    - json: JSON 格式
    - table: 表格格式（默认）
    - csv: CSV 格式，可用于 Excel
    - yaml: YAML 格式
    - paths: 仅输出文件路径
    - tree: 树形结构
    """
    try:
        # 向后兼容：如果指定了 --json，使用 json 格式
        if json_output:
            output_format = "json"

        # 如果指定了知识库，临时切换
        if kb:
            from .config import use_kb

            with use_kb(kb):
                _list_impl(note_type, tags, limit, output_format)
        else:
            _list_impl(note_type, tags, limit, output_format)

    except Exception as e:
        result = {
            "success": False,
            "error": str(e),
        }
        if output_format == "json":
            print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


def _show_impl(note_ref: str):
    """查看笔记完整内容的内部实现"""
    # 通过 ID 或标题定位笔记
    note_id = find_note_id_by_title_or_id(note_ref)
    if not note_id:
        raise ValueError(f"笔记不存在: {note_ref}")

    # 加载笔记
    n = note.load_note_by_id(note_id)
    if not n:
        raise ValueError(f"笔记不存在: {note_id}")

    # 输出原始 Markdown 内容
    content = n.filepath.read_text(encoding="utf-8")
    print(content)


@app.command()
def show(
    note_ref: str = typer.Argument(..., help="笔记 ID 或标题"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
):
    """
    查看笔记完整内容

    输出原始 Markdown（含 YAML frontmatter），只读不修改。
    支持通过笔记 ID 或标题定位。
    """
    try:
        if kb:
            from .config import use_kb

            with use_kb(kb):
                _show_impl(note_ref)
        else:
            _show_impl(note_ref)

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


def _refs_impl(
    note_id: Optional[str],
    search: Optional[str],
    output_format: str,
    json_output: bool,
):
    """查看笔记引用关系的内部实现"""
    if search:
        # 搜索笔记
        all_notes = note.list_notes()
        matches = [n for n in all_notes if search.lower() in n.title.lower()]

        result = {
            "query": search,
            "matches": [{"id": n.id, "title": n.title, "type": n.type.value} for n in matches],
        }

        if output_format == "json":
            print(output_json(result))
        else:
            console.print(f"[bold]Search:[/bold] '{search}'\n")
            if matches:
                for n in matches:
                    console.print(f"- [{n.type.value}] {n.title}")
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
                forward_links.append(
                    {"id": link_id, "title": link_note.title, "type": link_note.type.value}
                )

        # 获取反向链接
        backward_links = []
        for back_id in n.backlinks:
            back_note = note.load_note_by_id(back_id)
            if back_note:
                backward_links.append(
                    {"id": back_id, "title": back_note.title, "type": back_note.type.value}
                )

        result = {
            "note": {
                "id": n.id,
                "title": n.title,
                "type": n.type.value,
            },
            "forward_links": forward_links,
            "backward_links": backward_links,
        }

        if output_format == "json":
            print(output_json(result))
        else:
            console.print(f"[bold]{n.title}[/bold]\n")

            if forward_links:
                console.print("[cyan]→ Links to:[/cyan]")
                for link in forward_links:
                    console.print(f"  - [{link['type']}] {link['title']}")
                console.print()

            if backward_links:
                console.print("[green]← Linked by:[/green]")
                for link in backward_links:
                    console.print(f"  - [{link['type']}] {link['title']}")
                console.print()

            if not forward_links and not backward_links:
                console.print("[dim]No connections yet[/dim]")

    else:
        # 显示所有笔记及其链接统计
        all_notes = note.list_notes()
        notes_with_links = []
        for n in all_notes:
            notes_with_links.append(
                {
                    "id": n.id,
                    "title": n.title,
                    "type": n.type.value,
                    "outgoing": len(n.links),
                    "incoming": len(n.backlinks),
                }
            )

        result = {"notes": notes_with_links}

        if output_format == "json":
            print(output_json(result))
        else:
            table = Table(title="Note References")
            table.add_column("ID", style="dim")
            table.add_column("Title", style="cyan")
            table.add_column("Type", style="green")
            table.add_column("Out", justify="right")
            table.add_column("In", justify="right")

            for n in notes_with_links:
                table.add_row(
                    n["id"][:14], n["title"][:40], n["type"], str(n["outgoing"]), str(n["incoming"])
                )

            console.print(table)


@app.command()
def refs(
    note_id: Optional[str] = typer.Option(None, "--note", "-n", help="查看特定笔记的引用关系"),
    search: Optional[str] = typer.Option(None, "--search", "-s", help="搜索笔记标题"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"
    ),
):
    """查看笔记引用关系（反向链接）"""
    try:
        # 处理 --json 快捷方式
        if json_output:
            output_format = "json"

        # 如果指定了知识库，临时切换
        if kb:
            from .config import use_kb

            with use_kb(kb):
                _refs_impl(note_id, search, output_format, json_output)
        else:
            _refs_impl(note_id, search, output_format, json_output)

    except Exception as e:
        result = {"success": False, "error": str(e)}
        if output_format == "json":
            print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


def _delete_impl(
    note_id: str,
    force: bool,
    output_format: str,
):
    """删除笔记的内部实现"""
    # 先查找笔记
    n = note.load_note_by_id(note_id)
    if not n:
        raise ValueError(f"Note not found: {note_id}")

    # 确认删除
    if not force:
        if output_format == "json":
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

        if output_format == "json":
            print(output_json(result))
        else:
            _print_action_table(
                "deleted",
                {
                    "ID": note_id,
                    "Title": n.title,
                },
            )
    else:
        raise Exception("Failed to delete note")


@app.command()
def delete(
    note_id: str = typer.Argument(..., help="笔记 ID"),
    force: bool = typer.Option(False, "--force", "-f", help="强制删除不确认"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    output_format: str = typer.Option("table", "--format", help="输出格式: json, table"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"
    ),
):
    """删除笔记"""
    try:
        # 向后兼容：--json 快捷方式
        if json_output:
            output_format = "json"

        # 如果指定了知识库，临时切换
        if kb:
            from .config import use_kb

            with use_kb(kb):
                _delete_impl(note_id, force, output_format)
        else:
            _delete_impl(note_id, force, output_format)

    except typer.Exit:
        raise
    except Exception as e:
        result = {
            "success": False,
            "error": str(e),
        }
        if output_format == "json":
            print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


def _read_content_file(content_file: str) -> str:
    """从文件或 stdin 读取内容（--content-file 共用逻辑）"""
    if content_file == "-":
        import sys

        return sys.stdin.read()

    p = Path(content_file)
    if not p.exists():
        raise ValueError(f"文件不存在: {content_file}")
    if not p.is_file():
        raise ValueError(f"路径不是文件: {content_file}")
    try:
        return p.read_text(encoding="utf-8")
    except PermissionError:
        raise ValueError(f"无权限读取文件: {content_file}")
    except UnicodeDecodeError:
        raise ValueError(f"文件编码错误（需要 UTF-8）: {content_file}")


def _edit_impl(
    note_id: str,
    content: Optional[str],
    content_file: Optional[str],
    title: Optional[str],
    tags: Optional[List[str]],
    note_type: Optional[str],
    source: Optional[str],
    output_format: str,
):
    """编辑笔记的内部实现"""
    # 验证：--content 和 --content-file 互斥
    if content is not None and content_file is not None:
        raise ValueError("--content 和 --content-file 不能同时指定")

    # 从文件读取内容
    if content_file is not None:
        content = _read_content_file(content_file)

    # 验证：至少指定一个编辑字段
    if all(v is None for v in [content, title, tags, note_type, source]):
        raise ValueError(
            "至少指定一个要编辑的字段 "
            "(--content, --content-file, --title, --tags, --type, --source)"
        )

    # 加载笔记
    n = note.load_note_by_id(note_id)
    if not n:
        raise ValueError(f"笔记不存在: {note_id}")

    old_title = n.title
    old_links = set(n.links)

    # 更新字段
    if content is not None:
        n.content = content
    if title is not None:
        n.title = title
    if tags is not None:
        n.tags = tags
    if source is not None:
        n.source = source if source else None  # 空字符串清除 source
    if note_type is not None:
        try:
            new_type = NoteType(note_type.lower())
        except ValueError:
            raise ValueError(
                f"Invalid note type: {note_type}. Use: fleeting, literature, permanent"
            )
        n.type = new_type

    # 如果内容被更新，解析 wiki links
    if content is not None:
        wiki_links = extract_wiki_links(content)
        resolved_links = []
        unresolved = []

        all_notes = note.list_notes() if wiki_links else []
        for link_text in wiki_links:
            target_id = find_note_id_by_title_or_id(link_text, all_notes=all_notes)
            if target_id:
                resolved_links.append(target_id)
            else:
                unresolved.append(link_text)

        n.links = resolved_links
    else:
        unresolved = []

    # 保存更新
    if note.update_note(n):
        # 更新反向链接
        new_links = set(n.links)

        # 新增的链接 → 添加反向链接
        added_links = new_links - old_links
        for target_id in added_links:
            target_note = note.load_note_by_id(target_id)
            if target_note and n.id not in target_note.backlinks:
                target_note.backlinks.append(n.id)
                note.save_note(target_note, add_to_index=False)

        # 移除的链接 → 删除反向链接
        removed_links = old_links - new_links
        for target_id in removed_links:
            target_note = note.load_note_by_id(target_id)
            if target_note and n.id in target_note.backlinks:
                target_note.backlinks.remove(n.id)
                note.save_note(target_note, add_to_index=False)

        result = {
            "success": True,
            "note": {
                "id": n.id,
                "title": n.title,
                "type": n.type.value,
                "filepath": str(n.filepath),
            },
        }
        if old_title != n.title:
            result["title_changed"] = {"old": old_title, "new": n.title}
        if unresolved:
            result["warnings"] = f"Unresolved links: {', '.join(unresolved)}"

        if output_format == "json":
            print(output_json(result))
        else:
            # 收集修改的字段名
            changed = []
            if content is not None:
                changed.append("content")
            if title is not None:
                changed.append("title")
            if tags is not None:
                changed.append("tags")
            if note_type is not None:
                changed.append("type")
            if source is not None:
                changed.append("source")
            _print_action_table(
                "updated",
                {
                    "ID": n.id,
                    "Title": n.title,
                    "Fields": ", ".join(changed),
                },
            )
            if old_title != n.title:
                console.print(f"  [dim]Title: {old_title} → {n.title}[/dim]")
            if unresolved:
                console.print(
                    f"  [yellow]Warning: Unresolved links - {', '.join(unresolved)}[/yellow]"
                )
    else:
        raise Exception("Failed to update note")


@app.command()
def edit(
    note_id: str = typer.Argument(..., help="笔记 ID"),
    content: Optional[str] = typer.Option(None, "--content", "-c", help="新内容"),
    content_file: Optional[str] = typer.Option(
        None, "--content-file", help="从文件读取内容（支持长文本和特殊字符）"
    ),
    title: Optional[str] = typer.Option(None, "--title", "-t", help="新标题"),
    tags: Optional[List[str]] = typer.Option(None, "--tag", help="新标签（替换全部）"),
    note_type: Optional[str] = typer.Option(
        None, "--type", help="新类型 (fleeting/literature/permanent)"
    ),
    source: Optional[str] = typer.Option(None, "--source", "-s", help="新来源"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"
    ),
):
    """编辑已有笔记（保留 ID 和创建时间）"""
    try:
        # 向后兼容：--json 快捷方式
        if json_output:
            output_format = "json"

        if kb:
            from .config import use_kb

            with use_kb(kb):
                _edit_impl(
                    note_id, content, content_file, title, tags, note_type, source, output_format
                )
        else:
            _edit_impl(
                note_id, content, content_file, title, tags, note_type, source, output_format
            )
    except typer.Exit:
        raise
    except Exception as e:
        result = {
            "success": False,
            "error": str(e),
        }
        if output_format == "json":
            print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


def _query_impl(
    query_str: str,
    top: int,
    graph_depth: int,
    json_output: bool,
):
    """语义搜索 + 知识图谱联合查询的内部实现"""
    # 1. 语义搜索
    vector_results = note.search_notes(query_str, top_k=top)

    # 2. 构建知识图谱并查找相关笔记
    from .graph import KnowledgeGraph

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
                    related_notes.append(
                        {
                            "id": nid,
                            "title": n.title,
                            "type": n.type.value,
                            "depth": depth,
                        }
                    )

        enriched_results.append(
            {
                **r,
                "related_notes": related_notes,
                "graph_stats": {
                    "neighbors": len(graph.get_neighbors(note_id)),
                },
            }
        )

    result = {
        "query": query_str,
        "semantic_results": len(vector_results),
        "results": enriched_results,
    }

    if json_output:
        print(output_json(result))
    else:
        console.print(f"[bold]Query:[/bold] {query_str}")
        console.print(f"[bold]Results:[/bold] {len(enriched_results)}\n")

        for i, r in enumerate(enriched_results, 1):
            score = r.get("score", 0)
            panel_content = f"[cyan]{r['document'][:150]}...[/cyan]"

            if r["related_notes"]:
                panel_content += "\n\n[dim]Related:[/dim]"
                for rel in r["related_notes"][:3]:
                    panel_content += f"\n  - [{rel['type']}] {rel['title']}"

            console.print(
                Panel(
                    panel_content,
                    title=f"{i}. [{score:.2f}] {r['metadata'].get('title', 'Untitled')}",
                    border_style="blue",
                )
            )


@app.command()
def query(
    query_str: str = typer.Argument(..., help="搜索查询"),
    top: int = typer.Option(5, "--top", "-n", help="返回结果数量"),
    graph_depth: int = typer.Option(2, "--depth", "-d", help="图谱遍历深度"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="JSON 输出"),
):
    """语义搜索 + 知识图谱联合查询"""
    try:
        # 如果指定了知识库，临时切换
        if kb:
            from .config import use_kb

            with use_kb(kb):
                _query_impl(query_str, top, graph_depth, json_output)
        else:
            _query_impl(query_str, top, graph_depth, json_output)

    except Exception as e:
        result = {"success": False, "error": str(e)}
        if json_output:
            print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


def _graph_impl(
    note_id: Optional[str],
    depth: int,
    stats: bool,
    orphans: bool,
    output_format: str,
    json_output: bool,
):
    """知识图谱可视化和分析的内部实现"""
    from .graph import KnowledgeGraph

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

        if output_format == "json":
            print(output_json(result))
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
                console.print(f"  - {nid}: {title} ({deg} connections)")

    elif orphans:
        # 显示孤立笔记
        orphan_ids = kg.get_orphan_notes()
        orphans_list = []
        for oid in orphan_ids:
            n = note.load_note_by_id(oid)
            if n:
                orphans_list.append({"id": oid, "title": n.title, "type": n.type.value})

        result = {"orphans": orphans_list}

        if output_format == "json":
            print(output_json(result))
        else:
            console.print(f"[bold]Orphan Notes ({len(orphans_list)}):[/bold]\n")
            for o in orphans_list:
                console.print(f"  - [{o['type']}] {o['title']} ({o['id']})")

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

        if output_format == "json":
            print(output_json(result))
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


@app.command()
def graph(
    note_id: Optional[str] = typer.Option(None, "--note", "-n", help="查看特定笔记的图谱"),
    depth: int = typer.Option(2, "--depth", "-d", help="遍历深度"),
    stats: bool = typer.Option(False, "--stats", "-s", help="显示统计信息"),
    orphans: bool = typer.Option(False, "--orphans", "-o", help="显示孤立笔记"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"
    ),
):
    """知识图谱可视化和分析"""
    try:
        # 处理 --json 快捷方式
        if json_output:
            output_format = "json"

        # 如果指定了知识库，临时切换
        if kb:
            from .config import use_kb

            with use_kb(kb):
                _graph_impl(note_id, depth, stats, orphans, output_format, json_output)
        else:
            _graph_impl(note_id, depth, stats, orphans, output_format, json_output)

    except Exception as e:
        result = {"success": False, "error": str(e)}
        if output_format == "json":
            print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


def _daily_impl(
    date: Optional[str],
    output_format: str,
    json_output: bool,
):
    """查看某天笔记的内部实现"""
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

    if output_format == "json":
        print(output_json(result))
    else:
        console.print(f"[bold]Notes for {target_date.strftime('%Y-%m-%d')}:[/bold]\n")
        if daily_notes:
            for n in daily_notes:
                console.print(f"- [{n.type.value}] {n.title}")
        else:
            console.print("[dim]No notes found for this date.[/dim]")


@app.command()
def daily(
    date: Optional[str] = typer.Option(None, "--date", "-d", help="日期 (YYYY-MM-DD, 默认今天)"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"
    ),
):
    """查看某天的笔记（默认今天）"""
    try:
        # 处理 --json 快捷方式
        if json_output:
            output_format = "json"

        # 如果指定了知识库，临时切换
        if kb:
            from .config import use_kb

            with use_kb(kb):
                _daily_impl(date, output_format, json_output)
        else:
            _daily_impl(date, output_format, json_output)

    except Exception as e:
        result = {"success": False, "error": str(e)}
        if output_format == "json":
            print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


def _inbox_impl(
    limit: int,
    output_format: str,
    json_output: bool,
):
    """查看临时笔记的内部实现"""
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

    if output_format == "json":
        print(output_json(result))
    else:
        console.print(f"[bold]Fleeting Notes ({len(fleeting_notes)}):[/bold]\n")
        for n in fleeting_notes:
            time_str = n.created.strftime("%H:%M") if n.created else ""
            console.print(f"- [{time_str}] {n.title}")


def _suggest_links_impl(
    content: str,
    top_k: int,
    threshold: float,
    output_format: str,
    json_output: bool,
):
    """推荐链接笔记的内部实现"""
    suggestions = note.suggest_links(content, top_k=top_k, threshold=threshold)

    result = {
        "content": content[:200] + "..." if len(content) > 200 else content,
        "total_suggestions": len(suggestions),
        "threshold": threshold,
        "suggestions": suggestions,
    }

    if output_format == "json":
        print(output_json(result))
    else:
        if suggestions:
            console.print(f"[bold]Suggested links (confidence > {threshold}):[/bold]\n")
            for i, s in enumerate(suggestions, 1):
                match_badge = (
                    "[cyan]semantic[/cyan]"
                    if s["match_type"] == "semantic"
                    else "[yellow]keyword[/yellow]"
                )
                console.print(f"{i}. [{s['score']:.2f}] {s['title']} ({s['id']})")
                console.print(f"   Match type: {match_badge}")
                if s.get("matched_keywords"):
                    console.print(f"   Keywords: {', '.join(s['matched_keywords'])}")
                console.print()

            console.print('[dim]Use with: jfox add "... [[note title]] ..."[/dim]')
        else:
            console.print(f"[dim]No suggestions found (threshold: {threshold})[/dim]")


@app.command()
def suggest_links(
    content: str = typer.Argument(..., help="内容文本（用于推荐相关笔记）"),
    top_k: int = typer.Option(5, "--top", "-n", help="返回建议数量"),
    threshold: float = typer.Option(0.6, "--threshold", "-t", help="相似度阈值 (0-1)"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"
    ),
):
    """
    根据内容推荐可以链接的已有笔记

    使用语义相似度和关键词匹配混合策略，帮助发现知识间的联系。

    示例:
        jfox suggest-links "今天学习了 Python 的 async/await 机制"
        jfox suggest-links "笔记内容" --top 10 --threshold 0.5
    """
    # 处理 --json 快捷方式
    if json_output:
        output_format = "json"

    try:
        # 如果指定了知识库，临时切换
        if kb:
            from .config import use_kb

            with use_kb(kb):
                _suggest_links_impl(content, top_k, threshold, output_format, json_output)
        else:
            _suggest_links_impl(content, top_k, threshold, output_format, json_output)

    except Exception as e:
        result = {"success": False, "error": str(e)}
        if output_format == "json":
            print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def inbox(
    limit: int = typer.Option(20, "--limit", "-n", help="显示数量"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"
    ),
):
    """查看临时笔记 (Fleeting Notes)"""
    try:
        # 处理 --json 快捷方式
        if json_output:
            output_format = "json"

        # 如果指定了知识库，临时切换
        if kb:
            from .config import use_kb

            with use_kb(kb):
                _inbox_impl(limit, output_format, json_output)
        else:
            _inbox_impl(limit, output_format, json_output)

    except Exception as e:
        result = {"success": False, "error": str(e)}
        if output_format == "json":
            print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


def _index_impl(action: str, output_format: str):
    """索引管理实现：查看状态、重建索引、验证完整性"""
    if action == "rebuild-bm25":
        # 重建 BM25 索引
        from . import note as note_module
        from .bm25_index import get_bm25_index

        console.print("[yellow]Rebuilding BM25 index...[/yellow]")
        bm25_index = get_bm25_index()
        notes = note_module.list_notes(limit=10000)
        success = bm25_index.rebuild_from_notes(notes)

        result = {
            "success": success,
            "indexed": len(notes),
        }

        if output_format == "json":
            print(output_json(result))
        else:
            if success:
                console.print(f"[green]✓[/green] BM25 index rebuilt: {len(notes)} notes")
            else:
                console.print("[red]✗[/red] Failed to rebuild BM25 index")

    elif action == "bm25-status":
        # 查看 BM25 索引状态
        from .bm25_index import get_bm25_index

        bm25_index = get_bm25_index()
        stats = bm25_index.get_stats()

        result = {
            "bm25_index": stats,
        }

        if output_format == "json":
            print(output_json(result))
        else:
            table = Table(title="BM25 Index Status")
            table.add_column("Property", style="cyan")
            table.add_column("Value", style="green")
            table.add_row("Indexed Documents", str(stats["indexed"]))
            table.add_row("Index Version", str(stats["version"]))
            table.add_row("Index File", str(stats["index_path"]))
            table.add_row("Index Exists", "Yes" if stats["index_exists"] else "No")
            console.print(table)

    else:
        from .indexer import Indexer
        from .vector_store import get_vector_store

        vector_store = get_vector_store()
        indexer = Indexer(config, vector_store)

        if action == "status":
            stats = indexer.get_stats()
            vs_stats = vector_store.get_stats()

            result = {
                "total_indexed": stats.total_indexed,
                "last_indexed": (stats.last_indexed.isoformat() if stats.last_indexed else None),
                "pending_changes": stats.pending_changes,
                "vector_store": vs_stats,
            }

            if output_format == "json":
                print(output_json(result))
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
                        console.print(f"  - {err}")

        elif action == "rebuild":
            console.print("[yellow]Rebuilding index...[/yellow]")
            count = indexer.index_all()

            # 同时重建 BM25 索引
            from . import note as note_module
            from .bm25_index import get_bm25_index

            bm25_index = get_bm25_index()
            notes = note_module.list_notes(limit=10000)
            bm25_success = bm25_index.rebuild_from_notes(notes)

            result = {
                "success": True,
                "indexed": count,
                "bm25_rebuilt": bm25_success,
                "bm25_indexed": len(notes),
            }

            if output_format == "json":
                print(output_json(result))
            else:
                console.print(f"[green]✓[/green] Indexed {count} notes")
                if bm25_success:
                    console.print(f"[green]✓[/green] BM25 index rebuilt: {len(notes)} notes")
                else:
                    console.print("[yellow]⚠[/yellow] ChromaDB rebuilt, but BM25 rebuild failed")

        elif action == "verify":
            verification = indexer.verify_index()

            result = verification

            if output_format == "json":
                print(output_json(result))
            else:
                if verification["healthy"]:
                    console.print("[green]✓[/green] Index is healthy")
                else:
                    console.print("[yellow]⚠[/yellow] Index has issues")

                console.print(f"  Files: {verification['total_files']}")
                console.print(f"  Indexed: {verification['total_indexed']}")

                if verification["missing_from_index"]:
                    console.print(
                        f"\n[yellow]Missing from index "
                        f"({len(verification['missing_from_index'])}):[/yellow]"
                    )
                for nid in verification["missing_from_index"][:5]:
                    console.print(f"  - {nid}")

                if verification["orphaned_in_index"]:
                    console.print(
                        f"\n[yellow]Orphaned in index "
                        f"({len(verification['orphaned_in_index'])}):[/yellow]"
                    )
                    for nid in verification["orphaned_in_index"][:5]:
                        console.print(f"  - {nid}")

        else:
            console.print(
                f"[red]Unknown action: {action}. "
                "Use: status, rebuild, verify, rebuild-bm25, bm25-status[/red]"
            )
            raise typer.Exit(1)


@app.command()
def index(
    action: str = typer.Argument(
        "status", help="操作: status, rebuild, verify, rebuild-bm25, bm25-status"
    ),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"
    ),
):
    """索引管理：查看状态、重建索引、验证完整性"""
    try:
        # 处理 --json 快捷方式
        if json_output:
            output_format = "json"

        # 如果指定了知识库，临时切换
        if kb:
            from .config import use_kb

            with use_kb(kb):
                _index_impl(action, output_format)
        else:
            _index_impl(action, output_format)

    except typer.Exit:
        raise
    except Exception as e:
        result = {"success": False, "error": str(e)}
        if json_output:
            print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


# =============================================================================
# 知识库管理命令
# =============================================================================


@app.command()
def kb(
    action: str = typer.Argument(
        "list", help="操作: list, create, switch/use, remove, info, current, rename"
    ),
    name: Optional[str] = typer.Argument(None, help="知识库名称"),
    new_name: Optional[str] = typer.Argument(None, help="新名称（仅 rename 使用）"),
    path: Optional[str] = typer.Option(None, "--path", "-p", help="知识库路径（仅 create 使用）"),
    description: Optional[str] = typer.Option(None, "--desc", "-d", help="知识库描述"),
    force: bool = typer.Option(False, "--force", "-f", help="强制操作（删除时跳过确认）"),
    set_default: bool = typer.Option(False, "--default", help="创建后设为默认"),
    output_format: str = typer.Option(
        "table", "--format", help="输出格式: json, table, csv, yaml（仅 list/info/current 有效）"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"
    ),
):
    """
    知识库管理：列出、创建、切换、删除知识库

    示例:
        jfox kb list                    # 列出所有知识库
        jfox kb create work             # 创建名为 work 的知识库（~/.zettelkasten/work/）
        jfox kb create work --desc "工作笔记"
        jfox kb use work                # 切换到 work 知识库（或 jfox kb switch work）
        jfox kb current                 # 显示当前知识库
        jfox kb info work               # 查看 work 知识库详情
        jfox kb remove temp --force     # 强制删除 temp 知识库
        jfox kb rename old new          # 重命名知识库
    """
    try:
        manager = get_kb_manager()

        if action == "list":
            # 列出所有知识库
            from .formatters import OutputFormatter

            stats_list = manager.list_all()

            result = {
                "current": manager.config_manager.get_default_kb_name(),
                "knowledge_bases": [
                    {
                        "name": s.name,
                        "path": str(s.path),
                        "total_notes": s.total_notes,
                        "by_type": s.by_type,
                        "created": s.created,
                        "last_used": s.last_used,
                        "description": s.description,
                        "is_current": s.is_current,
                    }
                    for s in stats_list
                ],
            }

            # 处理 --json 快捷方式
            if json_output:
                output_format = "json"

            # 根据格式输出
            if output_format == "json":
                print(OutputFormatter.to_json(result))
            elif output_format == "yaml":
                print(OutputFormatter.to_yaml(result))
            elif output_format == "csv":
                # CSV 格式
                flat_data = []
                for s in stats_list:
                    flat_data.append(
                        {
                            "name": s.name,
                            "path": str(s.path),
                            "total_notes": s.total_notes,
                            "fleeting": s.by_type.get("fleeting", 0),
                            "literature": s.by_type.get("literature", 0),
                            "permanent": s.by_type.get("permanent", 0),
                            "created": s.created,
                            "last_used": s.last_used or "",
                            "description": s.description or "",
                            "is_current": "*" if s.is_current else "",
                        }
                    )
                console.print(
                    OutputFormatter.to_csv(
                        flat_data,
                        headers=[
                            "name",
                            "path",
                            "total_notes",
                            "fleeting",
                            "literature",
                            "permanent",
                            "created",
                            "last_used",
                            "description",
                            "is_current",
                        ],
                    )
                )
            elif output_format == "table":
                table = Table(title="Knowledge Bases")
                table.add_column("Status", style="dim", justify="center")
                table.add_column("Name", style="cyan")
                table.add_column("Path", style="green")
                table.add_column("Notes", justify="right")
                table.add_column("F/L/P", justify="center")
                table.add_column("Last Used", style="dim")

                for s in stats_list:
                    status = "*" if s.is_current else ""
                    types_str = f"{s.by_type.get('fleeting', 0)}/{s.by_type.get('literature', 0)}/{s.by_type.get('permanent', 0)}"
                    last_used = s.last_used[:10] if s.last_used else "Never"
                    table.add_row(
                        status,
                        s.name,
                        str(s.path)[:40],
                        str(s.total_notes),
                        types_str,
                        last_used,
                    )

                console.print(table)
                console.print("\n[dim]* = current default[/dim]")
            else:
                console.print(f"[red]Error:[/red] Unsupported format: {output_format}")
                raise typer.Exit(1)

        elif action == "create":
            if not name:
                console.print("[red]Error: name is required for create[/red]")
                raise typer.Exit(1)

            path_obj = Path(path) if path else None

            # 用户显式指定路径时，验证必须在管理目录下
            if path_obj is not None:
                from jfox.global_config import DEFAULT_KB_PATH

                resolved = path_obj.expanduser().resolve()
                kb_root = DEFAULT_KB_PATH.resolve()
                try:
                    resolved.relative_to(kb_root)
                except ValueError:
                    console.print(
                        f"[red]✗[/red] Path '{resolved}' is outside managed directory "
                        f"'{kb_root}'. All knowledge bases must be under {kb_root}/"
                    )
                    raise typer.Exit(1)

            success, message = manager.create(
                name=name, path=path_obj, description=description, set_as_default=set_default
            )

            result = {"success": success, "message": message}

            if json_output:
                print(output_json(result))
            else:
                if success:
                    console.print(f"[green]✓[/green] {message}")
                else:
                    console.print(f"[red]✗[/red] {message}")
                    raise typer.Exit(1)

        elif action in ("switch", "use"):
            if not name:
                console.print("[red]Error: name is required for switch/use[/red]")
                raise typer.Exit(1)

            success, message = manager.switch(name)
            result = {"success": success, "message": message}

            if json_output:
                print(output_json(result))
            else:
                if success:
                    console.print(f"[green]✓[/green] {message}")
                else:
                    console.print(f"[red]✗[/red] {message}")
                    raise typer.Exit(1)

        elif action == "remove" or action == "delete":
            if not name:
                console.print("[red]Error: name is required for remove[/red]")
                raise typer.Exit(1)

            # 确认删除
            if not force and not json_output:
                kb_info = manager.get_info(name)
                if kb_info:
                    console.print(f"Knowledge base: {kb_info.name}")
                    console.print(f"Path: {kb_info.path}")
                    console.print(f"Notes: {kb_info.total_notes}")
                    confirm = input("\nDelete this knowledge base? [y/N]: ")
                    if confirm.lower() != "y":
                        console.print("Cancelled")
                        raise typer.Exit(0)

            success, message = manager.remove(name, delete_data=force)
            result = {"success": success, "message": message}

            if json_output:
                print(output_json(result))
            else:
                if success:
                    console.print(f"[green]✓[/green] {message}")
                else:
                    console.print(f"[red]✗[/red] {message}")
                    raise typer.Exit(1)

        elif action == "current":
            # 显示当前知识库
            from .formatters import OutputFormatter

            current_name = manager.config_manager.get_default_kb_name()

            if not current_name:
                console.print("[red]No default knowledge base configured[/red]")
                raise typer.Exit(1)

            stats = manager.get_info(current_name)
            if not stats:
                console.print(f"[red]Knowledge base '{current_name}' not found[/red]")
                raise typer.Exit(1)

            result = {
                "name": stats.name,
                "path": str(stats.path),
                "total_notes": stats.total_notes,
                "by_type": stats.by_type,
                "created": stats.created,
                "last_used": stats.last_used,
                "description": stats.description,
                "is_current": True,
            }

            # 处理 --json 快捷方式
            if json_output:
                output_format = "json"

            # 根据格式输出
            if output_format == "json":
                print(OutputFormatter.to_json(result))
            elif output_format == "yaml":
                print(OutputFormatter.to_yaml(result))
            elif output_format == "table":
                # 表格格式输出
                table = Table(title=f"Current Knowledge Base: {stats.name}")
                table.add_column("Property", style="cyan")
                table.add_column("Value", style="green")

                table.add_row("Name", stats.name)
                table.add_row("Path", str(stats.path))
                table.add_row("Description", stats.description or "N/A")
                table.add_row("Created", stats.created or "Unknown")
                table.add_row("Last Used", stats.last_used or "Never")
                table.add_row("Total Notes", str(stats.total_notes))
                table.add_row("Fleeting", str(stats.by_type.get("fleeting", 0)))
                table.add_row("Literature", str(stats.by_type.get("literature", 0)))
                table.add_row("Permanent", str(stats.by_type.get("permanent", 0)))

                console.print(table)
            else:
                console.print(f"[red]Error:[/red] Unsupported format: {output_format}")
                raise typer.Exit(1)

        elif action == "info":
            # 如果没有指定名称，显示当前知识库
            from .formatters import OutputFormatter

            target_name = name or manager.config_manager.get_default_kb_name()

            stats = manager.get_info(target_name)
            if not stats:
                console.print(f"[red]Knowledge base '{target_name}' not found[/red]")
                raise typer.Exit(1)

            result = {
                "name": stats.name,
                "path": str(stats.path),
                "total_notes": stats.total_notes,
                "by_type": stats.by_type,
                "created": stats.created,
                "last_used": stats.last_used,
                "description": stats.description,
                "is_current": stats.is_current,
            }

            # 处理 --json 快捷方式
            if json_output:
                output_format = "json"

            # 根据格式输出
            if output_format == "json":
                print(OutputFormatter.to_json(result))
            elif output_format == "yaml":
                print(OutputFormatter.to_yaml(result))
            elif output_format == "table":
                # 表格格式输出
                title = f"Knowledge Base: {stats.name}"
                if stats.is_current:
                    title += " [current]"
                table = Table(title=title)
                table.add_column("Property", style="cyan")
                table.add_column("Value", style="green")

                table.add_row("Name", stats.name)
                table.add_row("Path", str(stats.path))
                table.add_row("Description", stats.description or "N/A")
                table.add_row("Created", stats.created or "Unknown")
                table.add_row("Last Used", stats.last_used or "Never")
                table.add_row("Total Notes", str(stats.total_notes))
                table.add_row("Fleeting", str(stats.by_type.get("fleeting", 0)))
                table.add_row("Literature", str(stats.by_type.get("literature", 0)))
                table.add_row("Permanent", str(stats.by_type.get("permanent", 0)))

                console.print(table)
            else:
                console.print(f"[red]Error:[/red] Unsupported format: {output_format}")
                raise typer.Exit(1)

        elif action == "rename":
            if not name or not new_name:
                console.print("[red]Error: both old and new name are required for rename[/red]")
                raise typer.Exit(1)

            success, message = manager.rename(name, new_name)
            result = {"success": success, "message": message}

            if json_output:
                print(output_json(result))
            else:
                if success:
                    console.print(f"[green]✓[/green] {message}")
                else:
                    console.print(f"[red]✗[/red] {message}")
                    raise typer.Exit(1)

        else:
            console.print(f"[red]Unknown action: {action}[/red]")
            console.print(
                "Available actions: list, create, switch/use, remove, info, current, rename"
            )
            raise typer.Exit(1)

    except Exception as e:
        result = {"success": False, "error": str(e)}
        if json_output:
            print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


# =============================================================================
# 性能优化命令
# =============================================================================


def _ingest_log_impl(
    repo_path: str,
    limit: int,
    note_type: str,
    batch_size: int,
    output_format: str,
    json_output: bool,
):
    """从 Git 仓库提取 commit 历史并导入为笔记"""
    from .git_extractor import commits_to_notes, extract_commits
    from .performance import bulk_import_notes

    # 提取 commits
    commits = extract_commits(repo_path, limit=limit)

    if not commits:
        result = {
            "success": True,
            "imported": 0,
            "total": 0,
            "message": "没有找到 commit 记录",
        }
        if output_format == "json":
            print(output_json(result))
        else:
            console.print("[yellow]![/yellow] 没有找到 commit 记录")
        return

    # 转换为笔记格式
    notes_data = commits_to_notes(commits, repo_path=repo_path)

    if output_format != "json":
        console.print(f"[yellow]提取了 {len(notes_data)} 条 commit，正在导入...[/yellow]")

    import_result = bulk_import_notes(
        notes_data=notes_data,
        note_type=note_type,
        batch_size=batch_size,
        show_progress=output_format != "json",
    )

    result = {
        "success": True,
        "repo_path": str(Path(repo_path).resolve()),
        "commits_extracted": len(commits),
        **import_result,
    }

    if output_format == "json":
        print(output_json(result))
    else:
        console.print(f"[green]✓[/green] 导入: {import_result['imported']}")
        console.print(f"[red]✗[/red] 失败: {import_result['failed']}")
        console.print(f"总计: {import_result['total']}")


@app.command()
def ingest_log(
    repo_path: str = typer.Argument(..., help="本地 Git 仓库路径"),
    limit: int = typer.Option(50, "--limit", "-n", help="提取 commit 数量"),
    note_type: str = typer.Option("fleeting", "--type", "-t", help="笔记类型"),
    batch_size: int = typer.Option(32, "--batch-size", "-b", help="批处理大小"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(
        False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"
    ),
):
    """
    从 Git 仓库提取 commit 历史并导入为笔记

    使用 block 分隔符格式提取 git log，自动处理 UTF-8 编码和路径规范化。

    示例:
        jfox ingest-log ./my-project --limit 50
        jfox ingest-log ./my-project --kb work --type permanent
    """
    try:
        # 处理 --json 快捷方式
        if json_output:
            output_format = "json"

        # 如果指定了知识库，临时切换
        if kb:
            from .config import use_kb

            with use_kb(kb):
                _ingest_log_impl(
                    repo_path, limit, note_type, batch_size, output_format, json_output
                )
        else:
            _ingest_log_impl(repo_path, limit, note_type, batch_size, output_format, json_output)

    except ValueError as e:
        result = {"success": False, "error": str(e)}
        if output_format == "json":
            print(output_json(result))
        else:
            console.print(f"[red]✗[/red] {e}")
        raise typer.Exit(1)
    except Exception as e:
        result = {"success": False, "error": str(e)}
        if output_format == "json":
            print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def bulk_import(
    file_path: str = typer.Argument(..., help="JSON 文件路径，包含笔记数据"),
    note_type: str = typer.Option("permanent", "--type", "-t", help="笔记类型"),
    batch_size: int = typer.Option(32, "--batch-size", "-b", help="批处理大小"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库名称"),
    json_output: bool = typer.Option(True, "--json/--no-json", help="JSON 输出"),
):
    """
    批量导入笔记（性能优化版）

    从 JSON 文件批量导入笔记，使用批量嵌入和批量数据库操作。

    JSON 文件格式:
        [
            {"title": "笔记1", "content": "内容1", "tags": ["tag1"]},
            {"title": "笔记2", "content": "内容2"}
        ]

    示例:
        jfox bulk-import notes.json --type permanent --batch-size 32
        jfox bulk-import notes.json --kb work --type permanent
    """
    try:
        import json

        # 读取文件
        with open(file_path, "r", encoding="utf-8") as f:
            notes_data = json.load(f)

        console.print(f"[yellow]Importing {len(notes_data)} notes...[/yellow]")

        from .performance import bulk_import_notes

        # 如果指定了知识库，临时切换
        if kb:
            from .config import use_kb

            with use_kb(kb):
                result = bulk_import_notes(
                    notes_data=notes_data,
                    note_type=note_type,
                    batch_size=batch_size,
                    show_progress=not json_output,
                )
        else:
            result = bulk_import_notes(
                notes_data=notes_data,
                note_type=note_type,
                batch_size=batch_size,
                show_progress=not json_output,
            )

        if json_output:
            print(output_json(result))
        else:
            console.print(f"[green]✓[/green] Imported: {result['imported']}")
            console.print(f"[red]✗[/red] Failed: {result['failed']}")
            console.print(f"Total: {result['total']}")

    except Exception as e:
        result = {"success": False, "error": str(e)}
        if json_output:
            print(output_json(result))
        else:
            console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def perf(
    action: str = typer.Argument("report", help="操作: report, clear-cache"),
):
    """
    性能工具和报告

    示例:
        jfox perf report         # 显示性能报告
        jfox perf clear-cache    # 清除模型缓存
    """
    try:
        if action == "report":
            from .performance import get_perf_monitor

            monitor = get_perf_monitor()
            report = monitor.report()

            if not report:
                console.print("[dim]No performance data yet[/dim]")
                return

            table = Table(title="Performance Report")
            table.add_column("Operation", style="cyan")
            table.add_column("Count", justify="right")
            table.add_column("Avg (s)", justify="right")
            table.add_column("Total (s)", justify="right")

            for op, stats in sorted(report.items(), key=lambda x: x[1]["total"], reverse=True):
                table.add_row(
                    op,
                    str(stats["count"]),
                    f"{stats['avg']:.3f}",
                    f"{stats['total']:.3f}",
                )

            console.print(table)

        elif action == "clear-cache":
            from .performance import ModelCache

            ModelCache.clear()
            console.print("[green]✓[/green] Model cache cleared")

        else:
            console.print(f"[red]Unknown action: {action}[/red]")
            console.print("Available: report, clear-cache")
            raise typer.Exit(1)

    except Exception as e:
        console.print(f"[red]✗[/red] Error: {e}")
        raise typer.Exit(1)


@app.command()
def daemon(
    action: str = typer.Argument("status", help="操作: start, stop, status"),
    port: int = typer.Option(18700, "--port", "-p", help="Daemon 监听端口"),
):
    """
    管理嵌入模型守护进程

    启动后台 daemon 可避免每次 CLI 调用重复加载模型（节省 ~5-15 秒）。
    daemon 仅持有 embedding 模型，不持有知识库数据。

    示例:

        jfox daemon start       # 启动 daemon
        jfox daemon status      # 查看状态
        jfox daemon stop        # 停止 daemon
    """
    from .daemon.process import (
        get_daemon_status,
        is_daemon_running,
        start_daemon,
        stop_daemon,
    )

    try:
        if action == "start":
            from .daemon.process import DAEMON_LOG_FILE

            console.print("[yellow]正在启动 embedding daemon...[/yellow]")
            console.print(f"[dim]日志文件: {DAEMON_LOG_FILE}[/dim]")
            ok = start_daemon(port=port)
            if ok:
                info = get_daemon_status()
                if info:
                    table = Table(title="Embedding Daemon")
                    table.add_column("属性", style="cyan")
                    table.add_column("值", style="green")
                    table.add_row("状态", "[green]运行中[/green]")
                    table.add_row("PID", str(info["pid"]))
                    table.add_row("端口", str(info["port"]))
                    table.add_row("模型", info["model"])
                    table.add_row("维度", str(info["dimension"]))
                    table.add_row("设备", info.get("device", "unknown"))
                    console.print(table)
                else:
                    console.print("[green]✓ Daemon 已启动[/green]")
            else:
                console.print("[red]✗ Daemon 启动失败[/red]")
                console.print(f"[dim]查看日志: {DAEMON_LOG_FILE}[/dim]")
                raise typer.Exit(1)

        elif action == "stop":
            if not is_daemon_running():
                console.print("[dim]Daemon 未运行[/dim]")
                return
            console.print("[yellow]正在停止 daemon...[/yellow]")
            stop_daemon()
            console.print("[green]✓ Daemon 已停止[/green]")

        elif action == "status":
            info = get_daemon_status()
            if info:
                table = Table(title="Embedding Daemon")
                table.add_column("属性", style="cyan")
                table.add_column("值", style="green")
                table.add_row("状态", "[green]运行中[/green]")
                table.add_row("PID", str(info["pid"]))
                table.add_row("端口", str(info["port"]))
                table.add_row("模型", info.get("model", "unknown"))
                table.add_row("维度", str(info.get("dimension", "unknown")))
                table.add_row("设备", info.get("device", "unknown"))
                console.print(table)
            else:
                console.print("[dim]Daemon 未运行[/dim]")
                console.print("提示: 运行 [cyan]jfox daemon start[/cyan] 启动")

        else:
            console.print(f"[red]未知操作: {action}[/red]")
            console.print("可用操作: start, stop, status")
            raise typer.Exit(1)

    except typer.Exit:
        raise
    except Exception as e:
        console.print(f"[red]✗[/red] 错误: {e}")
        raise typer.Exit(1)


def _download_impl(
    model: Optional[str],
    force: bool = False,
) -> dict:
    """下载模型实现（可复用）"""
    from .embedding_backend import EmbeddingBackend
    from .model_downloader import ModelDownloader

    # 解析模型名
    if model is None or model == "auto":
        backend = EmbeddingBackend()
        device = backend._resolve_device()
        model = backend._resolve_model_name(device)

    downloader = ModelDownloader(model)

    if force and downloader._check_cached():
        import shutil

        shutil.rmtree(downloader._model_cache, ignore_errors=True)

    ok = downloader.ensure_cached()
    return {
        "model": model,
        "success": ok,
        "cache_dir": str(downloader._model_cache),
        "instructions": downloader.get_manual_instructions() if not ok else "",
    }


@model_app.command("download")
def download(
    model: Optional[str] = typer.Option(
        None, "--model", "-m", help="模型名（默认从配置读取，auto 则按设备自动选择）"
    ),
    force: bool = typer.Option(False, "--force", "-f", help="强制重新下载（覆盖已有缓存）"),
    kb: Optional[str] = typer.Option(
        None, "--kb", "-k", help="目标知识库名称（模型下载不依赖知识库）"
    ),
    output_format: str = typer.Option("table", "--format", help="输出格式: json, table"),
    json_output: bool = typer.Option(False, "--json", help="JSON 输出快捷方式"),
):
    """
    手动下载 embedding 模型

    自动尝试 3 种下载方式（huggingface_hub → 镜像站 → curl）。
    通常不需要手动调用，daemon start 会自动执行。

    示例:

        jfox model download                    # 下载默认模型
        jfox model download --model bge-m3     # 下载指定模型
        jfox model download --force            # 强制重新下载
        jfox model download --json             # JSON 输出
    """
    # kb 参数保持 CLI 一致性（模型下载不依赖知识库）
    _ = kb

    if json_output:
        output_format = "json"

    console.print(f"[yellow]准备下载模型: {model or 'auto'}[/yellow]")

    result = _download_impl(model=model, force=force)

    if output_format == "json":
        console.print(output_json(result))
    else:
        if result["success"]:
            console.print(f"[green]✓ 模型下载完成: {result['model']}[/green]")
        else:
            console.print("[red]✗ 模型下载失败[/red]")
            console.print(Panel(result["instructions"], title="手动下载"))

    if not result["success"]:
        raise typer.Exit(1)


# 入口点
def main():
    """CLI 入口点"""
    import os

    # 离线模式：跳过 HuggingFace 网络请求，节省 0.5-2s
    # 仅在 CLI 入口设置，不影响测试环境
    os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("TRANSFORMERS_OFFLINE", "1")

    app()


if __name__ == "__main__":
    main()
