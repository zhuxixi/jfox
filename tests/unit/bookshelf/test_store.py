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
    assert meta.source["original_file"] == "original.pdf"  # 以实际复制的文件为准，非用户值 x.pdf
    assert meta.source["original_sha256"]  # 非空（用户 meta 没给也要补上）


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


def test_add_invalid_slug_windows_chars_rejected(tmp_path, make_book_folder):
    from jfox.bookshelf.store import InvalidBundleError

    shelf = BookShelf(tmp_path)
    folder = make_book_folder(slug="ok", pages=1)
    with pytest.raises(InvalidBundleError):
        shelf.add(folder, slug="bad:slug", added_at="t")
    with pytest.raises(InvalidBundleError):
        shelf.add(folder, slug="bad?name", added_at="t")


def test_remove(tmp_path, make_book_folder):
    shelf = BookShelf(tmp_path)
    shelf.add(make_book_folder(slug="rm", pages=1), added_at="t")
    assert shelf.exists("rm")
    shelf.remove("rm")
    assert not shelf.exists("rm")


def test_remove_missing_raises(tmp_path):
    with pytest.raises(BookNotFoundError):
        BookShelf(tmp_path).remove("nope")


def test_book_dir_rejects_traversal(tmp_path):
    # issue-3：read/delete 路径也要挡路径遍历
    from jfox.bookshelf.store import InvalidBundleError

    shelf = BookShelf(tmp_path)
    with pytest.raises(InvalidBundleError):
        shelf.book_dir("../evil")
    with pytest.raises(InvalidBundleError):
        shelf.book_dir("..")


def test_add_rejects_traversal_slug(tmp_path, make_book_folder):
    # issue-3：add 时 slug="../evil" 必须被拒（_validate_slug 先挡 / ，book_dir 兜底）
    from jfox.bookshelf.store import InvalidBundleError

    shelf = BookShelf(tmp_path)
    folder = make_book_folder(slug="ok", pages=1)
    with pytest.raises(InvalidBundleError):
        shelf.add(folder, slug="../evil", added_at="t")


def test_validate_slug_rejects_windows_reserved(tmp_path):
    # issue-10：Windows 保留名 + 尾点/尾空格 + 超长
    from jfox.bookshelf.store import InvalidBundleError

    for bad in ("CON", "PRN", "AUX", "NUL", "COM1", "LPT9", "file.", "name ", "CON.txt"):
        with pytest.raises(InvalidBundleError):
            BookShelf._validate_slug(bad)
    # 合法的还在
    BookShelf._validate_slug("good-slug")
    BookShelf._validate_slug("book.pdf")


def test_validate_slug_rejects_too_long(tmp_path):
    from jfox.bookshelf.store import InvalidBundleError

    with pytest.raises(InvalidBundleError):
        BookShelf._validate_slug("x" * 256)


def test_find_original_prefers_known_ext(tmp_path):
    # issue-5：cover.jpg（更大）+ book.pdf（更小）→ 选 book.pdf（已知原件扩展名优先）
    folder = tmp_path / "src" / "mix"
    folder.mkdir(parents=True)
    (folder / "bundle").mkdir()
    (folder / "bundle" / "manifest.json").write_text("{}", encoding="utf-8")
    (folder / "cover.jpg").write_bytes(b"X" * 1000)  # 更大但不是已知原件扩展名
    (folder / "book.pdf").write_bytes(b"%PDF-1.4 small")  # 更小但是 .pdf
    name, sha = BookShelf._find_original(folder)
    assert name == "book.pdf"
    assert sha


def test_find_original_fallback_largest_when_no_known_ext(tmp_path):
    # 无已知原件扩展名时退回最大文件，且大小并列时按名字确定性排序
    folder = tmp_path / "src" / "fallback"
    folder.mkdir(parents=True)
    (folder / "bundle").mkdir()
    (folder / "bundle" / "manifest.json").write_text("{}", encoding="utf-8")
    (folder / "a.bin").write_bytes(b"XXXX")  # 4 字节
    (folder / "b.bin").write_bytes(b"XX")  # 2 字节
    name, _ = BookShelf._find_original(folder)
    assert name == "a.bin"


def test_add_corrupt_manifest_raises_invalid(tmp_path):
    # issue-4：bundle/manifest.json 是坏 JSON → InvalidBundleError（不 traceback）
    from jfox.bookshelf.store import InvalidBundleError

    shelf = BookShelf(tmp_path)
    bad = tmp_path / "src" / "corrupt"
    (bad / "bundle").mkdir(parents=True)
    (bad / "bundle" / "manifest.json").write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(InvalidBundleError):
        shelf.add(bad, added_at="t")


def test_list_books_skips_stage_dir(tmp_path):
    # r2 cc-#16：list_books 跳过 .{slug}.stage.{pid} 目录（add 期间不出现 ghost book）
    import json as _json

    shelf = BookShelf(tmp_path)
    real_dir = shelf.root / "real"
    real_dir.mkdir(parents=True)
    (real_dir / "meta.json").write_text(
        _json.dumps({"slug": "real", "title": "Real", "added_at": "t"}),
        encoding="utf-8",
    )
    stage_dir = shelf.root / ".x.stage.123"
    stage_dir.mkdir(parents=True)
    (stage_dir / "meta.json").write_text(
        _json.dumps({"slug": "ghost", "title": "Ghost", "added_at": "t"}),
        encoding="utf-8",
    )
    books = shelf.list_books()
    assert [b.slug for b in books] == ["real"]


def test_read_bundle_manifest_corrupt_raises_invalid(shelf_with_book):
    # r2 cc-#15：bundle/manifest.json 损坏 → InvalidBundleError（与 add() 一致），
    # 非 BookNotFoundError
    from jfox.bookshelf.store import InvalidBundleError

    manifest_path = shelf_with_book.book_dir("sapiens") / "bundle" / "manifest.json"
    manifest_path.write_text("{ not valid json", encoding="utf-8")
    with pytest.raises(InvalidBundleError):
        shelf_with_book.read_bundle_manifest("sapiens")


def test_list_books_corrupt_tags_skipped(tmp_path):
    # r2 cc-#14：meta.json 的 tags=null 触发 TypeError → list_books 跳过不崩
    import json as _json

    shelf = BookShelf(tmp_path)
    bad_dir = shelf.root / "bad"
    bad_dir.mkdir(parents=True)
    # tags=null 会让 BookMeta.from_dict 里 list(None) 抛 TypeError
    (bad_dir / "meta.json").write_text(
        _json.dumps({"slug": "bad", "title": "Bad", "added_at": "t", "tags": None}),
        encoding="utf-8",
    )
    good_dir = shelf.root / "good"
    good_dir.mkdir(parents=True)
    (good_dir / "meta.json").write_text(
        _json.dumps({"slug": "good", "title": "Good", "added_at": "t"}),
        encoding="utf-8",
    )
    books = shelf.list_books()
    assert [b.slug for b in books] == ["good"]


def test_validate_slug_length_cap(tmp_path):
    # r2 cc-#12：slug 长度上限 80（考虑 stage-dir 开销 + Windows MAX_PATH）
    from jfox.bookshelf.store import InvalidBundleError

    BookShelf._validate_slug("a" * 80)  # 边界值，合法
    with pytest.raises(InvalidBundleError):
        BookShelf._validate_slug("a" * 81)
