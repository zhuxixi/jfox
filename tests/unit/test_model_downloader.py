"""ModelDownloader 单元测试"""

import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from jfox.model_downloader import ModelDownloader


class TestModelDownloader:
    """ModelDownloader 单元测试"""

    @pytest.fixture
    def downloader(self, tmp_path):
        """创建带临时缓存的 downloader"""
        local_path = tmp_path / "local_models" / "sentence-transformers--all-MiniLM-L6-v2"
        with (
            patch(
                "jfox.model_downloader.ModelDownloader._get_hf_hub_cache",
                return_value=tmp_path / "hub",
            ),
            patch.object(
                ModelDownloader,
                "_get_local_model_path",
                return_value=local_path,
            ),
        ):
            d = ModelDownloader("sentence-transformers/all-MiniLM-L6-v2")
            yield d
            # 清理本地模型目录，避免影响后续测试
            if local_path.exists():
                import shutil

                shutil.rmtree(local_path)

    def test_check_cached_when_not_exists(self, downloader):
        """缓存不存在时返回 False"""
        assert downloader._check_cached() is False

    def test_check_cached_when_exists(self, downloader):
        """缓存存在时返回 True"""
        snapshot = downloader._model_cache / "snapshots" / "abc123"
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
        with patch.object(downloader, "_try_hf_hub_download", return_value=True) as mock_hf:
            with patch.object(downloader, "_try_modelscope_http") as mock_http:
                with patch.object(downloader, "_try_curl_download") as mock_curl:
                    result = downloader.ensure_cached()
                    assert result is True
                    mock_hf.assert_called_once()
                    mock_http.assert_not_called()
                    mock_curl.assert_not_called()

    def test_ensure_cached_step1_fails_step2_succeeds(self, downloader):
        """Step 1 失败，Step 2 成功"""
        with patch.object(downloader, "_try_hf_hub_download", return_value=False) as mock_hf:
            with patch.object(downloader, "_try_modelscope_http", return_value=True) as mock_http:
                with patch.object(downloader, "_try_curl_download") as mock_curl:
                    result = downloader.ensure_cached()
                    assert result is True
                    mock_hf.assert_called_once()
                    mock_http.assert_called_once()
                    mock_curl.assert_not_called()

    def test_ensure_cached_step1_2_fail_step3_succeeds(self, downloader):
        """Step 1/2 失败，Step 3 成功"""
        with patch.object(downloader, "_try_hf_hub_download", return_value=False) as mock_hf:
            with patch.object(downloader, "_try_modelscope_http", return_value=False) as mock_http:
                with patch.object(downloader, "_try_curl_download", return_value=True) as mock_curl:
                    result = downloader.ensure_cached()
                    assert result is True
                    mock_hf.assert_called_once()
                    mock_http.assert_called_once()
                    mock_curl.assert_called_once()

    def test_ensure_cached_all_fail(self, downloader):
        """全部失败，返回 False"""
        with patch.object(downloader, "_try_hf_hub_download", return_value=False):
            with patch.object(downloader, "_try_modelscope_http", return_value=False):
                with patch.object(downloader, "_try_curl_download", return_value=False):
                    result = downloader.ensure_cached()
                    assert result is False

    def test_try_curl_download_no_curl(self, downloader):
        """curl 不存在时返回 False"""
        with patch("jfox.model_downloader.shutil.which", return_value=None):
            result = downloader._try_curl_download()
            assert result is False

    def test_check_cached_with_pytorch_bin(self, downloader):
        """pytorch_model.bin 格式的缓存也能正常识别"""
        snapshot = downloader._model_cache / "snapshots" / "abc123"
        snapshot.mkdir(parents=True)
        (snapshot / "pytorch_model.bin").write_text("fake")
        assert downloader._check_cached() is True

    def test_try_hf_hub_download_fallback_to_pytorch(self, downloader):
        """model.safetensors 不存在时回退到 pytorch_model.bin"""
        call_count = 0

        def hf_hub_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:  # model.safetensors 失败
                raise Exception("not found")
            # pytorch_model.bin + 其他文件均成功
            return str(downloader._model_cache / "snapshots" / "abc")

        with patch("huggingface_hub.hf_hub_download") as mock_download:
            mock_download.side_effect = hf_hub_side_effect
            result = downloader._try_hf_hub_download()
            assert result is True

    def test_try_curl_download_success(self, downloader):
        """curl 下载成功，文件写入本地目录"""
        local_path = downloader._get_local_model_path()

        def subprocess_side_effect(*args, **kwargs):
            cmd = args[0]
            outfile = cmd[cmd.index("-o") + 1]
            Path(outfile).write_text("fake model")
            return MagicMock(returncode=0)

        with patch("jfox.model_downloader.shutil.which", return_value="curl"):
            with patch(
                "jfox.model_downloader.subprocess.run",
                side_effect=subprocess_side_effect,
            ) as mock_run:
                result = downloader._try_curl_download()
                assert result is True
                assert (local_path / "model.safetensors").exists()
                # 验证 curl 调用了 ModelScope API URL
                calls = mock_run.call_args_list
                assert len(calls) >= 1
                cmd = calls[0][0][0]
                url = cmd[-1]
                assert "modelscope.cn" in url or "api/v1/models" in url

    def test_try_curl_download_custom_mirror(self, downloader):
        """JFOX_MODEL_MIRROR 环境变量生效"""
        with patch.dict(os.environ, {"JFOX_MODEL_MIRROR": "https://custom.mirror.com"}):

            def subprocess_side_effect(*args, **kwargs):
                cmd = args[0]
                outfile = cmd[cmd.index("-o") + 1]
                Path(outfile).write_text("fake model")
                return MagicMock(returncode=0)

            with patch("jfox.model_downloader.shutil.which", return_value="curl"):
                with patch(
                    "jfox.model_downloader.subprocess.run",
                    side_effect=subprocess_side_effect,
                ) as mock_run:
                    result = downloader._try_curl_download()
                    assert result is True
                    calls = mock_run.call_args_list
                    url = calls[0][0][0][-1]
                    assert "custom.mirror.com" in url

    def test_cleanup_partial(self, downloader):
        """curl 返回成功码但未写入文件，视为失败"""
        with patch("jfox.model_downloader.shutil.which", return_value="curl"):
            with patch("jfox.model_downloader.subprocess.run") as mock_run:
                mock_run.return_value = MagicMock(returncode=0)
                result = downloader._try_curl_download()
                # subprocess 返回 0 但文件不存在，返回 False
                assert result is False

    def test_check_cached_local_dir_with_weight(self, downloader):
        """本地目录存在权重文件时返回 True"""
        local = downloader._get_local_model_path()
        local.mkdir(parents=True, exist_ok=True)
        (local / "model.safetensors").write_text("fake")
        assert downloader._check_cached() is True

    def test_check_cached_local_dir_without_weight(self, downloader):
        """本地目录存在但无权重文件时返回 False"""
        local = downloader._get_local_model_path()
        local.mkdir(parents=True, exist_ok=True)
        (local / "config.json").write_text("fake")
        assert downloader._check_cached() is False

    def test_try_modelscope_http_success(self, downloader):
        """ModelScope HTTP 下载成功"""
        with patch("jfox.model_downloader.urlretrieve") as mock_retrieve:

            def urlretrieve_side_effect(url, dest):
                Path(dest).write_text("fake model")

            mock_retrieve.side_effect = urlretrieve_side_effect

            result = downloader._try_modelscope_http()
            assert result is True
            local_path = downloader._get_local_model_path()
            assert (local_path / "model.safetensors").exists()

    def test_try_modelscope_http_fallback_to_pytorch(self, downloader):
        """model.safetensors 不存在时回退到 pytorch_model.bin"""
        call_count = 0

        def urlretrieve_side_effect(url, dest):
            nonlocal call_count
            call_count += 1
            if "model.safetensors" in url:
                raise Exception("404")
            Path(dest).write_text("fake model")

        with patch("jfox.model_downloader.urlretrieve") as mock_retrieve:
            mock_retrieve.side_effect = urlretrieve_side_effect
            result = downloader._try_modelscope_http()
            assert result is True
            assert call_count >= 1

    def test_try_modelscope_http_all_fail(self, downloader):
        """所有权重文件下载失败"""
        with patch("jfox.model_downloader.urlretrieve", side_effect=Exception("network")):
            result = downloader._try_modelscope_http()
            assert result is False

    def test_try_modelscope_http_custom_mirror(self, downloader):
        """JFOX_MODEL_MIRROR 环境变量生效"""
        with patch.dict(os.environ, {"JFOX_MODEL_MIRROR": "https://custom.mirror.com"}):
            with patch("jfox.model_downloader.urlretrieve") as mock_retrieve:

                def urlretrieve_side_effect(url, dest):
                    assert "custom.mirror.com" in url
                    Path(dest).write_text("fake")

                mock_retrieve.side_effect = urlretrieve_side_effect
                result = downloader._try_modelscope_http()
                assert result is True

    def test_get_manual_instructions(self, downloader):
        """手动下载指引包含 ModelScope URL 和本地路径"""
        instructions = downloader.get_manual_instructions()
        assert "modelscope.cn" in instructions or "JFOX_MODEL_MIRROR" in instructions
        assert downloader.model_name in instructions
        assert str(downloader._get_local_model_path()) in instructions

    def test_get_manual_instructions_custom_mirror(self, downloader):
        """自定义镜像站时指引使用自定义 URL"""
        with patch.dict(os.environ, {"JFOX_MODEL_MIRROR": "https://custom.mirror.com"}):
            instructions = downloader.get_manual_instructions()
            assert "custom.mirror.com" in instructions
