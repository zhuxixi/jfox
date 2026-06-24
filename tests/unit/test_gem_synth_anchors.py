"""锚点查询：从 fragments.db 取高信号未处理锚点。"""

from jfox.fragment.store import FragmentStore
from jfox.gem_synth.anchors import count_anchors, find_anchors
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


def test_count_anchors(tmp_path):
    """count_anchors 返回锚点总数（不区分是否已处理）。"""
    store = FragmentStore(db_path=tmp_path / "f.db")
    store.insert("s1", "correction", "UserPromptSubmit", "不对", {})
    store.insert("s1", "decision", "UserPromptSubmit", "我决定", {})
    store.insert("s1", "user_input", "UserPromptSubmit", "hi", {})  # 非锚点
    store.close()
    log = SynthesisLog(db_path=tmp_path / "syn.db")
    n = count_anchors(
        fragments_db=tmp_path / "f.db",
        anchor_types=["correction", "decision", "ask_user_question"],
    )
    assert n == 2
    log.close()


def test_count_anchors_empty_anchor_types(tmp_path):
    """空 anchor_types 应回退为 0，不发 SQL（避免空 WHERE 拉全表）。"""
    store = FragmentStore(db_path=tmp_path / "f.db")
    store.insert("s1", "correction", "UserPromptSubmit", "不对", {})
    store.close()
    assert count_anchors(fragments_db=tmp_path / "f.db", anchor_types=[]) == 0
