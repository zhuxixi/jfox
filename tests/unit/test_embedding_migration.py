"""Dimension mismatch detection across all KBs (#442)."""

from jfox.embedding_migration import (
    DimensionMismatchReport,
    check_dimension_mismatch,
)


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
    """kb_specs: list of (kb_name, exists, dim_or_None, count[, unregistered]).

    unregistered=True: chroma dir exists on disk but is NOT registered in
    chroma_roots, so FakeChroma.PersistentClient raises (corrupt-dir path).
    """
    import jfox.embedding_migration as em
    from jfox.global_config import KnowledgeBaseEntry

    entries = []
    chroma_roots = {}
    for spec in kb_specs:
        kb_name, exists, dim, count = spec[:4]
        unregistered = spec[4] if len(spec) > 4 else False
        kb_path = tmp_path / kb_name
        kb_path.mkdir()
        entries.append(KnowledgeBaseEntry(name=kb_name, path=str(kb_path), created="2026-08-28"))
        if exists:
            chroma_root = kb_path / ".zk" / "chroma_db"
            chroma_root.mkdir(parents=True)
            if not unregistered:
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
            monkeypatch,
            tmp_path,
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
            monkeypatch,
            tmp_path,
            health_dim=512,
            kb_specs=[("default", True, 512, 100)],
        )
        assert check_dimension_mismatch() is None

    def test_empty_kb_skipped(self, monkeypatch, tmp_path):
        _patch_env(
            monkeypatch,
            tmp_path,
            health_dim=512,
            kb_specs=[("default", True, None, 0), ("fresh", False, None, 0)],
        )
        assert check_dimension_mismatch() is None

    def test_corrupt_kb_skipped_not_fatal(self, monkeypatch, tmp_path):
        # "broken" KB has an empty chroma DB (count=0) -> skipped as empty KB,
        # while the healthy mismatching KB is still reported.
        _patch_env(
            monkeypatch,
            tmp_path,
            health_dim=512,
            kb_specs=[("default", True, 384, 10), ("broken", True, None, 0)],
        )
        report = check_dimension_mismatch()
        assert report is not None
        assert report.affected_kbs == ["default"]

    def test_unregistered_chroma_dir_raises_and_is_skipped(self, monkeypatch, tmp_path):
        # "broken" KB: chroma dir exists but NOT registered -> PersistentClient
        # raises inside the per-KB try; the loop must continue to "default".
        _patch_env(
            monkeypatch,
            tmp_path,
            health_dim=512,
            kb_specs=[
                ("default", True, 384, 10),
                ("broken", True, None, 0, True),
            ],
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

    def test_default_dimension_without_health_field_skips_check(self, monkeypatch):
        # Daemon up, but /health omitted "dimension": DaemonClient fell back to
        # its 512 default and flagged it not-from-health — check must skip (#442).
        import jfox.embedding_migration as em

        class StaleDaemonClient:
            available = True
            dimension = 512
            _dimension_from_health = False

        monkeypatch.setattr(em, "_DaemonClient", StaleDaemonClient)
        monkeypatch.setattr(em, "_is_daemon_running", lambda: True)
        monkeypatch.setattr(em, "_get_daemon_url", lambda: "http://127.0.0.1:8300")
        assert check_dimension_mismatch() is None


class TestPromptMigration:
    def _report(self):
        return DimensionMismatchReport(
            model_dimension=512,
            affected_kbs=["default"],
            kb_dimensions={"default": 384},
        )

    def test_confirm_yes_triggers_rebuild(self, monkeypatch):
        import jfox.embedding_migration as em

        rebuilt = []

        class FakeIndexer:
            def __init__(self, config, vector_store):
                pass

            def index_all(self, progress_callback=None):
                rebuilt.append(True)
                return 7

        entered = []

        class FakeUseKb:
            def __init__(self, name):
                self.name = name

            def __enter__(self):
                entered.append(self.name)

            def __exit__(self, *args):
                return False

        monkeypatch.setattr(em, "_Indexer", FakeIndexer)
        monkeypatch.setattr(em, "_use_kb", FakeUseKb)
        monkeypatch.setattr(em, "_get_vector_store", lambda: object())
        monkeypatch.setattr("typer.confirm", lambda *a, **kw: True)
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)

        em.prompt_migration(self._report())
        assert rebuilt == [True]
        assert entered == ["default"]

    def test_confirm_no_skips_rebuild(self, monkeypatch):
        import jfox.embedding_migration as em

        def _must_not_rebuild(*a):
            raise AssertionError("must not rebuild")

        monkeypatch.setattr(em, "_Indexer", _must_not_rebuild)
        monkeypatch.setattr("typer.confirm", lambda *a, **kw: False)
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)

        em.prompt_migration(self._report())  # must not raise

    def test_non_tty_prints_hint_only(self, monkeypatch):
        import jfox.embedding_migration as em

        def _must_not_confirm(*a, **kw):
            raise AssertionError("must not confirm")

        monkeypatch.setattr("sys.stdin.isatty", lambda: False)
        monkeypatch.setattr("typer.confirm", _must_not_confirm)

        em.prompt_migration(self._report())  # must not raise

    def test_rebuild_continues_after_kb_failure(self, monkeypatch):
        import jfox.embedding_migration as em

        attempts = []
        entered = []

        class FlakyIndexer:
            def __init__(self, config, vector_store):
                pass

            def index_all(self, progress_callback=None):
                attempts.append(1)
                if len(attempts) == 1:
                    raise RuntimeError("chroma boom")
                return 3

        class FakeUseKb:
            def __init__(self, name):
                self.name = name

            def __enter__(self):
                entered.append(self.name)

            def __exit__(self, *args):
                return False

        report = DimensionMismatchReport(
            model_dimension=512,
            affected_kbs=["bad", "good"],
            kb_dimensions={"bad": 384, "good": 384},
        )

        monkeypatch.setattr(em, "_Indexer", FlakyIndexer)
        monkeypatch.setattr(em, "_use_kb", FakeUseKb)
        monkeypatch.setattr(em, "_get_vector_store", lambda: object())
        monkeypatch.setattr("typer.confirm", lambda *a, **kw: True)
        monkeypatch.setattr("sys.stdin.isatty", lambda: True)

        em.prompt_migration(report)  # must not raise
        assert attempts == [1, 1]  # both KBs attempted
        assert entered == ["bad", "good"]
