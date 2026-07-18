"""note.py 生命周期注册表纯单测（不依赖 gem_synth）。"""

import pytest

from jfox.note import (
    _LIFECYCLE_HOOKS,
    _dispatch,
    register_lifecycle_hook,
    unregister_lifecycle_hook,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


@pytest.fixture(autouse=True)
def _clean_hooks():
    """每测前后清空注册表，避免互相污染。"""
    _LIFECYCLE_HOOKS.clear()
    yield
    _LIFECYCLE_HOOKS.clear()


def test_dispatch_calls_registered_callback():
    calls = []
    register_lifecycle_hook("post_delete", lambda **kw: calls.append(kw))
    _dispatch("post_delete", note_id="123", note_type="candidate")
    assert calls == [{"note_id": "123", "note_type": "candidate"}]


def test_dispatch_no_callbacks_is_noop():
    # 未注册任何回调时不抛
    _dispatch("post_delete", note_id="123", note_type="candidate")


def test_dispatch_isolates_callback_exceptions():
    """一个回调抛异常不影响其他回调，且不向外抛（dispatch 内 warning 兜底）。"""
    seen = []

    def bad(**kw):
        raise RuntimeError("boom")

    register_lifecycle_hook("post_delete", bad)
    register_lifecycle_hook("post_delete", lambda **kw: seen.append(kw["note_id"]))
    _dispatch("post_delete", note_id="123", note_type="candidate")
    assert seen == ["123"]


def test_register_is_idempotent():
    """同一 callback 重复注册只挂一次。"""
    calls = []

    def cb(**kw):
        calls.append(1)

    register_lifecycle_hook("post_delete", cb)
    register_lifecycle_hook("post_delete", cb)
    _dispatch("post_delete", note_id="1", note_type="candidate")
    assert len(calls) == 1


def test_unregister_removes_callback():
    seen = []

    def cb(**kw):
        seen.append(1)

    register_lifecycle_hook("post_delete", cb)
    unregister_lifecycle_hook("post_delete", cb)
    _dispatch("post_delete", note_id="1", note_type="candidate")
    assert seen == []


def test_dispatch_isolates_events():
    """post_delete 的回调不被 post_archive 触发。"""
    deleted = []
    archived = []
    register_lifecycle_hook("post_delete", lambda **kw: deleted.append(kw["note_id"]))
    register_lifecycle_hook("post_archive", lambda **kw: archived.append(kw["note_id"]))
    _dispatch("post_delete", note_id="9", note_type="candidate")
    assert deleted == ["9"]
    assert archived == []
