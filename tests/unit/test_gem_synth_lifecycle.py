"""gem_synth lifecycle 订阅器单测：4 事件回调 + 类型守卫 + kb 解析。"""

from unittest.mock import patch

import pytest

from jfox.models import NoteType

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_on_deleted_candidate_deletes_and_releases():
    from jfox.gem_synth.lifecycle import _on_deleted

    with (
        patch("jfox.gem_synth.lifecycle.delete_dedup") as dd,
        patch("jfox.gem_synth.lifecycle.release_blocked_anchors") as rba,
        patch("jfox.gem_synth.lifecycle._resolve_kb_name", return_value="kb1"),
    ):
        _on_deleted(note_id="n1", note_type=NoteType.CANDIDATE)
        dd.assert_called_once_with("kb1", "n1")
        rba.assert_called_once_with("n1")


def test_on_deleted_permanent_also_syncs():
    """删 permanent 同样清 dedup + 释放锚点（原 note.py 守卫含 PERMANENT）。"""
    from jfox.gem_synth.lifecycle import _on_deleted

    with (
        patch("jfox.gem_synth.lifecycle.delete_dedup") as dd,
        patch("jfox.gem_synth.lifecycle.release_blocked_anchors") as rba,
        patch("jfox.gem_synth.lifecycle._resolve_kb_name", return_value="kb1"),
    ):
        _on_deleted(note_id="n1", note_type=NoteType.PERMANENT)
        dd.assert_called_once_with("kb1", "n1")
        rba.assert_called_once_with("n1")


def test_on_deleted_fleeting_skips_early():
    """fleeting/literature/session 无 dedup 行：早返回，不解析 kb 也不碰 store。"""
    from jfox.gem_synth.lifecycle import _on_deleted

    with (
        patch("jfox.gem_synth.lifecycle.delete_dedup") as dd,
        patch("jfox.gem_synth.lifecycle.release_blocked_anchors") as rba,
        patch("jfox.gem_synth.lifecycle._resolve_kb_name") as rkn,
    ):
        _on_deleted(note_id="n1", note_type=NoteType.FLEETING)
        dd.assert_not_called()
        rba.assert_not_called()
        rkn.assert_not_called()


def test_on_archived_reuses_deleted_logic():
    from jfox.gem_synth import lifecycle

    with (
        patch("jfox.gem_synth.lifecycle.delete_dedup") as dd,
        patch("jfox.gem_synth.lifecycle.release_blocked_anchors") as rba,
        patch("jfox.gem_synth.lifecycle._resolve_kb_name", return_value="kb1"),
    ):
        lifecycle._on_archived(note_id="n1", note_type=NoteType.CANDIDATE)
        dd.assert_called_once_with("kb1", "n1")
        rba.assert_called_once_with("n1")


def test_on_promoted_updates_type_to_permanent():
    from jfox.gem_synth.lifecycle import _on_promoted

    with (
        patch("jfox.gem_synth.lifecycle.update_dedup_type") as udt,
        patch("jfox.gem_synth.lifecycle._resolve_kb_name", return_value="kb1"),
    ):
        _on_promoted(note_id="n1", note_type=NoteType.PERMANENT)
        udt.assert_called_once_with("kb1", "n1", "permanent")


def test_on_rejected_deletes_and_releases():
    from jfox.gem_synth.lifecycle import _on_rejected

    with (
        patch("jfox.gem_synth.lifecycle.delete_dedup") as dd,
        patch("jfox.gem_synth.lifecycle.release_blocked_anchors") as rba,
        patch("jfox.gem_synth.lifecycle._resolve_kb_name", return_value="kb1"),
    ):
        _on_rejected(note_id="n1", note_type=NoteType.CANDIDATE)
        dd.assert_called_once_with("kb1", "n1")
        rba.assert_called_once_with("n1")


def test_register_hooks_four_events():
    """register() 把 4 回调注册到 note.py，事件名齐全。"""
    from jfox.gem_synth import lifecycle

    with patch("jfox.note.register_lifecycle_hook") as reg:
        lifecycle.register()
        events = {c.args[0] for c in reg.call_args_list}
        assert events == {"post_delete", "post_archive", "post_promote", "post_reject"}


def test_register_calls_four_hooks_each_invocation():
    """register() 每次调用注册 4 个事件回调（mock 不去重 → 2 次调用 = 8 次 register_lifecycle_hook）；真正幂等性由 register_lifecycle_hook 去重保证，见 test_note_lifecycle_hooks.py。"""
    from jfox.gem_synth import lifecycle

    with patch("jfox.note.register_lifecycle_hook") as reg:
        lifecycle.register()
        lifecycle.register()
        assert len(reg.call_args_list) == 8
