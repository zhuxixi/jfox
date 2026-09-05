"""MOC 草稿构建与更新 diff 的纯逻辑。

本模块不含 I/O：不读索引、不写文件、不调用向量后端。
create/update 命令共享这些函数，便于单元测试。
"""

from __future__ import annotations

import re
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


def _member_link(note_id: str, title: str) -> str:
    """渲染成员 wiki 链接：ID 为目标、标题为别名；标题不安全时只写 ID。

    标题含换行或 `]`（含 `]]`）时无法安全作为管道别名——单 `]` 会提前截断
    `[[token]]` 语法，导致 _MEMBER_ROW_RE 无法再识别该行（重复 add 会不断追加、
    remove 删不掉）。退化为 `[[ID]]` 形式，规避 #458/#470。
    """
    if "\n" in title or "\r" in title or "]" in title:
        return f"[[{note_id}]]"
    return f"[[{note_id}|{title}]]"


def render_moc_content(draft: MocCreateDraft) -> str:
    """渲染 MOC 正文（不含 frontmatter 与标题行，create_note 负责补全）。

    小节顺序：各 tag 分组 → 「待归类」（孤儿）→ 「近期活动」占位。
    成员链接使用 ID canonical 形式（[[ID|标题]]），标题不安全时退化为 [[ID]]。
    """
    lines: List[str] = []
    for group in draft.groups:
        lines.append(f"## {group.name}")
        lines.append("")
        for member in group.members:
            link = _member_link(member.id, member.title)
            lines.append(f"- {link} — {member.link_degree} links")
        lines.append("")

    if draft.orphan_bucket:
        lines.append(f"## {_ORPHAN_SECTION}")
        lines.append("")
        for orphan in draft.orphan_bucket:
            link = _member_link(orphan.id, orphan.title)
            lines.append(f"- {link} — {orphan.link_degree} links")
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


# ---------------------------------------------------------------------------
# 单成员正文行管理（add-member / remove-member 的纯函数层，spec §3.5）
# ---------------------------------------------------------------------------

# 系统区段：不参与 tag 匹配，不允许作为显式 --group，标题永不因删行而删除
_SYSTEM_SECTIONS = frozenset({_ORPHAN_SECTION, _RECENT_SECTION})
# tag 匹配额外排除「其他」：它是 fallback 组，不作普通 tag 命中目标（spec §3.5）
_TAG_MATCH_EXCLUDED = frozenset({_OTHER_GROUP, *_SYSTEM_SECTIONS})

# 成员行：可选缩进的短横线列表项，且首个 wiki 链接 token 紧随其后
_MEMBER_ROW_RE = re.compile(r"^\s*-\s+\[\[(?P<token>[^\]]*)\]\]")


@dataclass(frozen=True)
class MemberUpsertResult:
    """upsert_member_line 的结果契约（spec §3.5）。"""

    content: str
    resolved_group: Optional[str]
    changed: bool
    rows_added: int
    rows_canonicalized: int
    had_existing_row: bool
    matched_groups: tuple[str, ...]
    ambiguous_legacy: bool


@dataclass(frozen=True)
class MemberRemovalResult:
    """remove_member_lines 的结果契约（spec §3.5）。"""

    content: str
    changed: bool
    removed_rows: int
    removed_groups: tuple[str, ...]
    ambiguous_legacy: bool


@dataclass
class _Section:
    """扫描出的顶层 H2 区段（内部结构，不对外）。"""

    name: str
    heading_index: int
    end_index: int  # 不含；下一个顶层标题行号或总行数

    @property
    def is_system(self) -> bool:
        return self.name in _SYSTEM_SECTIONS


@dataclass
class _BodyRow:
    """识别到的成员行（内部结构，不对外）。"""

    line_index: int
    section: _Section
    target: str  # token 中 | 左侧的精确目标
    alias: Optional[str]  # | 右侧别名；无 | 时 None
    has_pipe: bool


def _detect_ending(lines: List[str]) -> str:
    """取正文首个换行风格，供新插入行复用。"""
    for raw in lines:
        if raw.endswith("\r\n"):
            return "\r\n"
        if raw.endswith("\n"):
            return "\n"
    return "\n"


def _scan_body(lines: List[str]) -> tuple[List[_Section], List[_BodyRow]]:
    """逐行扫描正文：顶层 H2 区段 + 区段内成员行。

    - fenced code block（``` 围栏）内的行不参与识别；围栏行本身跳过。
    - 只有顶层 `## ` 开头的行开启区段；H3 不开新组。
    - 成员行 = 可选缩进的短横线列表项，首个 wiki 链接 token 结构化解析成功；
      token 按 | 首次出现拆分目标与别名，不使用 ID 前缀匹配。
    - 任何区段之外的成员行不归属区段，不参与匹配。
    """
    sections: List[_Section] = []
    rows: List[_BodyRow] = []
    in_fence = False
    current: Optional[_Section] = None
    for idx, raw in enumerate(lines):
        text = raw.rstrip("\r\n")
        if text.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        if text.startswith("## "):
            if current is not None:
                current.end_index = idx
            current = _Section(name=text[3:].strip(), heading_index=idx, end_index=len(lines))
            sections.append(current)
            continue
        if current is None:
            continue
        match = _MEMBER_ROW_RE.match(text)
        if not match:
            continue
        token = match.group("token")
        if "|" in token:
            target, alias = token.split("|", 1)
            has_pipe = True
        else:
            target, alias, has_pipe = token, None, False
        rows.append(
            _BodyRow(
                line_index=idx,
                section=current,
                target=target,
                alias=alias,
                has_pipe=has_pipe,
            )
        )
    return sections, rows


def _validate_explicit_group(group: str) -> None:
    """显式组名必须是单行非空，且不得是系统区段名（CLI 层负责映射错误文案）。"""
    if not group.strip() or "\n" in group or "\r" in group:
        raise ValueError("group name must be a non-empty single-line name")
    if group in _SYSTEM_SECTIONS:
        raise ValueError(f"group name must not be the reserved section: {group}")


def _insert_into_section(lines: List[str], section: _Section, row_text: str, ending: str) -> None:
    """组内追加：插在区段最后一个非空行之后；区段体全空白时插在标题后空行之后。"""
    start = section.heading_index + 1
    end = section.end_index
    insert_at: Optional[int] = None
    for i in range(start, end):
        if lines[i].strip():
            insert_at = i + 1
    if insert_at is not None:
        lines.insert(insert_at, row_text + ending)
        return
    if start < end:
        # 体全空白：紧跟标题后的空行之后追加，保留原有空行
        lines.insert(start + 1, row_text + ending)
    else:
        # 体为空（标题直接挨下一个标题）：补一个空行再追加
        lines.insert(start, ending)
        lines.insert(start + 1, row_text + ending)


def _append_new_group(
    lines: List[str], name: str, row_text: str, ending: str, before_system: Optional[int]
) -> None:
    """新建组：有系统区段时插在其前，否则追加到正文末尾并保持空行分隔。"""
    if before_system is not None:
        block = [f"## {name}{ending}", ending, row_text + ending, ending]
        if before_system > 0 and lines[before_system - 1].strip():
            block.insert(0, ending)
        lines[before_system:before_system] = block
        return
    block = [f"## {name}{ending}", ending, row_text + ending]
    if lines and lines[-1].strip():
        block.insert(0, ending)
    lines[len(lines) :] = block


def _legacy_rows_for(rows: List[_BodyRow], title: Optional[str]) -> List[_BodyRow]:
    """legacy [[标题]] 行：无管道、目标与标题逐字符相等（不截断、不子串）。"""
    if not title:
        return []
    return [row for row in rows if not row.has_pipe and row.target == title]


def _dedup_names(rows: List[_BodyRow]) -> tuple[str, ...]:
    """按正文出现顺序收集行所属组名并去重。"""
    names: List[str] = []
    for row in rows:
        if row.section.name not in names:
            names.append(row.section.name)
    return tuple(names)


def upsert_member_line(
    content: str,
    note_id: str,
    title: str,
    tags: Sequence[str],
    group: Optional[str],
    *,
    legacy_title_unique: bool,
) -> MemberUpsertResult:
    """插入、认领或修复一个 MOC 成员正文行；纯函数（spec §3.5）。

    - 已有 canonical 行（[[ID]] / [[ID|别名]]）：不搬组、不改别名、不重复插入；
      同时存在的 legacy 行原样保留。
    - 无 canonical 行且有唯一 legacy [[标题]] 行：原地改写为 canonical 目标，
      保留原组与行后缀，不额外插入。
    - 无 canonical 行且 legacy 标题歧义：不改写旧行，按选组规则追加一条
      canonical 行，ambiguous_legacy=True。
    - 选组：显式 group 精确匹配已有普通组（不存在则新建，插在第一个系统区段
      之前）；缺省按正文顺序用 tags 匹配普通组名（排除其他/待归类/近期活动），
      未命中用/建「其他」。
    """
    if group is not None:
        _validate_explicit_group(group)

    lines = content.splitlines(keepends=True)
    ending = _detect_ending(lines)
    sections, rows = _scan_body(lines)

    canonical_rows = [row for row in rows if row.target == note_id]
    legacy_rows = _legacy_rows_for(rows, title)

    if canonical_rows:
        return MemberUpsertResult(
            content=content,
            resolved_group=canonical_rows[0].section.name,
            changed=False,
            rows_added=0,
            rows_canonicalized=0,
            had_existing_row=True,
            matched_groups=_dedup_names(canonical_rows),
            ambiguous_legacy=False,
        )

    if legacy_rows and legacy_title_unique:
        old_token = f"[[{title}]]"
        new_token = _member_link(note_id, title)
        for row in legacy_rows:
            lines[row.line_index] = lines[row.line_index].replace(old_token, new_token, 1)
        return MemberUpsertResult(
            content="".join(lines),
            resolved_group=legacy_rows[0].section.name,
            changed=True,
            rows_added=0,
            rows_canonicalized=len(legacy_rows),
            had_existing_row=True,
            matched_groups=_dedup_names(legacy_rows),
            ambiguous_legacy=False,
        )

    ambiguous = bool(legacy_rows) and not legacy_title_unique

    target_section: Optional[_Section] = None
    new_group_name: Optional[str] = None
    if group is not None:
        for section in sections:
            if not section.is_system and section.name == group:
                target_section = section
                break
        if target_section is None:
            new_group_name = group
    else:
        for section in sections:
            if section.name not in _TAG_MATCH_EXCLUDED and section.name in tags:
                target_section = section
                break
        if target_section is None:
            for section in sections:
                if not section.is_system and section.name == _OTHER_GROUP:
                    target_section = section
                    break
        if target_section is None:
            new_group_name = _OTHER_GROUP

    row_text = f"- {_member_link(note_id, title)}"
    if new_group_name is not None:
        first_system = next((s.heading_index for s in sections if s.is_system), None)
        _append_new_group(lines, new_group_name, row_text, ending, first_system)
        resolved = new_group_name
    else:
        assert target_section is not None  # 选组逻辑保证二者必有其一
        _insert_into_section(lines, target_section, row_text, ending)
        resolved = target_section.name

    return MemberUpsertResult(
        content="".join(lines),
        resolved_group=resolved,
        changed=True,
        rows_added=1,
        rows_canonicalized=0,
        had_existing_row=False,
        matched_groups=(resolved,),
        ambiguous_legacy=ambiguous,
    )


def remove_member_lines(
    content: str,
    note_id: str,
    title: Optional[str],
    *,
    legacy_title_unique: bool,
) -> MemberRemovalResult:
    """删除一个成员在所有区段中的正文行；纯函数（spec §3.5）。

    - 删除所有精确匹配 NOTE_ID 的 canonical 行（[[ID]] / [[ID|别名]]，跨所有
      区段，含系统区段内的行）。
    - title 存在且全库唯一时，同时删除精确匹配的 legacy [[标题]] 行；
      title 存在但歧义时保留旧行并置 ambiguous_legacy=True；title=None 时
      不动任何标题行。
    - 删行后只剩空白的普通组连同标题删除；含说明文字、子标题、代码或其他
      Markdown 的组保留标题；系统区段标题永不删除。
    """
    lines = content.splitlines(keepends=True)
    _sections, rows = _scan_body(lines)

    canonical_rows = [row for row in rows if row.target == note_id]
    legacy_rows = _legacy_rows_for(rows, title)
    ambiguous = bool(legacy_rows) and not legacy_title_unique
    remove_rows = canonical_rows + legacy_rows if legacy_title_unique else canonical_rows

    if not remove_rows:
        return MemberRemovalResult(
            content=content,
            changed=False,
            removed_rows=0,
            removed_groups=(),
            ambiguous_legacy=ambiguous,
        )

    removed_from = _dedup_names(remove_rows)
    for idx in sorted({row.line_index for row in remove_rows}, reverse=True):
        del lines[idx]
        # 删行后若与前行连成连续空行，吸收紧随其后的那个空行（避免双空行残留）
        if idx < len(lines) and not lines[idx].strip():
            if idx > 0 and not lines[idx - 1].strip():
                del lines[idx]

    # 删行后行号已变：重扫后清理只剩空白的普通组（系统区段标题永不删除）
    sections_after, _rows_after = _scan_body(lines)
    spans: List[tuple[int, int]] = []
    for section in sections_after:
        if section.is_system or section.name not in removed_from:
            continue
        body = lines[section.heading_index + 1 : section.end_index]
        if not any(raw.strip() for raw in body):
            spans.append((section.heading_index, section.end_index))
    for start, end in sorted(spans, reverse=True):
        del lines[start:end]

    return MemberRemovalResult(
        content="".join(lines),
        changed=True,
        removed_rows=len(remove_rows),
        removed_groups=removed_from,
        ambiguous_legacy=ambiguous,
    )
