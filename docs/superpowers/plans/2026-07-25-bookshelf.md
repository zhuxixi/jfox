# bookshelf 子命令 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 jfox 加一个 `bookshelf` 子命令，把好书（PDF 原件 + scan2book 抽取的 bundle + jfox 自有元数据）作为资产管进每个知识库，纯文件管理、不进索引、不搜索。

**Architecture:** per-KB 的 `bookshelf/<slug>/` 目录与 `notes/` 平级。三层模块镜像 `jfox/fragment/`：`meta.py`（元数据 dataclass + schema）、`store.py`（文件系统 CRUD）、`cli.py`（Typer sub-app，`--kb`/`--format json` 沿用全仓惯例）。不碰 chroma/bm25、不碰 note 生命周期。

**Tech Stack:** Python ≥3.10，stdlib（pathlib/json/shutil/hashlib/datetime）+ 已有依赖 typer/rich。无新依赖。

## Global Constraints

- spec：`docs/superpowers/specs/2026-07-25-bookshelf-design.md`（commit `99e18c8`）。本计划不得偏离 spec 的非目标（不进索引、不 search、不 OCR、不调 scan2book）。
- 行宽 100；注释/文档中文；`from __future__ import annotations` 置顶。
- **提交前必须 ruff 和 black 都过**：`uv run ruff check jfox/bookshelf tests/unit/bookshelf` 且 `uv run --with black==26.3.1 black --check jfox/bookshelf tests/unit/bookshelf`（CI lint 两步，只跑 ruff 会挂）。
- 测试须为快速单元/集成测试：不加载 embedding、不碰 ChromaDB、不触发 `embedding`/`slow` 自动标记（文件名/用例名不含 search/embedding/semantic/bulk）。
- 跨平台路径：测试断言用 `Path` / `str(Path(...))`，不硬编码 unix 路径串（windows CI 会挂）。
- 打包：`pyproject.toml` 里 `packages = ["jfox"]`，新建 `jfox/bookshelf/` 自动随包发布，**不改 pyproject**。
- per-KB：所有读写经 `with use_kb(kb):` 包裹，`BookShelf(config.base_dir)` 在块内构造以捕获正确 KB 根。

## File Structure

| 文件 | 职责 |
|------|------|
| `jfox/bookshelf/__init__.py` | 子包导出（`BookMeta`、`BookShelf`） |
| `jfox/bookshelf/meta.py` | `BookMeta` dataclass + `build_meta_from_bundle` / `normalize_user_meta`（jfox 自有 meta.json schema，wrap scan2book manifest） |
| `jfox/bookshelf/store.py` | `BookShelf`：文件夹 CRUD（list/get/page/add/remove）+ 3 个异常 |
| `jfox/bookshelf/cli.py` | `bookshelf_app` Typer sub-app：add/list/show/remove |
| `jfox/cli.py` | 修改：注册 `bookshelf_app`（~L119 后两行） |
| `tests/unit/bookshelf/__init__.py` | 空包标识（`tests/unit/__init__.py` 已存在，子目录须跟进） |
| `tests/unit/bookshelf/conftest.py` | `make_book_folder` fixture：造假 scan2book bundle 文件夹 |
| `tests/unit/bookshelf/test_meta.py` | meta.py 单元测试 |
| `tests/unit/bookshelf/test_store.py` | store.py 单元测试 |
| `tests/unit/bookshelf/test_cli.py` | cli.py 集成测试（subprocess via `cli_fast`） |
| `packages/cc-plugin/skills/bookshelf/SKILL.md` | 极简 cc-plugin skill |
| `CLAUDE.md` | 模块表加 bookshelf 行 |

公契（锁定，跨任务不得改名）：

- `meta.py`：`SCHEMA_VERSION=1`；`@dataclass BookMeta(slug, title, added_at, source, book, tags, distill, schema_version)`，方法 `to_dict()/to_json()/save(path)/load(path)/from_dict(d)`；`build_meta_from_bundle(*, slug, bundle_manifest, original_file, original_sha256, extractor="scan2book", extractor_version="", added_at) -> BookMeta`；`normalize_user_meta(d, *, slug, added_at) -> BookMeta`。
- `store.py`：常量 `BUNDLE_DIRNAME="bundle"`、`MANIFEST_FILENAME="manifest.json"`、`META_FILENAME="meta.json"`；异常 `BookAlreadyExistsError`、`BookNotFoundError`、`InvalidBundleError`；`class BookShelf(base_dir)` 方法 `book_dir(slug)/meta_path(slug)/exists(slug)/list_books()/get(slug)/page_path(slug,page)/read_page(slug,page)/add(src_folder,*,slug=None,move=False,force=False,added_at=None)/remove(slug)`。

---

### Task 1: meta.py — BookMeta + 构造器

**Files:**
- Create: `jfox/bookshelf/__init__.py`
- Create: `jfox/bookshelf/meta.py`
- Create: `tests/unit/bookshelf/__init__.py`（空）
- Test: `tests/unit/bookshelf/test_meta.py`

**Interfaces:**
- Produces: `BookMeta`、`build_meta_from_bundle`、`normalize_user_meta`、`SCHEMA_VERSION`（Task 2/3/4 依赖）。

- [ ] **Step 1: 写失败测试** `tests/unit/bookshelf/test_meta.py`

先建空包标识 `tests/unit/bookshelf/__init__.py`（空文件，使 pytest 能把 bookshelf 当作 `tests.unit` 的子包发现——`tests/unit/__init__.py` 已存在）。

```python
"""bookshelf meta.py 单元测试。"""

from jfox.bookshelf.meta import (
    SCHEMA_VERSION,
    BookMeta,
    build_meta_from_bundle,
    normalize_user_meta,
)


def _sample_manifest(title="Sapiens", page_count=3):
    return {
        "slug": "sapiens",
        "meta": {"title": title},
        "page_count": page_count,
        "pages": [
            {"page": 1, "md": "pages/p001.md", "image": "images/p001.jpg", "chars": 10, "has_image": True}
        ],
    }


def test_build_meta_basic():
    meta = build_meta_from_bundle(
        slug="sapiens",
        bundle_manifest=_sample_manifest(),
        original_file="original.pdf",
        original_sha256="abc123",
        added_at="2026-07-25T20:42:00+08:00",
    )
    assert meta.slug == "sapiens"
    assert meta.title == "Sapiens"
    assert meta.book["page_count"] == 3
    assert meta.book["meta"] == {"title": "Sapiens"}
    assert meta.source["original_file"] == "original.pdf"
    assert meta.source["original_sha256"] == "abc123"
    assert meta.source["extractor"] == "scan2book"
    assert meta.distill == {"status": "none", "reference_notes": []}
    assert meta.schema_version == SCHEMA_VERSION


def test_build_meta_title_falls_back_to_slug():
    meta = build_meta_from_bundle(
        slug="fallback-slug",
        bundle_manifest={"slug": "x", "meta": {}, "page_count": 0, "pages": []},
        original_file=None,
        original_sha256=None,
        added_at="2026-07-25T20:42:00+08:00",
    )
    assert meta.title == "fallback-slug"
    assert meta.source["original_file"] == ""


def test_meta_roundtrip(tmp_path):
    meta = build_meta_from_bundle(
        slug="sapiens",
        bundle_manifest=_sample_manifest(),
        original_file="original.pdf",
        original_sha256="abc123",
        added_at="2026-07-25T20:42:00+08:00",
    )
    path = tmp_path / "meta.json"
    meta.save(path)
    loaded = BookMeta.load(path)
    assert loaded.slug == meta.slug
    assert loaded.title == meta.title
    assert loaded.book == meta.book
    assert loaded.source == meta.source


def test_normalize_user_meta_forces_fields():
    user = {
        "slug": "ignored",
        "title": "Keep Me",
        "added_at": "old",
        "source": {"original_file": "x.pdf"},
        "book": {"page_count": 10},
        "tags": ["history"],
        "schema_version": 999,
        "distill": {"status": "weird", "reference_notes": ["n1"]},
    }
    meta = normalize_user_meta(user, slug="real-slug", added_at="2026-07-25T20:42:00+08:00")
    assert meta.slug == "real-slug"
    assert meta.added_at == "2026-07-25T20:42:00+08:00"
    assert meta.schema_version == SCHEMA_VERSION
    assert meta.title == "Keep Me"
    assert meta.tags == ["history"]
    assert meta.distill == {"status": "none", "reference_notes": ["n1"]}


def test_to_dict_canonical_order():
    meta = build_meta_from_bundle(
        slug="sapiens",
        bundle_manifest=_sample_manifest(),
        original_file="original.pdf",
        original_sha256="abc123",
        added_at="2026-07-25T20:42:00+08:00",
    )
    assert list(meta.to_dict().keys()) == [
        "schema_version", "slug", "title", "added_at", "source", "book", "tags", "distill",
    ]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/bookshelf/test_meta.py -v`
Expected: FAIL（`No module named 'jfox.bookshelf.meta'`）

- [ ] **Step 3: 写实现** `jfox/bookshelf/meta.py`

```python
"""bookshelf 元数据：jfox 自有 meta.json，wrap scan2book bundle manifest。

与 scan2book 的 bundle/manifest.json 解耦：scan2book Phase 2 改 manifest 字段
通过 book.meta 透传，jfox schema 不用改。
"""

from __future__ import annotations

import json
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
        path.write_text(self.to_json(), encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "BookMeta":
        return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "BookMeta":
        return cls(
            slug=d["slug"],
            title=d.get("title", d["slug"]),
            added_at=d.get("added_at", ""),
            source=d.get("source", {}),
            book=d.get("book", {}),
            tags=list(d.get("tags", [])),
            distill=d.get("distill", {"status": "none", "reference_notes": []}),
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
    meta.distill = {"status": status, "reference_notes": list(notes)}
    return meta


__all__ = [
    "SCHEMA_VERSION",
    "BookMeta",
    "build_meta_from_bundle",
    "normalize_user_meta",
]
```

`jfox/bookshelf/__init__.py`：

```python
"""JFox bookshelf 子包：好书资产管理（PDF + scan2book bundle + 元数据）。"""

from .meta import BookMeta, build_meta_from_bundle, normalize_user_meta

__all__ = ["BookMeta", "build_meta_from_bundle", "normalize_user_meta"]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/bookshelf/test_meta.py -v`
Expected: PASS（5 用例）

- [ ] **Step 5: 提交**

```bash
uv run ruff check jfox/bookshelf tests/unit/bookshelf && \
uv run --with black==26.3.1 black --check jfox/bookshelf tests/unit/bookshelf && \
git add jfox/bookshelf/__init__.py jfox/bookshelf/meta.py tests/unit/bookshelf/__init__.py tests/unit/bookshelf/test_meta.py && \
git commit -m "feat(bookshelf): meta schema + BookMeta (#325)"
```

---

### Task 2: store.py 读侧（list/get/page）

**Files:**
- Create: `jfox/bookshelf/store.py`
- Create: `tests/unit/bookshelf/conftest.py`
- Test: `tests/unit/bookshelf/test_store.py`

**Interfaces:**
- Consumes: `BookMeta`（Task 1）。
- Produces: `BookShelf`（读方法）、`BookNotFoundError`、`InvalidBundleError`、`BookAlreadyExistsError`、常量、`make_book_folder` fixture（Task 3/4/5/6 用）。

- [ ] **Step 1: 写测试夹具** `tests/unit/bookshelf/conftest.py`

```python
"""bookshelf 测试共用 fixture。"""

import json
from pathlib import Path

import pytest


@pytest.fixture
def make_book_folder(tmp_path):
    """工厂：在 tmp_path/src/<slug> 下造假 scan2book bundle 文件夹。

    返回该文件夹 Path。默认 3 页 + original.pdf、无用户 meta.json。
    重复同名调用会覆盖（exist_ok），供 collision/force 测试用。
    """

    def _make(
        *,
        slug: str = "sapiens",
        title: str = "Sapiens",
        pages: int = 3,
        with_original: bool = True,
        original_name: str = "original.pdf",
        with_meta: dict | None = None,
    ) -> Path:
        folder = tmp_path / "src" / slug
        bundle = folder / "bundle"
        (bundle / "pages").mkdir(parents=True, exist_ok=True)
        (bundle / "images").mkdir(parents=True, exist_ok=True)
        pages_list = []
        for i in range(1, pages + 1):
            (bundle / "pages" / f"p{i:03d}.md").write_text(
                f"# page {i}\n第 {i} 页内容", encoding="utf-8"
            )
            (bundle / "images" / f"p{i:03d}.jpg").write_bytes(b"\xff\xd8\xff\xe0")
            pages_list.append(
                {
                    "page": i,
                    "md": f"pages/p{i:03d}.md",
                    "image": f"images/p{i:03d}.jpg",
                    "chars": 10,
                    "has_image": True,
                }
            )
        manifest = {
            "slug": slug,
            "meta": {"title": title},
            "page_count": pages,
            "pages": pages_list,
        }
        (bundle / "manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
        )
        if with_original:
            (folder / original_name).write_bytes(b"%PDF-1.4 fake content")
        if with_meta is not None:
            (folder / "meta.json").write_text(
                json.dumps(with_meta, ensure_ascii=False), encoding="utf-8"
            )
        return folder

    return _make
```

- [ ] **Step 2: 写失败测试** `tests/unit/bookshelf/test_store.py`

```python
"""bookshelf store.py 单元测试。"""

import shutil

import pytest

from jfox.bookshelf.meta import build_meta_from_bundle
from jfox.bookshelf.store import BookNotFoundError, BookShelf


@pytest.fixture
def shelf_with_book(tmp_path, make_book_folder):
    """装好一本书的 shelf（手动落盘，不依赖 add）。"""
    shelf = BookShelf(tmp_path)
    folder = make_book_folder(slug="sapiens", title="Sapiens", pages=3, with_original=False)
    dest = shelf.book_dir("sapiens")
    shutil.copytree(folder / "bundle", dest / "bundle")
    meta = build_meta_from_bundle(
        slug="sapiens",
        bundle_manifest={"meta": {"title": "Sapiens"}, "page_count": 3, "pages": []},
        original_file=None,
        original_sha256=None,
        added_at="2026-07-25T20:42:00+08:00",
    )
    meta.save(shelf.meta_path("sapiens"))
    return shelf


def test_list_books_empty(tmp_path):
    assert BookShelf(tmp_path).list_books() == []


def test_list_books_returns_meta(shelf_with_book):
    books = shelf_with_book.list_books()
    assert len(books) == 1
    assert books[0].slug == "sapiens"
    assert books[0].title == "Sapiens"


def test_get_existing(shelf_with_book):
    assert shelf_with_book.get("sapiens").slug == "sapiens"


def test_get_missing_raises(tmp_path):
    with pytest.raises(BookNotFoundError):
        BookShelf(tmp_path).get("nope")


def test_exists(shelf_with_book):
    assert shelf_with_book.exists("sapiens")
    assert not shelf_with_book.exists("nope")


def test_read_page(shelf_with_book):
    assert "第 1 页内容" in shelf_with_book.read_page("sapiens", 1)


def test_read_page_missing_raises(shelf_with_book):
    with pytest.raises(BookNotFoundError):
        shelf_with_book.read_page("sapiens", 99)


def test_page_path_zero_padded(shelf_with_book):
    assert shelf_with_book.page_path("sapiens", 1).name == "p001.md"
```

- [ ] **Step 3: 跑测试确认失败**

Run: `uv run pytest tests/unit/bookshelf/test_store.py -v`
Expected: FAIL（`No module named 'jfox.bookshelf.store'`）

- [ ] **Step 4: 写实现** `jfox/bookshelf/store.py`（读侧；写侧 Task 3 追加）

```python
"""bookshelf 文件夹存储层：per-KB，<kb>/bookshelf/<slug>/。

纯文件管理，不进 chroma/bm25 索引。
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

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
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/unit/bookshelf/test_store.py -v`
Expected: PASS（8 用例）

- [ ] **Step 6: 提交**

```bash
uv run ruff check jfox/bookshelf tests/unit/bookshelf && \
uv run --with black==26.3.1 black --check jfox/bookshelf tests/unit/bookshelf && \
git add jfox/bookshelf/store.py tests/unit/bookshelf/conftest.py tests/unit/bookshelf/test_store.py && \
git commit -m "feat(bookshelf): BookShelf read side + test fixture (#325)"
```

---

### Task 3: store.py 写侧（add + remove）

**Files:**
- Modify: `jfox/bookshelf/store.py`（顶部 imports + 追加 `add`/`remove`/helpers）
- Modify: `jfox/bookshelf/__init__.py`（导出 `BookShelf`）
- Test: `tests/unit/bookshelf/test_store.py`（追加写侧用例）

**Interfaces:**
- Produces: `BookShelf.add` / `BookShelf.remove`（Task 4 cli 依赖）。

- [ ] **Step 1: 追加失败测试**（`tests/unit/bookshelf/test_store.py` 末尾）

```python
def test_add_copy_default(tmp_path, make_book_folder):
    from jfox.bookshelf.store import InvalidBundleError  # noqa: F401  (保证可导入)

    shelf = BookShelf(tmp_path)
    folder = make_book_folder(slug="sapiens", pages=3)
    meta = shelf.add(folder, added_at="2026-07-25T20:42:00+08:00")
    assert meta.slug == "sapiens"
    assert meta.title == "Sapiens"
    assert meta.book["page_count"] == 3
    assert meta.source["original_file"] == "original.pdf"
    assert meta.source["original_sha256"]
    assert (folder / "original.pdf").exists()  # 复制，原件还在
    assert shelf.exists("sapiens")
    assert (shelf.book_dir("sapiens") / "bundle" / "pages" / "p001.md").exists()
    assert (shelf.book_dir("sapiens") / "original.pdf").exists()


def test_add_move_removes_source(tmp_path, make_book_folder):
    shelf = BookShelf(tmp_path)
    folder = make_book_folder(slug="mv", pages=1)
    shelf.add(folder, move=True, added_at="t")
    assert not (folder / "bundle").exists()
    assert not (folder / "original.pdf").exists()
    assert shelf.exists("mv")


def test_add_collision_rejected(tmp_path, make_book_folder):
    from jfox.bookshelf.store import BookAlreadyExistsError

    shelf = BookShelf(tmp_path)
    shelf.add(make_book_folder(slug="dup", pages=1), added_at="t")
    with pytest.raises(BookAlreadyExistsError):
        shelf.add(make_book_folder(slug="dup", pages=1), added_at="t")


def test_add_force_overwrites(tmp_path, make_book_folder):
    shelf = BookShelf(tmp_path)
    shelf.add(make_book_folder(slug="dup", title="Old", pages=1), added_at="t")
    shelf.add(make_book_folder(slug="dup", title="New", pages=2), force=True, added_at="t2")
    meta = shelf.get("dup")
    assert meta.title == "New"
    assert meta.book["page_count"] == 2
    assert meta.added_at == "t2"


def test_add_without_manifest_raises(tmp_path):
    from jfox.bookshelf.store import InvalidBundleError

    shelf = BookShelf(tmp_path)
    bad = tmp_path / "src" / "bad"
    (bad / "bundle").mkdir(parents=True)
    with pytest.raises(InvalidBundleError):
        shelf.add(bad, added_at="t")


def test_add_user_meta_normalized(tmp_path, make_book_folder):
    from jfox.bookshelf.meta import SCHEMA_VERSION

    shelf = BookShelf(tmp_path)
    user_meta = {
        "slug": "ignored",
        "title": "My Title",
        "added_at": "old",
        "source": {"original_file": "x.pdf"},
        "book": {"page_count": 5},
        "tags": ["t1"],
        "schema_version": 999,
    }
    folder = make_book_folder(slug="um", pages=2, with_meta=user_meta)
    meta = shelf.add(folder, added_at="2026-07-25T20:42:00+08:00")
    assert meta.slug == "um"
    assert meta.title == "My Title"
    assert meta.schema_version == SCHEMA_VERSION
    assert meta.tags == ["t1"]


def test_add_slug_from_manifest_when_none(tmp_path, make_book_folder):
    shelf = BookShelf(tmp_path)
    folder = make_book_folder(slug="manifest-slug", pages=1)
    assert shelf.add(folder, added_at="t").slug == "manifest-slug"


def test_add_invalid_slug_rejected(tmp_path, make_book_folder):
    from jfox.bookshelf.store import InvalidBundleError

    shelf = BookShelf(tmp_path)
    folder = make_book_folder(slug="ok", pages=1)
    with pytest.raises(InvalidBundleError):
        shelf.add(folder, slug="bad/slug", added_at="t")


def test_remove(tmp_path, make_book_folder):
    shelf = BookShelf(tmp_path)
    shelf.add(make_book_folder(slug="rm", pages=1), added_at="t")
    assert shelf.exists("rm")
    shelf.remove("rm")
    assert not shelf.exists("rm")


def test_remove_missing_raises(tmp_path):
    with pytest.raises(BookNotFoundError):
        BookShelf(tmp_path).remove("nope")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/bookshelf/test_store.py -v`
Expected: 新增用例 FAIL（`BookShelf` 无 `add` 属性）

- [ ] **Step 3: 改 store.py 顶部 imports**

把 `store.py` 顶部 import 段替换为（加 `hashlib`/`shutil`/`datetime`/`Any`/`Dict` 与 `build_meta_from_bundle`/`normalize_user_meta`）：

```python
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .meta import BookMeta, build_meta_from_bundle, normalize_user_meta
```

- [ ] **Step 4: 在 `BookShelf` 内追加 `add` / `remove` / helpers**（放在 `read_page` 之后、类结束前）

```python
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
            meta = normalize_user_meta(
                json.loads(user_meta_path.read_text(encoding="utf-8")),
                slug=slug,
                added_at=added_at,
            )
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
        if not slug or "/" in slug or "\\" in slug or slug in (".", ".."):
            raise InvalidBundleError(f"非法 slug: {slug!r}")

    @staticmethod
    def _find_original(src_folder: Path):
        """挑 src_folder 顶层最大的文件作原件，返回 (filename, sha256) 或 (None, None)。"""
        candidates = [
            f for f in src_folder.iterdir() if f.is_file() and f.name != META_FILENAME
        ]
        if not candidates:
            return None, None
        biggest = max(candidates, key=lambda f: f.stat().st_size)
        h = hashlib.sha256()
        with biggest.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return biggest.name, h.hexdigest()
```

在模块级（类外，`__all__` 之前）追加：

```python
def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
```

- [ ] **Step 5: 更新 `jfox/bookshelf/__init__.py` 导出 `BookShelf`**

```python
"""JFox bookshelf 子包：好书资产管理（PDF + scan2book bundle + 元数据）。"""

from .meta import BookMeta, build_meta_from_bundle, normalize_user_meta
from .store import BookAlreadyExistsError, BookNotFoundError, BookShelf, InvalidBundleError

__all__ = [
    "BookMeta",
    "BookShelf",
    "BookAlreadyExistsError",
    "BookNotFoundError",
    "InvalidBundleError",
    "build_meta_from_bundle",
    "normalize_user_meta",
]
```

- [ ] **Step 6: 跑测试确认通过**

Run: `uv run pytest tests/unit/bookshelf/ -v`
Expected: PASS（meta 5 + store 18）

- [ ] **Step 7: 提交**

```bash
uv run ruff check jfox/bookshelf tests/unit/bookshelf && \
uv run --with black==26.3.1 black --check jfox/bookshelf tests/unit/bookshelf && \
git add jfox/bookshelf/store.py jfox/bookshelf/__init__.py tests/unit/bookshelf/test_store.py && \
git commit -m "feat(bookshelf): BookShelf add/remove (#325)"
```

---

### Task 4: cli.py sub-app + add 命令 + 接线

**Files:**
- Create: `jfox/bookshelf/cli.py`
- Modify: `jfox/cli.py`（~L119 后注册 sub-app）
- Test: `tests/unit/bookshelf/test_cli.py`

**Interfaces:**
- Consumes: `BookShelf.add`（Task 3）、`config`/`use_kb`（`jfox.config`）。
- Produces: `bookshelf_app`（`jfox/cli.py` 注册）。

- [ ] **Step 1: 写失败测试** `tests/unit/bookshelf/test_cli.py`

```python
"""bookshelf CLI 集成测试（subprocess via cli_fast）。"""


def test_add_json(cli_fast, make_book_folder):
    folder = make_book_folder(slug="sapiens", title="Sapiens", pages=3)
    result = cli_fast.run("bookshelf", "add", str(folder))
    assert result.success, result.stderr
    data = result.json()
    assert data["success"] is True
    assert data["slug"] == "sapiens"
    assert data["title"] == "Sapiens"
    assert data["page_count"] == 3


def test_add_collision_rejected(cli_fast, make_book_folder):
    cli_fast.run("bookshelf", "add", str(make_book_folder(slug="dup", pages=1)))
    result = cli_fast.run("bookshelf", "add", str(make_book_folder(slug="dup", pages=1)))
    assert not result.success
    err = (result.json() or {}).get("error", "")
    assert "已存在" in err


def test_add_force(cli_fast, make_book_folder):
    cli_fast.run("bookshelf", "add", str(make_book_folder(slug="dup", title="Old", pages=1)))
    cli_fast.run("bookshelf", "add", str(make_book_folder(slug="dup", title="New", pages=2)), "--force")
    listing = cli_fast.run("bookshelf", "list").json()
    book = [b for b in listing["books"] if b["slug"] == "dup"][0]
    assert book["title"] == "New"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/bookshelf/test_cli.py -v`
Expected: FAIL（`No such command 'bookshelf'`）

- [ ] **Step 3: 写实现** `jfox/bookshelf/cli.py`

```python
"""bookshelf CLI 子命令组：jfox bookshelf add/list/show/remove。"""

from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Any, Dict, Optional

import typer
from rich.console import Console
from rich.table import Table

from ..config import config, use_kb
from .store import (
    BookAlreadyExistsError,
    BookNotFoundError,
    BookShelf,
    InvalidBundleError,
)

console = Console(legacy_windows=False)
_json_console = Console(legacy_windows=False, highlight=False, markup=False, no_color=True)

bookshelf_app = typer.Typer(
    name="bookshelf",
    help="管理好书书架：PDF + 抽取 bundle + 元数据",
    no_args_is_help=True,
)


def _shelf() -> BookShelf:
    return BookShelf(config.base_dir)


def _emit_json(data: Any) -> None:
    _json_console.print(_json.dumps(data, ensure_ascii=False, indent=2))


def _fail(message: str, output_format: str) -> None:
    if output_format == "json":
        _json_console.print(_json.dumps({"success": False, "error": message}, ensure_ascii=False))
    else:
        console.print(f"[red]{message}[/red]")
    raise typer.Exit(code=1)


@bookshelf_app.command("add")
def add_cmd(
    folder: str = typer.Argument(..., help="书文件夹（含 bundle/ + 可选 meta.json + 原件）"),
    force: bool = typer.Option(False, "--force", help="同名 slug 覆盖重加"),
    move: bool = typer.Option(False, "--move", help="移动原件而非复制"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(False, "--json", help="JSON 输出（等同 --format json）"),
) -> None:
    """把一本书加进书架。"""
    if json_output:
        output_format = "json"
    try:
        with use_kb(kb):
            shelf = _shelf()
            meta = shelf.add(Path(folder), move=move, force=force)
            data = {
                "success": True,
                "slug": meta.slug,
                "title": meta.title,
                "page_count": meta.book.get("page_count", 0),
                "path": str(shelf.book_dir(meta.slug)),
            }
    except BookAlreadyExistsError as e:
        _fail(f"书 '{e}' 已存在；用 --force 覆盖重加", output_format)
        return
    except InvalidBundleError as e:
        _fail(str(e), output_format)
        return
    if output_format == "json":
        _emit_json(data)
    else:
        console.print(f"[green]已加入书架[/green] {meta.title}")
        console.print(f"  slug:  {meta.slug}")
        console.print(f"  页数:  {meta.book.get('page_count', 0)}")
        console.print(f"  路径:  {shelf.book_dir(meta.slug)}")


__all__ = ["bookshelf_app"]
```

- [ ] **Step 4: 在 `jfox/cli.py` 注册 sub-app**（在 `gem-synth` 块之后，约 L119 后）

定位现有：
```python
app.add_typer(gem_synth_app, name="gem-synth", help="L3 宝石合成进度查看")
```
在其后插入：
```python
# bookshelf 子命令组（好书资产管理）
from .bookshelf.cli import bookshelf_app  # noqa: E402

app.add_typer(bookshelf_app, name="bookshelf", help="管理好书书架：PDF + 抽取 bundle + 元数据")
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/unit/bookshelf/test_cli.py -v`
Expected: PASS（3 用例；`test_add_force` 依赖 Task 5 的 list，先注释掉或一起跑到 Task 5 再全绿——若 Task 4 跑挂在 `list`，把 `test_add_force` 暂时跳过，Task 5 补齐后取消）

> 注：`test_add_force` 用到 `bookshelf list`，Task 5 才实现。Task 4 可先只跑 `test_add_json`/`test_add_collision_rejected`，Task 5 完成后整文件全绿。

- [ ] **Step 6: 提交**

```bash
uv run ruff check jfox/bookshelf tests/unit/bookshelf && \
uv run --with black==26.3.1 black --check jfox/bookshelf tests/unit/bookshelf && \
git add jfox/bookshelf/cli.py jfox/cli.py tests/unit/bookshelf/test_cli.py && \
git commit -m "feat(bookshelf): cli sub-app + add command (#325)"
```

---

### Task 5: cli list + show

**Files:**
- Modify: `jfox/bookshelf/cli.py`（追加 `list_cmd`/`show_cmd`）
- Test: `tests/unit/bookshelf/test_cli.py`（追加）

**Interfaces:**
- Produces: `bookshelf list`、`bookshelf show`。

- [ ] **Step 1: 追加失败测试**

```python
def test_list_empty(cli_fast):
    data = cli_fast.run("bookshelf", "list").json()
    assert data["total"] == 0
    assert data["books"] == []


def test_list_after_add(cli_fast, make_book_folder):
    cli_fast.run("bookshelf", "add", str(make_book_folder(slug="a", title="Aaa", pages=2)))
    cli_fast.run("bookshelf", "add", str(make_book_folder(slug="b", title="Bbb", pages=4)))
    data = cli_fast.run("bookshelf", "list").json()
    assert {b["slug"] for b in data["books"]} == {"a", "b"}


def test_show_meta_json(cli_fast, make_book_folder):
    cli_fast.run("bookshelf", "add", str(make_book_folder(slug="sapiens", title="Sapiens", pages=3)))
    data = cli_fast.run("bookshelf", "show", "sapiens").json()
    assert data["slug"] == "sapiens"
    assert data["title"] == "Sapiens"
    assert data["book"]["page_count"] == 3


def test_show_page_json(cli_fast, make_book_folder):
    cli_fast.run("bookshelf", "add", str(make_book_folder(slug="sapiens", pages=3)))
    data = cli_fast.run("bookshelf", "show", "sapiens", "--page", "1").json()
    assert data["page"] == 1
    assert "第 1 页内容" in data["content"]


def test_show_missing(cli_fast):
    result = cli_fast.run("bookshelf", "show", "nope")
    assert not result.success
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/bookshelf/test_cli.py -v`
Expected: 新 list/show 用例 FAIL

- [ ] **Step 3: 在 `cli.py` 追加 `list_cmd`/`show_cmd`**（`add_cmd` 之后、`__all__` 之前）

```python
@bookshelf_app.command("list")
def list_cmd(
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(False, "--json", help="JSON 输出（等同 --format json）"),
) -> None:
    """列出书架上的书。"""
    if json_output:
        output_format = "json"
    with use_kb(kb):
        shelf = _shelf()
        rows = [
            {
                "slug": m.slug,
                "title": m.title,
                "page_count": m.book.get("page_count", 0),
                "added_at": m.added_at,
                "distill_status": (m.distill or {}).get("status", "none"),
            }
            for m in shelf.list_books()
        ]
    if output_format == "json":
        _emit_json({"books": rows, "total": len(rows)})
        return
    table = Table(title=f"书架（共 {len(rows)} 本）")
    for col in ("slug", "title", "page_count", "added_at", "distill"):
        table.add_column(col)
    for r in rows:
        table.add_row(
            r["slug"], r["title"], str(r["page_count"]), r["added_at"], r["distill_status"]
        )
    console.print(table)


@bookshelf_app.command("show")
def show_cmd(
    slug: str = typer.Argument(..., help="书 slug"),
    page: Optional[int] = typer.Option(None, "--page", "-p", help="打印指定页的 md（页号，如 1）"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(False, "--json", help="JSON 输出（等同 --format json）"),
) -> None:
    """查看一本书的元数据或指定页内容。"""
    if json_output:
        output_format = "json"
    try:
        with use_kb(kb):
            shelf = _shelf()
            if page is not None:
                text = shelf.read_page(slug, page)
                if output_format == "json":
                    _emit_json({"slug": slug, "page": page, "content": text})
                else:
                    print(text)
                return
            meta = shelf.get(slug)
            data: Dict[str, Any] = meta.to_dict()
            data["path"] = str(shelf.book_dir(slug))
    except BookNotFoundError as e:
        _fail(f"找不到书/页：{e}", output_format)
        return
    if output_format == "json":
        _emit_json(data)
    else:
        console.print(f"[bold]{meta.title}[/bold]  ({meta.slug})")
        console.print(f"页数: {meta.book.get('page_count', 0)}  添加于: {meta.added_at}")
        console.print(f"路径: {shelf.book_dir(slug)}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/bookshelf/test_cli.py -v`
Expected: PASS（含 Task 4 的 `test_add_force`）

- [ ] **Step 5: 提交**

```bash
uv run ruff check jfox/bookshelf tests/unit/bookshelf && \
uv run --with black==26.3.1 black --check jfox/bookshelf tests/unit/bookshelf && \
git add jfox/bookshelf/cli.py tests/unit/bookshelf/test_cli.py && \
git commit -m "feat(bookshelf): list + show commands (#325)"
```

---

### Task 6: cli remove

**Files:**
- Modify: `jfox/bookshelf/cli.py`（追加 `remove_cmd`）
- Test: `tests/unit/bookshelf/test_cli.py`（追加）

**Interfaces:**
- Produces: `bookshelf remove`。

- [ ] **Step 1: 追加失败测试**

```python
def test_remove_yes(cli_fast, make_book_folder):
    cli_fast.run("bookshelf", "add", str(make_book_folder(slug="rm", pages=2)))
    result = cli_fast.run("bookshelf", "remove", "rm", "--yes")
    assert result.success
    assert result.json()["removed"] is True
    data = cli_fast.run("bookshelf", "list").json()
    assert all(b["slug"] != "rm" for b in data["books"])


def test_remove_missing(cli_fast):
    result = cli_fast.run("bookshelf", "remove", "nope", "--yes")
    assert not result.success
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/bookshelf/test_cli.py -v`
Expected: remove 用例 FAIL

- [ ] **Step 3: 在 `cli.py` 追加 `remove_cmd`**（`show_cmd` 之后、`__all__` 之前）

```python
@bookshelf_app.command("remove")
def remove_cmd(
    slug: str = typer.Argument(..., help="书 slug"),
    yes: bool = typer.Option(False, "--yes", "-y", help="跳过确认直接删除"),
    kb: Optional[str] = typer.Option(None, "--kb", "-k", help="目标知识库"),
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(False, "--json", help="JSON 输出（等同 --format json）"),
) -> None:
    """从书架删除一本书（不可逆）。"""
    if json_output:
        output_format = "json"
    try:
        with use_kb(kb):
            shelf = _shelf()
            if not shelf.exists(slug):
                raise BookNotFoundError(slug)
            if not yes:
                meta = shelf.get(slug)
                confirmed = typer.confirm(
                    f"确认删除《{meta.title}》（{meta.book.get('page_count', 0)} 页）？不可逆。",
                    default=False,
                )
                if not confirmed:
                    if output_format == "json":
                        _emit_json({"slug": slug, "removed": False})
                    else:
                        console.print("[yellow]已取消[/yellow]")
                    return
            shelf.remove(slug)
            data = {"slug": slug, "removed": True}
    except BookNotFoundError as e:
        _fail(f"找不到书：{e}", output_format)
        return
    if output_format == "json":
        _emit_json(data)
    else:
        console.print(f"[green]已删除[/green] {slug}")
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/unit/bookshelf/test_cli.py -v`
Expected: PASS（全部）

- [ ] **Step 5: 提交**

```bash
uv run ruff check jfox/bookshelf tests/unit/bookshelf && \
uv run --with black==26.3.1 black --check jfox/bookshelf tests/unit/bookshelf && \
git add jfox/bookshelf/cli.py tests/unit/bookshelf/test_cli.py && \
git commit -m "feat(bookshelf): remove command (#325)"
```

---

### Task 7: cc-plugin skill + CLAUDE.md + 冒烟

**Files:**
- Create: `packages/cc-plugin/skills/bookshelf/SKILL.md`
- Modify: `CLAUDE.md`（模块表加 bookshelf 行）
- Test: `tests/unit/bookshelf/test_cli.py`（追加 `--help` 冒烟）

**Interfaces:** 无（文档/技能 + 一条 CLI 冒烟）。

- [ ] **Step 1: 写冒烟测试**（`tests/unit/bookshelf/test_cli.py` 追加）

```python
def test_bookshelf_help_registered(cli_fast):
    """bookshelf 子命令已注册且 --help 列出 add/list/show/remove。

    --help 是 eager，会短路 ZKCLI 自动追加的 --json，直接打印 help 文本。
    """
    result = cli_fast.run("bookshelf", "--help")
    assert result.success
    for cmd in ("add", "list", "show", "remove"):
        assert cmd in result.stdout
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/unit/bookshelf/test_cli.py::test_bookshelf_help_registered -v`
Expected: Task 4-6 已注册 sub-app，此用例应已 PASS（若 PASS 直接进 Step 3）。

- [ ] **Step 3: 写 cc-plugin skill** `packages/cc-plugin/skills/bookshelf/SKILL.md`

```markdown
---
name: bookshelf
description: |
  Use when the user wants to manage books on the jfox bookshelf—add a book
  (PDF + scan2book-extracted bundle), list books, view a book's metadata or a
  specific page, or remove a book. Triggers on "书架", "bookshelf", "加书",
  "导入书", "看书 page", "书 页", "manage books", "add book to shelf".
---

# JFox 书架（bookshelf）管理

把读过的好书作为**资产**管进知识库：存 PDF 原件 + scan2book 抽取的 bundle + 元数据。
纯文件管理——不进语义索引、不做搜索召回。书的「思想」进 KB 走引用笔记（另起 issue）。

## 1. 前置条件

- jfox 已安装（`jfox --version`）
- 一本书的文件夹，结构：
  ```
  <folder>/
    bundle/              # scan2book 产物（含 manifest.json + pages/pNNN.md + images/）
    original.pdf         # 原件（可选）
    meta.json            # 可选；不给则 jfox 从 bundle manifest 脚手架生成
  ```
- scan2book（如需自己抽 bundle）：需 GPU，在 GPU 机器上跑 `scan2book <pdf> --out <dir>`，
  再把产出的文件夹交给 `jfox bookshelf add`。jfox 本身**不调 scan2book、不需 GPU**。

## 2. 命令

| 命令 | 作用 |
|------|------|
| `jfox bookshelf add <folder> [--force] [--move]` | 加一本书进书架（默认复制原件） |
| `jfox bookshelf list` | 列书架上的书 |
| `jfox bookshelf show <slug> [--page N]` | 看元数据 / 指定页 md |
| `jfox bookshelf remove <slug> [--yes]` | 删一本书（不可逆） |

全部支持 `--kb <name>` 切换知识库、`--json` / `--format json` 结构化输出。

## 3. 何时翻书架

- 用户问某本书里的原话/表述 → `bookshelf show <slug> --page N`。
- 用户想把一本已抽取的书管起来 → `bookshelf add <folder>`。
- 想看书架上有什么 → `bookshelf list`。

## 4. 不做什么

- 不做 OCR（用 scan2book 产物）。
- 不做语义搜索召回（书页不进索引）。
- 不调 scan2book（GPU 依赖在 jfox 之外）。
```

- [ ] **Step 4: 改 `CLAUDE.md` 模块表**（在 `fragment/` 行后加一行）

定位现有行：
```
| `fragment/` | 碎片采集：detector 分类 + store SQLite(WAL) + service 编排 |
```
在其后插入：
```
| `bookshelf/` | 好书资产管理：store 文件夹 CRUD + meta jfox 自有元数据（wrap scan2book manifest）+ cli sub-app；纯文件管理不进索引 |
```

- [ ] **Step 5: 跑全部 bookshelf 测试 + 冒烟**

Run: `uv run pytest tests/unit/bookshelf/ -v`
Expected: PASS（meta 5 + store 18 + cli 含冒烟）

- [ ] **Step 6: 手测 CLI（可选自测，非提交门）**

Run: `uv run jfox bookshelf --help && uv run jfox bookshelf add --help`
Expected: 列出 add/list/show/remove；无 import/接线报错。

- [ ] **Step 7: 提交**

```bash
uv run ruff check jfox/bookshelf tests/unit/bookshelf && \
uv run --with black==26.3.1 black --check jfox/bookshelf tests/unit/bookshelf && \
git add packages/cc-plugin/skills/bookshelf/SKILL.md CLAUDE.md tests/unit/bookshelf/test_cli.py && \
git commit -m "feat(bookshelf): cc-plugin skill + CLAUDE.md module map (#325)"
```

---

## Self-Review（写完后自查记录）

- **Spec 覆盖**：add（复制/移动/force/撞/no-manifest/用户 meta）✓ Task 3/4；list ✓ Task 5；show（meta + --page）✓ Task 5；remove（--yes + 缺失）✓ Task 6；meta schema（含 distill 预留、source/book 字段、透传）✓ Task 1；多 KB（`use_kb`）✓ 各 cli 任务；cc-plugin skill ✓ Task 7。非目标（不进索引/不 search/不 OCR/不调 scan2book）—— 实现里无 chroma/bm25/subprocess-scan2book import，符合。
- **占位符扫描**：无 TBD/TODO；每个代码步骤含完整代码。
- **类型/签名一致**：`BookShelf.add/exists/get/list_books/page_path/read_page/remove`、`BookMeta.to_dict/load/save`、`build_meta_from_bundle`/`normalize_user_meta`、三个异常名、常量名跨任务一致。
- **已知小坑**：
  - Task 4 的 `test_add_force` 依赖 Task 5 的 `list`——计划已注明 Task 4 先跑前两条，Task 5 全绿。
  - `typer.confirm` 无 TTY 时行为不定；测试一律 `--yes` 规避。
  - `cli_fast` subprocess 的源文件夹用绝对路径（`str(folder)`），cwd=repo root 不影响。

## 执行交接

Plan complete and saved to `docs/superpowers/plans/2026-07-25-bookshelf.md`. 两种执行方式：

1. **Subagent-Driven（推荐）** — 每个 task 派一个新 subagent，任务间两阶段 review，迭代快。
2. **Inline Execution** — 当前 session 直接跑 executing-plans，批量执行带 checkpoint。
```
