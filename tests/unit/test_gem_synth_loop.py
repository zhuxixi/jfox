"""gem_synth 循环：_tick_once 编排（mock 各组件）。"""

import threading
from unittest.mock import patch, MagicMock

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
    with (
        patch("jfox.gem_synth.loop.get_global_config_manager") as gm,
        patch(
            "jfox.gem_synth.loop.find_anchors",
            return_value=[
                {
                    "fragment_id": 1,
                    "session_id": "s",
                    "timestamp": "t",
                    "content": "c",
                    "transcript_path": "/x",
                    "metadata": {},
                }
            ],
        ) as fa,
        patch(
            "jfox.gem_synth.loop.synthesize_anchor",
            return_value={"candidate_note_id": "c1", "title": "T", "confidence": 0.8},
        ) as sa,
    ):
        gm.return_value.get_gem_synthesis_config.return_value = cfg
        msg = _tick_once(threading.Event())
    assert "1" in msg  # 处理了 1 个
    sa.assert_called_once()


def test_tick_synthesize_exception_does_not_crash():
    cfg = MagicMock()
    cfg.enabled = True
    cfg.anchor_types = ["correction"]
    cfg.grounding_top_k = 5
    cfg.target_kb = None
    with (
        patch("jfox.gem_synth.loop.get_global_config_manager") as gm,
        patch(
            "jfox.gem_synth.loop.find_anchors",
            return_value=[
                {
                    "fragment_id": 1,
                    "session_id": "s",
                    "timestamp": "t",
                    "content": "c",
                    "transcript_path": "/x",
                    "metadata": {},
                }
            ],
        ),
        patch("jfox.gem_synth.loop.synthesize_anchor", side_effect=RuntimeError("boom")),
    ):
        gm.return_value.get_gem_synthesis_config.return_value = cfg
        msg = _tick_once(threading.Event())  # 不应抛
    assert isinstance(msg, str)
