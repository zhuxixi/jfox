"""MOC 草稿构建与更新 diff 的纯逻辑测试。"""

from __future__ import annotations

import pytest

from jfox.moc.cluster import ClusterMember, ClusterSummary, OrphanNote
from jfox.moc.draft import (
    build_moc_draft,
    build_update_diff,
    render_moc_content,
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
    assert "- [[Zima Hub]] — 10 links" in content
    assert "## 其他" in content
    assert "## 待归类" in content
    assert "- [[Orphan A]] — 0 links" in content
    assert "## 近期活动" in content


def test_update_diff_adds_new_and_removes_dead_links():
    cluster = _cluster()
    diff = build_update_diff(
        current_links=["1", "2", "99"],  # 99 已死
        cluster_members=cluster.members,
        live_permanent_ids={"1", "2", "3", "4", "5"},
    )
    assert [m.id for m in diff.add] == ["3", "4", "5"]
    assert diff.remove == ["99"]
    assert diff.kept == 2
