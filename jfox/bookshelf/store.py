"""bookshelf 文件夹存储层：per-KB，<kb>/bookshelf/<slug>/。

纯文件管理，不进 chroma/bm25 索引。
"""

from __future__ import annotations

from pathlib import Path
from typing import List

from .meta import BookMeta

BUNDLE_DIRNAME = "bundle"
MANIFEST_FILENAME = "manifest.json"
META_FILENAME = "meta.json"


class BookAlreadyExistsError(Exception):
    """slug 已存在且未 --force。"""


class BookNotFoundError(Exception):
    """slug 不在书架上。"""


class InvalidBundleError(Exception):
    """输入文件夹不是合法 scan2book bundle。"""


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
