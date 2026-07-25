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
