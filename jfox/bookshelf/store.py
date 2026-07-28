"""bookshelf 文件夹存储层：per-KB，<kb>/bookshelf/<slug>/。

纯文件管理，不进 chroma/bm25 索引。
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from .meta import BookMeta, build_meta_from_bundle, normalize_user_meta

logger = logging.getLogger(__name__)

BUNDLE_DIRNAME = "bundle"
MANIFEST_FILENAME = "manifest.json"
META_FILENAME = "meta.json"
# #349：bundle 白名单——只有这些进 dest/bundle/，scan2book 过程文件（checkpoint/qa_*）自然丢弃
BUNDLE_WHITELIST_FILES = (MANIFEST_FILENAME,)
BUNDLE_WHITELIST_DIRS = ("pages", "images")
# --original 的 basename 不能冲撞 dest 保留名（meta.json 会被 meta.save 覆盖致原件静默丢失）
_ORIGINAL_RESERVED_NAMES = {META_FILENAME, BUNDLE_DIRNAME, *BUNDLE_WHITELIST_DIRS}
# 历史 stage/retire 残留目录名前缀（新代码已移出 bookshelf/，list_books 兜底过滤；k-14/k-17）
_STAGE_RETIRE_RE = re.compile(r"^\.bookshelf\..*\.(stage|retire)\.\d+$")


class BookAlreadyExistsError(Exception):
    """slug 已存在且未 --force。"""


class BookNotFoundError(Exception):
    """slug 不在书架上。"""


class InvalidBundleError(Exception):
    """输入文件夹不是合法 scan2book bundle。"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def _is_candidate_file(f: Path) -> bool:
    """原件候选：普通文件、非软链（cc-7）、非 meta.json。"""
    return f.is_file() and not f.is_symlink() and f.name != META_FILENAME


def _sha256_of(path: Path) -> str:
    """流式算文件 sha256（_find_original 与 --original 共用）。"""
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class BookShelf:
    """一个知识库的书架：<base_dir>/bookshelf/<slug>/。"""

    def __init__(self, base_dir: Path) -> None:
        self.base_dir = Path(base_dir).expanduser().resolve()
        self.root = self.base_dir / "bookshelf"

    def book_dir(self, slug: str) -> Path:
        # 空 slug 会被 resolve 成 root 自身，必须显式挡，否则 remove("") 会 rmtree 整个书架
        if not slug:
            raise InvalidBundleError("空 slug")
        # resolve + is_relative_to 防路径遍历（issue-3：read/delete 路径也要挡）
        root = self.root.resolve()
        path = (self.root / slug).resolve()
        if path == root or not path.is_relative_to(root):
            raise InvalidBundleError(f"非法 slug（越界）: {slug!r}")
        return path

    def meta_path(self, slug: str) -> Path:
        return self.book_dir(slug) / META_FILENAME

    def exists(self, slug: str) -> bool:
        return self.meta_path(slug).exists()

    def list_books(self) -> List[BookMeta]:
        if not self.root.exists():
            return []
        out: List[BookMeta] = []
        for meta_file in sorted(self.root.glob("*/meta.json")):
            # k-14/k-17：跳过 .bookshelf.<slug>.stage.<pid>/.retire.<pid> 残留目录名（限定前缀，避免误伤）
            if _STAGE_RETIRE_RE.match(meta_file.parent.name):
                continue
            try:
                m = BookMeta.load(meta_file)
            except (
                json.JSONDecodeError,
                KeyError,
                TypeError,
                ValueError,
                AttributeError,
                OSError,
            ) as e:
                logger.warning("跳过无法加载的 meta.json: %s (%s)", meta_file, e)
                continue
            if not m.slug:
                # cc-22/k-11：损坏 meta（缺 slug 或 slug=null）不进列表，也不当空 slug 书
                logger.warning("跳过 slug 为空的 meta.json: %s", meta_file)
                continue
            out.append(m)
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

    def read_bundle_manifest(self, slug: str) -> Dict[str, Any]:
        """读 bundle/manifest.json（scan2book 产物），用于 show 的页清单。"""
        path = self.book_dir(slug) / BUNDLE_DIRNAME / MANIFEST_FILENAME
        if not path.exists():
            raise BookNotFoundError(f"{slug} bundle manifest")
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise InvalidBundleError(f"{slug} bundle manifest 解析失败: {e}") from e
        if not isinstance(data, dict):
            raise InvalidBundleError(f"{slug} manifest 非 dict: {type(data).__name__}")
        return data

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
        """把 scan2book bundle 文件夹加入书架。

        - slug：取 bundle manifest 的 slug，否则用 src_folder 名；--slug 覆盖。
        - force：目标 slug 已存在时先删后写（原子 stage→dest 替换，中断只残留 stage）。
        - move：成功后删源；但源在书架内则跳过（删源=删新书，cc-1）。
        返回写入的 BookMeta。
        """
        src_folder = Path(src_folder).expanduser().resolve()
        bundle_src, layout = self._detect_bundle(src_folder)
        manifest_path = bundle_src / MANIFEST_FILENAME
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise InvalidBundleError(f"manifest.json 解析失败: {e}") from e
        if not isinstance(manifest, dict):
            raise InvalidBundleError(f"manifest 非 dict: {type(manifest).__name__}")
        if slug is None:
            slug = manifest.get("slug") or src_folder.name
        self._validate_slug(slug)
        orig_src_path, original_file, original_sha256 = self._resolve_original(
            src_folder,
            original,
        )
        if added_at is None:
            added_at = _now_iso()
        user_meta_path = src_folder / META_FILENAME
        if user_meta_path.exists():
            try:
                raw = json.loads(user_meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                raise InvalidBundleError(f"meta.json 解析失败: {e}") from e
            # meta.json 必须是 dict；嵌套 dict 字段（source/distill/book）防非 dict——
            # 否则下游 .get() 抛未捕获 AttributeError（kimi#21/cc#1/kimi#22/cc-2：
            # book 在 cli 多处 .get('page_count')）。
            if not isinstance(raw, dict):
                raise InvalidBundleError(f"meta.json 非 dict: {type(raw).__name__}")
            if not isinstance(raw.get("source"), dict):
                raw["source"] = {}
            if not isinstance(raw.get("distill"), dict):
                raw["distill"] = {}
            if not isinstance(raw.get("book"), dict):
                raw["book"] = {}
            # original_file/sha256 是"实际复制了哪个文件"的客观事实，以计算值为准
            # （覆盖用户值），否则 meta 指向的文件名可能和 dest/ 里真实文件对不上。
            raw["source"]["original_file"] = original_file or ""
            raw["source"]["original_sha256"] = original_sha256 or ""
            try:
                meta = normalize_user_meta(raw, slug=slug, added_at=added_at)
            except (KeyError, TypeError, ValueError) as e:
                raise InvalidBundleError(f"meta 构造失败: {e}") from e
        else:
            try:
                meta = build_meta_from_bundle(
                    slug=slug,
                    bundle_manifest=manifest,
                    original_file=original_file,
                    original_sha256=original_sha256,
                    added_at=added_at,
                )
            except (KeyError, TypeError, ValueError) as e:
                raise InvalidBundleError(f"meta 构造失败: {e}") from e
        # 冲突检查在写 stage 前（issue-2：--force 先删后写有丢书窗口）
        if self.exists(slug) and not force:
            raise BookAlreadyExistsError(slug)
        # 写入 stage 目录，完成后原子替换 dest（issue-2/11：中断/崩溃只残留 stage，
        # dest 不受污染；并发 add 各自 stage 独立，最后 os.replace 最后写入者胜。
        # 单用户本地 CLI 不再加文件锁——见 issue-11 取舍。）
        # stage/dest_bak 放 base_dir（KB 根）而非 bookshelf/ 下：避免被 list_books 扫到
        # 出现 ghost（cc-16），也不再需要 dot-prefix 过滤（该过滤反而会挡合法 dot-slug
        # 书，cc-19）；同文件系统 os.replace 仍然原子（k-12）。
        import os as _os

        stage = self.base_dir / f".bookshelf.{slug}.stage.{_os.getpid()}"
        # 只清本进程同 pid 的 stage（同进程重复 add 同 slug 时的残留）；不清别进程的 stage——
        # 那会破坏并发 add（k-18）。跨进程崩溃遗留的 stage/retire 分别是一次性中间产物 / 幸存副本，
        # 不自动回收（per-process 隔离），留给将来的 gc 命令。
        if stage.exists():
            shutil.rmtree(stage)
        # 外置初始化 dest_bak：否则 stage.mkdir 早期失败时 finally 会引用未绑定变量（k-15）
        dest_bak: Optional[Path] = None
        write_ok = False
        try:
            # 显式建书架根：stage 不再位于 bookshelf/ 下，不再有 mkdir(parents=True)
            # 顺带把 bookshelf/ 建出来的副作用；os.replace 需要目标父目录存在
            self.root.mkdir(parents=True, exist_ok=True)
            stage.mkdir(parents=True)
            self._copy_bundle_whitelist(bundle_src, stage / BUNDLE_DIRNAME)
            if original_file and orig_src_path is not None:
                shutil.copy2(str(orig_src_path), str(stage / original_file))
            meta.save(stage / META_FILENAME)
            dest = self.book_dir(slug)
            if dest.exists():
                dest_bak = self.base_dir / f".bookshelf.{slug}.retire.{_os.getpid()}"
                # k-19：同 pid 重复 force add 时 dest_bak 可能残留（同进程前次未清），replace 前先清目标
                if dest_bak.exists():
                    shutil.rmtree(dest_bak, ignore_errors=True)
                _os.replace(str(dest), str(dest_bak))  # 原子挪走旧 dest
            try:
                _os.replace(str(stage), str(dest))  # 成功：新书就位
            except OSError:
                # 替换失败：回滚，把旧 dest 挪回
                if dest_bak is not None and dest_bak.exists():
                    _os.replace(str(dest_bak), str(dest))
                raise
            write_ok = True  # 新书已就位
            # 成功后才删旧书备份（cc-21：放 finally 会吞掉双失败的唯一幸存副本）
            if dest_bak is not None and dest_bak.exists():
                try:
                    shutil.rmtree(dest_bak)
                except OSError as e:
                    # cc-23：不静默吞——记录孤儿 dest_bak 残留，便于排查/清理
                    logger.warning("清理旧书备份失败，残留孤儿目录 %s: %s", dest_bak, e)
        finally:
            # stage 是一次性中间产物，无论成败都清
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)
            if not write_ok and dest_bak is not None and dest_bak.exists():
                # 写入确实没完成（区别于「成功但清理失败」——后者 write_ok=True 不进这里），
                # dest_bak 是旧书唯一幸存副本，保留供排查
                logger.warning("写入未完成，旧书备份保留在 %s", dest_bak)

        # --move：成功替换后再删源（issue-2 点2：避免 meta.save 失败时源已搬走）。
        # 源在书架内部时跳过删源——那种情况源==目标书目录，删源=删新书（cc-1）。
        if move and not src_folder.is_relative_to(self.root.resolve()):
            safe_orig = orig_src_path
            if safe_orig is not None and safe_orig.is_relative_to(self.root.resolve()):
                # cc-1/D5：--original 指向书架内既有书的文件时跳过删源（删了=破坏既有书）
                safe_orig = None
            self._remove_consumed_sources(bundle_src, safe_orig, layout)

        return meta

    def remove(self, slug: str) -> None:
        d = self.book_dir(slug)
        if not d.exists():
            raise BookNotFoundError(slug)
        shutil.rmtree(d)

    _WINDOWS_RESERVED = (
        {"CON", "PRN", "AUX", "NUL"}
        | {f"COM{i}" for i in range(1, 10)}
        | {f"LPT{i}" for i in range(1, 10)}
    )

    @staticmethod
    def _validate_slug(slug: str) -> None:
        if not slug or slug in (".", ".."):
            raise InvalidBundleError(f"非法 slug: {slug!r}")
        forbidden = set('/:*?"<>|\\')
        if any(c in forbidden for c in slug) or any(ord(c) < 32 for c in slug):
            raise InvalidBundleError(f"非法 slug（含路径/非法字符）: {slug!r}")
        if slug != slug.rstrip(". "):
            raise InvalidBundleError(f"非法 slug（尾点/尾空格）: {slug!r}")
        if slug.split(".")[0].upper() in BookShelf._WINDOWS_RESERVED:
            raise InvalidBundleError(f"非法 slug（Windows 保留名）: {slug!r}")
        if len(slug.encode("utf-8")) > 80:
            # cc-20：按字节算（CJK/emoji 每字 3-4 字节），与 stage-dir 路径开销更贴切
            raise InvalidBundleError(f"非法 slug（超长，>80 字节）: {slug!r}")

    @staticmethod
    def _detect_bundle(src_folder: Path) -> tuple[Path, str]:
        """识别 bundle 源目录与布局：包装（<folder>/bundle/manifest.json，向后兼容）
        或扁平（<folder>/manifest.json，scan2book v1 真实产出）。返回 (bundle_src, layout)；
        都不在则报错。layout 供 --move 删源时区分整目录删 vs 仅删消费项（不靠 bundle_src
        名字猜——flat 文件夹可能恰叫 bundle）。"""
        wrapped = src_folder / BUNDLE_DIRNAME / MANIFEST_FILENAME
        if wrapped.exists():
            return src_folder / BUNDLE_DIRNAME, "wrapped"
        flat = src_folder / MANIFEST_FILENAME
        if flat.exists():
            return src_folder, "flat"
        raise InvalidBundleError(
            f"找不到 scan2book 产物 manifest.json（已尝试 "
            f"{BUNDLE_DIRNAME}/{MANIFEST_FILENAME} 与 {MANIFEST_FILENAME}）"
        )

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

    _KNOWN_ORIGINAL_EXTS = {".pdf", ".epub", ".mobi", ".azw", ".cbz", ".cbr", ".djvu"}

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

    def _resolve_original(self, src_folder: Path, original: Optional[str]) -> tuple:
        """返回 (原件绝对路径, 存储 basename, sha256)。
        --original 给定 → 用它（不存在则 InvalidBundleError，覆盖自动探测）；
        否则自动探测（仅已知扩展名，无则全 None）。原件源路径用于复制与 --move 删源。"""
        if original:
            raw = Path(original).expanduser()
            # cc-7（cc r1 issue-2）：拒绝软链——resolve 跟随软链会让 --move unlink 目标真实文件、
            # 留下悬空软链；自动探测 _find_original 经 _is_candidate_file 已排除软链，此处对齐
            if raw.is_symlink():
                raise InvalidBundleError(f"--original 不能是软链: {raw}")
            p = raw.resolve()
            if not p.is_file():
                raise InvalidBundleError(f"--original 指定的文件不存在: {p}")
            # cc r1 issue-3：防 basename 冲撞 dest 保留名（meta.json 会被 meta.save 覆盖致原件
            # 静默丢失）；再校验扩展名与 _find_original 的 _KNOWN_ORIGINAL_EXTS 白名单一致
            if p.name in _ORIGINAL_RESERVED_NAMES:
                raise InvalidBundleError(f"--original basename 与保留名冲撞: {p.name}")
            if p.suffix.lower() not in BookShelf._KNOWN_ORIGINAL_EXTS:
                raise InvalidBundleError(f"--original 非已知原件扩展名: {p.suffix or '(无)'}")
            return p, p.name, _sha256_of(p)
        name, sha = self._find_original(src_folder)
        if name is None:
            return None, None, None
        return src_folder / name, name, sha

    @staticmethod
    def _remove_consumed_sources(
        bundle_src: Path, orig_src_path: Optional[Path], layout: str
    ) -> None:
        """--move 删除本次消费的源：bundle 白名单组件（manifest/pages/images）+ 原件。
        layout 由 _detect_bundle 判定。包装→整 bundle/ 目录删；扁平→只删消费项，不动
        sibling 过程文件（checkpoint/qa_*）。原件删源见 add() 的书架内守卫。"""
        if layout == "wrapped":
            if bundle_src.exists():
                shutil.rmtree(bundle_src, ignore_errors=True)
        else:  # flat
            for name in BUNDLE_WHITELIST_FILES:
                f = bundle_src / name
                if f.is_file():
                    try:  # cc-6/cc r1 issue-1：删源失败不致「新书已就位却报失败」
                        f.unlink()
                    except OSError as e:
                        logger.warning("删源 bundle 文件失败（新书已就位）%s: %s", f, e)
            for d in BUNDLE_WHITELIST_DIRS:
                p = bundle_src / d
                if p.exists():
                    shutil.rmtree(p, ignore_errors=True)
        if orig_src_path is not None and orig_src_path.exists():
            try:
                orig_src_path.unlink()
            except OSError as e:
                logger.warning("删源原件失败（新书已就位）%s: %s", orig_src_path, e)
