"""锚点查询：从 fragments.db 取高信号未处理锚点。"""

import sqlite3

from jfox.fragment.store import FragmentStore
from jfox.gem_synth.anchors import count_anchors, find_anchors
from jfox.gem_synth.store import SynthesisLog


def _corrupt_metadata(db_path, fragment_id, bad_value="this is NOT valid json"):
    """直接把某行的 metadata_json 改成非法 JSON（模拟历史脏数据/写入中断）。"""
    con = sqlite3.connect(str(db_path))
    con.execute(
        "UPDATE session_fragments SET metadata_json = ? WHERE fragment_id = ?",
        (bad_value, fragment_id),
    )
    con.commit()
    con.close()


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


def test_find_anchors_skips_clustered_processed_and_returns_unprocessed(tmp_path):
    """已处理锚点集中在低 fragment_id 时，find_anchors(limit=1) 仍须返回未处理的（#290）。

    回归根因：旧实现 `LIMIT limit*3` 只取前几条，若前 3 条全是已处理的 → Python 侧
    filter_unprocessed 全滤掉 → 返回 0，哪怕后面还有未处理锚点。daemon 循环用 limit=1，
    每 tick 都取到这 3 条已处理的 → 永远返回 0 → 空转、不合成。
    修法：把"已处理"过滤下推到 SQL（NOT IN），让 LIMIT 直接作用在未处理锚点上。
    """
    store = FragmentStore(db_path=tmp_path / "f.db")
    # 前 3 条锚点（低 fragment_id）会被标记已处理；第 4 条未处理
    a1 = store.insert("s", "correction", "UserPromptSubmit", "纠1", {})
    a2 = store.insert("s", "correction", "UserPromptSubmit", "纠2", {})
    a3 = store.insert("s", "correction", "UserPromptSubmit", "纠3", {})
    a4 = store.insert("s", "correction", "UserPromptSubmit", "纠4", {})
    store.close()

    log = SynthesisLog(db_path=tmp_path / "syn.db")
    log.mark_processed(a1, "c1")
    log.mark_processed(a2, "c2")
    log.mark_processed(a3, "c3")

    # limit=1：旧实现 LIMIT 3 取 a1/a2/a3 全已处理 → 0；修后须跳过它们返回 a4
    anchors = find_anchors(
        fragments_db=tmp_path / "f.db", log=log, anchor_types=["correction"], limit=1
    )
    assert len(anchors) == 1
    assert anchors[0]["fragment_id"] == a4
    log.close()


def test_find_anchors_tolerates_malformed_metadata_json(tmp_path):
    """session_fragments 含非法 JSON 的 metadata_json 行时，find_anchors/count_anchors
    都不应崩——坏行跳过、合法 ask_user_question 照常返回/计数。

    回归 cc R2#1：ask_user_question 筛选从 LIKE 改 json_extract 后，json_extract 对非法
    JSON 抛 OperationalError，WHERE 中任一行非法即整查询崩 → status 崩 / daemon 静默阻塞。
    """
    store = FragmentStore(db_path=tmp_path / "fragments.db")
    ask = store.insert(
        "s1", "user_input", "PostToolUse", "AskUserQuestion", {"tool_name": "AskUserQuestion"}
    )
    bad_ask = store.insert("s1", "user_input", "PostToolUse", "x", {"tool_name": "AskUserQuestion"})
    store.close()
    _corrupt_metadata(tmp_path / "fragments.db", bad_ask)

    log = SynthesisLog(db_path=tmp_path / "syn.db")
    # find_anchors 不应抛 OperationalError；坏行跳过，合法 ask 返回
    ids = [
        a["fragment_id"]
        for a in find_anchors(
            fragments_db=tmp_path / "fragments.db", log=log, anchor_types=["ask_user_question"]
        )
    ]
    assert ask in ids
    assert bad_ask not in ids
    # count_anchors 也不应抛（status 命令用）
    assert count_anchors(tmp_path / "fragments.db", ["ask_user_question"]) == 1
    log.close()


def test_find_anchors_tolerates_malformed_metadata_on_correction(tmp_path):
    """correction 行的 metadata_json 非法时，find_anchors 不应崩（json.loads 降级 {}）。

    correction/decision 行不走 json_valid 守卫（按 fragment_type 选），故 line 69 的
    json.loads 需独立容忍，否则坏 metadata 同样让整查询崩。
    """
    store = FragmentStore(db_path=tmp_path / "fragments.db")
    corr = store.insert("s1", "correction", "UserPromptSubmit", "不对", {"ok": 1})
    store.close()
    _corrupt_metadata(tmp_path / "fragments.db", corr, bad_value="bad json")

    log = SynthesisLog(db_path=tmp_path / "syn.db")
    # 不应抛 json.JSONDecodeError；降级 {} 后 correction 仍返回（transcript_path=None）
    anchors = find_anchors(
        fragments_db=tmp_path / "fragments.db", log=log, anchor_types=["correction"]
    )
    assert corr in [a["fragment_id"] for a in anchors]
    log.close()
