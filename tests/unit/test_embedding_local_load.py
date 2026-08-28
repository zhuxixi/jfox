"""EmbeddingBackend 本地路径加载测试"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


class TestEmbeddingLocalLoad:
    """测试本地模型目录加载"""

    @pytest.fixture
    def backend(self):
        from jfox.embedding_backend import EmbeddingBackend

        return EmbeddingBackend(device="cpu", model_name="sentence-transformers/all-MiniLM-L6-v2")

    def test_get_local_model_path_when_exists(self, backend, tmp_path):
        """本地目录存在有效模型文件时返回路径"""
        fake_local = tmp_path / ".models" / "sentence-transformers--all-MiniLM-L6-v2"
        fake_local.mkdir(parents=True)
        (fake_local / "config.json").write_text("{}")
        (fake_local / "model.safetensors").write_text("fake")

        with patch("jfox.model_downloader._LOCAL_MODEL_DIR", tmp_path / ".models"):
            result = backend._get_local_model_path()
            assert result is not None
            assert "all-MiniLM-L6-v2" in str(result)

    def test_get_local_model_path_when_not_exists(self, backend, tmp_path):
        """本地目录不存在时返回 None"""
        with patch("jfox.model_downloader._LOCAL_MODEL_DIR", tmp_path / ".models"):
            result = backend._get_local_model_path()
            assert result is None

    def test_get_local_model_path_empty_dir(self, backend, tmp_path):
        """本地目录存在但为空时返回 None"""
        fake_local = tmp_path / ".models" / "sentence-transformers--all-MiniLM-L6-v2"
        fake_local.mkdir(parents=True)

        with patch("jfox.model_downloader._LOCAL_MODEL_DIR", tmp_path / ".models"):
            result = backend._get_local_model_path()
            assert result is None

    def test_get_local_model_path_config_only(self, backend, tmp_path):
        """仅有 config.json 无权重文件时返回 None"""
        fake_local = tmp_path / ".models" / "sentence-transformers--all-MiniLM-L6-v2"
        fake_local.mkdir(parents=True)
        (fake_local / "config.json").write_text("{}")

        with patch("jfox.model_downloader._LOCAL_MODEL_DIR", tmp_path / ".models"):
            result = backend._get_local_model_path()
            assert result is None

    def test_get_local_model_path_weight_only(self, backend, tmp_path):
        """仅有权重文件无 config.json 时返回 None"""
        fake_local = tmp_path / ".models" / "sentence-transformers--all-MiniLM-L6-v2"
        fake_local.mkdir(parents=True)
        (fake_local / "model.safetensors").write_text("fake")

        with patch("jfox.model_downloader._LOCAL_MODEL_DIR", tmp_path / ".models"):
            result = backend._get_local_model_path()
            assert result is None

    def test_load_uses_local_path_when_available(self, backend):
        """本地目录存在时优先使用本地路径加载"""
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 384
        fake_path = Path("/fake/local/model")

        with patch.object(backend, "_get_local_model_path", return_value=fake_path):
            with patch(
                "sentence_transformers.SentenceTransformer", return_value=mock_model
            ) as mock_st:
                with patch.object(backend, "_check_daemon", return_value=False):
                    backend.load()
                    mock_st.assert_called_once_with(str(fake_path), device="cpu")

    def test_load_uses_model_name_when_no_local(self, backend):
        """本地目录不存在时使用模型名加载"""
        mock_model = MagicMock()
        mock_model.get_sentence_embedding_dimension.return_value = 384

        with patch.object(backend, "_get_local_model_path", return_value=None):
            # ensure_cached is on the new load() path; mock it so this test
            # stays hermetic (no real download attempts in CI).
            with patch("jfox.model_downloader.ModelDownloader") as mock_downloader:
                mock_downloader.return_value.ensure_cached.return_value = False
                with patch(
                    "sentence_transformers.SentenceTransformer", return_value=mock_model
                ) as mock_st:
                    with patch.object(backend, "_check_daemon", return_value=False):
                        backend.load()
                        mock_st.assert_called_once_with(
                            "sentence-transformers/all-MiniLM-L6-v2", device="cpu"
                        )


@pytest.fixture(autouse=True)
def _stub_sentence_transformers(monkeypatch):
    """Stub the sentence_transformers module when it is not installed.

    CI installs the real dependency, so this is a no-op there. Local dev
    venvs without the heavy ML stack can still run these tests: the stub
    lets attribute-level patches ("sentence_transformers.SentenceTransformer")
    resolve against an importable module.
    """
    import sys
    import types

    try:
        import sentence_transformers  # noqa: F401

        return
    except ImportError:
        pass
    stub = types.ModuleType("sentence_transformers")
    stub.SentenceTransformer = object
    monkeypatch.setitem(sys.modules, "sentence_transformers", stub)


class TestLoadFallsBackToModelDownloader:
    """load() must try ModelDownloader.ensure_cached() when local dir misses (#374)."""

    def _make_backend(self, monkeypatch):
        from jfox import embedding_backend as eb

        backend = eb.EmbeddingBackend()
        backend.model_name = "BAAI/bge-small-zh-v1.5"
        backend._resolved_device = "cpu"
        monkeypatch.setattr(eb.EmbeddingBackend, "_check_daemon", lambda self: False)
        return backend, eb

    def test_ensure_cached_called_when_local_missing(self, monkeypatch):
        backend, eb = self._make_backend(monkeypatch)
        monkeypatch.setattr(eb.EmbeddingBackend, "_get_local_model_path", lambda self: None)

        calls = []

        class FakeDownloader:
            def __init__(self, model_name):
                calls.append(model_name)

            def ensure_cached(self):
                return False  # all three fallbacks fail

        monkeypatch.setattr("jfox.model_downloader.ModelDownloader", FakeDownloader)

        class FakeST:
            def __init__(self, name, device=None):
                raise RuntimeError("network unreachable")

        monkeypatch.setattr("sentence_transformers.SentenceTransformer", FakeST)

        with pytest.raises(RuntimeError):
            backend.load()
        assert calls == ["BAAI/bge-small-zh-v1.5"]

    def test_load_uses_local_dir_after_download(self, monkeypatch, tmp_path):
        backend, eb = self._make_backend(monkeypatch)
        local_dir = tmp_path / "downloaded-model"
        local_dir.mkdir()

        # First probe misses, second probe (after download) hits
        probes = []

        def fake_local_path(self):
            probes.append(1)
            return local_dir if len(probes) > 1 else None

        monkeypatch.setattr(eb.EmbeddingBackend, "_get_local_model_path", fake_local_path)

        class FakeDownloader:
            def __init__(self, model_name):
                pass

            def ensure_cached(self):
                return True

        monkeypatch.setattr("jfox.model_downloader.ModelDownloader", FakeDownloader)

        loaded_with = []

        class FakeST:
            def __init__(self, name, device=None):
                loaded_with.append(name)

            def get_sentence_embedding_dimension(self):
                return 512

        monkeypatch.setattr("sentence_transformers.SentenceTransformer", FakeST)

        backend.load()
        assert loaded_with == [str(local_dir)]
        assert backend.dimension == 512
