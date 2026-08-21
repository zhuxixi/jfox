"""MOC 草稿构建与更新 diff 的纯逻辑。

本模块不含 I/O：不读索引、不写文件、不调用向量后端。
create/update 命令共享这些函数，便于单元测试。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Sequence, Set

from .cluster import ClusterMember, ClusterSummary, OrphanNote

# 分组所需 tag 覆盖簇成员的最小比例（与最小计数 2 取 max）。
_GROUP_MIN_SHARE = 0.1
_OTHER_GROUP = "其他"
_ORPHAN_SECTION = "待归类"
_RECENT_SECTION = "近期活动"


@dataclass
class DraftGroup:
    """MOC 草稿中的一个成员分组。"""

    name: str
    members: List[ClusterMember] = field(default_factory=list)


@dataclass
class MocCreateDraft:
    """MOC 创建草稿：标题 + 分组 + 孤儿桶。"""

    title: str
    groups: List[DraftGroup] = field(default_factory=list)
    orphan_bucket: List[OrphanNote] = field(default_factory=list)
    total_members: int = 0


def build_moc_draft(
    cluster: ClusterSummary,
    tags_by_id: Dict[str, List[str]],
    max_size: int,
    orphans: Optional[List[OrphanNote]] = None,
    title: Optional[str] = None,
) -> MocCreateDraft:
    """把诊断簇渲染成 MOC 草稿。

    规则：
    - 簇 size 超过 max_size 时拒绝（ValueError），提示提高阈值拆分。
    - 成员按共享 tag 分组：tag 计数 >= max(2, 10% * size) 成组，余下「其他」。
    - 组内 hub 置顶，其余按 mean_similarity 降序。
    """
    members = list(cluster.members)
    if len(members) > max_size:
        raise ValueError(
            f"Cluster size {len(members)} exceeds --max-size {max_size}; "
            "raise --threshold to split the cluster or pass a larger --max-size explicitly"
        )

    hub = cluster.hub
    default_title = f"{hub.title} MOC" if hub is not None else f"MOC {len(members)} notes"
    draft_title = title if title else default_title

    # 共享 tag 计数
    tag_counts: Counter = Counter(
        tag for member in members for tag in tags_by_id.get(member.id, [])
    )
    min_share = max(2, int(_GROUP_MIN_SHARE * len(members)))
    grouped_tags = [tag for tag, count in tag_counts.items() if count >= min_share]
    # 大组在前（按覆盖成员数降序），更符合阅读预期
    grouped_tags.sort(key=lambda tag: -tag_counts[tag])

    # 分组（hub 置顶 + mean_similarity 降序）
    groups: List[DraftGroup] = []
    for tag in grouped_tags:
        group_members = sorted(
            [m for m in members if tag in tags_by_id.get(m.id, [])],
            key=lambda m: (m.id != (hub.id if hub else ""), -m.mean_similarity),
        )
        groups.append(DraftGroup(name=tag, members=group_members))

    other_members = [
        m for m in members if all(tag not in tags_by_id.get(m.id, []) for tag in grouped_tags)
    ]
    other_members.sort(key=lambda m: (m.id != (hub.id if hub else ""), -m.mean_similarity))
    if other_members:
        groups.append(DraftGroup(name=_OTHER_GROUP, members=other_members))

    return MocCreateDraft(
        title=draft_title,
        groups=groups,
        orphan_bucket=list(orphans or []),
        total_members=len(members),
    )


def render_moc_content(draft: MocCreateDraft) -> str:
    """渲染 MOC 正文（不含 frontmatter 与标题行，create_note 负责补全）。

    小节顺序：各 tag 分组 → 「待归类」（孤儿）→ 「近期活动」占位。
    """
    lines: List[str] = []
    for group in draft.groups:
        lines.append(f"## {group.name}")
        lines.append("")
        for member in group.members:
            lines.append(f"- [[{member.title}]] — {member.link_degree} links")
        lines.append("")

    if draft.orphan_bucket:
        lines.append(f"## {_ORPHAN_SECTION}")
        lines.append("")
        for orphan in draft.orphan_bucket:
            lines.append(f"- [[{orphan.title}]] — {orphan.link_degree} links")
        lines.append("")

    lines.append(f"## {_RECENT_SECTION}")
    lines.append("")
    return "\n".join(lines)


@dataclass
class MocUpdateDiff:
    """MOC 更新 diff：建议新增的簇成员与应摘除的死链。"""

    add: List[ClusterMember] = field(default_factory=list)
    remove: List[str] = field(default_factory=list)
    kept: int = 0


def filter_live_members(
    draft: MocCreateDraft,
    live_ids: Set[str],
) -> tuple[MocCreateDraft, list[str]]:
    """过滤掉已归档/不存在的 ghost 成员，返回 (过滤后的 draft, 跳过成员的 warning 列表)。

    - 从每个 group 中移除 id 不在 live_ids 的成员；空 group 丢弃。
    - orphan_bucket 同样过滤。
    - warnings 格式："skipped ghost member <id> (<title>)"。
    - total_members 重算为剩余成员数。
    """
    warnings: list[str] = []
    filtered_groups: list[DraftGroup] = []
    for group in draft.groups:
        kept_members = []
        for member in group.members:
            if member.id in live_ids:
                kept_members.append(member)
            else:
                warnings.append(f"skipped ghost member {member.id} ({member.title})")
        if kept_members:
            filtered_groups.append(DraftGroup(name=group.name, members=kept_members))

    filtered_orphans: list[OrphanNote] = []
    for orphan in draft.orphan_bucket:
        if orphan.id in live_ids:
            filtered_orphans.append(orphan)
        else:
            warnings.append(f"skipped ghost member {orphan.id} ({orphan.title})")

    total = len({m.id for g in filtered_groups for m in g.members})
    filtered = MocCreateDraft(
        title=draft.title,
        groups=filtered_groups,
        orphan_bucket=filtered_orphans,
        total_members=total,
    )
    return filtered, warnings


def build_update_diff(
    current_links: Sequence[str],
    cluster_members: Sequence[ClusterMember],
    existing_ids: Set[str],
) -> MocUpdateDiff:
    """对比 MOC 现有 links 与当前簇成员。

    existing_ids：磁盘上实际存在的笔记 id 集合（调用方做磁盘存在性校验后传入，
    覆盖任意笔记类型——#391 已知 note index 会 stale，以磁盘文件为准）。

    - add：簇内但不在 links 中的成员，且其 id 在 existing_ids 中（ghost 成员跳过）。
    - remove：links 中已不在 existing_ids 的死链（已归档/已删除/磁盘不存在）。
      覆盖任意笔记类型（不限 permanent），避免误摘 live 的 structure/literature
      等非 permanent 链接（spec D7）。
    - kept：links 与簇成员的交集数。语义漂移不自动摘除（人工判断）。
    """
    member_ids = {m.id for m in cluster_members}
    current = set(current_links)
    remove = sorted(mid for mid in current if mid not in existing_ids)
    add = [m for m in cluster_members if m.id not in current and m.id in existing_ids]
    kept = len(current & member_ids)
    return MocUpdateDiff(add=add, remove=remove, kept=kept)
