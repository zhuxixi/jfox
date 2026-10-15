"""
测试类型: 单元测试
目标功能: wiki-link 候选契约 split_wiki_target / extract_wiki_link_targets（issue #458）
预估耗时: <1 秒

不依赖真实知识库与 embedding；纯函数断言。
"""

from unittest.mock import MagicMock, patch

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


def _make_meta(note_id: str, title: str):
    meta = MagicMock()
    meta.id = note_id
    meta.title = title
    return meta


def _make_index(notes):
    """notes: List[Tuple[id, title]]，构造 mock NoteIndex（沿用 test_wiki_link_resolution 模式）"""

    def _find_by_id(nid):
        for nid_, title in notes:
            if nid_ == nid:
                return _make_meta(nid_, title)
        return None

    def _find_by_title(title):
        tl = title.lower()
        for nid_, t in notes:
            if t.lower() == tl:
                return _make_meta(nid_, t)
        return None

    idx = MagicMock()
    idx.find_by_id.side_effect = _find_by_id
    idx.find_by_title.side_effect = _find_by_title
    idx.get_all_meta.return_value = [_make_meta(i, t) for i, t in notes]
    return idx


class TestResolveLinkTarget:
    """候选顺序解析（spec 回归用例清单⑤–⑩）"""

    def test_full_text_exact_hit(self):
        """⑤ 完整原文精确命中"""
        from jfox.cli import resolve_link_target

        notes = [("20260101000001", "A#B"), ("20260101000002", "A")]
        with patch("jfox.note_index.get_note_index", return_value=_make_index(notes)):
            assert resolve_link_target(["A#B", "A"]) == "20260101000001"

    def test_prefix_exact_hit_when_full_misses(self):
        """⑥ 完整原文不中、前缀精确命中（锚点语义保留）"""
        from jfox.cli import resolve_link_target

        notes = [("20260101000002", "A")]
        with patch("jfox.note_index.get_note_index", return_value=_make_index(notes)):
            assert resolve_link_target(["A#B", "A"]) == "20260101000002"

    def test_full_text_substring_hit(self):
        """⑦ 两者都不中、完整原文子串命中（缩写标题链接不回归）"""
        from jfox.cli import resolve_link_target

        notes = [("20260101000003", "Issue #81 执行计划 — 防崩溃 + 断点续跑（任务拆分与优先级）")]
        with patch("jfox.note_index.get_note_index", return_value=_make_index(notes)):
            assert resolve_link_target(["Issue #81 执行计划", "Issue"]) == "20260101000003"

    def test_prefix_substring_must_not_match(self):
        """⑧ 前缀能子串命中、完整原文不能 → 必须返回 None（本 spec 的核心行为变更）"""
        from jfox.cli import resolve_link_target

        # 完整原文 "Issue #81 执行计划" 不是任何标题的子串；前缀 "Issue" 是
        notes = [("20260101000004", "某条标题里含 Issue 字样")]
        with patch("jfox.note_index.get_note_index", return_value=_make_index(notes)):
            assert resolve_link_target(["Issue #81 执行计划", "Issue"]) is None

    def test_all_miss_returns_none(self):
        """⑨ 全不中 → None（悬空路径）"""
        from jfox.cli import resolve_link_target

        with patch("jfox.note_index.get_note_index", return_value=_make_index([])):
            assert resolve_link_target(["不存在的东西"]) is None

    def test_real_world_hash_truncation_case(self):
        """⑩ #458 评论区实测复现形态：真目标 vs 干扰笔记"""
        from jfox.cli import resolve_link_target

        title = "zima-blue-cli #213：执行历史缺 token/cost 账本（usage 采集）"
        noise = "改 zima-blue-cli 仓库根 CLAUDE.md 前怎么确认不破坏测试"
        notes = [("202609030803256065", title), ("202609141007301934", noise)]
        with patch("jfox.note_index.get_note_index", return_value=_make_index(notes)):
            assert resolve_link_target([title, "zima-blue-cli #213"]) == "202609030803256065"

    def test_candidates_case_insensitive_exact_title(self):
        """⑪ 候选比较须 casefold（test_note_index.py:340 契约）"""
        from jfox.cli import resolve_link_target

        notes = [("20260101000005", "SomeTITLE")]
        with patch("jfox.note_index.get_note_index", return_value=_make_index(notes)):
            assert resolve_link_target(["sometitle#x", "sometitle"]) == "20260101000005"
