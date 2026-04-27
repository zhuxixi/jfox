"""模型下载集成测试"""

from unittest.mock import MagicMock, patch

import pytest

from jfox.model_downloader import ModelDownloader

pytestmark = [pytest.mark.integration]


class TestModelDownloadRetryChain:
    """mock 网络层，验证完整重试链按顺序执行"""

    @pytest.fixture
    def downloader(self, tmp_path):
        with patch(
            "jfox.model_downloader.ModelDownloader._get_hf_hub_cache",
            return_value=tmp_path / "hub",
        ):
            return ModelDownloader("sentence-transformers/all-MiniLM-L6-v2")

    def test_full_chain_step1_succeeds(self, downloader):
        """Step 1 成功，后续步骤不执行"""
        with patch.object(downloader, "_try_hf_hub_download", side_effect=[True, False]) as mock_hf:
            with patch.object(downloader, "_try_curl_download") as mock_curl:
                result = downloader.ensure_cached()
                assert result is True
                assert mock_hf.call_count == 1
                mock_curl.assert_not_called()

    def test_full_chain_step1_fails_step2_succeeds(self, downloader):
        """Step 1 失败，Step 2 成功"""
        with patch.object(downloader, "_try_hf_hub_download", side_effect=[False, True]) as mock_hf:
            with patch.object(downloader, "_try_curl_download") as mock_curl:
                result = downloader.ensure_cached()
                assert result is True
                calls = mock_hf.call_args_list
                assert len(calls) == 2
                assert calls[0][1].get("endpoint") is None
                assert calls[1][1].get("endpoint") is not None
                mock_curl.assert_not_called()

    def test_full_chain_step1_2_fail_step3_succeeds(self, downloader):
        """Step 1/2 失败，Step 3 成功"""
        with patch.object(downloader, "_try_hf_hub_download", return_value=False):
            with patch.object(downloader, "_try_curl_download", return_value=True) as mock_curl:
                result = downloader.ensure_cached()
                assert result is True
                mock_curl.assert_called_once()

    def test_full_chain_all_fail(self, downloader):
        """全部失败，返回 False"""
        with patch.object(downloader, "_try_hf_hub_download", return_value=False):
            with patch.object(downloader, "_try_curl_download", return_value=False):
                result = downloader.ensure_cached()
                assert result is False

    def test_daemon_start_calls_downloader(self):
        """验证 daemon start 启动前调用下载检查"""
        from jfox.daemon.process import start_daemon

        with patch("jfox.daemon.process._http_health_check", return_value=None):
            with patch("jfox.daemon.process._check_model_cache") as mock_cache:
                mock_cache.return_value = {
                    "needs_download": True,
                    "model_name": "test-model",
                    "size_hint": "90MB",
                }
                with patch(
                    "jfox.model_downloader.ModelDownloader",
                ) as mock_cls:
                    mock_downloader = MagicMock()
                    mock_downloader.ensure_cached.return_value = True
                    mock_cls.return_value = mock_downloader

                    with patch("jfox.daemon.process.subprocess.Popen"):
                        with patch(
                            "jfox.daemon.process._http_health_check",
                            side_effect=[None, {"pid": 123}],
                        ):
                            start_daemon()
                            mock_cls.assert_called_once_with("test-model")
                            mock_downloader.ensure_cached.assert_called_once()

    def test_cli_model_download_command(self):
        """验证 CLI model download 命令正确调用 downloader"""
        from typer.testing import CliRunner

        from jfox.cli import app

        runner = CliRunner()

        with patch(
            "jfox.model_downloader.ModelDownloader",
        ) as mock_cls:
            mock_downloader = MagicMock()
            mock_downloader.ensure_cached.return_value = True
            mock_downloader._check_cached.return_value = False
            mock_cls.return_value = mock_downloader

            result = runner.invoke(app, ["model", "download"])
            assert result.exit_code == 0
            mock_cls.assert_called_once()
            mock_downloader.ensure_cached.assert_called_once()
