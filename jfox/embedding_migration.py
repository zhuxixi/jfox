"""Embedding model migration detection (#442).

Compares each KB's ChromaDB collection dimension against the dimension
served by the running embedding daemon. Returns a report when at least
one KB was indexed with a different (old) model.
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import chromadb
from chromadb.config import Settings

logger = logging.getLogger(__name__)

# Re-exported seams for tests (monkeypatch these instead of real modules)
from .daemon.client import DaemonClient as _DaemonClient
from .daemon.process import _get_daemon_url, is_daemon_running as _is_daemon_running
from .global_config import GlobalConfigManager as _GlobalConfigManager


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
        model_dim = client.dimension
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
        chroma_path = Path(kb.path).expanduser() / ".zk" / "chroma_db"
        if not chroma_path.exists():
            continue
        try:
            c = chromadb.PersistentClient(
                path=str(chroma_path),
                settings=Settings(anonymized_telemetry=False),
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
