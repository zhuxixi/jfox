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
        # __init__ only sets attributes (no network); fresh client must default
        # to 512 and must NOT claim the dimension came from /health (#442).
        client = DaemonClient("http://127.0.0.1:8300")
        assert client._dimension == 512
        assert client._dimension_from_health is False
