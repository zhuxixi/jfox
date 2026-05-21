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
            with patch(
                "sentence_transformers.SentenceTransformer", return_value=mock_model
            ) as mock_st:
                with patch.object(backend, "_check_daemon", return_value=False):
                    backend.load()
                    mock_st.assert_called_once_with(
                        "sentence-transformers/all-MiniLM-L6-v2", device="cpu"
                    )
