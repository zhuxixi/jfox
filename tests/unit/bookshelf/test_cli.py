"""bookshelf CLI 集成测试（subprocess via cli_fast）。"""

import subprocess
import sys


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
    assert isinstance(data["pages"], list)
    assert len(data["pages"]) == 3
    assert data["pages"][0]["page"] == 1


def test_show_page_json(cli_fast, make_book_folder):
    cli_fast.run("bookshelf", "add", str(make_book_folder(slug="sapiens", pages=3)))
    data = cli_fast.run("bookshelf", "show", "sapiens", "--page", "1").json()
    assert data["page"] == 1
    assert "第 1 页内容" in data["content"]


def test_show_missing(cli_fast):
    result = cli_fast.run("bookshelf", "show", "nope")
    assert not result.success


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


def test_bookshelf_help_registered(cli_fast):
    """bookshelf 子命令已注册且 --help 列出 add/list/show/remove。

    --help 是 eager，会短路 ZKCLI 自动追加的 --json，直接打印 help 文本。
    使用 raw subprocess 避免 cli_fast 自动添加 --kb 导致解析错误。
    """
    result = subprocess.run(
        [sys.executable, "-m", "jfox", "bookshelf", "--help"],
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    assert result.returncode == 0
    stdout = result.stdout
    for cmd in ("add", "list", "show", "remove"):
        assert cmd in stdout


def test_emit_json_long_path_not_wrapped(capsys):
    """regression #336: rich 默认按 80 列折行，曾在 windows CI 把长 path 折进 JSON
    字符串内部（插入换行），破坏 json.loads。soft_wrap=True 后须保持可解析。"""
    import json as _stdjson

    from jfox.bookshelf.cli import _emit_json

    long_path = "/" + "x" * 100 + "/bookshelf/sapiens"
    _emit_json({"success": True, "slug": "sapiens", "path": long_path})
    out = capsys.readouterr().out
    data = _stdjson.loads(out)  # 不应抛 JSONDecodeError
    assert data["path"] == long_path
