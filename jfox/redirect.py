"""引用重定向：把所有指向旧笔记的引用迁移到保留笔记。

设计要点：
1. `delete` 只能清理被删笔记自己的出链对应的 backlinks，无法推断替代目标，
   因此引用迁移必须是独立、显式的操作（issue #435）。
2. frontmatter `links` 与正文 wiki link 是同一引用关系的两种表示，
   必须在同一次操作里同步重写；只改一处会在下次 `edit` 重新解析时回退。
3. 正文改写保持无损：保留 alias 与 anchor，不触碰非链接文本，
   不丢失未知 frontmatter 字段。
4. 标题歧义（重复标题）无法确定原始目标，preflight 阶段直接拒绝。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Set, Tuple

import yaml

from .config import ZKConfig
from .note import _atomic_write, load_note_by_id
from .note_index import _normalize_wiki_link_title, get_note_index

logger = logging.getLogger(__name__)

# 捕获完整 [[...]] span，用于按原始偏移做无损替换
_WIKI_LINK_SPAN_RE = re.compile(r"\[\[([^\[\]]+)\]\]")

# 需要排除的 Markdown 区域（与 note_index 的扫描口径保持一致）
_FENCED_CODE_RE = re.compile(r"```[\s\S]*?```")
_HTML_COMMENT_RE = re.compile(r"<!--[\s\S]*?-->")

# frontmatter / 正文切分：保留分隔符原样以便字节级还原
_FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---(\r?\n)(.*)$", re.DOTALL)


@dataclass
class ReferenceReport:
    """入链扫描结果与 preflight 诊断"""

    old_id: str
    old_title: str = ""
    keep_id: Optional[str] = None
    keep_title: Optional[str] = None

    # (source_id, source_title, path)
    frontmatter_refs: List[Tuple[str, str, Path]] = field(default_factory=list)
    body_refs: List[Tuple[str, str, Path]] = field(default_factory=list)

    # preflight 硬门禁
    old_not_found: bool = False
    keep_not_found: bool = False
    same_id: bool = False
    duplicate_old_titles: List[Tuple[str, str]] = field(default_factory=list)
    duplicate_keep_titles: List[Tuple[str, str]] = field(default_factory=list)

    def referencing_ids(self) -> Set[str]:
        """去重后的引用方 ID 集合"""
        return {sid for sid, _, _ in self.frontmatter_refs} | {sid for sid, _, _ in self.body_refs}

    def has_references(self) -> bool:
        return bool(self.frontmatter_refs or self.body_refs)

    def blocking_reasons(self) -> List[str]:
        """返回阻止继续执行的原因列表；为空表示 preflight 通过"""
        reasons: List[str] = []
        if self.old_not_found:
            reasons.append(f"OLD note not found: {self.old_id}")
        if self.keep_not_found:
            reasons.append(f"KEEP note not found: {self.keep_id}")
        if self.same_id:
            reasons.append("OLD and KEEP must be different notes")
        if self.duplicate_old_titles:
            ids = ", ".join(nid for nid, _ in self.duplicate_old_titles)
            reasons.append(
                f"Ambiguous OLD title '{self.old_title}': shared by {len(self.duplicate_old_titles)} notes ({ids}). "
                "Rename or archive duplicates before redirecting."
            )
        if self.duplicate_keep_titles:
            ids = ", ".join(nid for nid, _ in self.duplicate_keep_titles)
            reasons.append(
                f"Ambiguous KEEP title '{self.keep_title}': shared by {len(self.duplicate_keep_titles)} notes ({ids})."
            )
        return reasons

    def can_proceed(self) -> bool:
        return not self.blocking_reasons()


@dataclass
class RedirectResult:
    """redirect 执行结果。文件改写与派生索引分开统计。"""

    success: bool
    old_id: str
    keep_id: str
    dry_run: bool = False

    files_changed: int = 0
    frontmatter_links_updated: int = 0
    body_links_updated: int = 0
    backlinks_updated: int = 0

    conflicts: List[str] = field(default_factory=list)
    unreadable_files: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    verification_passed: bool = False


def _mask_exclusions(text: str) -> str:
    """把 fenced code block / HTML 注释替换为等长空白，保持字符偏移不变。

    这样在掩码文本上定位 wiki link，偏移可以直接套用到原文，
    既排除了代码块内的伪链接，又不会错位。
    """

    def _blank(match: re.Match) -> str:
        # 保留换行，其余字符替换为空格，长度不变
        return re.sub(r"[^\n]", " ", match.group(0))

    text = _FENCED_CODE_RE.sub(_blank, text)
    text = _HTML_COMMENT_RE.sub(_blank, text)
    return text


def _link_matches_old(inner: str, old_id: str, old_title: str) -> bool:
    """判断一个 wiki link 内容是否精确指向旧笔记。

    只接受精确 ID 或精确标题匹配；不做 substring 模糊匹配，
    避免把 [[Foo]] 误判为对 "Foo Bar" 的引用。
    """
    target = _normalize_wiki_link_title(inner)
    if target == old_id:
        return True
    return bool(old_title) and target.casefold() == old_title.casefold()


def _rewritten_inner(inner: str, keep_id: str) -> str:
    """生成新的 link 内容，保留 alias 与 anchor。

    [[Old]]              -> [[KEEP]]
    [[Old|别名]]          -> [[KEEP|别名]]
    [[Old#锚点]]          -> [[KEEP#锚点]]
    [[Old#锚点|别名]]      -> [[KEEP#锚点|别名]]
    """
    target_part, sep, alias_part = inner.partition("|")
    _, anchor_sep, anchor = target_part.partition("#")

    new_target = keep_id
    if anchor_sep:
        new_target = f"{keep_id}#{anchor.strip()}"
    if sep:
        return f"{new_target}|{alias_part}"
    return new_target


def _rewrite_body_links(body: str, old_id: str, old_title: str, keep_id: str) -> Tuple[str, int]:
    """重写正文中指向旧笔记的 wiki link，返回 (新正文, 改写处数)。

    代码块与 HTML 注释内的内容不会被改写。
    """
    masked = _mask_exclusions(body)

    replacements: List[Tuple[int, int, str]] = []
    for match in _WIKI_LINK_SPAN_RE.finditer(masked):
        inner = match.group(1)
        if not _link_matches_old(inner, old_id, old_title):
            continue
        replacements.append((match.start(), match.end(), f"[[{_rewritten_inner(inner, keep_id)}]]"))

    if not replacements:
        return body, 0

    # 从后往前替换，保持前面的偏移有效
    new_body = body
    for start, end, new_text in reversed(replacements):
        new_body = new_body[:start] + new_text + new_body[end:]

    return new_body, len(replacements)


def scan_references(
    old_id: str,
    old_title: Optional[str] = None,
    keep_id: Optional[str] = None,
    cfg: Optional[ZKConfig] = None,
) -> ReferenceReport:
    """扫描所有指向 old_id 的引用（frontmatter links + 正文 wiki link）。

    扫描范围显式包含归档笔记：归档笔记既是有效引用来源，也是有效目标，
    但默认的 list/rebuild 路径会把它们过滤掉。

    Args:
        old_id: 旧笔记 ID
        old_title: 旧笔记标题（省略时从笔记文件读取）
        keep_id: 保留笔记 ID（提供时会一并做 preflight 校验）
        cfg: 目标知识库配置（省略时使用当前默认配置）
    """
    report = ReferenceReport(old_id=old_id, old_title=old_title or "", keep_id=keep_id)

    old_note = load_note_by_id(old_id, cfg=cfg)
    if not old_note:
        report.old_not_found = True
        return report
    report.old_title = old_note.title

    if keep_id:
        if keep_id == old_id:
            report.same_id = True
            return report
        keep_note = load_note_by_id(keep_id, cfg=cfg)
        if not keep_note:
            report.keep_not_found = True
            return report
        report.keep_title = keep_note.title

    idx = get_note_index(cfg)
    all_meta = idx.get_all_meta()

    old_title_matches = [
        (m.id, m.title) for m in all_meta if m.title.casefold() == report.old_title.casefold()
    ]
    if len(old_title_matches) > 1:
        report.duplicate_old_titles = old_title_matches

    if report.keep_title:
        keep_title_matches = [
            (m.id, m.title) for m in all_meta if m.title.casefold() == report.keep_title.casefold()
        ]
        if len(keep_title_matches) > 1:
            report.duplicate_keep_titles = keep_title_matches

    for meta in all_meta:
        if meta.id == old_id:
            continue
        if old_id in meta.links:
            report.frontmatter_refs.append((meta.id, meta.title, Path(meta.filepath)))

    report.body_refs = _find_body_refs(all_meta, old_id, report.old_title)

    return report


def _find_body_refs(
    metas: List,
    old_id: str,
    old_title: str,
) -> List[Tuple[str, str, Path]]:
    """按正文 wiki link 精确匹配（ID 或标题）发现引用方。

    与 _rewrite_body_links 同口径（等长掩码 + normalize + 精确比较）。
    不能只用 NoteIndex.find_notes_referencing_title：它只按标题匹配，
    手写/外部导入文件可能仅有正文 [[OLD_ID]] 引用而无 frontmatter
    links 回填——那正是 #435 要消灭的悬空来源（CR issue-1）。
    """
    refs: List[Tuple[str, str, Path]] = []
    for meta in metas:
        if meta.id == old_id:
            continue
        try:
            text = Path(meta.filepath).read_text(encoding="utf-8")
        except OSError:
            continue
        masked = _mask_exclusions(text)
        for m in _WIKI_LINK_SPAN_RE.finditer(masked):
            if _link_matches_old(m.group(1), old_id, old_title):
                refs.append((meta.id, meta.title, Path(meta.filepath)))
                break
    return refs


def redirect_references(
    old_id: str,
    keep_id: str,
    dry_run: bool = False,
    cfg: Optional[ZKConfig] = None,
) -> RedirectResult:
    """把所有指向 old_id 的引用迁移到 keep_id。

    旧笔记本身不会被删除：删除是独立决策，需要在验证通过后显式执行。

    Args:
        old_id: 旧笔记 ID
        keep_id: 保留笔记 ID
        dry_run: 只报告影响范围，不写任何文件
        cfg: 目标知识库配置
    """
    result = RedirectResult(success=False, old_id=old_id, keep_id=keep_id, dry_run=dry_run)

    report = scan_references(old_id, keep_id=keep_id, cfg=cfg)
    blocking = report.blocking_reasons()
    if blocking:
        result.errors.extend(blocking)
        return result

    old_title = report.old_title

    # frontmatter 与正文引用可能落在同一文件，先合并去重
    target_paths = sorted(
        {p for _, _, p in report.frontmatter_refs} | {p for _, _, p in report.body_refs}
    )

    # 路径 → 引用方 ID（仅收集实际改写成功的，供 backlinks 同步；CR issue-8）
    path_sources = {}
    for sid, _, p in list(report.frontmatter_refs) + list(report.body_refs):
        path_sources.setdefault(p, set()).add(sid)
    migrated_ids: Set[str] = set()

    for path in target_paths:
        try:
            if not path.exists():
                result.unreadable_files.append(str(path))
                continue

            original = path.read_text(encoding="utf-8")
            match = _FRONTMATTER_RE.match(original)
            if not match:
                result.unreadable_files.append(str(path))
                continue

            fm_raw, separator, rest = match.group(1), match.group(2), match.group(3)
            try:
                frontmatter = yaml.safe_load(fm_raw)
            except yaml.YAMLError as exc:
                result.unreadable_files.append(f"{path}: invalid frontmatter ({exc})")
                continue

            if not isinstance(frontmatter, dict):
                result.unreadable_files.append(str(path))
                continue

            fm_changed = False
            links = frontmatter.get("links")
            if isinstance(links, list) and old_id in links:
                migrated: List[str] = []
                for value in links:
                    replacement = keep_id if value == old_id else value
                    if replacement not in migrated:
                        migrated.append(replacement)
                frontmatter["links"] = migrated
                result.frontmatter_links_updated += 1
                fm_changed = True

            new_rest, body_count = _rewrite_body_links(rest, old_id, old_title, keep_id)
            body_changed = body_count > 0

            if not (fm_changed or body_changed):
                continue

            result.files_changed += 1
            result.body_links_updated += body_count

            if dry_run:
                continue

            new_fm_raw = yaml.dump(
                frontmatter, allow_unicode=True, sort_keys=False, default_flow_style=False
            )
            new_content = f"---\n{new_fm_raw}---{separator}{new_rest}"

            # 写前复核：内容在扫描后被改动则报冲突，不覆盖他人修改
            if path.read_text(encoding="utf-8") != original:
                result.conflicts.append(str(path))
                result.files_changed -= 1
                result.body_links_updated -= body_count
                if fm_changed:
                    result.frontmatter_links_updated -= 1
                continue

            _atomic_write(path, new_content)
            migrated_ids |= path_sources.get(path, set())

        except OSError as exc:
            result.errors.append(f"{path}: {exc}")
            logger.error("redirect failed for %s: %s", path, exc)

    # 保留笔记的 backlinks 需要纳入新增来源，并清掉旧笔记残留；
    # 只纳入实际改写成功的来源（conflict/unreadable 的不进，CR issue-8）
    if not dry_run and not result.errors:
        result.backlinks_updated = _sync_keep_backlinks(keep_id, old_id, migrated_ids, cfg=cfg)

    if not dry_run:
        # 改写后索引缓存已过期，验证前必须重建
        from .note_index import reset_note_index

        reset_note_index()
        verification = scan_references(old_id, cfg=cfg)
        result.verification_passed = not verification.has_references()

    # success 必须涵盖全部失败面：errors / conflicts / unreadable_files，
    # 且非 dry-run 时验证必须通过，否则 CLI 会出现 success:true +
    # verification_passed:false 的矛盾输出（CR issue-5）
    result.success = (
        not result.errors
        and not result.conflicts
        and not result.unreadable_files
        and (dry_run or result.verification_passed)
    )
    return result


def _sync_keep_backlinks(
    keep_id: str,
    old_id: str,
    source_ids: Set[str],
    cfg: Optional[ZKConfig] = None,
) -> int:
    """把迁移来的来源写入保留笔记的 backlinks，并移除旧笔记残留。

    采用 re-read-and-merge：只改 backlinks 字段，避免覆盖并发修改。
    文件定位用 find_note_file（按 cfg 搜索）；不能依赖 Note.filepath
    property —— from_markdown 不回填 _filepath，它会退回全局 config 推算路径。
    """
    from .config import config
    from .note import find_note_file

    use_cfg = cfg if cfg is not None else config
    path = find_note_file(use_cfg, keep_id)
    if not path or not path.exists():
        return 0

    try:
        original = path.read_text(encoding="utf-8")
        match = _FRONTMATTER_RE.match(original)
        if not match:
            return 0

        fm_raw, separator, rest = match.group(1), match.group(2), match.group(3)
        frontmatter = yaml.safe_load(fm_raw)
        if not isinstance(frontmatter, dict):
            return 0

        current = frontmatter.get("backlinks")
        backlinks = list(current) if isinstance(current, list) else []

        merged = [b for b in backlinks if b != old_id]
        for source_id in sorted(source_ids):
            if source_id != keep_id and source_id not in merged:
                merged.append(source_id)

        if merged == backlinks:
            return 0

        frontmatter["backlinks"] = merged
        new_fm_raw = yaml.dump(
            frontmatter, allow_unicode=True, sort_keys=False, default_flow_style=False
        )
        _atomic_write(path, f"---\n{new_fm_raw}---{separator}{rest}")
        return len(merged) - len(backlinks) if len(merged) != len(backlinks) else 1
    except (OSError, yaml.YAMLError) as exc:
        logger.error("failed to sync backlinks for %s: %s", keep_id, exc)
        return 0
