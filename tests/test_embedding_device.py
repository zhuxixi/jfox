"""Tests for EmbeddingBackend device detection and model selection"""
from unittest.mock import MagicMock, patch

import pytest

from jfox.embedding_backend import EmbeddingBackend


class TestDeviceResolution:
    """测试 device 解析逻辑"""

    @patch("jfox.embedding_backend.torch", create=True)
    def test_auto_resolves_to_cuda_when_available(self, mock_torch_module):
        """auto 模式下，CUDA 可用时解析为 cuda"""
        with patch("torch.cuda.is_available", return_value=True):
            with patch("torch.cuda.get_device_name", return_value="NVIDIA RTX 4000"):
                backend = EmbeddingBackend(device="auto")
                resolved = backend._resolve_device()
                assert resolved == "cuda"

    def test_auto_resolves_to_cpu_when_no_cuda(self):
        """auto 模式下，CUDA 不可用时解析为 cpu"""
        with patch("torch.cuda.is_available", return_value=False):
            backend = EmbeddingBackend(device="auto")
            resolved = backend._resolve_device()
            assert resolved == "cpu"

    def test_explicit_cuda_skips_detection(self):
        """手动指定 cuda 时跳过自动检测"""
        backend = EmbeddingBackend(device="cuda")
        resolved = backend._resolve_device()
        assert resolved == "cuda"

    def test_explicit_cpu_skips_detection(self):
        """手动指定 cpu 时跳过自动检测"""
        backend = EmbeddingBackend(device="cpu")
        resolved = backend._resolve_device()
        assert resolved == "cpu"


class TestModelSelection:
    """测试模型自动选择"""

    def test_none_model_with_cuda_selects_bge_m3(self):
        """model_name=None + device=cuda → 选择 bge-m3"""
        with patch("torch.cuda.is_available", return_value=True):
            with patch("torch.cuda.get_device_name", return_value="NVIDIA RTX 4000"):
                backend = EmbeddingBackend(model_name=None, device="cuda")
                resolved_model = backend._resolve_model_name("cuda")
                assert resolved_model == "BAAI/bge-m3"

    def test_none_model_with_cpu_selects_minilm(self):
        """model_name=None + device=cpu → 选择 MiniLM"""
        backend = EmbeddingBackend(model_name=None, device="cpu")
        resolved_model = backend._resolve_model_name("cpu")
        assert resolved_model == "sentence-transformers/all-MiniLM-L6-v2"

    def test_explicit_model_overrides_auto(self):
        """手动指定模型时优先使用手动值"""
        backend = EmbeddingBackend(
            model_name="BAAI/bge-large-zh-v1.5", device="cpu"
        )
        resolved_model = backend._resolve_model_name("cpu")
        assert resolved_model == "BAAI/bge-large-zh-v1.5"

    def test_auto_model_string_selects_by_device(self):
        """model_name='auto' 等同于 None，根据 device 选模型"""
        with patch("torch.cuda.is_available", return_value=True):
            with patch("torch.cuda.get_device_name", return_value="NVIDIA RTX 4000"):
                backend = EmbeddingBackend(model_name="auto", device="cuda")
                resolved_model = backend._resolve_model_name("cuda")
                assert resolved_model == "BAAI/bge-m3"


class TestGetBackend:
    """测试 get_backend() 从 config 读取配置"""

    def test_reads_config_device(self):
        """get_backend() 从 config.device 读取"""
        from jfox.embedding_backend import get_backend, reset_backend

        reset_backend()
        with patch("jfox.config.config") as mock_config:
            mock_config.embedding_model = "BAAI/bge-m3"
            mock_config.device = "cuda"
            backend = get_backend()
            assert backend.device == "cuda"
            assert backend.model_name == "BAAI/bge-m3"
        reset_backend()

    def test_auto_model_resolves_to_none(self):
        """config.embedding_model='auto' 传 None 给 EmbeddingBackend"""
        from jfox.embedding_backend import get_backend, reset_backend

        reset_backend()
        with patch("jfox.config.config") as mock_config:
            mock_config.embedding_model = "auto"
            mock_config.device = "cpu"
            backend = get_backend()
            assert backend.model_name is None  # None = auto-select
        reset_backend()

    def test_reset_backend_clears_singleton(self):
        """reset_backend() 清除全局单例"""
        from jfox.embedding_backend import reset_backend

        reset_backend()
        import jfox.embedding_backend as eb

        assert eb._backend is None
