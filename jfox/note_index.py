"""轻量级元数据索引，只解析 frontmatter 不读正文"""

import logging
import time
from datetime import datetime
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import yaml

from .config import ZKConfig
from .models import NoteType

logger = logging.getLogger(__name__)


@dataclass
class NoteMeta:
    """笔记元数据（不含正文）"""

    id: str
    title: str
    type: NoteType
    tags: List[str] = field(default_factory=list)
    created: str = ""
    updated: str = ""
    filepath: str = ""
    links: List[str] = field(default_factory=list)
    backlinks: List[str] = field(default_factory=list)


_MAX_FRONTMATTER_LINES = 200


def _parse_frontmatter_only(filepath: Path) -> Optional[dict]:
    """只读取 frontmatter 部分，不解析正文内容。

    Returns:
        解析后的 frontmatter dict，解析失败返回 None
    """
    try:
        with open(filepath, "r", encoding="utf-8-sig") as f:
            first_line = f.readline()
            if first_line.strip() != "---":
                return None

            lines = []
            for line in f:
                stripped = line.strip()
                if stripped == "---":
                    break
                lines.append(line)
                if len(lines) > _MAX_FRONTMATTER_LINES:
                    return None

            if not lines:
                return None

            fm_text = "".join(lines)
            result = yaml.safe_load(fm_text)
            if not isinstance(result, dict):
                return None
            return result

    except (yaml.YAMLError, UnicodeDecodeError, OSError, AttributeError):
        return None


class NoteIndex:
    """轻量级元数据索引，CLI 模式每次启动时重建"""

    def __init__(self, cfg: ZKConfig):
        self._cfg = cfg
        self._by_id: Dict[str, NoteMeta] = {}
        self._by_title: Dict[str, NoteMeta] = {}  # title.lower() -> meta
        self._by_type: Dict[NoteType, List[NoteMeta]] = {t: [] for t in NoteType}
        self._invalid_files: List[str] = []

    def rebuild(self) -> None:
        """重建索引：遍历所有笔记目录，只解析 frontmatter"""
        self._by_id.clear()
        self._by_title.clear()
        for t in NoteType:
            self._by_type[t] = []
        self._invalid_files.clear()

        start = time.monotonic()

        for note_type in NoteType:
            dir_path = self._cfg.notes_dir / note_type.value
            if not dir_path.exists():
                continue

            for filepath in sorted(dir_path.glob("*.md"), reverse=True):
                fm = _parse_frontmatter_only(filepath)
                if fm is None:
                    self._invalid_files.append(str(filepath))
                    continue

                try:
                    note_id = fm.get("id", "")
                    if not note_id:
                        self._invalid_files.append(str(filepath))
                        continue

                    def _to_str(val):
                        if val is None:
                            return ""
                        if isinstance(val, datetime):
                            return val.isoformat()
                        return str(val)

                    def _to_list(val):
                        if val is None:
                            return []
                        return list(val) if isinstance(val, list) else []

                    meta = NoteMeta(
                        id=note_id,
                        title=fm.get("title", "Untitled"),
                        type=NoteType(fm.get("type", "fleeting")),
                        tags=_to_list(fm.get("tags")),
                        created=_to_str(fm.get("created")),
                        updated=_to_str(fm.get("updated")),
                        filepath=str(filepath),
                        links=_to_list(fm.get("links")),
                        backlinks=_to_list(fm.get("backlinks")),
                    )

                    self._by_id[meta.id] = meta
                    lower_title = meta.title.lower()
                    if lower_title in self._by_title:
                        logger.debug(
                            f"Duplicate title '{meta.title}': "
                            f"overwriting {self._by_title[lower_title].id} with {meta.id}"
                        )
                    self._by_title[lower_title] = meta
                    self._by_type[meta.type].append(meta)

                except (ValueError, KeyError):
                    self._invalid_files.append(str(filepath))
                    continue

        elapsed = time.monotonic() - start
        logger.debug(
            f"NoteIndex rebuilt: {len(self._by_id)} notes, "
            f"{len(self._invalid_files)} invalid, "
            f"{elapsed:.3f}s"
        )

    def find_by_id(self, note_id: str) -> Optional[NoteMeta]:
        """按 ID 精确查找"""
        return self._by_id.get(note_id)

    def find_by_title(self, title: str) -> Optional[NoteMeta]:
        """按标题查找（大小写不敏感）"""
        return self._by_title.get(title.lower())

    def find_by_title_prefix(self, prefix: str) -> List[NoteMeta]:
        """按标题前缀模糊匹配"""
        prefix_lower = prefix.lower()
        return [m for m in self._by_id.values() if m.title.lower().startswith(prefix_lower)]

    def list_meta(
        self,
        note_type: Optional[NoteType] = None,
        tags: Optional[List[str]] = None,
        limit: Optional[int] = None,
    ) -> List[NoteMeta]:
        """列出元数据，支持类型/标签过滤和 limit 截断"""
        if note_type:
            result = list(self._by_type.get(note_type, []))
        else:
            result = list(self._by_id.values())

        if tags:
            result = [m for m in result if all(t in m.tags for t in tags)]

        if limit:
            result = result[:limit]

        return result

    def get_all_meta(self) -> List[NoteMeta]:
        """返回全部元数据"""
        return list(self._by_id.values())

    def get_invalid_files(self) -> List[str]:
        """返回无效文件路径列表"""
        return list(self._invalid_files)


# 模块级缓存：同一命令进程内只构建一次
_index_cache: Optional[NoteIndex] = None
_index_cfg_path: Optional[str] = None


def get_note_index(cfg: Optional[ZKConfig] = None) -> NoteIndex:
    """获取 NoteIndex 单例（按 cfg.base_dir 缓存）"""
    from .config import config

    use_cfg = cfg or config
    global _index_cache, _index_cfg_path

    cfg_path = str(use_cfg.base_dir)
    if _index_cache is not None and _index_cfg_path == cfg_path:
        return _index_cache

    idx = NoteIndex(use_cfg)
    idx.rebuild()
    _index_cache = idx
    _index_cfg_path = cfg_path
    return idx


def reset_note_index():
    """重置索引缓存（供 use_kb 切换知识库时调用）"""
    global _index_cache, _index_cfg_path
    _index_cache = None
    _index_cfg_path = None
