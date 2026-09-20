"""A1/A2 (#519): 语义组件可用性探测、缓存与安装提示。"""

import importlib.util
import sys
from unittest.mock import patch

import pytest

import jfox.embedding_backend as eb
from jfox.embedding_backend import (
    EmbedDependencyMissingError,
    format_embed_hint,
    is_embedding_service_available,
    is_local_embed_available,
    reset_embed_availability_cache,
)


@pytest.fixture(autouse=True)
def _reset_probe_cache():
    reset_embed_availability_cache()
    yield
    reset_embed_availability_cache()


class TestLocalProbe:
    def test_true_when_spec_found(self, monkeypatch):
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
        assert is_local_embed_available() is True

    def test_false_when_spec_missing(self, monkeypatch):
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
        assert is_local_embed_available() is False

    def test_cached_after_first_probe(self, monkeypatch):
        calls = []

        def counting(name):
            calls.append(name)
            return None

        monkeypatch.setattr(importlib.util, "find_spec", counting)
        is_local_embed_available()
        is_local_embed_available()
        assert len(calls) == 1  # 第二次走缓存

        reset_embed_availability_cache()
        is_local_embed_available()
        assert len(calls) == 2  # reset 后重查


class TestServiceAvailability:
    def test_local_available_short_circuits(self, monkeypatch):
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: object())
        with patch("jfox.daemon.process.is_daemon_running") as m:
            assert is_embedding_service_available() is True
            m.assert_not_called()  # 本地可用时不查 daemon

    def test_daemon_running_and_client_available(self, monkeypatch):
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
        monkeypatch.setattr("jfox.daemon.process.is_daemon_running", lambda: True)
        monkeypatch.setattr("jfox.daemon.process._get_daemon_url", lambda: "http://127.0.0.1:18700")
        with patch("jfox.daemon.client.DaemonClient") as client_cls:
            client_cls.return_value.available = True
            assert is_embedding_service_available() is True

    def test_daemon_not_running(self, monkeypatch):
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
        monkeypatch.setattr("jfox.daemon.process.is_daemon_running", lambda: False)
        assert is_embedding_service_available() is False

    def test_daemon_process_env_ignores_daemon(self, monkeypatch):
        # daemon 进程内部不得代理自己：JFOX_DAEMON_PROCESS 下只看本地
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)
        monkeypatch.setattr("jfox.daemon.process.is_daemon_running", lambda: True)
        monkeypatch.setenv("JFOX_DAEMON_PROCESS", "1")
        assert is_embedding_service_available() is False

    def test_daemon_check_exception_is_false(self, monkeypatch):
        monkeypatch.setattr(importlib.util, "find_spec", lambda name: None)

        def boom():
            raise RuntimeError("pid file corrupted")

        monkeypatch.setattr("jfox.daemon.process.is_daemon_running", boom)
        assert is_embedding_service_available() is False


class TestHintAndError:
    def test_hint_contains_four_elements(self):
        hint = format_embed_hint("语义检索")
        assert "UV_TORCH_BACKEND=cpu" in hint
        assert "jfox-cli[embed]" in hint
        assert "https://download.pytorch.org/whl/cpu" in hint
        assert "index rebuild" in hint
        assert "语义检索" in hint  # context 前缀拼入

    def test_hint_default_context(self):
        hint = format_embed_hint()
        assert hint.startswith("[提示]")

    def test_error_carries_hint(self):
        err = EmbedDependencyMissingError(format_embed_hint("写入语义索引"))
        assert "UV_TORCH_BACKEND" in str(err)


class TestLoadRaisesTypedError:
    def test_load_without_package_raises_typed(self, monkeypatch):
        # sys.modules 置 None 使 `from sentence_transformers import ...` 抛 ImportError
        monkeypatch.setitem(sys.modules, "sentence_transformers", None)
        monkeypatch.setattr("jfox.daemon.process.is_daemon_running", lambda: False)

        backend = eb.EmbeddingBackend(model_name="BAAI/bge-small-zh-v1.5", device="cpu")
        with pytest.raises(EmbedDependencyMissingError) as exc_info:
            backend.load()
        assert "UV_TORCH_BACKEND" in str(exc_info.value)
