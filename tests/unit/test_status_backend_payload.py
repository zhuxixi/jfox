"""#363 status backend 块组装纯函数单测（A1 + A8）。"""

from jfox.cli import _display_dimension, _status_backend_payload

LOCAL_LOADED = {"type": "cuda", "model": "BAAI/bge-m3", "loaded": True, "dimension": 1024}
LOCAL_PINNED_UNLOADED = {"type": "cpu", "model": "BAAI/bge-m3", "loaded": False, "dimension": 1024}
LOCAL_AUTO = {"type": "unknown", "model": None, "loaded": False, "dimension": 512}

DAEMON = {
    "pid": 19793,
    "host": "127.0.0.1",
    "port": 18700,
    "model": "BAAI/bge-m3",
    "dimension": 1024,
    "device": "cuda",
    "started_at": None,
}


class TestDaemonSource:
    """A1：daemon 在跑时完全覆盖本地值。"""

    def test_daemon_wins_over_local(self):
        assert _status_backend_payload(LOCAL_AUTO, DAEMON) == {
            "type": "cuda",
            "model": "BAAI/bge-m3",
            "dimension": 1024,
            "source": "daemon",
        }

    def test_missing_keys_fall_back_without_raising(self):
        assert _status_backend_payload(LOCAL_AUTO, {}) == {
            "type": "unknown",
            "model": "unknown",
            "dimension": None,
            "source": "daemon",
        }

    def test_degraded_daemon_passes_through_zero(self):
        """A8：degraded daemon 上报 dimension=0，必须原样透传。"""
        degraded = {"model": "unavailable", "dimension": 0, "device": "none"}
        assert _status_backend_payload(LOCAL_AUTO, degraded) == {
            "type": "none",
            "model": "unavailable",
            "dimension": 0,
            "source": "daemon",
        }


class TestLocalSource:
    """A1：同进程已 load 时用真实维度。"""

    def test_loaded_backend_uses_real_dimension(self):
        assert _status_backend_payload(LOCAL_LOADED, None) == {
            "type": "cuda",
            "model": "BAAI/bge-m3",
            "dimension": 1024,
            "source": "local",
        }


class TestUnloadedSource:
    """A1：未加载时不伪造维度。"""

    def test_auto_model_has_null_dimension(self):
        assert _status_backend_payload(LOCAL_AUTO, None) == {
            "type": "unknown",
            "model": "auto (未加载)",
            "dimension": None,
            "source": "unloaded",
        }

    def test_pinned_model_keeps_name_but_no_dimension(self):
        payload = _status_backend_payload(LOCAL_PINNED_UNLOADED, None)
        assert payload["model"] == "BAAI/bge-m3"
        assert payload["dimension"] is None
        assert payload["source"] == "unloaded"

    def test_key_set_is_stable(self):
        for local, daemon in ((LOCAL_AUTO, DAEMON), (LOCAL_LOADED, None), (LOCAL_AUTO, None)):
            assert set(_status_backend_payload(local, daemon)) == {
                "type",
                "model",
                "dimension",
                "source",
            }


class TestDisplayDimension:
    """A9 的显示侧：None→unknown，0 保留。"""

    def test_none_renders_unknown(self):
        assert _display_dimension(None) == "unknown"

    def test_zero_is_kept(self):
        assert _display_dimension(0) == "0"

    def test_int_renders_plain(self):
        assert _display_dimension(1024) == "1024"
