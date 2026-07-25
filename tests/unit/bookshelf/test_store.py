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
