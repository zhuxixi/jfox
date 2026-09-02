"""strict grounding + prompt history evidence 测试。"""

from unittest.mock import MagicMock, patch

import pytest

from jfox.prompts.grounding import (
    build_prompt_history,
    fetch_judgment_grounding,
    fetch_unresolved_evidence,
)

pytestmark = [pytest.mark.unit, pytest.mark.fast]


# ---------------------------------------------------------------------------
# fetch_judgment_grounding
# ---------------------------------------------------------------------------


def _search_result(note_id="n1", title="笔记A", doc_type="permanent", content="正文内容"):
    return {
        "id": note_id,
        "document": content,
        "metadata": {"id": note_id, "title": title, "type": doc_type},
        "score": 0.85,
    }


def test_grounding_returns_only_permanent():
    with patch("jfox.prompts.grounding.HybridSearchEngine") as MockEngine:
        mock = MockEngine.return_value
        mock.search.return_value = [
            _search_result("n1", "permanent笔记", "permanent", "内容A"),
            _search_result("n2", "candidate笔记", "candidate", "内容B"),
            _search_result("n3", "fleeting笔记", "fleeting", "内容C"),
        ]
        result = fetch_judgment_grounding("查询", top_k=5)
        # 只留 permanent
        assert len(result.evidence) == 1
        assert result.evidence[0]["id"] == "n1"
        assert result.evidence[0]["title"] == "permanent笔记"
        assert result.unavailable is False


def test_grounding_empty_query_returns_empty():
    result = fetch_judgment_grounding("")
    assert result.evidence == []
    assert result.unavailable is False  # 空 query 是合法空，不是异常


def test_grounding_no_results_is_valid_empty():
    with patch("jfox.prompts.grounding.HybridSearchEngine") as MockEngine:
        mock = MockEngine.return_value
        mock.search.return_value = []
        result = fetch_judgment_grounding("没有覆盖的话题")
        assert result.evidence == []
        assert result.unavailable is False  # 空结果≠异常


def test_grounding_search_failure_marks_unavailable():
    with patch("jfox.prompts.grounding.HybridSearchEngine") as MockEngine:
        MockEngine.side_effect = RuntimeError("chromadb down")
        result = fetch_judgment_grounding("查询")
        assert result.unavailable is True
        assert result.evidence == []


def test_grounding_excludes_unresolved_tag_notes():
    """带 unresolved-problems 标签的清单笔记不进已解决 grounding。"""
    unresolved_result = _search_result("n9", "待解决问题清单", "permanent", "清单内容")
    unresolved_result["metadata"]["tags"] = ["unresolved-problems", "other"]
    with patch("jfox.prompts.grounding.HybridSearchEngine") as MockEngine:
        mock = MockEngine.return_value
        mock.search.return_value = [
            _search_result("n1", "正常笔记", "permanent", "内容A"),
            unresolved_result,
        ]
        result = fetch_judgment_grounding("查询")
        ids = [e["id"] for e in result.evidence]
        assert "n1" in ids
        assert "n9" not in ids


def test_grounding_content_respects_max_chars():
    with patch("jfox.prompts.grounding.HybridSearchEngine") as MockEngine:
        mock = MockEngine.return_value
        mock.search.return_value = [
            _search_result("n1", "长文", "permanent", "x" * 10000),
        ]
        result = fetch_judgment_grounding("查询", max_chars=100)
        assert len(result.evidence[0]["content"]) <= 100


# ---------------------------------------------------------------------------
# fetch_unresolved_evidence
# ---------------------------------------------------------------------------


def test_unresolved_evidence_reads_active_items():
    store = MagicMock()
    store.list_unresolved.return_value = [
        {"kb_name": "default", "prompt_id": 42, "state": "active", "note_id": "note-1"}
    ]
    items = fetch_unresolved_evidence(store, "default")
    assert len(items) == 1
    assert items[0]["prompt_id"] == 42
    store.list_unresolved.assert_called_once_with("default", state="active")


# ---------------------------------------------------------------------------
# build_prompt_history
# ---------------------------------------------------------------------------


def _make_store_with_prompts(tmp_path, prompts_with_sessions):
    """构造一个有 prompt 数据的 PromptStore。"""
    from jfox.prompts.store import PromptStore

    store = PromptStore(db_path=tmp_path / "fragments.db")
    for i, (session_id, prompt) in enumerate(prompts_with_sessions):
        store.insert_prompt(
            {
                "hook_event_name": "UserPromptSubmit",
                "session_id": session_id,
                "prompt": prompt,
            },
            source_key=f"capture:c{i}",
        )
    return store


def test_history_includes_same_session_prior_prompts(tmp_path):
    store = _make_store_with_prompts(
        tmp_path,
        [
            ("s1", "第一问"),
            ("s1", "第二问"),
            ("s1", "当前问题"),
            ("s2", "其他session的问题"),
        ],
    )
    history = build_prompt_history(store, prompt_id=3, session_id="s1", limit=10)
    # 当前 session 之前的 prompt 在历史里
    prompt_texts = [h["prompt"] for h in history]
    assert "第一问" in prompt_texts
    assert "第二问" in prompt_texts
    # 当前问题自身不在
    assert "当前问题" not in prompt_texts


def test_history_includes_hash_matched_from_other_session(tmp_path):
    """规范化 hash 相同的历史 prompt（其他 session）也应出现。"""
    store = _make_store_with_prompts(
        tmp_path,
        [
            ("s-old", "  完全相同的问题  "),  # 首尾空白不同 → hash 相同
            ("s1", "完全相同的问题"),
        ],
    )
    history = build_prompt_history(store, prompt_id=2, session_id="s1", limit=10)
    prompt_texts = [h["prompt"] for h in history]
    assert "  完全相同的问题  " in prompt_texts  # 其他 session 的相同 prompt


def test_history_respects_limit(tmp_path):
    store = _make_store_with_prompts(
        tmp_path,
        [("s1", f"历史问题{i}") for i in range(10)] + [("s1", "当前")],
    )
    history = build_prompt_history(store, prompt_id=11, session_id="s1", limit=3)
    assert len(history) <= 3


def test_history_empty_for_first_prompt(tmp_path):
    store = _make_store_with_prompts(tmp_path, [("s1", "唯一的")])
    history = build_prompt_history(store, prompt_id=1, session_id="s1", limit=10)
    assert history == []
