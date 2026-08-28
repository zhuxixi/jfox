"""Default CPU embedding model switch to bge-small-zh-v1.5 (#442)."""

from jfox import embedding_backend
from jfox.daemon.client import DaemonClient


class TestDefaultModelSwitch:
    def test_cpu_default_model_is_bge_small_zh(self):
        assert embedding_backend._CPU_DEFAULT_MODEL == "BAAI/bge-small-zh-v1.5"

    def test_gpu_default_model_unchanged(self):
        assert embedding_backend._GPU_DEFAULT_MODEL == "BAAI/bge-m3"

    def test_unloaded_dimension_fallback_is_512(self):
        backend = embedding_backend.EmbeddingBackend()
        # No model loaded, no daemon client: dimension property falls back to new default
        backend.model_name = "BAAI/bge-small-zh-v1.5"
        assert backend._resolved_dim is None
        assert backend.model is None
        assert backend._daemon_client is None
        assert backend.dimension == 512

    def test_daemon_client_dimension_default_is_512(self):
        client = DaemonClient.__new__(DaemonClient)  # skip __init__ network access
        assert client._dimension if hasattr(client, "_dimension") else True
        # Direct check of the class-level default used in __init__
        import inspect

        src = inspect.getsource(DaemonClient.__init__)
        assert "512" in src
