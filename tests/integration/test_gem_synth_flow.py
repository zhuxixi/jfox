"""端到端：真实 transcript + fragments → 合成 → candidate 笔记。

标记 integration：依赖真实 daemon + claude 二进制 + 模型。
用户手动跑：uv run pytest tests/integration/test_gem_synth_flow.py -v -m integration
前置：jfox config set gem_synthesis.enabled true；daemon restart。
"""

import pytest

pytestmark = pytest.mark.integration


def test_synthesize_one_anchor_produces_candidate(tmp_path):
    """用真实 fragment + 临时 transcript，跑 synthesizer 全链路（含真 claude 调用）。"""
    from jfox.fragment.store import FragmentStore
    from jfox.gem_synth.store import SynthesisLog
    from jfox.gem_synth.synthesizer import synthesize_anchor
    from jfox.global_config import get_global_config_manager

    transcript = tmp_path / "t.jsonl"
    transcript.write_text(
        '{"type":"user","message":{"role":"user","content":"不对，这里应该用 patch 而不是 sed"},"timestamp":"2026-06-21T06:25:00","uuid":"u1"}\n'
        '{"type":"assistant","message":{"role":"assistant","content":[{"type":"text","text":"好的，改用 patch"}]},"timestamp":"2026-06-21T06:25:10","uuid":"a1"}\n',
        encoding="utf-8",
    )
    fstore = FragmentStore(db_path=tmp_path / "frag.db")
    fid = fstore.insert(
        "s-test",
        "correction",
        "UserPromptSubmit",
        "不对，这里应该用 patch 而不是 sed",
        {"transcript_path": str(transcript), "session_id": "s-test"},
    )
    fstore.close()

    anchor = {
        "fragment_id": fid,
        "session_id": "s-test",
        "timestamp": "2026-06-21 06:25:00",
        "content": "不对，这里应该用 patch 而不是 sed",
        "transcript_path": str(transcript),
        "metadata": {"transcript_path": str(transcript)},
    }
    log = SynthesisLog(db_path=tmp_path / "syn.db")
    cfg = get_global_config_manager().get_gem_synthesis_config()
    if not cfg.enabled:
        pytest.skip(
            "gem_synthesis 未启用；先 `jfox config set gem_synthesis.enabled true` 并 daemon restart"
        )

    result = synthesize_anchor(anchor, log=log, cfg=cfg, kb=None)
    assert result is not None
    assert result["candidate_note_id"]
    assert log.is_processed(fid)
