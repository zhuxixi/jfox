"""grounding：检索 permanent 笔记 top-K（mock search，不加载模型）。"""

from unittest.mock import patch

from jfox.gem_synth.grounding import fetch_grounding


def test_fetch_grounding_returns_top_k():
    # 带 metadata.type=permanent 以通过收紧后的 post-filter（旧宽松 None 分支已移除）
    fake = [
        {
            "title": "笔记A",
            "content": "内容A",
            "id": "1",
            "score": 0.9,
            "metadata": {"type": "permanent"},
        },
        {
            "title": "笔记B",
            "content": "内容B",
            "id": "2",
            "score": 0.7,
            "metadata": {"type": "permanent"},
        },
    ]
    with patch("jfox.gem_synth.grounding.HybridSearchEngine") as Mock:
        inst = Mock.return_value
        inst.search.return_value = fake
        out = fetch_grounding("锚点", top_k=2)
    assert [g["title"] for g in out] == ["笔记A", "笔记B"]
    inst.search.assert_called_once()
    _, kwargs = inst.search.call_args
    assert kwargs.get("note_type") == "permanent"


def test_fetch_grounding_empty_query_returns_empty():
    with patch("jfox.gem_synth.grounding.HybridSearchEngine"):
        assert fetch_grounding("", top_k=5) == []


def test_fetch_grounding_handles_exception():
    with patch("jfox.gem_synth.grounding.HybridSearchEngine") as Mock:
        Mock.return_value.search.side_effect = RuntimeError("boom")
        assert fetch_grounding("x", top_k=5) == []


def test_fetch_grounding_filters_out_non_permanent():
    """post-filter：只保留 permanent 笔记（BM25 路径不过滤 note_type）"""
    fake = [
        {"title": "永久A", "content": "cA", "id": "1", "metadata": {"type": "permanent"}},
        {"title": "临时B", "content": "cB", "id": "2", "metadata": {"type": "fleeting"}},
    ]
    with patch("jfox.gem_synth.grounding.HybridSearchEngine") as Mock:
        Mock.return_value.search.return_value = fake
        out = fetch_grounding("x", top_k=5)
    titles = [g["title"] for g in out]
    assert "永久A" in titles and "临时B" not in titles


def test_fetch_grounding_drops_missing_type_metadata():
    """cc#6：收紧 post-filter 后，缺失 type 元数据的结果也被剔除。

    旧宽松分支（type in (None, "permanent")）会放行无 type 的结果，可能混入
    fleeting/literature（元数据不全）；现严格要求 type == 'permanent'。
    """
    fake = [
        {"title": "无类型A", "content": "cA", "id": "1"},  # 无 metadata.type
        {"title": "永久B", "content": "cB", "id": "2", "metadata": {"type": "permanent"}},
    ]
    with patch("jfox.gem_synth.grounding.HybridSearchEngine") as Mock:
        Mock.return_value.search.return_value = fake
        out = fetch_grounding("x", top_k=5)
    titles = [g["title"] for g in out]
    assert "永久B" in titles and "无类型A" not in titles
