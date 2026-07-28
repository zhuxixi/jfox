"""bookshelf 测试共用 fixture。"""

import json
from pathlib import Path

import pytest


@pytest.fixture
def make_book_folder(tmp_path):
    """工厂：在 tmp_path/src/<slug> 下造假 scan2book bundle 文件夹。

    返回该文件夹 Path。默认 3 页 + original.pdf、无用户 meta.json。
    重复同名调用会覆盖（exist_ok），供 collision/force 测试用。

    关键参数：
    - layout: "wrapped"（默认，folder/bundle/manifest.json）或 "flat"
      （folder/manifest.json，scan2book v1 真实产出）
    - with_process_files: True 时在 folder 顶层落 checkpoint.json / qa_report.json /
      qa_review.html（scan2book 过程文件，flat 布局 sibling of manifest），默认 False
    """

    def _make(
        *,
        slug: str = "sapiens",
        title: str = "Sapiens",
        pages: int = 3,
        with_original: bool = True,
        original_name: str = "original.pdf",
        with_meta: dict | None = None,
        layout: str = "wrapped",
        with_process_files: bool = False,
    ) -> Path:
        folder = tmp_path / "src" / slug
        # wrapped: manifest 在 folder/bundle/；flat: manifest 在 folder/ 顶层
        bundle = folder / "bundle" if layout == "wrapped" else folder
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
        if with_process_files:
            # scan2book 过程文件（顶层，sibling of manifest）
            for pname, content in (
                ("checkpoint.json", "{}"),
                ("qa_report.json", "{}"),
                ("qa_review.html", "<html><body>qa</body></html>"),
            ):
                (folder / pname).write_text(content, encoding="utf-8")
        return folder

    return _make
