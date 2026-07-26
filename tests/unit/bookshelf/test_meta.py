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
            {
                "page": 1,
                "md": "pages/p001.md",
                "image": "images/p001.jpg",
                "chars": 10,
                "has_image": True,
            }
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
        "schema_version",
        "slug",
        "title",
        "added_at",
        "source",
        "book",
        "tags",
        "distill",
    ]


def test_from_dict_rejects_non_dict():
    # r3 cc-#22：JSON 解出 list/null/str 等（非 dict）→ ValueError，被 list_books 捕获跳过
    import pytest

    for bad in ([], None, "scalar", 42):
        with pytest.raises(ValueError):
            BookMeta.from_dict(bad)
