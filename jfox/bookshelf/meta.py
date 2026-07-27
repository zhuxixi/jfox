"""bookshelf 元数据：jfox 自有 meta.json，wrap scan2book bundle manifest。

与 scan2book 的 bundle/manifest.json 解耦：scan2book Phase 2 改 manifest 字段
通过 book.meta 透传，jfox schema 不用改。
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

SCHEMA_VERSION = 1


@dataclass
class BookMeta:
    """一本书在 jfox 书架上的元数据。"""

    slug: str
    title: str
    added_at: str  # ISO8601 带时区
    source: Dict[str, Any]
    book: Dict[str, Any]
    tags: List[str] = field(default_factory=list)
    distill: Dict[str, Any] = field(
        default_factory=lambda: {"status": "none", "reference_notes": []}
    )
    schema_version: int = SCHEMA_VERSION

    def to_dict(self) -> Dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "slug": self.slug,
            "title": self.title,
            "added_at": self.added_at,
            "source": self.source,
            "book": self.book,
            "tags": self.tags,
            "distill": self.distill,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2)

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(self.to_json(), encoding="utf-8")
        os.replace(tmp, path)  # 原子替换，中断不留半截 meta.json

    @classmethod
    def load(cls, path: Path) -> "BookMeta":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BookMeta":
        # cc-22：JSON 解出 list/null/str 等（非 dict）在此显式报错，被 list_books 捕获跳过
        if not isinstance(d, dict):
            raise ValueError(f"meta 不是 dict: {type(d).__name__}")
        # source/book/distill 防 non-dict：旧/手改 meta.json 可能含非 dict 字段，
        # 下游 .get() 会崩（kimi bookshelf-r13）。所有加载路径（list/show/get）经此兜底。
        src = d.get("source", {})
        bk = d.get("book", {})
        dl = d.get("distill")
        if not isinstance(dl, dict):
            # 新建独立实例，不复用模块级共享常量（cc r15：避免多 BookMeta 共享可变默认）
            dl = {"status": "none", "reference_notes": []}
        _tags = d.get("tags")
        return cls(
            slug=d.get("slug", ""),
            title=d.get("title", d.get("slug", "")),
            added_at=d.get("added_at", ""),
            source=src if isinstance(src, dict) else {},
            book=bk if isinstance(bk, dict) else {},
            # cc-5：非 list 不拆字符/不崩
            tags=list(_tags) if isinstance(_tags, list) else [],
            distill=dl,
            schema_version=d.get("schema_version", SCHEMA_VERSION),
        )


def build_meta_from_bundle(
    *,
    slug: str,
    bundle_manifest: Dict[str, Any],
    original_file: Optional[str],
    original_sha256: Optional[str],
    extractor: str = "scan2book",
    extractor_version: str = "",
    added_at: str,
) -> BookMeta:
    """从 scan2book bundle/manifest.json + 原件信息构造 BookMeta。"""
    meta_block = bundle_manifest.get("meta", {})
    # kimi r15 issue-35：manifest.meta 非 dict 时 .get("title") 会崩，兜底为 {}
    if not isinstance(meta_block, dict):
        meta_block = {}
    title = meta_block.get("title") or slug
    page_count = int(bundle_manifest.get("page_count", 0))
    return BookMeta(
        slug=slug,
        title=title,
        added_at=added_at,
        source={
            "original_file": original_file or "",
            "original_sha256": original_sha256 or "",
            "extractor": extractor,
            "extractor_version": extractor_version,
            "bundle_dir": "bundle",
            "bundle_manifest": "bundle/manifest.json",
        },
        book={
            "page_count": page_count,
            "pages_dir": "bundle/pages",
            "images_dir": "bundle/images",
            "meta": meta_block,
        },
    )


def normalize_user_meta(d: Dict[str, Any], *, slug: str, added_at: str) -> BookMeta:
    """校验/归一化用户提供的 meta dict。

    强制 schema_version=SCHEMA_VERSION、added_at 与 slug 为传入值；
    distill.status 只允许 none/partial/done，否则回退 none。
    """
    meta = BookMeta.from_dict(d)
    meta.slug = slug
    meta.added_at = added_at
    meta.schema_version = SCHEMA_VERSION
    status = (meta.distill or {}).get("status", "none")
    if status not in ("none", "partial", "done"):
        status = "none"
    notes = (meta.distill or {}).get("reference_notes", [])
    meta.distill = {
        "status": status,
        "reference_notes": list(notes) if isinstance(notes, list) else [],  # cc-5
    }
    return meta


__all__ = [
    "SCHEMA_VERSION",
    "BookMeta",
    "build_meta_from_bundle",
    "normalize_user_meta",
]
