"""#519: 搜索引擎双路径（semantic / hybrid）的 embed 缺失告警。"""

from types import SimpleNamespace

from jfox.embedding_backend import EmbedDependencyMissingError, format_embed_hint
from jfox.models import NoteType
from jfox.search_engine import HybridSearchEngine, SearchMode


class FakeVectorStore:
    def __init__(self, exc=None):
        self._exc = exc

    def search(self, *args, **kwargs):
        if self._exc:
            raise self._exc
        return []


class FakeBM25:
    needs_rebuild = False

    def __init__(self, results=None):
        self._results = results or []

    def search(self, *args, **kwargs):
        return self._results

    def check_stale_and_reload(self):
        pass


def _fake_note_loader(monkeypatch, note_id="n1"):
    import jfox.note as note_module

    fake = SimpleNamespace(
        id=note_id,
        title="标题",
        content="内容",
        type=NoteType.FLEETING,
        tags=[],
        archived=False,
        filepath=None,
    )
    monkeypatch.setattr(note_module, "load_note_by_id", lambda nid, cfg=None: fake)


def _engine(store, bm25):
    return HybridSearchEngine(vector_store=store, bm25_index=bm25)


def test_semantic_mode_returns_empty_with_warning(monkeypatch):
    _fake_note_loader(monkeypatch)
    typed = EmbedDependencyMissingError(format_embed_hint("语义检索"))
    engine = _engine(FakeVectorStore(exc=typed), FakeBM25())
    results = engine.search("查询", mode=SearchMode.SEMANTIC, include_archived=True)
    assert results == []
    assert engine.last_embed_warning is not None
    assert "UV_TORCH_BACKEND" in engine.last_embed_warning


def test_hybrid_mode_falls_back_to_bm25_with_warning(monkeypatch):
    _fake_note_loader(monkeypatch)
    typed = EmbedDependencyMissingError(format_embed_hint("语义检索"))
    engine = _engine(
        FakeVectorStore(exc=typed), FakeBM25(results=[{"note_id": "n1", "score": 1.0}])
    )
    results = engine.search("查询", mode=SearchMode.HYBRID, include_archived=True)
    assert engine.last_embed_warning is not None
    assert len(results) >= 1  # BM25 兜底结果可见
    assert results[0]["id"] == "n1"


def test_search_clears_stale_warning(monkeypatch):
    _fake_note_loader(monkeypatch)
    engine = _engine(
        FakeVectorStore(), FakeBM25(results=[{"note_id": "n1", "score": 1.0}])
    )
    engine.last_embed_warning = "旧告警"
    engine.search("查询", mode=SearchMode.KEYWORD, include_archived=True)
    assert engine.last_embed_warning is None
