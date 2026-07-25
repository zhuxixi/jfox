"""JFox bookshelf 子包：好书资产管理（PDF + scan2book bundle + 元数据）。"""

from .meta import BookMeta, build_meta_from_bundle, normalize_user_meta

__all__ = ["BookMeta", "build_meta_from_bundle", "normalize_user_meta"]
