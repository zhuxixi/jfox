"""bookshelf 文件夹存储层：per-KB，<kb>/bookshelf/<slug>/。

纯文件管理，不进 chroma/bm25 索引。
"""

from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .meta import BookMeta, build_meta_from_bundle, normalize_user_meta

BUNDLE_DIRNAME = "bundle"
MANIFEST_FILENAME = "manifest.json"
META_FILENAME = "meta.json"


class BookAlreadyExistsError(Exception):
    """slug 已存在且未 --force。"""


class BookNotFoundError(Exception):
    """slug 不在书架上。"""


class InvalidBundleError(Exception):
    """输入文件夹不是合法 scan2book bundle。"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


class BookShelf:
    """一个知识库的书架：<base_dir>/bookshelf/<slug>/。"""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir)
        self.root = self.base_dir / "bookshelf"

    def book_dir(self, slug: str) -> Path:
        return self.root / slug

    def meta_path(self, slug: str) -> Path:
        return self.book_dir(slug) / META_FILENAME

    def exists(self, slug: str) -> bool:
        return self.meta_path(slug).exists()

    def list_books(self) -> List[BookMeta]:
        if not self.root.exists():
            return []
        out: List[BookMeta] = []
        for meta_file in sorted(self.root.glob("*/meta.json")):
            try:
                out.append(BookMeta.load(meta_file))
            except Exception:
                continue
        return out

    def get(self, slug: str) -> BookMeta:
        path = self.meta_path(slug)
        if not path.exists():
            raise BookNotFoundError(slug)
        return BookMeta.load(path)

    def page_path(self, slug: str, page: int) -> Path:
        # 与 scan2book 一致：p001.md（3 位零填充，>999 自然扩位）
        return self.book_dir(slug) / BUNDLE_DIRNAME / "pages" / f"p{page:03d}.md"

    def read_page(self, slug: str, page: int) -> str:
        path = self.page_path(slug, page)
        if not path.exists():
            raise BookNotFoundError(f"{slug} page {page}")
        return path.read_text(encoding="utf-8")

    def read_bundle_manifest(self, slug: str) -> Dict[str, Any]:
        """读 bundle/manifest.json（scan2book 产物），用于 show 的页清单。"""
        path = self.book_dir(slug) / BUNDLE_DIRNAME / MANIFEST_FILENAME
        if not path.exists():
            raise BookNotFoundError(f"{slug} bundle manifest")
        return json.loads(path.read_text(encoding="utf-8"))

    def add(
        self,
        src_folder: Path,
        *,
        slug: Optional[str] = None,
        move: bool = False,
        force: bool = False,
        added_at: Optional[str] = None,
    ) -> BookMeta:
        src_folder = Path(src_folder)
        manifest_path = src_folder / BUNDLE_DIRNAME / MANIFEST_FILENAME
        if not manifest_path.exists():
            raise InvalidBundleError(
                f"找不到 {manifest_path}（需要 scan2book 产物 bundle/manifest.json）"
            )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if slug is None:
            slug = manifest.get("slug") or src_folder.name
        self._validate_slug(slug)
        if self.exists(slug):
            if not force:
                raise BookAlreadyExistsError(slug)
            shutil.rmtree(self.book_dir(slug))
        original_file, original_sha256 = self._find_original(src_folder)
        if added_at is None:
            added_at = _now_iso()
        user_meta_path = src_folder / META_FILENAME
        if user_meta_path.exists():
            raw = json.loads(user_meta_path.read_text(encoding="utf-8"))
            raw.setdefault("source", {})
            # original_file/sha256 是"实际复制了哪个文件"的客观事实，以计算值为准
            # （覆盖用户值），否则 meta 指向的文件名可能和 dest/ 里真实文件对不上。
            raw["source"]["original_file"] = original_file or ""
            raw["source"]["original_sha256"] = original_sha256 or ""
            meta = normalize_user_meta(raw, slug=slug, added_at=added_at)
        else:
            meta = build_meta_from_bundle(
                slug=slug,
                bundle_manifest=manifest,
                original_file=original_file,
                original_sha256=original_sha256,
                added_at=added_at,
            )
        dest = self.book_dir(slug)
        dest.mkdir(parents=True, exist_ok=True)
        bundle_src = src_folder / BUNDLE_DIRNAME
        bundle_dst = dest / BUNDLE_DIRNAME
        if move:
            shutil.move(str(bundle_src), str(bundle_dst))
        else:
            shutil.copytree(str(bundle_src), str(bundle_dst))
        if original_file:
            orig_src = src_folder / original_file
            if orig_src.exists():
                if move:
                    shutil.move(str(orig_src), str(dest / original_file))
                else:
                    shutil.copy2(str(orig_src), str(dest / original_file))
        meta.save(self.meta_path(slug))
        return meta

    def remove(self, slug: str) -> None:
        d = self.book_dir(slug)
        if not d.exists():
            raise BookNotFoundError(slug)
        shutil.rmtree(d)

    @staticmethod
    def _validate_slug(slug: str) -> None:
        # 拒绝空、路径分隔符、Windows 非法字符、控制字符，以及 . / ..
        if not slug or slug in (".", ".."):
            raise InvalidBundleError(f"非法 slug: {slug!r}")
        forbidden = set('/:*?"<>|\\')
        if any(c in forbidden for c in slug) or any(ord(c) < 32 for c in slug):
            raise InvalidBundleError(f"非法 slug（含路径/非法字符）: {slug!r}")

    @staticmethod
    def _find_original(src_folder: Path):
        """挑 src_folder 顶层最大的文件作原件，返回 (filename, sha256) 或 (None, None)。"""
        candidates = [f for f in src_folder.iterdir() if f.is_file() and f.name != META_FILENAME]
        if not candidates:
            return None, None
        biggest = max(candidates, key=lambda f: f.stat().st_size)
        h = hashlib.sha256()
        with biggest.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return biggest.name, h.hexdigest()
