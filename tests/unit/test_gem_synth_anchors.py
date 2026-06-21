"""锚点查询：从 fragments.db 取高信号未处理锚点。"""

from jfox.fragment.store import FragmentStore
from jfox.gem_synth.anchors import find_anchors
from jfox.gem_synth.store import SynthesisLog


def _seed_fragments(tmp_path):
    store = FragmentStore(db_path=tmp_path / "fragments.db")
    correction = store.insert("s1", "correction", "UserPromptSubmit", "不对，应该用 patch", {})
    decision = store.insert("s1", "decision", "UserPromptSubmit", "我决定用方案 A", {})
    ask = store.insert(
        "s1",
        "user_input",
        "PostToolUse",
        "AskUserQuestion",
        {"tool_name": "AskUserQuestion"},
    )
    store.insert("s1", "user_input", "UserPromptSubmit", "继续", {})
    store.insert("s1", "tool_call", "PostToolUse", "done", {})
    store.close()
    return correction, decision, ask


def test_find_anchors_returns_high_signal(tmp_path):
    correction, decision, ask = _seed_fragments(tmp_path)
    log = SynthesisLog(db_path=tmp_path / "syn.db")
    ids = [
        a["fragment_id"]
        for a in find_anchors(
            fragments_db=tmp_path / "fragments.db",
            log=log,
            anchor_types=["correction", "decision", "ask_user_question"],
        )
    ]
    assert {correction, decision, ask} <= set(ids)


def test_find_anchors_excludes_processed(tmp_path):
    correction, decision, ask = _seed_fragments(tmp_path)
    log = SynthesisLog(db_path=tmp_path / "syn.db")
    log.mark_processed(correction, "c1")
    ids = [
        a["fragment_id"]
        for a in find_anchors(
            fragments_db=tmp_path / "fragments.db",
            log=log,
            anchor_types=["correction", "decision", "ask_user_question"],
        )
    ]
    assert correction not in ids and decision in ids


def test_find_anchors_has_transcript_path(tmp_path):
    _seed_fragments(tmp_path)
    log = SynthesisLog(db_path=tmp_path / "syn.db")
    store = FragmentStore(db_path=tmp_path / "fragments.db")
    store.insert(
        "s1",
        "correction",
        "UserPromptSubmit",
        "x",
        {"transcript_path": "/tmp/t.jsonl", "session_id": "s1"},
    )
    store.close()
    anchors = find_anchors(
        fragments_db=tmp_path / "fragments.db", log=log, anchor_types=["correction"]
    )
    assert any(a.get("transcript_path") for a in anchors)
