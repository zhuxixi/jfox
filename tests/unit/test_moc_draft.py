"""MOC 草稿构建与更新 diff 的纯逻辑测试。"""

from __future__ import annotations

import pytest

from jfox.moc.cluster import ClusterMember, ClusterSummary, OrphanNote
from jfox.moc.draft import (
    DraftGroup,
    MemberRemovalResult,
    MemberUpsertResult,
    MocCreateDraft,
    build_moc_draft,
    build_update_diff,
    filter_live_members,
    remove_member_lines,
    render_moc_content,
    upsert_member_line,
)


def _member(nid: str, title: str, degree: int = 2, sim: float = 0.8) -> ClusterMember:
    return ClusterMember(id=nid, title=title, link_degree=degree, mean_similarity=sim)


def _cluster() -> ClusterSummary:
    hub = _member("1", "Zima Hub", degree=10, sim=0.95)
    members = [
        hub,
        _member("2", "Zima CR Flow", degree=5, sim=0.9),
        _member("3", "Zima Gem V2", degree=3, sim=0.85),
        _member("4", "Zima MVP Plan", degree=1, sim=0.7),
        _member("5", "Misc Note", degree=0, sim=0.6),
    ]
    return ClusterSummary(size=len(members), members=members, hub=hub)


def _tags() -> dict:
    return {
        "1": ["zima", "cr"],
        "2": ["zima", "cr"],
        "3": ["zima", "gem"],
        "4": ["zima"],
        "5": ["misc"],
    }


def test_build_draft_groups_by_shared_tags():
    draft = build_moc_draft(_cluster(), _tags(), max_size=50)

    names = [g.name for g in draft.groups]
    assert names == ["zima", "cr", "其他"]  # zima: 4 条(>=min(2, 10%)), cr: 2 条; gem/misc 不成组
    zima_group = draft.groups[0]
    assert [m.id for m in zima_group.members][0] == "1"  # hub 置顶
    other_group = [g for g in draft.groups if g.name == "其他"][0]
    # 成员 4 带成组 tag zima，属 zima 组；「其他」仅余成员 5（misc）
    assert [m.id for m in other_group.members] == ["5"]


def test_build_draft_default_title_derives_from_hub():
    draft = build_moc_draft(_cluster(), _tags(), max_size=50)
    assert draft.title == "Zima Hub MOC"


def test_build_draft_title_override():
    draft = build_moc_draft(_cluster(), _tags(), max_size=50, title="我的主题")
    assert draft.title == "我的主题"


def test_build_draft_rejects_oversized_cluster():
    with pytest.raises(ValueError, match="exceeds --max-size"):
        build_moc_draft(_cluster(), _tags(), max_size=4)


def test_build_draft_includes_orphans():
    orphans = [OrphanNote("9", "Orphan A", True, True)]
    draft = build_moc_draft(_cluster(), _tags(), max_size=50, orphans=orphans)
    assert [o.id for o in draft.orphan_bucket] == ["9"]


def test_render_content_has_groups_orphans_and_recent_section():
    orphans = [OrphanNote("9", "Orphan A", True, True)]
    draft = build_moc_draft(_cluster(), _tags(), max_size=50, orphans=orphans)
    content = render_moc_content(draft)

    assert "## zima" in content
    assert "- [[1|Zima Hub]] — 10 links" in content
    assert "## 其他" in content
    assert "## 待归类" in content
    assert "- [[9|Orphan A]] — 0 links" in content
    assert "## 近期活动" in content


def test_render_content_uses_id_canonical_member_links():
    draft = build_moc_draft(_cluster(), _tags(), max_size=50)
    content = render_moc_content(draft)

    assert "- [[1|Zima Hub]] — 10 links" in content
    assert "- [[Zima Hub]] — 10 links" not in content


def test_render_content_uses_id_only_for_unsafe_titles():
    member = ClusterMember(id="1", title="Unsafe ]] title", link_degree=1, mean_similarity=0.8)
    draft = MocCreateDraft(title="Unsafe MOC", groups=[DraftGroup("misc", [member])])

    content = render_moc_content(draft)

    assert "- [[1]] — 1 links" in content
    assert "Unsafe ]] title" not in content


def test_render_content_uses_id_only_for_single_bracket_title():
    """单 `]`（非 `]]`）也会截断行识别：必须回退 [[ID]]（#505 CR issue-2）。"""
    member = ClusterMember(id="1", title="foo]bar", link_degree=2, mean_similarity=0.8)
    draft = MocCreateDraft(title="Bracket MOC", groups=[DraftGroup("misc", [member])])

    content = render_moc_content(draft)

    assert "- [[1]] — 2 links" in content
    assert "foo]bar" not in content


def test_member_row_roundtrip_with_single_bracket_title():
    """单 `]` 标题写入后：重复 upsert 不追加、remove 能删（幂等/自修复契约）。"""
    base = "## zima\n\n## 近期活动\n"

    first = upsert_member_line(base, "1", "foo]bar", ["zima"], None, legacy_title_unique=True)
    assert "[[1]]" in first.content
    assert "foo]bar" not in first.content

    second = upsert_member_line(
        first.content, "1", "foo]bar", ["zima"], None, legacy_title_unique=True
    )
    assert second.changed is False
    assert second.rows_added == 0
    assert second.had_existing_row is True

    removed = remove_member_lines(second.content, "1", "foo]bar", legacy_title_unique=True)
    assert removed.removed_rows == 1
    assert "[[1]]" not in removed.content


def test_update_diff_adds_new_and_removes_dead_links():
    cluster = _cluster()
    diff = build_update_diff(
        current_links=["1", "2", "99"],  # 99 已死
        cluster_members=cluster.members,
        existing_ids={"1", "2", "3", "4", "5"},
    )
    assert [m.id for m in diff.add] == ["3", "4", "5"]
    assert diff.remove == ["99"]
    assert diff.kept == 2


def test_update_diff_keeps_live_non_permanent_links():
    """live 但非 permanent 的链接不应被摘除（spec D7：死链仅已归档/不存在）。"""
    cluster = _cluster()
    diff = build_update_diff(
        current_links=["1", "2", "88"],  # 88 是 live 的 structure 笔记
        cluster_members=cluster.members,
        existing_ids={"1", "2", "3", "4", "5", "88"},  # 88 在 existing 集合
    )
    assert diff.remove == []  # 88 不是死链，不摘除
    assert diff.kept == 2


def test_update_diff_excludes_ghost_members_from_add():
    """簇成员不在 existing_ids（ghost，磁盘不存在）时不加入 add。"""
    cluster = _cluster()
    diff = build_update_diff(
        current_links=["1"],  # 只链了 1
        cluster_members=cluster.members,
        existing_ids={"1", "2", "3"},  # 4、5 磁盘不存在（ghost）
    )
    assert [m.id for m in diff.add] == ["2", "3"]  # 4、5 被排除
    assert diff.kept == 1


def test_filter_live_members_removes_ghost_members():
    """ghost 成员（不在 live_ids）被过滤，返回 warning。"""
    draft = build_moc_draft(_cluster(), _tags(), max_size=50)
    # 成员 3 和 5 不在 live_ids → 被过滤
    filtered, warnings = filter_live_members(draft, live_ids={"1", "2", "4"})

    all_member_ids = [m.id for g in filtered.groups for m in g.members]
    assert "3" not in all_member_ids
    assert "5" not in all_member_ids
    assert "1" in all_member_ids
    assert "2" in all_member_ids
    assert "4" in all_member_ids
    assert any("3" in w for w in warnings)
    assert any("5" in w for w in warnings)


def test_filter_live_members_drops_empty_groups():
    """整组被过滤后空 group 丢弃。"""
    draft = build_moc_draft(_cluster(), _tags(), max_size=50)
    # 只保留成员 1 → cr 组（成员 1,2）过滤后可能空
    filtered, _warnings = filter_live_members(draft, live_ids={"1"})
    for group in filtered.groups:
        assert len(group.members) > 0  # 无空组


def test_filter_live_members_filters_orphan_bucket():
    """孤儿桶里的 ghost 孤儿也被过滤。"""
    orphans = [OrphanNote("9", "Orphan A", True, True), OrphanNote("10", "Orphan B", True, True)]
    draft = build_moc_draft(_cluster(), _tags(), max_size=50, orphans=orphans)
    filtered, warnings = filter_live_members(draft, live_ids={"1", "2", "3", "4", "5", "9"})

    assert [o.id for o in filtered.orphan_bucket] == ["9"]
    assert any("10" in w for w in warnings)


def test_filter_live_members_recounts_total_members():
    """total_members 重算为剩余成员数。"""
    draft = build_moc_draft(_cluster(), _tags(), max_size=50)
    filtered, _warnings = filter_live_members(draft, live_ids={"1", "2", "3"})
    assert filtered.total_members == 3


# ---------------------------------------------------------------------------
# 单成员正文行 upsert / remove（spec §3.5 纯函数层）
# ---------------------------------------------------------------------------


def _doc(*lines: str) -> str:
    """按渲染格式拼一个 MOC 正文样本。"""
    return "\n".join(lines) + "\n"


@pytest.mark.parametrize(
    ("content", "tags", "group", "expected_group"),
    [
        ("## zima\n\n## 近期活动\n", ["zima"], None, "zima"),
        ("## zima\n\n## 近期活动\n", ["other"], None, "其他"),
        ("## zima\n\n## 近期活动\n", ["zima"], "manual", "manual"),
    ],
)
def test_upsert_selects_group_and_inserts_before_system_section(
    content, tags, group, expected_group
):
    result = upsert_member_line(
        content, "20260820000003", "New Note", tags, group, legacy_title_unique=True
    )
    assert result.resolved_group == expected_group
    assert "[[20260820000003|New Note]]" in result.content
    assert result.content.index("[[20260820000003|New Note]]") < result.content.index("## 近期活动")


def test_upsert_first_matching_group_in_body_order():
    """多个 tag 命中时取正文中第一个出现的普通组（body order）。"""
    content = _doc("## zima", "", "## cr", "", "## 近期活动", "")

    result = upsert_member_line(
        content, "2", "New Note", ["cr", "zima"], None, legacy_title_unique=True
    )

    assert result.resolved_group == "zima"


def test_upsert_tag_match_skips_reserved_group_names():
    """其他/待归类/近期活动不作为 tag 匹配目标；fallback 仍可用已有其他组。"""
    content = _doc("## 其他", "", "## 待归类", "", "## 近期活动", "")

    result = upsert_member_line(
        content, "2", "New Note", ["其他", "待归类", "近期活动"], None, legacy_title_unique=True
    )

    assert result.resolved_group == "其他"
    assert result.content.index("[[2|New Note]]") < result.content.index("## 待归类")


def test_upsert_existing_canonical_row_not_moved_or_duped():
    """已有 canonical 行（ID-only / ID+alias）时不搬组、不重复、不改别名；并存的 legacy 行保留。"""
    content = _doc(
        "## zima",
        "",
        "- [[7|Old Alias]] — 3 links",
        "",
        "## cr",
        "",
        "- [[7]]",
        "- [[Zima Hub]] — 9 links",
        "",
        "## 近期活动",
        "",
    )

    result = upsert_member_line(content, "7", "Zima Hub", ["zima"], None, legacy_title_unique=True)

    assert result.content == content
    assert result.had_existing_row is True
    assert result.changed is False
    assert result.rows_added == 0
    assert result.rows_canonicalized == 0
    assert result.ambiguous_legacy is False
    assert result.resolved_group == "zima"
    assert result.matched_groups == ("zima", "cr")


def test_upsert_unique_legacy_canonicalized_in_place():
    """唯一 legacy [[标题]] 行原地改写为 canonical，保留原组与行后缀，不额外插入。"""
    content = _doc(
        "## zima",
        "",
        "- [[Zima Hub]] — 10 links",
        "",
        "## cr",
        "",
        "- [[Zima Hub]] — 5 links",
        "",
        "## 近期活动",
        "",
    )
    expected = _doc(
        "## zima",
        "",
        "- [[1|Zima Hub]] — 10 links",
        "",
        "## cr",
        "",
        "- [[1|Zima Hub]] — 5 links",
        "",
        "## 近期活动",
        "",
    )

    result = upsert_member_line(content, "1", "Zima Hub", ["zima"], None, legacy_title_unique=True)

    assert result.content == expected
    assert result.rows_canonicalized == 2
    assert result.rows_added == 0
    assert result.changed is True
    assert result.had_existing_row is True
    assert result.ambiguous_legacy is False
    assert result.resolved_group == "zima"
    assert result.matched_groups == ("zima", "cr")


def test_upsert_ambiguous_legacy_appends_canonical_row():
    """标题歧义时不改写旧行，追加一条 canonical 行并置 ambiguous_legacy。"""
    content = _doc("## zima", "", "- [[Zima Hub]] — 2 links", "", "## 近期活动", "")
    expected = _doc(
        "## zima", "", "- [[Zima Hub]] — 2 links", "- [[1|Zima Hub]]", "", "## 近期活动", ""
    )

    result = upsert_member_line(content, "1", "Zima Hub", ["zima"], None, legacy_title_unique=False)

    assert result.content == expected
    assert result.ambiguous_legacy is True
    assert result.rows_added == 1
    assert result.rows_canonicalized == 0
    assert result.had_existing_row is False


def test_upsert_ambiguous_title_without_legacy_rows_plain_insert():
    """标题在全库不唯一但正文没有旧行：无歧义可报告，直接插入。"""
    content = _doc("## zima", "", "## 近期活动", "")

    result = upsert_member_line(
        content, "2", "Dup Title", ["zima"], None, legacy_title_unique=False
    )

    assert result.ambiguous_legacy is False
    assert result.rows_added == 1
    assert "- [[2|Dup Title]]" in result.content


def test_upsert_appends_after_last_member_row():
    """组内追加在最后一个非空行之后，保留尾部空行。"""
    content = _doc("## zima", "", "- [[1|A]] — 2 links", "", "## 近期活动", "")
    expected = _doc("## zima", "", "- [[1|A]] — 2 links", "- [[2|B]]", "", "## 近期活动", "")

    result = upsert_member_line(content, "2", "B", ["zima"], None, legacy_title_unique=True)

    assert result.content == expected


def test_upsert_new_group_after_last_ordinary_without_system_section():
    """无系统区段时新组追加在最后一个普通组之后。"""
    content = _doc("## zima", "", "- [[1|A]] — 2 links")
    expected = _doc("## zima", "", "- [[1|A]] — 2 links", "", "## 其他", "", "- [[2|B]]")

    result = upsert_member_line(content, "2", "B", ["other"], None, legacy_title_unique=True)

    assert result.content == expected
    assert result.resolved_group == "其他"


def test_upsert_creates_group_at_end_when_no_sections():
    """正文没有任何顶层组时在末尾创建组与成员行。"""
    content = "intro\n"
    expected = "intro\n\n## 其他\n\n- [[2|B]]\n"

    result = upsert_member_line(content, "2", "B", ["other"], None, legacy_title_unique=True)

    assert result.content == expected


def test_upsert_fenced_code_ignored():
    """fenced code block 内的伪标题/伪成员行不参与识别。"""
    content = _doc(
        "## zima",
        "",
        "- [[1|A]] — 2 links",
        "",
        "## 其他",
        "",
        "```text",
        "## fake",
        "",
        "- [[9|Ghost]] — 1 links",
        "```",
        "",
        "## 近期活动",
        "",
    )

    result = upsert_member_line(
        content, "9", "Ghost Note", ["other"], None, legacy_title_unique=True
    )

    assert result.had_existing_row is False
    assert "- [[9|Ghost Note]]" in result.content
    # 围栏内的旧行原样保留，未被认领
    assert result.content.count("[[9|Ghost]]") == 1
    assert result.content.index("```") < result.content.index("- [[9|Ghost Note]]")


def test_upsert_unsafe_newline_title_uses_id_only():
    """标题含换行时新行退化为 [[ID]]（补 \n 分支覆盖，Task 1 只测过 ]]）。"""
    content = _doc("## zima", "", "## 近期活动", "")

    result = upsert_member_line(
        content, "2", "Multi\nLine", ["zima"], None, legacy_title_unique=True
    )

    assert "- [[2]]\n" in result.content
    assert "[[2|" not in result.content


def test_upsert_hash_title_matches_legacy_exactly():
    """标题含 # 时按 raw 标题精确匹配 legacy 行，不走截断解析。"""
    content = _doc("## zima", "", "- [[Fix #387 note]] — 1 links", "", "## 近期活动", "")
    expected = _doc("## zima", "", "- [[1|Fix #387 note]] — 1 links", "", "## 近期活动", "")

    result = upsert_member_line(
        content, "1", "Fix #387 note", ["zima"], None, legacy_title_unique=True
    )

    assert result.content == expected
    assert result.rows_canonicalized == 1


def test_upsert_pipe_title_keeps_alias_form():
    """标题含 | 不影响目标解析，仍用 [[ID|标题]]。"""
    content = _doc("## zima", "", "## 近期活动", "")

    result = upsert_member_line(content, "2", "A|B", ["zima"], None, legacy_title_unique=True)

    assert "- [[2|A|B]]" in result.content


@pytest.mark.parametrize("bad_group", ["近期活动", "待归类"])
def test_upsert_rejects_reserved_group_names(bad_group):
    """系统区段名不允许作为 --group（CLI 层负责映射错误文案，纯函数先行拒绝）。"""
    with pytest.raises(ValueError):
        upsert_member_line("## zima\n", "2", "B", ["zima"], bad_group, legacy_title_unique=True)


@pytest.mark.parametrize("bad_group", ["", "   ", "a\nb"])
def test_upsert_rejects_blank_or_multiline_group(bad_group):
    with pytest.raises(ValueError):
        upsert_member_line("## zima\n", "2", "B", ["zima"], bad_group, legacy_title_unique=True)


def test_remove_deletes_canonical_rows_across_sections():
    """跨区段删除所有 ID 行；空普通组连标题删除；系统区段标题保留。"""
    content = _doc(
        "## zima", "", "- [[7|A]] — 1 links", "", "## 待归类", "", "- [[7]]", "", "## 近期活动", ""
    )
    expected = _doc("## 待归类", "", "## 近期活动", "")

    result = remove_member_lines(content, "7", "A", legacy_title_unique=True)

    assert result.content == expected
    assert result.removed_rows == 2
    assert result.removed_groups == ("zima", "待归类")
    assert result.changed is True
    assert result.ambiguous_legacy is False


def test_remove_unique_legacy_rows_deleted():
    """标题唯一时 legacy [[标题]] 行与 canonical 行一并删除。"""
    content = _doc(
        "## zima",
        "",
        "- [[Zima Hub]] — 5 links",
        "- [[7|Zima Hub]] — 3 links",
        "",
        "## 近期活动",
        "",
    )

    result = remove_member_lines(content, "7", "Zima Hub", legacy_title_unique=True)

    assert result.content == _doc("## 近期活动", "")
    assert result.removed_rows == 2
    assert result.removed_groups == ("zima",)


def test_remove_ambiguous_legacy_preserved():
    """标题歧义时 legacy 行保留并置 ambiguous_legacy；canonical 行照删。"""
    content = _doc(
        "## zima",
        "",
        "- [[Zima Hub]] — 5 links",
        "- [[7|Zima Hub]] — 3 links",
        "",
        "## 近期活动",
        "",
    )
    expected = _doc("## zima", "", "- [[Zima Hub]] — 5 links", "", "## 近期活动", "")

    result = remove_member_lines(content, "7", "Zima Hub", legacy_title_unique=False)

    assert result.content == expected
    assert result.ambiguous_legacy is True
    assert result.removed_rows == 1
    assert result.removed_groups == ("zima",)


def test_remove_without_title_leaves_legacy_rows():
    """title=None（目标笔记不存在）时只清 ID 行，不动任何标题行。"""
    content = _doc(
        "## zima",
        "",
        "- [[Zima Hub]] — 5 links",
        "- [[7|Zima Hub]] — 3 links",
        "",
        "## 近期活动",
        "",
    )
    expected = _doc("## zima", "", "- [[Zima Hub]] — 5 links", "", "## 近期活动", "")

    result = remove_member_lines(content, "7", None, legacy_title_unique=True)

    assert result.content == expected
    assert result.ambiguous_legacy is False


@pytest.mark.parametrize(
    ("label", "extra"),
    [
        ("prose", ["说明文字。"]),
        ("subheading", ["### 子主题"]),
        ("fence", ["```python", "print(1)", "```"]),
    ],
)
def test_remove_keeps_ordinary_group_with_extra_content(label, extra):
    """组体含说明文字/子标题/代码时只删行，保留组标题。"""
    content = _doc("## zima", "", *extra, "", "- [[7|A]] — 1 links", "", "## 近期活动", "")

    result = remove_member_lines(content, "7", "A", legacy_title_unique=True)

    assert "## zima" in result.content
    assert "- [[7|A]]" not in result.content
    for line in extra:
        assert line in result.content
    assert result.removed_groups == ("zima",)


def test_remove_never_deletes_system_section_headings():
    """待归类/近期活动区段内的行可删，标题永不删除。"""
    content = _doc("## 待归类", "", "- [[7|A]]", "", "## 近期活动", "")
    expected = _doc("## 待归类", "", "## 近期活动", "")

    result = remove_member_lines(content, "7", "A", legacy_title_unique=True)

    assert result.content == expected
    assert result.removed_groups == ("待归类",)


def test_remove_no_match_returns_unchanged():
    content = _doc("## zima", "", "- [[1|A]] — 2 links", "", "## 近期活动", "")

    result = remove_member_lines(content, "99", "Missing", legacy_title_unique=True)

    assert result.content == content
    assert result.changed is False
    assert result.removed_rows == 0
    assert result.removed_groups == ()
    assert result.ambiguous_legacy is False


def test_remove_fenced_code_rows_ignored():
    content = _doc("## zima", "", "```text", "- [[7|A]] — 1 links", "```", "", "## 近期活动", "")

    result = remove_member_lines(content, "7", "A", legacy_title_unique=True)

    assert result.content == content
    assert result.changed is False
    assert result.removed_rows == 0


def test_remove_duplicate_rows_in_same_group_counted_once_per_group():
    """同组重复行全部删除，removed_groups 去重。"""
    content = _doc("## zima", "", "- [[7|A]]", "- [[7|B]]", "", "## 近期活动", "")

    result = remove_member_lines(content, "7", "A", legacy_title_unique=True)

    assert result.content == _doc("## 近期活动", "")
    assert result.removed_rows == 2
    assert result.removed_groups == ("zima",)


def test_result_dataclasses_are_frozen_contracts():
    """结果契约按 spec §3.5 固定为 frozen dataclass。"""
    up = upsert_member_line("## zima\n", "2", "B", ["zima"], None, legacy_title_unique=True)
    rm = remove_member_lines("## zima\n", "2", "B", legacy_title_unique=True)

    assert isinstance(up, MemberUpsertResult)
    assert isinstance(rm, MemberRemovalResult)
    with pytest.raises(Exception):
        up.changed = True  # type: ignore[misc]
    with pytest.raises(Exception):
        rm.changed = True  # type: ignore[misc]
