"""JFox 碎片采集子包（Phase 1：Hook → Daemon REST API）。"""

from .detector import classify
from .service import ingest_event, set_default_store
from .store import FragmentStore

__all__ = ["classify", "ingest_event", "set_default_store", "FragmentStore"]
