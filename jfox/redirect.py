"""引用重定向：批量更新所有指向旧笔记的引用。

核心功能：
1. 扫描谁引用了 OLD_ID（frontmatter links + 正文 wiki link）
2. 批量重写为 KEEP_ID（保留 alias/anchor，保持 grounded_by 不变）
3. Preflight 检查重复标题、不存在的 ID、文件可读性
"""

from __future__ import annotations

import hashlib
import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

import yaml

from .config import config
from .models import Note
from .note import load_note_by_id
from .note_index import (
    _normalize_wiki_link_title,
    _strip_wiki_link_exclusions,
    extract_wiki_links_from_text,
    get_note_index,
)

logger = logging.getLogger(__name__)

# Wiki link 正则：捕获完整 span 以便 lossless rewrite
_WIKI_LINK_SPAN_RE = re.compile(r"\[\[([^\]]+)\]\]")


@dataclass
class ReferenceReport:
    """入链扫描报告"""

    old_id: str
    old_title: str
    keep_id: Optional[str] = None
    keep_title: Optional[str] = None

    # 引用方列表
    frontmatter_refs: List[Tuple[str, str, Path]] = field(default_factory=list)  # (src_id, src_title, path)
    body_refs: List[Tuple[str, str, Path]] = field(default_factory=list)

    # Preflight 问题
    duplicate_old_titles: List[Tuple[str, str]] = field(default_factory=list)  # (id, title) 列表
    duplicate_keep_titles: List[Tuple[str, str]] = field(default_factory=list)
    unreadable_files: List[str] = field(default_factory=list)
    old_not_found: bool = False
    keep_not_found: bool = False

    def has_references(self) -> bool:
        """是否存在任何引用"""
        return bool(self.frontmatter_refs or self.body_refs)

    def can_proceed(self) -> bool:
        """Preflight 是否通过"""
        return not (
            self.old_not_found
            or self.keep_not_found
            or self.duplicate_old_titles
            or self.duplicate_keep_titles
        )


@dataclass
class RedirectResult:
    """Redirect 执行结果"""

    success: bool
    old_id: str
    keep_id: str

    files_changed: int = 0
    frontmatter_links_updated: int = 0
    body_links_updated: int = 0
    backlinks_updated: int = 0

    conflicts: List[str] = field(default_factory=list)  # 文件冲突（mtime 变化）
    unmigratable: List[str] = field(default_factory=list)  # substring-only 匹配
    unreadable_files: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    verification_passed: bool = False


def scan_references(
    old_id: str, old_title: Optional[str] = None, keep_id: Optional[str] = None
) -> ReferenceReport:
    """扫描所有引用 old_id 的笔记（frontmatter + 正文）。

    Args:
        old_id: 旧笔记 ID
        old_title: 旧笔记标题（可选，若不提供则从文件加载）
        keep_id: 新笔记 ID（可选，用于 preflight 检查重复标题）

    Returns:
        ReferenceReport 包含所有引用方和 preflight 问题
    """
    report = ReferenceReport(old_id=old_id, old_title=old_title or "", keep_id=keep_id)

    # 加载 old/keep 笔记，验证存在性
    try:
        old_note = load_note_by_id(old_id)
    except Exception:
        old_note = None
    
    if not old_note:
        report.old_not_found = True
        return report
    report.old_title = old_note.title

    if keep_id:
        try:
            keep_note = load_note_by_id(keep_id)
        except Exception:
            keep_note = None
        
        if not keep_note:
            report.keep_not_found = True
            return report
        report.keep_title = keep_note.title

    # 检查重复标题
    idx = get_note_index()
    all_meta = idx.get_all_meta()

    old_title_matches = [
        (m.id, m.title) for m in all_meta if m.title.casefold() == old_note.title.casefold()
    ]
    if len(old_title_matches) > 1:
        report.duplicate_old_titles = old_title_matches

    if keep_id and report.keep_title:
        keep_title_matches = [
            (m.id, m.title)
            for m in all_meta
            if m.title.casefold() == report.keep_title.casefold()
        ]
        if len(keep_title_matches) > 1:
            report.duplicate_keep_titles = keep_title_matches

    # 扫描 frontmatter links
    for meta in all_meta:
        if old_id in meta.links:
            report.frontmatter_refs.append((meta.id, meta.title, Path(meta.filepath)))

    # 扫描正文引用（包含归档来源）
    body_referencers = idx.find_notes_referencing_title(old_note.title)
    for meta in body_referencers:
        report.body_refs.append((meta.id, meta.title, Path(meta.filepath)))

    return report


def redirect_references(
    old_id: str, keep_id: str, dry_run: bool = False, force: bool = False
) -> RedirectResult:
    """批量重写所有引用 old_id 的笔记。

    Args:
        old_id: 旧笔记 ID
        keep_id: 新笔记 ID
        dry_run: True 时只报告、不实际写文件
        force: True 时跳过 mtime 冲突检查

    Returns:
        RedirectResult 包含更新统计和错误列表
    """
    result = RedirectResult(success=False, old_id=old_id, keep_id=keep_id)

    # Preflight
    report = scan_references(old_id, keep_id=keep_id)
    if not report.can_proceed():
        if report.old_not_found:
            result.errors.append(f"OLD note not found: {old_id}")
        if report.keep_not_found:
            result.errors.append(f"KEEP note not found: {keep_id}")
        if report.duplicate_old_titles:
            result.errors.append(
                f"Ambiguous OLD title: {len(report.duplicate_old_titles)} notes share '{report.old_title}'"
            )
        if report.duplicate_keep_titles:
            result.errors.append(
                f"Ambiguous KEEP title: {len(report.duplicate_keep_titles)} notes share '{report.keep_title}'"
            )
        return result

    if not report.has_references():
        result.success = True
        return result

    old_title = report.old_title
    changed_files: Set[Path] = set()

    # 收集所有需要更新的文件（frontmatter + body 可能重叠）
    all_paths = set([p for _, _, p in report.frontmatter_refs] + [p for _, _, p in report.body_refs])

    for path in all_paths:
        try:
            if not path.exists():
                result.unreadable_files.append(str(path))
                continue

            original = path.read_text(encoding="utf-8")
            original_mtime = path.stat().st_mtime_ns
            original_hash = hashlib.sha256(original.encode("utf-8")).hexdigest()

            # 解析 frontmatter + body
            match = re.match(r"^---\n(.*?)\n---\n+(.*)$", original, re.DOTALL)
            if not match:
                result.unreadable_files.append(str(path))
                continue

            fm_raw, body = match.group(1), match.group(2)
            fm = yaml.safe_load(fm_raw)
            if not isinstance(fm, dict):
                result.unreadable_files.append(str(path))
                continue

            changed = False

            # 1. 更新 frontmatter links
            if isinstance(fm.get("links"), list) and old_id in fm["links"]:
                fm["links"] = [keep_id if x == old_id else x for x in fm["links"]]
                result.frontmatter_links_updated += 1
                changed = True

            # 2. 更新 frontmatter backlinks（若当前笔记是 keep_id）
            if fm.get("id") == keep_id and isinstance(fm.get("backlinks"), list):
                if old_id in fm["backlinks"]:
                    fm["backlinks"] = [x for x in fm["backlinks"] if x != old_id]
                    result.backlinks_updated += 1
                    changed = True

            # 3. 更新正文 wiki link：[[OLD_TITLE]] / [[OLD_ID]] → [[KEEP_ID]]
            #    保留 alias/anchor：[[OLD_TITLE|alias]] → [[KEEP_ID|alias]]
            new_body, body_changed_count = _rewrite_body_links(body, old_id, old_title, keep_id)
            if body_changed_count > 0:
                body = new_body
                result.body_links_updated += body_changed_count
                changed = True

            if not changed:
                continue

            if dry_run:
                result.files_changed += 1
                continue

            # 冲突检查
            if not force:
                current_mtime = path.stat().st_mtime_ns
                if current_mtime != original_mtime:
                    result.conflicts.append(str(path))
                    continue

            # 写回
            new_fm_raw = yaml.dump(fm, allow_unicode=True, sort_keys=False)
            new_content = f"---\n{new_fm_raw}---\n\n{body}"
            path.write_text(new_content, encoding="utf-8")

            changed_files.add(path)
            result.files_changed += 1

        except Exception as e:
            result.errors.append(f"{path}: {e}")
            logger.error(f"Failed to update {path}: {e}")

    # Post-redirect 验证
    if not dry_run and not result.conflicts and not result.errors:
        verify_report = scan_references(old_id)
        result.verification_passed = not verify_report.has_references()

    result.success = result.files_changed > 0 or (not report.has_references())
    return result


def _rewrite_body_links(
    body: str, old_id: str, old_title: str, keep_id: str
) -> Tuple[str, int]:
    """重写正文中的 wiki link：[[OLD_TITLE]] / [[OLD_ID]] → [[KEEP_ID]]。

    保留 alias 和 anchor：
    - [[OLD_TITLE|alias]] → [[KEEP_ID|alias]]
    - [[OLD_TITLE#anchor]] → [[KEEP_ID#anchor]]
    - [[OLD_TITLE|alias#anchor]] → [[KEEP_ID|alias#anchor]]（极端情况）

    Args:
        body: 正文
        old_id: 旧 ID
        old_title: 旧标题（精确匹配）
        keep_id: 新 ID

    Returns:
        (new_body, changed_count)
    """
    # 剥除 code block/HTML comment 再扫 wiki link
    excluded_body = _strip_wiki_link_exclusions(body)
    spans = list(_WIKI_LINK_SPAN_RE.finditer(excluded_body))
    if not spans:
        return body, 0

    # 收集需要替换的 span（逆序，从后往前替换以保持 offset）
    replacements: List[Tuple[int, int, str]] = []  # (start, end, new_text)
    for m in reversed(spans):
        inner = m.group(1).strip()
        target_part = inner.split("|", 1)[0].split("#", 1)[0].strip()
        normalized = _normalize_wiki_link_title(inner)

        # 匹配条件：精确 ID 或精确标题
        if target_part == old_id or normalized.casefold() == old_title.casefold():
            # 保留 alias/anchor
            if "|" in inner:
                # [[target|alias]] → [[KEEP_ID|alias]]
                alias_part = inner.split("|", 1)[1]
                new_inner = f"{keep_id}|{alias_part}"
            elif "#" in inner.split("|", 1)[0]:
                # [[target#anchor]] → [[KEEP_ID#anchor]]
                anchor_part = inner.split("|", 1)[0].split("#", 1)[1]
                new_inner = f"{keep_id}#{anchor_part}"
            else:
                # [[target]] → [[KEEP_ID]]
                new_inner = keep_id

            replacements.append((m.start(), m.end(), f"[[{new_inner}]]"))

    # 执行替换
    if not replacements:
        return body, 0

    # 注意：excluded_body 的 offset 可能与 body 不同（剥除了 code block）
    # 所以需要在原始 body 上重新匹配并替换
    original_spans = list(_WIKI_LINK_SPAN_RE.finditer(body))
    original_replacements: List[Tuple[int, int, str]] = []

    for orig_m in reversed(original_spans):
        inner = orig_m.group(1).strip()
        target_part = inner.split("|", 1)[0].split("#", 1)[0].strip()
        normalized = _normalize_wiki_link_title(inner)

        if target_part == old_id or normalized.casefold() == old_title.casefold():
            if "|" in inner:
                alias_part = inner.split("|", 1)[1]
                new_inner = f"{keep_id}|{alias_part}"
            elif "#" in inner.split("|", 1)[0]:
                anchor_part = inner.split("|", 1)[0].split("#", 1)[1]
                new_inner = f"{keep_id}#{anchor_part}"
            else:
                new_inner = keep_id
            original_replacements.append((orig_m.start(), orig_m.end(), f"[[{new_inner}]]"))

    new_body = body
    for start, end, new_text in original_replacements:
        new_body = new_body[:start] + new_text + new_body[end:]

    return new_body, len(original_replacements)
