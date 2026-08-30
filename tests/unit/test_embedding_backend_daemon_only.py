"""
测试类型: 单元测试
目标模块: jfox.embedding_backend（daemon_only 模式，#383 F2）
预估耗时: < 1秒

契约：daemon_only=True 时，daemon 不可用或编码失败都不得回退本地模型加载
（add 防重路径的秒级延迟红线），异常向上抛由闸门层降级。
"""

from unittest.mock import MagicMock

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]


class _Sentinel(Exception):
    """哨兵异常：证明回退路径被走到了（无需真加载模型）。"""


@pytest.fixture
def backend():
    from jfox.embedding_backend import EmbeddingBackend

    b = EmbeddingBackend(device="cpu", model_name="mock-model")
    # 绕过真实 daemon 探测：缓存结果 + stub client
    b._use_daemon = True
    b._daemon_client = MagicMock()
    b._daemon_client.encode.side_effect = RuntimeError("daemon encode exploded")
    return b


def _record_load(b, raise_sentinel: bool):
    calls = []
    orig = b.load

    def _load():
        calls.append(1)
        if raise_sentinel:
            raise _Sentinel("local load attempted")
        return orig()

    b.load = _load
    return calls


class TestDaemonOnlyMode:
    def test_daemon_encode_failure_raises_without_local_load(self, backend):
        """daemon_only：daemon 编码失败 → 异常上抛，不设 _use_daemon=False，不 load。"""
        calls = _record_load(backend, raise_sentinel=True)
        with pytest.raises(RuntimeError, match="daemon encode exploded"):
            backend.encode(["x"], daemon_only=True)
        assert calls == []
        assert backend._use_daemon is True  # 不毒化缓存

    def test_daemon_unavailable_raises_without_local_load(self, backend):
        """daemon_only：daemon 本就不可用 → 直接抛 RuntimeError，不 load。"""
        backend._use_daemon = False
        backend._daemon_client = None
        calls = _record_load(backend, raise_sentinel=True)
        with pytest.raises(RuntimeError, match="daemon"):
            backend.encode(["x"], daemon_only=True)
        assert calls == []

    def test_default_mode_still_falls_back_to_local(self, backend):
        """默认模式行为不变：daemon 失败 → 回退本地（load 被走到，哨兵上抛）。"""
        calls = _record_load(backend, raise_sentinel=True)
        with pytest.raises(_Sentinel):
            backend.encode(["x"])
        assert calls == [1]
        assert backend._use_daemon is False

    def test_encode_single_passes_daemon_only(self, backend):
        """encode_single 透传 daemon_only（gem_synth dedup 的调用入口）。"""
        calls = _record_load(backend, raise_sentinel=True)
        with pytest.raises(RuntimeError, match="daemon encode exploded"):
            backend.encode_single("x", daemon_only=True)
        assert calls == []
