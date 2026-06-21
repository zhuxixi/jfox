"""grounding：检索 permanent 笔记 top-K（mock search，不加载模型）。"""

from unittest.mock import patch

from jfox.gem_synth.grounding import fetch_grounding


def test_fetch_grounding_returns_top_k():
    fake = [
        {"title": "笔记A", "content": "内容A", "id": "1", "score": 0.9},
        {"title": "笔记B", "content": "内容B", "id": "2", "score": 0.7},
    ]
    with patch("jfox.gem_synth.grounding.HybridSearchEngine") as Mock:
        inst = Mock.return_value
        inst.search.return_value = fake
        out = fetch_grounding("锚点", top_k=2, kb="default")
    assert [g["title"] for g in out] == ["笔记A", "笔记B"]
    inst.search.assert_called_once()
    _, kwargs = inst.search.call_args
    assert kwargs.get("note_type") == "permanent"


def test_fetch_grounding_empty_query_returns_empty():
    with patch("jfox.gem_synth.grounding.HybridSearchEngine"):
        assert fetch_grounding("", top_k=5, kb="default") == []


def test_fetch_grounding_handles_exception():
    with patch("jfox.gem_synth.grounding.HybridSearchEngine") as Mock:
        Mock.return_value.search.side_effect = RuntimeError("boom")
        assert fetch_grounding("x", top_k=5, kb="default") == []
