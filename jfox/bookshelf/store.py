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


class BookAlreadyExistsError(Exception):
    """slug 已存在且未 --force。"""


class BookNotFoundError(Exception):
    """slug 不在书架上。"""


class InvalidBundleError(Exception):
    """输入文件夹不是合法 scan2book bundle。"""


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


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
            # k-14：跳过历史 stage/retire 残留目录名（新代码已移出 bookshelf/，此为兜底）
            if re.match(r"^\..*\.(stage|retire)\.\d+$", meta_file.parent.name):
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
            return json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise InvalidBundleError(f"{slug} bundle manifest 解析失败: {e}") from e

    def add(
        self,
        src_folder: Path,
        *,
        slug: Optional[str] = None,
        move: bool = False,
        force: bool = False,
        added_at: Optional[str] = None,
    ) -> BookMeta:
        src_folder = Path(src_folder).expanduser().resolve()
        manifest_path = src_folder / BUNDLE_DIRNAME / MANIFEST_FILENAME
        if not manifest_path.exists():
            raise InvalidBundleError(
                f"找不到 {manifest_path}（需要 scan2book 产物 bundle/manifest.json）"
            )
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            raise InvalidBundleError(f"manifest.json 解析失败: {e}") from e
        if slug is None:
            slug = manifest.get("slug") or src_folder.name
        self._validate_slug(slug)
        original_file, original_sha256 = self._find_original(src_folder)
        if added_at is None:
            added_at = _now_iso()
        user_meta_path = src_folder / META_FILENAME
        if user_meta_path.exists():
            try:
                raw = json.loads(user_meta_path.read_text(encoding="utf-8"))
            except json.JSONDecodeError as e:
                raise InvalidBundleError(f"meta.json 解析失败: {e}") from e
            raw.setdefault("source", {})
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
        # k-12：清理同 slug 历史 stage/retire 残留（上次崩溃遗留），避免 os.replace 目标已存在
        for stale in self.base_dir.glob(f".bookshelf.{slug}.stage.*"):
            shutil.rmtree(stale, ignore_errors=True)
        for stale in self.base_dir.glob(f".bookshelf.{slug}.retire.*"):
            shutil.rmtree(stale, ignore_errors=True)
        if stage.exists():
            shutil.rmtree(stage)
        try:
            # 显式建书架根：stage 不再位于 bookshelf/ 下，不再有 mkdir(parents=True)
            # 顺带把 bookshelf/ 建出来的副作用；os.replace 需要目标父目录存在
            self.root.mkdir(parents=True, exist_ok=True)
            stage.mkdir(parents=True)
            bundle_src = src_folder / BUNDLE_DIRNAME
            shutil.copytree(str(bundle_src), str(stage / BUNDLE_DIRNAME))
            if original_file:
                orig_src = src_folder / original_file
                if orig_src.exists():
                    shutil.copy2(str(orig_src), str(stage / original_file))
            meta.save(stage / META_FILENAME)
            dest = self.book_dir(slug)
            dest_bak: Optional[Path] = None
            if dest.exists():
                dest_bak = self.base_dir / f".bookshelf.{slug}.retire.{_os.getpid()}"
                _os.replace(str(dest), str(dest_bak))  # 原子挪走旧 dest
            try:
                _os.replace(str(stage), str(dest))  # 成功：新书就位
            except OSError:
                # 替换失败：回滚，把旧 dest 挪回
                if dest_bak is not None and dest_bak.exists():
                    _os.replace(str(dest_bak), str(dest))
                raise
            # 成功后才删旧书备份（cc-21：放 finally 会吞掉双失败的唯一幸存副本）
            if dest_bak is not None and dest_bak.exists():
                try:
                    shutil.rmtree(dest_bak)
                except OSError as e:
                    # cc-23：不静默吞——记录孤儿 dest_bak 残留，便于排查/清理
                    logger.warning("清理旧书备份失败，残留孤儿目录 %s: %s", dest_bak, e)
        finally:
            # stage 是一次性中间产物，无论成败都清；dest_bak 由成功分支自己清
            if stage.exists():
                shutil.rmtree(stage, ignore_errors=True)
            if dest_bak is not None and dest_bak.exists():
                # cc-23：到这里说明成功分支没清掉 dest_bak（写入/回滚失败）——它是旧书唯一幸存
                # 副本，不能删，记录在案供排查
                logger.warning("写入未完成，旧书备份保留在 %s", dest_bak)

        # --move：成功替换后再删源（issue-2 点2：避免 meta.save 失败时源已搬走）
        if move:
            shutil.rmtree(str(src_folder / BUNDLE_DIRNAME), ignore_errors=True)
            if original_file:
                orig_src = src_folder / original_file
                if orig_src.exists():
                    orig_src.unlink()

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

    _KNOWN_ORIGINAL_EXTS = {".pdf", ".epub", ".mobi", ".azw", ".cbz", ".cbr", ".djvu"}

    @staticmethod
    def _find_original(src_folder: Path):
        """挑原件：优先已知原件扩展名，否则退回最大文件。按 (-size, name) 确定性排序，
        避免大小并列时 max() 因遍历顺序不同而跨机器不稳定。"""
        all_entries = list(src_folder.iterdir())
        files = [f for f in all_entries if f.is_file() and f.name != META_FILENAME]
        if not files:
            return None, None
        known = [f for f in files if f.suffix.lower() in BookShelf._KNOWN_ORIGINAL_EXTS]
        pool = known or files
        biggest = sorted(pool, key=lambda f: (-f.stat().st_size, f.name.lower()))[0]
        h = hashlib.sha256()
        with biggest.open("rb") as fh:
            for chunk in iter(lambda: fh.read(65536), b""):
                h.update(chunk)
        return biggest.name, h.hexdigest()
