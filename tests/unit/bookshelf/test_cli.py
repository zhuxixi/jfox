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
    cli_fast.run(
        "bookshelf", "add", str(make_book_folder(slug="dup", title="New", pages=2)), "--force"
    )
    listing = cli_fast.run("bookshelf", "list").json()
    book = [b for b in listing["books"] if b["slug"] == "dup"][0]
    assert book["title"] == "New"


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
    cli_fast.run(
        "bookshelf", "add", str(make_book_folder(slug="sapiens", title="Sapiens", pages=3))
    )
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
