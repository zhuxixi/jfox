"""gem_synth 循环：_tick_once 编排（mock 各组件）。"""

import logging
import sqlite3
import threading
from unittest.mock import MagicMock, patch

from jfox.gem_synth.loop import _tick_once


def test_tick_disabled_returns_skip():
    cfg = MagicMock()
    cfg.enabled = False
    with patch("jfox.gem_synth.loop.get_global_config_manager") as gm:
        gm.return_value.get_gem_synthesis_config.return_value = cfg
        msg = _tick_once(threading.Event())
    assert "禁用" in msg or "跳过" in msg


def test_tick_enabled_processes_anchors():
    cfg = MagicMock()
    cfg.enabled = True
    cfg.anchor_types = ["correction"]
    cfg.grounding_top_k = 5
    cfg.target_kb = None
    cfg.interval_minutes = 30
    anchor = {
        "fragment_id": 1,
        "session_id": "s",
        "timestamp": "t",
        "content": "c",
        "transcript_path": "/x",
        "metadata": {},
    }
    # limit=1 循环：第一次返回一个锚点，第二次返回空（无积压）
    with (
        patch("jfox.gem_synth.loop.get_global_config_manager") as gm,
        patch("jfox.gem_synth.loop.find_anchors", side_effect=[[anchor], []]),
        patch(
            "jfox.gem_synth.loop.synthesize_anchor",
            return_value={"candidate_note_id": "c1", "title": "T", "confidence": 0.8},
        ) as sa,
    ):
        gm.return_value.get_gem_synthesis_config.return_value = cfg
        msg = _tick_once(threading.Event())
    assert "success=1" in msg  # 处理了 1 个
    sa.assert_called_once()


def test_tick_synthesize_exception_does_not_crash():
    cfg = MagicMock()
    cfg.enabled = True
    cfg.anchor_types = ["correction"]
    cfg.grounding_top_k = 5
    cfg.target_kb = None
    cfg.interval_minutes = 30
    # limit=1 循环：第一次返回一个锚点，之后返回空（避免无限重试同一锚点）
    anchor_once = [
        {
            "fragment_id": 1,
            "session_id": "s",
            "timestamp": "t",
            "content": "c",
            "transcript_path": "/x",
            "metadata": {},
        }
    ]
    with (
        patch("jfox.gem_synth.loop.get_global_config_manager") as gm,
        patch(
            "jfox.gem_synth.loop.find_anchors",
            side_effect=[anchor_once, []],
        ),
        patch("jfox.gem_synth.loop.synthesize_anchor", side_effect=RuntimeError("boom")),
    ):
        gm.return_value.get_gem_synthesis_config.return_value = cfg
        msg = _tick_once(threading.Event())  # 不应抛
    assert isinstance(msg, str)


def test_tick_exception_marks_failed_no_busy_loop():
    """synthesize_anchor 抛异常时，loop 必须 mark_failed 隔离坏锚点（不 busy-loop）"""
    from jfox.gem_synth.loop import _tick_once

    cfg = MagicMock(
        enabled=True,
        anchor_types=["correction"],
        grounding_top_k=5,
        target_kb=None,
        interval_minutes=30,
    )
    call_count = {"n": 0}

    def fake_find(*a, **k):
        call_count["n"] += 1
        # 第1次返回锚点，第2次+返回空（若没 mark_failed 会一直返回同一锚点 → 死循环）
        return (
            [
                {
                    "fragment_id": 99,
                    "session_id": "s",
                    "timestamp": "t",
                    "content": "c",
                    "transcript_path": "/x",
                    "metadata": {},
                }
            ]
            if call_count["n"] == 1
            else []
        )

    mock_log = MagicMock()
    mock_log.mark_failed = MagicMock()
    with (
        patch("jfox.gem_synth.loop.get_global_config_manager") as gm,
        patch("jfox.gem_synth.loop.find_anchors", side_effect=fake_find),
        patch("jfox.gem_synth.loop.synthesize_anchor", side_effect=RuntimeError("boom")),
        patch("jfox.gem_synth.loop.SynthesisLog", return_value=mock_log),
    ):
        gm.return_value.get_gem_synthesis_config.return_value = cfg
        msg = _tick_once(threading.Event())
    # mark_failed 被调（坏锚点被隔离）
    mock_log.mark_failed.assert_called()
    assert "failed=1" in msg


def test_tick_find_anchors_exception_distinct_message():
    """find_anchors 抛异常时，返回 msg 应与'无锚点'区分（含 find_anchors 字样）"""
    from jfox.gem_synth.loop import _tick_once

    cfg = MagicMock(
        enabled=True,
        anchor_types=["correction"],
        grounding_top_k=5,
        target_kb=None,
        interval_minutes=30,
    )
    mock_log = MagicMock()
    with (
        patch("jfox.gem_synth.loop.get_global_config_manager") as gm,
        patch("jfox.gem_synth.loop.find_anchors", side_effect=RuntimeError("db locked")),
        patch("jfox.gem_synth.loop.SynthesisLog", return_value=mock_log),
    ):
        gm.return_value.get_gem_synthesis_config.return_value = cfg
        msg = _tick_once(threading.Event())
    assert "find_anchors" in msg
    assert "异常" in msg


def test_tick_mark_failed_failure_logs_warning(caplog):
    """mark_failed 自身失败时不应静默吞 → 记 warning 便于排查（cc R2#2）。

    mark_failed 持续失败会让 busy-loop 防护静默失效且无日志。修复：except 记 warning。
    """
    from jfox.gem_synth.loop import _tick_once

    cfg = MagicMock(
        enabled=True,
        anchor_types=["correction"],
        grounding_top_k=5,
        target_kb=None,
        interval_minutes=30,
    )
    mock_log = MagicMock()
    # mark_failed 自身抛（database locked / disk full 等）
    mock_log.mark_failed = MagicMock(side_effect=sqlite3.OperationalError("database is locked"))
    call_count = {"n": 0}

    def fake_find(*a, **k):
        call_count["n"] += 1
        # 第1次返回锚点（触发 synthesize_anchor 抛异常 → 进 mark_failed 失败路径），之后空
        return (
            [
                {
                    "fragment_id": 7,
                    "session_id": "s",
                    "timestamp": "t",
                    "content": "c",
                    "transcript_path": "/x",
                    "metadata": {},
                }
            ]
            if call_count["n"] == 1
            else []
        )

    with (
        patch("jfox.gem_synth.loop.get_global_config_manager") as gm,
        patch("jfox.gem_synth.loop.find_anchors", side_effect=fake_find),
        patch("jfox.gem_synth.loop.synthesize_anchor", side_effect=RuntimeError("boom")),
        patch("jfox.gem_synth.loop.SynthesisLog", return_value=mock_log),
    ):
        gm.return_value.get_gem_synthesis_config.return_value = cfg
        with caplog.at_level(logging.WARNING, logger="jfox.gem_synth.loop"):
            msg = _tick_once(threading.Event())
    # mark_failed 被尝试调用（隔离坏锚点）
    mock_log.mark_failed.assert_called()
    # 失败被记 warning（不再静默吞）
    assert any("mark_failed" in r.message for r in caplog.records)
    assert "failed=1" in msg


def test_tick_time_budget_stops_immediately_when_zero():
    """interval_minutes=0 → 预算 0，不处理任何锚点（时间检查在合成前）"""
    cfg = MagicMock()
    cfg.enabled = True
    cfg.anchor_types = ["correction"]
    cfg.grounding_top_k = 5
    cfg.target_kb = None
    cfg.interval_minutes = 0  # 预算 0
    fake_anchor = {
        "fragment_id": 1,
        "session_id": "s",
        "timestamp": "t",
        "content": "c",
        "transcript_path": "/x",
        "metadata": {},
    }
    with (
        patch("jfox.gem_synth.loop.get_global_config_manager") as gm,
        patch("jfox.gem_synth.loop.find_anchors", return_value=[fake_anchor]),
        patch(
            "jfox.gem_synth.loop.synthesize_anchor",
            return_value={"candidate_note_id": "c1"},
        ) as sa,
    ):
        gm.return_value.get_gem_synthesis_config.return_value = cfg
        msg = _tick_once(threading.Event())
    sa.assert_not_called()  # 预算 0 → 一个都不处理
    assert isinstance(msg, str)


def test_tick_processes_one_at_a_time_until_empty():
    """预算内逐个处理（limit=1），直到无锚点"""
    cfg = MagicMock()
    cfg.enabled = True
    cfg.anchor_types = ["correction"]
    cfg.grounding_top_k = 5
    cfg.target_kb = None
    cfg.interval_minutes = 30  # 充足预算
    call_count = {"n": 0}

    def fake_find(*a, **k):
        call_count["n"] += 1
        # 前 2 次返回锚点，第 3 次返回空（无积压）
        if call_count["n"] <= 2:
            return [
                {
                    "fragment_id": call_count["n"],
                    "session_id": "s",
                    "timestamp": "t",
                    "content": "c",
                    "transcript_path": "/x",
                    "metadata": {},
                }
            ]
        return []

    with (
        patch("jfox.gem_synth.loop.get_global_config_manager") as gm,
        patch("jfox.gem_synth.loop.find_anchors", side_effect=fake_find),
        patch(
            "jfox.gem_synth.loop.synthesize_anchor",
            return_value={"candidate_note_id": "c"},
        ),
    ):
        gm.return_value.get_gem_synthesis_config.return_value = cfg
        msg = _tick_once(threading.Event())
    assert "success=2" in msg
