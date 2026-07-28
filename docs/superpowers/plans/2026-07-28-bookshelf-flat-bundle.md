# bookshelf 扁平 bundle 契约 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 让 `jfox bookshelf add` 按 scan2book v1 扁平契约消费 bundle（同时向后兼容包装布局），选择性复制跳过过程文件，收紧原件探测，新增 `--original` flag。

**Architecture:** store 层加三个内部助手（`_detect_bundle` 布局探测 / `_copy_bundle_whitelist` 白名单复制 / `_resolve_original` 原件解析），`add()` 改用它们；CLI `add_cmd` 加 `--original` flag。目的地布局、meta schema、show/list/remove 不变。

**Tech Stack:** Python ≥3.10，Typer CLI，pytest（已有 `make_book_folder` fixture + `cli_fast`）。

## Global Constraints
- 注释/文档中文；行宽 100（black + ruff）。
- 目的地恒为 `<kb>/bookshelf/<slug>/{meta.json, bundle/{manifest.json, pages/, images/}, <original>?}`，**不改**。
- meta schema 不变（`BookMeta` / `build_meta_from_bundle` / `normalize_user_meta` 字段不动）。
- `bundle/` 内绝不出现 `checkpoint.json / qa_report.json / qa_review.html`。
- 软链原件一律不复制（沿用 `_is_candidate_file` 的 `not f.is_symlink()`）。
- 改完 `.py` 提交前必须 `ruff check` **和** `black --check` 都过（black 用 `uv run --with black==26.3.1 black --check`）。
- 快速单测可自主跑；bookshelf 单测在 `tests/unit/bookshelf/`，纯逻辑不碰 embedding/ChromaDB，可自主跑。
- main 是保护分支；所有改动在本 worktree 分支提交。

---

## File Structure
- **Modify** `jfox/bookshelf/store.py` — 加 `_sha256_of`、`_detect_bundle`、`_copy_bundle_whitelist`、`_resolve_original`、`_remove_consumed_sources`；收紧 `_find_original`；`add()` 改用新助手 + 加 `original` 参数。
- **Modify** `jfox/bookshelf/cli.py` — `add_cmd` 加 `--original` flag，透传 `shelf.add(..., original=...)`。
- **Modify** `tests/unit/bookshelf/conftest.py` — `make_book_folder` 加 `layout` + `with_process_files` 参数。
- **Modify** `tests/unit/bookshelf/test_store.py` — 加 flat/白名单/`--original`/move-flat 测试；改 `test_find_original_fallback_largest_when_no_known_ext`。
- **Modify** `tests/unit/bookshelf/test_cli.py` — 加 CLI `--original` 测试。

---

### Task 1: 扩展 `make_book_folder` fixture 支持扁平布局 + 过程文件

**Files:**
- Modify: `tests/unit/bookshelf/conftest.py`
- Test: `tests/unit/bookshelf/test_store.py`（新增 `test_make_book_folder_flat_layout`）

**Interfaces:**
- Produces: `make_book_folder(layout="wrapped"|"flat", with_process_files=False)`。`layout="flat"` 时 manifest/pages/images 直接落在 `folder/` 顶层（无 `bundle/` 子目录）；`with_process_files=True` 在 `folder/` 顶层写 `checkpoint.json / qa_report.json / qa_review.html`。默认 `layout="wrapped"` 不破坏现有 wrapped 测试。

- [ ] **Step 1: Write the failing test**

追加到 `tests/unit/bookshelf/test_store.py` 末尾：

```python
def test_make_book_folder_flat_layout(make_book_folder):
    """fixture 的 flat 布局：manifest/pages/images 在 folder 顶层，无 bundle/ 包装。"""
    folder = make_book_folder(slug="flatbook", pages=2, layout="flat", with_process_files=True)
    assert (folder / "manifest.json").exists()
    assert not (folder / "bundle").exists()
    assert (folder / "pages" / "p001.md").exists()
    assert (folder / "images" / "p001.jpg").exists()
    # 过程文件在顶层（sibling of manifest）
    assert (folder / "checkpoint.json").exists()
    assert (folder / "qa_report.json").exists()
    assert (folder / "qa_review.html").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/bookshelf/test_store.py::test_make_book_folder_flat_layout -v`
Expected: FAIL（`TypeError: _make() got an unexpected keyword argument 'layout'`）

- [ ] **Step 3: Modify the fixture**

把 `tests/unit/bookshelf/conftest.py` 的 `_make` 改为（替换整个 `_make` 函数体，签名加两个参数，bundle 目录按 layout 选择，末尾加过程文件写入）：

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/bookshelf/test_store.py::test_make_book_folder_flat_layout -v`
Expected: PASS

- [ ] **Step 5: Regression — wrapped 默认不受影响**

Run: `uv run pytest tests/unit/bookshelf/test_store.py -v`
Expected: 全 PASS（现有 wrapped 测试零回归）

- [ ] **Step 6: Commit**

```bash
git add tests/unit/bookshelf/conftest.py tests/unit/bookshelf/test_store.py
git commit -m "test(bookshelf): #349 make_book_folder 支持 flat 布局 + 过程文件"
```

---

### Task 2: `_detect_bundle` 布局探测助手

**Files:**
- Modify: `jfox/bookshelf/store.py`（加 `_detect_bundle` 静态方法）
- Test: `tests/unit/bookshelf/test_store.py`

**Interfaces:**
- Produces: `BookShelf._detect_bundle(src_folder: Path) -> Path` — 返回 bundle 源目录（wrapped → `src_folder/bundle`；flat → `src_folder`）；都不在抛 `InvalidBundleError`。

- [ ] **Step 1: Write the failing tests**

追加到 `tests/unit/bookshelf/test_store.py`：

```python
def test_detect_bundle_wrapped(tmp_path):
    from jfox.bookshelf.store import BookShelf
    folder = tmp_path / "src" / "w"
    (folder / "bundle").mkdir(parents=True)
    (folder / "bundle" / "manifest.json").write_text("{}", encoding="utf-8")
    assert BookShelf._detect_bundle(folder) == folder / "bundle"


def test_detect_bundle_flat(tmp_path):
    from jfox.bookshelf.store import BookShelf
    folder = tmp_path / "src" / "f"
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text("{}", encoding="utf-8")
    assert BookShelf._detect_bundle(folder) == folder


def test_detect_bundle_wrapped_preferred_over_flat(tmp_path):
    # 两种都在时优先 wrapped（向后兼容）
    from jfox.bookshelf.store import BookShelf
    folder = tmp_path / "src" / "both"
    (folder / "bundle").mkdir(parents=True)
    (folder / "bundle" / "manifest.json").write_text("{}", encoding="utf-8")
    (folder / "manifest.json").write_text("{}", encoding="utf-8")
    assert BookShelf._detect_bundle(folder) == folder / "bundle"


def test_detect_bundle_neither_raises(tmp_path):
    from jfox.bookshelf.store import BookShelf, InvalidBundleError
    folder = tmp_path / "src" / "empty"
    folder.mkdir(parents=True)
    with pytest.raises(InvalidBundleError):
        BookShelf._detect_bundle(folder)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/bookshelf/test_store.py -k detect_bundle -v`
Expected: FAIL（`AttributeError: _detect_bundle`）

- [ ] **Step 3: Add `_detect_bundle`**

在 `jfox/bookshelf/store.py` 的 `_validate_slug` 静态方法之后、`_KNOWN_ORIGINAL_EXTS` 之前，加：

```python
    @staticmethod
    def _detect_bundle(src_folder: Path) -> Path:
        """识别 bundle 源目录：包装布局 <folder>/bundle/manifest.json（向后兼容）优先，
        否则扁平布局 <folder>/manifest.json（scan2book v1 真实产出）。都不在则报错。"""
        wrapped = src_folder / BUNDLE_DIRNAME / MANIFEST_FILENAME
        if wrapped.exists():
            return src_folder / BUNDLE_DIRNAME
        flat = src_folder / MANIFEST_FILENAME
        if flat.exists():
            return src_folder
        raise InvalidBundleError(
            f"找不到 scan2book 产物 manifest.json（已尝试 "
            f"{BUNDLE_DIRNAME}/{MANIFEST_FILENAME} 与 {MANIFEST_FILENAME}）"
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/bookshelf/test_store.py -k detect_bundle -v`
Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/bookshelf/store.py tests/unit/bookshelf/test_store.py
git commit -m "feat(bookshelf): #349 _detect_bundle 探测包装/扁平布局"
```

---

### Task 3: 收紧 `_find_original`（仅已知扩展名，去最大文件兜底）+ 抽 `_sha256_of`

**Files:**
- Modify: `jfox/bookshelf/store.py`（加模块级 `_sha256_of`；改 `_find_original`）
- Test: `tests/unit/bookshelf/test_store.py`（改 `test_find_original_fallback_largest_when_no_known_ext`）

**Interfaces:**
- Produces: `_sha256_of(path: Path) -> str`（模块级）；`_find_original` 无候选时返回 `(None, None)`。
- Consumes: 无（首个 store 改动）。

- [ ] **Step 1: Update the fallback test to new semantics**

把 `tests/unit/bookshelf/test_store.py` 里的 `test_find_original_fallback_largest_when_no_known_ext` 整体替换为：

```python
def test_find_original_returns_none_when_no_known_ext(tmp_path):
    # #349 收紧：无已知原件扩展名 → (None, None)，不再退回最大文件（避免误选 qa_review.html）
    folder = tmp_path / "src" / "fallback"
    folder.mkdir(parents=True)
    (folder / "bundle").mkdir()
    (folder / "bundle" / "manifest.json").write_text("{}", encoding="utf-8")
    (folder / "qa_review.html").write_bytes(b"X" * 200)  # 更大但非已知原件扩展名
    (folder / "checkpoint.json").write_bytes(b"XX")
    name, sha = BookShelf._find_original(folder)
    assert name is None
    assert sha is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/bookshelf/test_store.py::test_find_original_returns_none_when_no_known_ext -v`
Expected: FAIL（旧实现返回 `qa_review.html`）

- [ ] **Step 3: Refactor hashing + tighten `_find_original`**

在 `jfox/bookshelf/store.py` 的 `_is_candidate_file` 函数之后，加模块级 helper：

```python
def _sha256_of(path: Path) -> str:
    """流式算文件 sha256（_find_original 与 --original 共用）。"""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()
```

然后把 `_find_original` 静态方法整体替换为：

```python
    @staticmethod
    def _find_original(src_folder: Path):
        """挑原件：仅已知原件扩展名的普通文件（非软链）；无则 (None, None)。
        多个时按 (-size, name) 确定性选最大。#349：去掉「最大文件兜底」，
        避免扁平布局下把过程文件 qa_review.html 误当原件。"""
        # 排除软链原件（cc-7：软链可能指向外部大/敏感文件，复制进来有风险）
        files = [f for f in src_folder.iterdir() if _is_candidate_file(f)]
        known = [f for f in files if f.suffix.lower() in BookShelf._KNOWN_ORIGINAL_EXTS]
        if not known:
            return None, None
        biggest = sorted(known, key=lambda f: (-f.stat().st_size, f.name.lower()))[0]
        return biggest.name, _sha256_of(biggest)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/bookshelf/test_store.py -k "find_original" -v`
Expected: 2 PASS（`test_find_original_prefers_known_ext` + 新的 `_returns_none_when_no_known_ext`）

- [ ] **Step 5: Commit**

```bash
git add jfox/bookshelf/store.py tests/unit/bookshelf/test_store.py
git commit -m "fix(bookshelf): #349 _find_original 仅认已知原件扩展名，去最大文件兜底"
```

---

### Task 4: `add()` 改用 `_detect_bundle` + 白名单复制（核心）

**Files:**
- Modify: `jfox/bookshelf/store.py`（加 `BUNDLE_WHITELIST_FILES/DIRS` 常量 + `_copy_bundle_whitelist`；改 `add()` 的 manifest 定位与复制段）
- Test: `tests/unit/bookshelf/test_store.py`

**Interfaces:**
- Consumes: Task 2 `_detect_bundle`、Task 3 `_find_original`。
- Produces: `add()` 支持扁平布局；`_copy_bundle_whitelist(bundle_src, dest_bundle)`。

- [ ] **Step 1: Write the failing tests**

追加到 `tests/unit/bookshelf/test_store.py`：

```python
def test_add_flat_layout_excludes_process_files(tmp_path, make_book_folder):
    # #349：扁平 bundle（含 checkpoint/qa_*）入库后，dest bundle/ 不含过程文件
    shelf = BookShelf(tmp_path)
    folder = make_book_folder(
        slug="sapiens", pages=2, layout="flat", with_process_files=True, with_original=False
    )
    meta = shelf.add(folder, added_at="t")
    assert meta.slug == "sapiens"
    dest = shelf.book_dir("sapiens")
    # 白名单内容齐全
    assert (dest / "bundle" / "manifest.json").exists()
    assert (dest / "bundle" / "pages" / "p001.md").exists()
    assert (dest / "bundle" / "images" / "p001.jpg").exists()
    # 过程文件被排除
    assert not (dest / "bundle" / "checkpoint.json").exists()
    assert not (dest / "bundle" / "qa_report.json").exists()
    assert not (dest / "bundle" / "qa_review.html").exists()
    # 无原件（with_original=False 且无已知扩展名）
    assert meta.source["original_file"] == ""


def test_add_flat_layout_without_manifest_raises(tmp_path):
    from jfox.bookshelf.store import InvalidBundleError
    shelf = BookShelf(tmp_path)
    bad = tmp_path / "src" / "noflat"
    bad.mkdir(parents=True)
    # 既无 bundle/manifest.json 也无 manifest.json
    with pytest.raises(InvalidBundleError):
        shelf.add(bad, added_at="t")


def test_add_wrapped_layout_still_works(tmp_path, make_book_folder):
    # 回归：包装布局照旧（向后兼容）
    shelf = BookShelf(tmp_path)
    folder = make_book_folder(slug="wrap", pages=1, layout="wrapped")
    meta = shelf.add(folder, added_at="t")
    assert meta.slug == "wrap"
    assert (shelf.book_dir("wrap") / "bundle" / "pages" / "p001.md").exists()
    assert (shelf.book_dir("wrap") / "original.pdf").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/bookshelf/test_store.py -k "flat_layout or wrapped_layout_still" -v`
Expected: FAIL（`InvalidBundleError: 找不到 .../bundle/manifest.json`，因为旧 `add` 写死 bundle/）

- [ ] **Step 3: Add whitelist constants + `_copy_bundle_whitelist`**

在 `jfox/bookshelf/store.py` 模块顶部常量区（`META_FILENAME` 之后），加：

```python
# #349：bundle 白名单——只有这些进 dest/bundle/，scan2book 过程文件（checkpoint/qa_*）自然丢弃
BUNDLE_WHITELIST_FILES = (MANIFEST_FILENAME,)
BUNDLE_WHITELIST_DIRS = ("pages", "images")
```

在 `BookShelf` 类内、`_detect_bundle` 之后，加实例方法：

```python
    @staticmethod
    def _copy_bundle_whitelist(bundle_src: Path, dest_bundle: Path) -> None:
        """白名单复制：只 manifest.json + pages/ + images/ 进 dest/bundle/。
        跳过 checkpoint.json / qa_report.json / qa_review.html / original.* 等。"""
        dest_bundle.mkdir(parents=True, exist_ok=True)
        for name in BUNDLE_WHITELIST_FILES:
            src = bundle_src / name
            if src.is_file():
                shutil.copy2(str(src), str(dest_bundle / name))
        for d in BUNDLE_WHITELIST_DIRS:
            src = bundle_src / d
            if src.is_dir():
                shutil.copytree(str(src), str(dest_bundle / d))
```

- [ ] **Step 4: Rewire `add()` to use `_detect_bundle` + whitelist copy**

在 `jfox/bookshelf/store.py` 的 `add()` 里：

(a) 把开头的 manifest 定位段：
```python
        src_folder = Path(src_folder).expanduser().resolve()
        manifest_path = src_folder / BUNDLE_DIRNAME / MANIFEST_FILENAME
        if not manifest_path.exists():
            raise InvalidBundleError(
                f"找不到 {manifest_path}（需要 scan2book 产物 bundle/manifest.json）"
            )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
```
替换为：
```python
        src_folder = Path(src_folder).expanduser().resolve()
        bundle_src = self._detect_bundle(src_folder)
        manifest_path = bundle_src / MANIFEST_FILENAME
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
```

(b) 把 stage 段里的整目录复制：
```python
            bundle_src = src_folder / BUNDLE_DIRNAME
            shutil.copytree(str(bundle_src), str(stage / BUNDLE_DIRNAME))
```
替换为：
```python
            self._copy_bundle_whitelist(bundle_src, stage / BUNDLE_DIRNAME)
```

（注意：`bundle_src` 现在是 `_detect_bundle` 的返回值，已在 (a) 定义，删除 (b) 里那行重复赋值。）

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/bookshelf/test_store.py -v`
Expected: 全 PASS（新 3 个 + 现有全部）

- [ ] **Step 6: Commit**

```bash
git add jfox/bookshelf/store.py tests/unit/bookshelf/test_store.py
git commit -m "fix(bookshelf): #349 add 支持扁平布局 + 白名单复制跳过过程文件"
```

---

### Task 5: `--original` flag（`_resolve_original` + `add()` 参数）

**Files:**
- Modify: `jfox/bookshelf/store.py`（加 `_resolve_original`；`add()` 加 `original` 参数）
- Test: `tests/unit/bookshelf/test_store.py`

**Interfaces:**
- Consumes: Task 3 `_sha256_of`、`_find_original`。
- Produces: `add(..., original: Optional[str]=None)`；`_resolve_original(src_folder, original) -> (orig_src_path, basename, sha)`。

- [ ] **Step 1: Write the failing tests**

追加到 `tests/unit/bookshelf/test_store.py`：

```python
def test_add_original_flag_copies_external_pdf(tmp_path, make_book_folder):
    # #349：--original 指外部 sibling PDF（scan2book 未把原件纳入 bundle）
    shelf = BookShelf(tmp_path)
    folder = make_book_folder(
        slug="sapiens", pages=1, layout="flat", with_original=False, with_process_files=True
    )
    external = tmp_path / "sibling.pdf"
    external.write_bytes(b"%PDF-1.4 external original")
    meta = shelf.add(folder, original=str(external), added_at="t")
    assert meta.source["original_file"] == "sibling.pdf"
    assert meta.source["original_sha256"]
    assert (shelf.book_dir("sapiens") / "sibling.pdf").exists()
    assert external.exists()  # 默认 copy 不删源


def test_add_original_flag_missing_raises(tmp_path, make_book_folder):
    from jfox.bookshelf.store import InvalidBundleError
    shelf = BookShelf(tmp_path)
    folder = make_book_folder(slug="sapiens", pages=1, layout="flat", with_original=False)
    with pytest.raises(InvalidBundleError):
        shelf.add(folder, original=str(tmp_path / "nope.pdf"), added_at="t")


def test_add_original_flag_overrides_auto_detect(tmp_path, make_book_folder):
    # --original 优先于自动探测（folder 里有 original.pdf 但 flag 指另一个）
    shelf = BookShelf(tmp_path)
    folder = make_book_folder(slug="sapiens", pages=1, layout="flat", with_original=True)
    external = tmp_path / "override.epub"
    external.write_bytes(b"EPUB override")
    meta = shelf.add(folder, original=str(external), added_at="t")
    assert meta.source["original_file"] == "override.epub"  # flag 胜出，非 original.pdf
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/bookshelf/test_store.py -k "original_flag" -v`
Expected: FAIL（`TypeError: add() got an unexpected keyword argument 'original'`）

- [ ] **Step 3: Add `_resolve_original`**

在 `jfox/bookshelf/store.py` 的 `_find_original` 静态方法之后，加：

```python
    def _resolve_original(
        self, src_folder: Path, original: Optional[str]
    ) -> tuple:
        """返回 (原件绝对路径, 存储 basename, sha256)。
        --original 给定 → 用它（不存在则 InvalidBundleError，覆盖自动探测）；
        否则自动探测（仅已知扩展名，无则全 None）。原件源路径用于复制与 --move 删源。"""
        if original:
            p = Path(original).expanduser().resolve()
            if not p.is_file():
                raise InvalidBundleError(f"--original 指定的文件不存在: {p}")
            return p, p.name, _sha256_of(p)
        name, sha = self._find_original(src_folder)
        if name is None:
            return None, None, None
        return src_folder / name, name, sha
```

- [ ] **Step 4: Wire `original` param into `add()`**

(a) 改 `add()` 签名，在 `force: bool = False,` 之后加参数：
```python
    def add(
        self,
        src_folder: Path,
        *,
        slug: Optional[str] = None,
        move: bool = False,
        force: bool = False,
        original: Optional[str] = None,
        added_at: Optional[str] = None,
    ) -> BookMeta:
```

(b) 把原件解析行：
```python
        original_file, original_sha256 = self._find_original(src_folder)
```
替换为：
```python
        orig_src_path, original_file, original_sha256 = self._resolve_original(
            src_folder, original
        )
```

(c) 把 stage 段里复制原件的条件块：
```python
            if original_file:
                orig_src = src_folder / original_file
                if orig_src.exists():
                    shutil.copy2(str(orig_src), str(stage / original_file))
```
替换为（用 `orig_src_path`，覆盖自动探测与 --original 两种来源）：
```python
            if original_file and orig_src_path is not None:
                shutil.copy2(str(orig_src_path), str(stage / original_file))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/bookshelf/test_store.py -v`
Expected: 全 PASS

- [ ] **Step 6: Commit**

```bash
git add jfox/bookshelf/store.py tests/unit/bookshelf/test_store.py
git commit -m "feat(bookshelf): #349 add --original flag 覆盖原件自动探测"
```

---

### Task 6: 扁平布局 `--move` 删除消费项（`_remove_consumed_sources`）

**Files:**
- Modify: `jfox/bookshelf/store.py`（加 `_remove_consumed_sources`；改 `add()` 的 move 段）
- Test: `tests/unit/bookshelf/test_store.py`

**Interfaces:**
- Consumes: Task 4 `bundle_src`、Task 5 `orig_src_path`、白名单常量。

- [ ] **Step 1: Write the failing tests**

追加到 `tests/unit/bookshelf/test_store.py`：

```python
def test_add_move_flat_removes_consumed_keeps_process(tmp_path, make_book_folder):
    # #349：扁平 --move 只删消费项（manifest/pages/images + 原件），不动 sibling 过程文件
    shelf = BookShelf(tmp_path)
    folder = make_book_folder(
        slug="mv", pages=1, layout="flat", with_original=True, with_process_files=True
    )
    shelf.add(folder, move=True, added_at="t")
    # 消费项已删
    assert not (folder / "manifest.json").exists()
    assert not (folder / "pages").exists()
    assert not (folder / "images").exists()
    assert not (folder / "original.pdf").exists()
    # 过程文件保留（scan2book 产物，不该 bookshelf 清理）
    assert (folder / "checkpoint.json").exists()
    assert (folder / "qa_report.json").exists()
    assert (folder / "qa_review.html").exists()
    # 书已入库
    assert shelf.exists("mv")


def test_add_move_wrapped_still_removes_bundle_dir(tmp_path, make_book_folder):
    # 回归：包装 --move 仍整目录删 bundle/
    shelf = BookShelf(tmp_path)
    folder = make_book_folder(slug="mvw", pages=1, layout="wrapped")
    shelf.add(folder, move=True, added_at="t")
    assert not (folder / "bundle").exists()
    assert not (folder / "original.pdf").exists()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/bookshelf/test_store.py -k "move_flat or move_wrapped_still" -v`
Expected: `test_add_move_flat_removes_consumed_keeps_process` FAIL（旧 move 找 `src_folder/bundle` 不存在，消费项残留）；wrapped 回归 PASS。

- [ ] **Step 3: Add `_remove_consumed_sources`**

在 `jfox/bookshelf/store.py` 的 `_resolve_original` 之后，加：

```python
    @staticmethod
    def _remove_consumed_sources(
        bundle_src: Path, orig_src_path: Optional[Path]
    ) -> None:
        """--move 删除本次消费的源：bundle 白名单组件（manifest/pages/images）+ 原件。
        包装布局（bundle_src=<folder>/bundle）整目录删；扁平布局（bundle_src=<folder>）
        只删消费项，不动 sibling 过程文件（checkpoint/qa_*）。"""
        # 扁平：bundle_src == 其父文件夹的 manifest 所在层；用「是否含 bundle/ 子目录」区分更稳
        is_wrapped = (bundle_src.name == BUNDLE_DIRNAME)
        if is_wrapped:
            if bundle_src.exists():
                shutil.rmtree(bundle_src, ignore_errors=True)
        else:
            for name in BUNDLE_WHITELIST_FILES:
                f = bundle_src / name
                if f.is_file():
                    f.unlink()
            for d in BUNDLE_WHITELIST_DIRS:
                p = bundle_src / d
                if p.exists():
                    shutil.rmtree(p, ignore_errors=True)
        if orig_src_path is not None and orig_src_path.exists():
            try:
                orig_src_path.unlink()
            except OSError as e:
                logger.warning("删源原件失败（新书已就位）%s: %s", orig_src_path, e)
```

- [ ] **Step 4: Rewire `add()` move section**

把 `add()` 末尾的 move 段：
```python
        # --move：成功替换后再删源（issue-2 点2：避免 meta.save 失败时源已搬走）。
        # 源在书架内部时跳过删源——那种情况源==目标书目录，删源=删新书（cc-1）。
        if move and not src_folder.is_relative_to(self.root.resolve()):
            shutil.rmtree(str(src_folder / BUNDLE_DIRNAME), ignore_errors=True)
            if original_file:
                orig_src = src_folder / original_file
                if orig_src.exists():
                    try:  # cc-6：unlink 失败不致「新书已就位却报失败」
                        orig_src.unlink()
                    except OSError as e:
                        logger.warning("删源原件失败（新书已就位）%s: %s", orig_src, e)
```
替换为：
```python
        # --move：成功替换后再删源（issue-2 点2：避免 meta.save 失败时源已搬走）。
        # 源在书架内部时跳过删源——那种情况源==目标书目录，删源=删新书（cc-1）。
        if move and not src_folder.is_relative_to(self.root.resolve()):
            self._remove_consumed_sources(bundle_src, orig_src_path)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/unit/bookshelf/test_store.py -v`
Expected: 全 PASS（含两个 move 测试 + `test_add_move_removes_source` 回归）

- [ ] **Step 6: Commit**

```bash
git add jfox/bookshelf/store.py tests/unit/bookshelf/test_store.py
git commit -m "fix(bookshelf): #349 扁平 --move 只删消费项，保留过程文件"
```

---

### Task 7: CLI `add` 加 `--original` flag

**Files:**
- Modify: `jfox/bookshelf/cli.py`（`add_cmd` 加 `--original`，透传 `add`）
- Test: `tests/unit/bookshelf/test_cli.py`

**Interfaces:**
- Consumes: Task 5 `BookShelf.add(..., original=...)`。

- [ ] **Step 1: Write the failing test**

追加到 `tests/unit/bookshelf/test_cli.py`：

```python
def test_add_original_flag_cli(cli_fast, make_book_folder, tmp_path):
    folder = make_book_folder(
        slug="sapiens", pages=1, layout="flat", with_original=False, with_process_files=True
    )
    external = tmp_path / "sibling.pdf"
    external.write_bytes(b"%PDF-1.4 cli original")
    r = cli_fast.run("bookshelf", "add", str(folder), "--original", str(external))
    assert r.success, r.stderr
    data = r.json()
    assert data["success"] is True
    assert data["slug"] == "sapiens"


def test_add_flat_layout_cli(cli_fast, make_book_folder):
    # 扁平 bundle（无原件）CLI 跑通，stderr 给出 ⚠️ 未找到原件提示
    folder = make_book_folder(
        slug="noflat", pages=2, layout="flat", with_original=False, with_process_files=True
    )
    r = cli_fast.run("bookshelf", "add", str(folder))
    assert r.success, r.stderr
    assert r.json()["slug"] == "noflat"
    assert "未找到原件" in r.stderr
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/unit/bookshelf/test_cli.py -k "original_flag_cli or flat_layout_cli" -v`
Expected: FAIL（`--original` 选项不存在；扁平因 store 已支持其实会过，但 CLI 走的还是 add——先看是否都 FAIL；`original_flag_cli` 会因 No such option 失败）

- [ ] **Step 3: Add `--original` to `add_cmd`**

在 `jfox/bookshelf/cli.py` 的 `add_cmd` 签名里，`move: bool = ...` 之后、`kb` 之前，加：

```python
    original: Optional[str] = typer.Option(
        None,
        "--original",
        "-O",
        help="原件路径（PDF/EPUB…），覆盖自动探测；用于 scan2book 未把原件纳入 bundle",
    ),
```

并把 `add_cmd` 里的调用：
```python
            meta = shelf.add(
                Path(folder).expanduser().resolve(),
                move=move,
                force=force,
            )
```
改为：
```python
            meta = shelf.add(
                Path(folder).expanduser().resolve(),
                move=move,
                force=force,
                original=original,
            )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/unit/bookshelf/test_cli.py -v`
Expected: 全 PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/bookshelf/cli.py tests/unit/bookshelf/test_cli.py
git commit -m "feat(bookshelf): #349 CLI add 加 --original flag"
```

---

### Task 8: 全量 bookshelf 单测 + lint + 本机真实 bundle 验收

**Files:**
- 无新文件；验证为主。

- [ ] **Step 1: 跑全部 bookshelf 单测**

Run: `uv run pytest tests/unit/bookshelf/ -v`
Expected: 全 PASS

- [ ] **Step 2: ruff + black 双检**

Run: `uv run ruff check jfox/bookshelf/ tests/unit/bookshelf/ && uv run --with black==26.3.1 black --check jfox/bookshelf/ tests/unit/bookshelf/`
Expected: 都干净（black 行宽 100）

- [ ] **Step 3: 本机真实 bundle 验收（issue 验收标准）**

Run（用临时 KB 避免污染默认库）:
```bash
uv run jfox kb create bookshelf-verify-349 2>/dev/null || true
uv run jfox bookshelf add /home/elling/ebooks/人类简史-从动物到上帝 \
  --original "/home/elling/ebooks/人类简史 450.pdf" --kb bookshelf-verify-349
uv run jfox bookshelf list --kb bookshelf-verify-349
uv run jfox bookshelf show 人类简史-从动物到上帝 --page 1 --kb bookshelf-verify-349 | head -20
uv run jfox bookshelf show 人类简史-从动物到上帝 --page 100 --kb bookshelf-verify-349 | head -20
```
Expected: add 跑通（自动探测无原件→`--original` 兜底）；list 列出；show 第 1/100 页有内容。检查 `~/.zettelkasten/bookshelf-verify-349/bookshelf/人类简史-从动物到上帝/` 下 `bundle/` 无 `checkpoint.json/qa_*`。

- [ ] **Step 4: 清理验收临时 KB**

```bash
uv run jfox kb remove bookshelf-verify-349 2>/dev/null || rm -rf ~/.zettelkasten/bookshelf-verify-349
```

- [ ] **Step 5: 若 Step 3 有问题，补 fix commit；否则跳过**

只有真实 bundle 验收暴露新 bug 才提交；通过则本 task 无 commit。

---

## Self-Review

**1. Spec 覆盖：** D1 布局探测 → Task 2；D2 白名单复制 → Task 4；D3 `_find_original` 收紧 → Task 3；D4 `--original` → Task 5（store）+ Task 7（CLI）；D5 扁平 move → Task 6；fixture 基础 → Task 1；验收 → Task 8。✓ 无遗漏。

**2. 占位符扫描：** 每步都有真实代码/命令，无 TBD/TODO。✓

**3. 类型一致性：** `_detect_bundle→Path`、`_resolve_original→(Path|None, str|None, str|None)`、`_remove_consumed_sources(bundle_src, orig_src_path)`、`add(..., original: Optional[str])`、CLI flag `--original`/`-O`。Task 6 用 `bundle_src.name == BUNDLE_DIRNAME` 判 wrapped（比 `== src_folder` 更稳，避免 resolve 边界）。✓
