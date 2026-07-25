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
