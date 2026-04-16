"""Unit tests for 'jfox config set' command"""
from unittest.mock import patch

import pytest
import yaml


class TestConfigSet:
    """测试 jfox config set 命令"""

    def test_set_device_writes_to_yaml(self, tmp_path):
        """config set device cuda 写入 config.yaml"""
        from jfox.cli import _config_set_impl

        zk_dir = tmp_path / ".zk"
        zk_dir.mkdir(parents=True)

        with patch("jfox.cli.config") as mock_config:
            mock_config.zk_dir = zk_dir
            mock_config.device = "auto"
            mock_config.embedding_model = "auto"
            _config_set_impl("device", "cuda")

        config_file = zk_dir / "config.yaml"
        with open(config_file) as f:
            data = yaml.safe_load(f)
        assert data["device"] == "cuda"

    def test_set_embedding_model_writes_to_yaml(self, tmp_path):
        """config set embedding_model BAAI/bge-m3 写入 config.yaml"""
        from jfox.cli import _config_set_impl

        zk_dir = tmp_path / ".zk"
        zk_dir.mkdir(parents=True)

        with patch("jfox.cli.config") as mock_config:
            mock_config.zk_dir = zk_dir
            mock_config.device = "auto"
            mock_config.embedding_model = "auto"
            _config_set_impl("embedding_model", "BAAI/bge-m3")

        config_file = zk_dir / "config.yaml"
        with open(config_file) as f:
            data = yaml.safe_load(f)
        assert data["embedding_model"] == "BAAI/bge-m3"

    def test_set_invalid_key_raises(self):
        """config set invalid_key 抛出错误"""
        from jfox.cli import _config_set_impl

        with pytest.raises(ValueError, match="不支持的配置项"):
            _config_set_impl("invalid_key", "value")

    def test_set_resets_backend_singleton(self, tmp_path):
        """config set 后重置 backend 单例"""
        from jfox.cli import _config_set_impl

        zk_dir = tmp_path / ".zk"
        zk_dir.mkdir(parents=True)

        with (
            patch("jfox.cli.config") as mock_config,
            patch("jfox.embedding_backend.reset_backend") as mock_reset,
        ):
            mock_config.zk_dir = zk_dir
            mock_config.device = "auto"
            mock_config.embedding_model = "auto"
            _config_set_impl("device", "cuda")
            mock_reset.assert_called_once()

    def test_valid_config_keys(self):
        """验证所有合法的配置键"""
        from jfox.cli import _VALID_CONFIG_KEYS

        assert "device" in _VALID_CONFIG_KEYS
        assert "embedding_model" in _VALID_CONFIG_KEYS
        assert "batch_size" in _VALID_CONFIG_KEYS
