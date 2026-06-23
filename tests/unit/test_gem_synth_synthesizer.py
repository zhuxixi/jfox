"""synthesizer 编排测试（mock transcript/grounding/llm/save）。"""

from unittest.mock import MagicMock, patch

from jfox.gem_synth.store import SynthesisLog
from jfox.gem_synth.synthesizer import synthesize_anchor


def _anchor(frag_id, tmp_path):
    return {
        "fragment_id": frag_id,
        "session_id": "s1",
        "timestamp": "2026-06-21 14:30:00",
        "content": "不对，应该用 patch",
        "transcript_path": str(tmp_path / "t.jsonl"),
        "metadata": {"session_id": "s1"},
    }


def test_synthesize_anchor_produces_candidate_note(tmp_path):
    log = SynthesisLog(db_path=tmp_path / "syn.db")
    fake_llm = {
        "title": "用 patch 而非 sed",
        "content": "## 知识\n改文件优先 patch",
        "confidence": 0.85,
        "knowledge_type": "procedural",
        "grounded_by": ["补丁规范"],
    }
    with (
        patch("jfox.gem_synth.synthesizer.extract_turn_around", return_value="上下文X"),
        patch(
            "jfox.gem_synth.synthesizer.fetch_grounding",
            return_value=[{"title": "补丁规范", "content": "y"}],
        ),
        patch("jfox.gem_synth.synthesizer.synthesize_with_llm", return_value=fake_llm),
        patch(
            "jfox.gem_synth.synthesizer._save_candidate_note",
            return_value="candidate_20260621143000",
        ),
    ):
        result = synthesize_anchor(
            _anchor(42, tmp_path), log=log, cfg=MagicMock(grounding_top_k=5), kb="default"
        )
    assert result is not None
    assert result["candidate_note_id"] == "candidate_20260621143000"
    assert result["title"] == "用 patch 而非 sed"
    assert log.is_processed(42) is True


def test_synthesize_anchor_skips_when_llm_returns_none(tmp_path):
    log = SynthesisLog(db_path=tmp_path / "syn.db")
    with (
        patch("jfox.gem_synth.synthesizer.extract_turn_around", return_value="上下文"),
        patch("jfox.gem_synth.synthesizer.fetch_grounding", return_value=[]),
        patch("jfox.gem_synth.synthesizer.synthesize_with_llm", return_value=None),
    ):
        result = synthesize_anchor(
            _anchor(43, tmp_path), log=log, cfg=MagicMock(grounding_top_k=5), kb="default"
        )
    assert result is None
    assert log.is_processed(43) is False  # 失败不记账，下轮可重试


def test_synthesize_anchor_skips_when_no_transcript(tmp_path):
    log = SynthesisLog(db_path=tmp_path / "syn.db")
    a = _anchor(44, tmp_path)
    a["transcript_path"] = None
    assert synthesize_anchor(a, log=log, cfg=MagicMock(grounding_top_k=5), kb="default") is None


def test_synthesize_handles_non_numeric_confidence(tmp_path):
    """LLM 返回非数值 confidence 不应崩（safe float 回退）"""
    from jfox.gem_synth.synthesizer import _safe_float

    assert _safe_float("high") == 0.0
    assert _safe_float(0.85) == 0.85
    assert _safe_float(None) == 0.0
    assert _safe_float("0.9") == 0.9
