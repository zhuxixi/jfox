"""
测试类型: 单元测试
目标功能: wiki-link 候选契约 split_wiki_target / extract_wiki_link_targets（issue #458）
预估耗时: <1 秒

不依赖真实知识库与 embedding；纯函数断言。
"""

from jfox.note_index import extract_wiki_link_targets, split_wiki_target


class TestSplitWikiTarget:
    """候选拆分（spec 回归用例清单①–④）"""

    def test_hash_title_returns_full_then_prefix(self):
        """① 含 # 时返回 [完整原文, 前缀]"""
        assert split_wiki_target("A#B") == ["A#B", "A"]

    def test_no_hash_single_candidate(self):
        """② 无 # 时单候选"""
        assert split_wiki_target("A") == ["A"]

    def test_alias_stripped_before_anchor(self):
        """③ 先剥 alias 再切锚点"""
        assert split_wiki_target("A#B|C") == ["A#B", "A"]

    def test_empty_prefix_no_empty_candidate(self):
        """④ 空前缀不得产生空候选"""
        assert split_wiki_target("#B") == ["#B"]


class TestExtractWikiLinkTargets:
    """每个链接一组候选，顺序即优先级"""

    def test_multiple_links(self):
        text = "见 [[A#B]] 与 [[C]]"
        assert extract_wiki_link_targets(text) == [["A#B", "A"], ["C"]]

    def test_real_title_with_hash_keeps_full_text(self):
        """#458 形态：完整标题含 #，完整原文必须是第一候选"""
        title = "jfox 增量索引修复方案（#387）：verify 差集 + 单条修复替代日常全量 rebuild"
        assert extract_wiki_link_targets(f"见 [[{title}]]")[0][0] == title
