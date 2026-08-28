"""Dimension mismatch detection across all KBs (#442)."""

from jfox.embedding_migration import check_dimension_mismatch


class _FakeCollection:
    def __init__(self, dim=None, count=0):
        self._dim = dim
        self._count = count

    def count(self):
        return self._count

    def peek(self, limit=1):
        if self._dim is None:
            return {"embeddings": None}
        return {"embeddings": [[0.0] * self._dim]}


class _FakeClient:
    def __init__(self, collections):
        self._collections = collections

    def get_collection(self, name):
        if name not in self._collections:
            raise ValueError(f"Collection {name} does not exist")
        return self._collections[name]


def _patch_env(monkeypatch, tmp_path, health_dim, kb_specs):
    """kb_specs: list of (kb_name, exists, dim_or_None, count). Returns affected expectations."""
    import jfox.embedding_migration as em
    from jfox.global_config import KnowledgeBaseEntry

    entries = []
    chroma_roots = {}
    for kb_name, exists, dim, count in kb_specs:
        kb_path = tmp_path / kb_name
        kb_path.mkdir()
        entries.append(
            KnowledgeBaseEntry(name=kb_name, path=str(kb_path), created="2026-08-28")
        )
        if exists:
            chroma_root = kb_path / ".zk" / "chroma_db"
            chroma_root.mkdir(parents=True)
            chroma_roots[str(chroma_root)] = _FakeCollection(dim=dim, count=count)

    class FakeGlobalConfigManager:
        def list_knowledge_bases(self):
            return entries

    monkeypatch.setattr(em, "_GlobalConfigManager", FakeGlobalConfigManager)

    class FakeDaemonClient:
        # Accept the daemon URL like the real DaemonClient(url) constructor
        def __init__(self, url):
            self.url = url

        available = True
        dimension = health_dim

    monkeypatch.setattr(em, "_DaemonClient", FakeDaemonClient)
    monkeypatch.setattr(em, "_is_daemon_running", lambda: True)
    monkeypatch.setattr(em, "_get_daemon_url", lambda: "http://127.0.0.1:8300")

    class FakeChroma:
        @staticmethod
        def PersistentClient(path=None, settings=None):
            if path not in chroma_roots:
                raise RuntimeError("corrupt dir")
            return _FakeClient({"notes": chroma_roots[path]})

    monkeypatch.setattr(em, "chromadb", FakeChroma)


class TestCheckDimensionMismatch:
    def test_mismatch_detected(self, monkeypatch, tmp_path):
        # default KB has 384-dim index, model reports 512
        _patch_env(
            monkeypatch, tmp_path,
            health_dim=512,
            kb_specs=[("default", True, 384, 100), ("work", True, 512, 5)],
        )
        report = check_dimension_mismatch()
        assert report is not None
        assert report.model_dimension == 512
        assert report.affected_kbs == ["default"]
        assert report.kb_dimensions == {"default": 384}

    def test_all_match_returns_none(self, monkeypatch, tmp_path):
        _patch_env(
            monkeypatch, tmp_path,
            health_dim=512,
            kb_specs=[("default", True, 512, 100)],
        )
        assert check_dimension_mismatch() is None

    def test_empty_kb_skipped(self, monkeypatch, tmp_path):
        _patch_env(
            monkeypatch, tmp_path,
            health_dim=512,
            kb_specs=[("default", True, None, 0), ("fresh", False, None, 0)],
        )
        assert check_dimension_mismatch() is None

    def test_corrupt_kb_skipped_not_fatal(self, monkeypatch, tmp_path):
        # "broken" KB: chroma dir exists but unlisted in chroma_roots -> PersistentClient raises
        _patch_env(
            monkeypatch, tmp_path,
            health_dim=512,
            kb_specs=[("default", True, 384, 10), ("broken", True, None, 0)],
        )
        report = check_dimension_mismatch()
        assert report is not None
        assert report.affected_kbs == ["default"]

    def test_daemon_down_returns_none(self, monkeypatch, tmp_path):
        import jfox.embedding_migration as em

        monkeypatch.setattr(em, "_is_daemon_running", lambda: False)
        assert check_dimension_mismatch() is None

    def test_health_without_dimension_returns_none(self, monkeypatch, tmp_path):
        import jfox.embedding_migration as em

        class NoDimClient:
            def __init__(self, url):
                self.url = url

            available = False

        monkeypatch.setattr(em, "_DaemonClient", NoDimClient)
        monkeypatch.setattr(em, "_is_daemon_running", lambda: True)
        monkeypatch.setattr(em, "_get_daemon_url", lambda: "http://127.0.0.1:8300")
        assert check_dimension_mismatch() is None
