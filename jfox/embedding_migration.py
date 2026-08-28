"""Embedding model migration detection (#442).

Compares each KB's ChromaDB collection dimension against the dimension
served by the running embedding daemon. Returns a report when at least
one KB was indexed with a different (old) model.
"""

import logging
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import chromadb
from chromadb.config import Settings

logger = logging.getLogger(__name__)

# Re-exported seams for tests (monkeypatch these instead of real modules)
from .config import use_kb as _use_kb
from .daemon.client import DaemonClient as _DaemonClient
from .daemon.process import _get_daemon_url
from .daemon.process import is_daemon_running as _is_daemon_running
from .global_config import GlobalConfigManager as _GlobalConfigManager
from .indexer import Indexer as _Indexer
from .vector_store import get_vector_store as _get_vector_store


@dataclass
class DimensionMismatchReport:
    model_dimension: int
    affected_kbs: List[str] = field(default_factory=list)
    kb_dimensions: Dict[str, int] = field(default_factory=dict)


def check_dimension_mismatch() -> Optional[DimensionMismatchReport]:
    """Scan all KBs for dimension mismatch. Never raises."""
    try:
        if not _is_daemon_running():
            return None
        client = _DaemonClient(_get_daemon_url())
        if not client.available:
            return None
        # Stale/old daemons may omit "dimension" from /health; DaemonClient then
        # falls back to a default 512 we cannot trust for migration checks (#442).
        if getattr(client, "_dimension_from_health", True) is not True:
            return None
        model_dim = client.dimension
        if not isinstance(model_dim, int) or model_dim <= 0:
            return None
    except Exception as e:
        logger.debug(f"migration check skipped, daemon unavailable: {e}")
        return None

    report = DimensionMismatchReport(model_dimension=model_dim)
    try:
        kbs = _GlobalConfigManager().list_knowledge_bases()
    except Exception as e:
        logger.debug(f"migration check skipped, cannot list KBs: {e}")
        return None

    for kb in kbs:
        try:
            chroma_path = Path(kb.path).expanduser() / ".zk" / "chroma_db"
            if not chroma_path.exists():
                continue
            # Settings MUST stay aligned with VectorStore.init: ChromaDB caches
            # clients per path at process level and rejects a second client on
            # the same path with different settings (#442).
            c = chromadb.PersistentClient(
                path=str(chroma_path),
                settings=Settings(anonymized_telemetry=False, allow_reset=True),
            )
            collection = c.get_collection("notes")
            if collection.count() == 0:
                continue
            peek = collection.peek(limit=1)
            embeddings = peek.get("embeddings")
            if not embeddings:
                continue
            kb_dim = len(embeddings[0])
        except Exception as e:
            # Single-KB failure must not block the rest
            logger.debug(f"migration check skipped KB {kb.name}: {e}")
            continue
        if kb_dim != model_dim:
            report.affected_kbs.append(kb.name)
            report.kb_dimensions[kb.name] = kb_dim

    return report if report.affected_kbs else None


def prompt_migration(report: DimensionMismatchReport) -> None:
    """Warn about dimension mismatch and offer interactive per-KB rebuild."""
    from rich.console import Console

    console = Console()
    dims = [report.kb_dimensions.get(kb) for kb in report.affected_kbs]
    if len(set(dims)) == 1 and isinstance(dims[0], int):
        # Canonical copy from spec §4.5 for the common single-dimension case
        console.print(
            f"[yellow]⚠ 检测到 embedding 模型已更换"
            f"（索引维度 {dims[0]} ≠ 当前模型 {report.model_dimension}）[/yellow]"
        )
        console.print(f"  受影响知识库: {', '.join(report.affected_kbs)}")
    else:
        console.print(
            f"[yellow]⚠ 检测到 embedding 模型已更换（当前模型 {report.model_dimension} 维）[/yellow]"
        )
        for kb in report.affected_kbs:
            console.print(
                f"  - 知识库 [cyan]{kb}[/cyan]: 索引 {report.kb_dimensions.get(kb, '?')} 维"
            )
    console.print("  影响语义搜索（返回空结果）与新笔记向量索引。")

    if not sys.stdin.isatty():
        console.print(
            "  非交互环境，请手动执行 [cyan]jfox index rebuild --kb <name>[/cyan] 重建索引。"
        )
        return

    import typer

    if not typer.confirm("是否现在重建索引？将逐库重新嵌入全部笔记", default=False):
        console.print("  已跳过。可稍后执行 [cyan]jfox index rebuild[/cyan] 重建。")
        return

    from .config import config

    # Per-KB isolation: one broken KB must not abort the remaining rebuilds
    # nor turn a successful daemon start into exit code 1 (#442).
    failed: list = []
    for kb in report.affected_kbs:
        try:
            with _use_kb(kb):
                indexer = _Indexer(config, _get_vector_store())
                count = indexer.index_all()
                console.print(f"[green]✓[/green] {kb}: 已重建 {count} 条笔记索引")
        except Exception as e:
            logger.error(f"rebuild failed for KB {kb}: {e}")
            console.print(f"[red]✗ {kb}: 重建失败，已跳过[/red]")
            failed.append(kb)
    if failed:
        console.print(
            f"[yellow]以下知识库重建失败: {', '.join(failed)}，"
            f"请稍后手动执行 [cyan]jfox index rebuild --kb <name>[/cyan][/yellow]"
        )
    else:
        console.print("[green]索引迁移完成，语义搜索已恢复。[/green]")
