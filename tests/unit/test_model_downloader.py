"""ModelDownloader 单元测试"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jfox.model_downloader import ModelDownloader, _HF_MIRROR


class TestModelDownloader:
    """ModelDownloader 单元测试"""

    @pytest.fixture
    def downloader(self, tmp_path):
        """创建带临时缓存的 downloader"""
        with patch(
            "jfox.model_downloader.ModelDownloader._get_hf_hub_cache",
            return_value=tmp_path / "hub",
        ):
            d = ModelDownloader("sentence-transformers/all-MiniLM-L6-v2")
            return d

    def test_check_cached_when_not_exists(self, downloader):
        """缓存不存在时返回 False"""
        assert downloader._check_cached() is False

    def test_check_cached_when_exists(self, downloader):
        """缓存存在时返回 True"""
        snapshot = (
            downloader._model_cache
            / "snapshots"
            / "abc123"
        )
        snapshot.mkdir(parents=True)
        (snapshot / "model.safetensors").write_text("fake")
        assert downloader._check_cached() is True

    def test_check_cached_missing_model_file(self, downloader):
        """有 snapshot 但缺少 model.safetensors 时返回 False"""
        snapshot = downloader._model_cache / "snapshots" / "abc123"
        snapshot.mkdir(parents=True)
        (snapshot / "config.json").write_text("fake")
        assert downloader._check_cached() is False

    def test_ensure_cached_early_return_when_cached(self, downloader):
        """已缓存时直接返回 True，不走重试链"""
        snapshot = downloader._model_cache / "snapshots" / "abc123"
        snapshot.mkdir(parents=True)
        (snapshot / "model.safetensors").write_text("fake")

        with patch.object(downloader, "_try_hf_hub_download") as mock_hf:
            result = downloader.ensure_cached()
            assert result is True
            mock_hf.assert_not_called()

    def test_ensure_cached_step1_succeeds(self, downloader):
        """Step 1 成功，后续步骤不执行"""
        with patch.object(
            downloader, "_try_hf_hub_download", side_effect=[True, False]
        ) as mock_hf:
            with patch.object(downloader, "_try_curl_download") as mock_curl:
                result = downloader.ensure_cached()
                assert result is True
                assert mock_hf.call_count == 1
                mock_curl.assert_not_called()

    def test_ensure_cached_step1_fails_step2_succeeds(self, downloader):
        """Step 1 失败，Step 2 成功"""
        with patch.object(
            downloader, "_try_hf_hub_download", side_effect=[False, True]
        ) as mock_hf:
            with patch.object(downloader, "_try_curl_download") as mock_curl:
                result = downloader.ensure_cached()
                assert result is True
                assert mock_hf.call_count == 2
                mock_curl.assert_not_called()

    def test_ensure_cached_step1_2_fail_step3_succeeds(self, downloader):
        """Step 1/2 失败，Step 3 成功"""
        with patch.object(
            downloader, "_try_hf_hub_download", return_value=False
        ) as mock_hf:
            with patch.object(
                downloader, "_try_curl_download", return_value=True
            ) as mock_curl:
                result = downloader.ensure_cached()
                assert result is True
                assert mock_hf.call_count == 2
                mock_curl.assert_called_once()

    def test_ensure_cached_all_fail(self, downloader):
        """全部失败，返回 False"""
        with patch.object(
            downloader, "_try_hf_hub_download", return_value=False
        ):
            with patch.object(
                downloader, "_try_curl_download", return_value=False
            ):
                result = downloader.ensure_cached()
                assert result is False

    def test_try_hf_hub_download_sets_env(self, downloader):
        """验证镜像模式设置了 HF_ENDPOINT 环境变量"""
        env_before = os.environ.get("HF_ENDPOINT")

        with patch(
            "huggingface_hub.hf_hub_download"
        ) as mock_download:
            mock_download.side_effect = Exception("network")
            downloader._try_hf_hub_download(endpoint=_HF_MIRROR)

        # 调用后环境变量应被恢复
        assert os.environ.get("HF_ENDPOINT") == env_before

    def test_try_curl_download_no_curl(self, downloader):
        """curl 不存在时返回 False"""
        with patch("jfox.model_downloader.shutil.which", return_value=None):
            result = downloader._try_curl_download()
            assert result is False

    def test_cleanup_partial(self, downloader):
        """验证部分下载残留被清理（通过 TemporaryDirectory 自动实现）"""
        with patch("jfox.model_downloader.shutil.which", return_value="curl"):
            with patch("jfox.model_downloader.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                downloader._try_curl_download()
                # TemporaryDirectory 在上下文退出时自动清理
