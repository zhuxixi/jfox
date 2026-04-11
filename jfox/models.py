"""笔记数据模型"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


class NoteType(Enum):
    """笔记类型"""

    FLEETING = "fleeting"  # 闪念笔记
    LITERATURE = "literature"  # 文献笔记
    PERMANENT = "permanent"  # 永久笔记


@dataclass
class Note:
    """知识卡片模型"""

    id: str  # 时间戳 ID (20250322143022)
    title: str  # 标题
    content: str  # 内容 (Markdown)
    type: NoteType  # 类型
    created: datetime  # 创建时间
    updated: datetime  # 更新时间
    tags: List[str] = field(default_factory=list)
    links: List[str] = field(default_factory=list)  # 正向链接
    backlinks: List[str] = field(default_factory=list)  # 反向链接
    source: Optional[str] = None  # 来源（文献笔记）

    # 运行时字段（不持久化到 frontmatter）
    embedding: Optional[List[float]] = None  # 向量
    score: Optional[float] = None  # 检索得分
    hop: Optional[int] = None  # 图谱距离
    _filepath: Optional[Path] = None  # 自定义文件路径（覆盖默认）

    def set_filepath(self, path: Path):
        """设置自定义文件路径（用于测试）"""
        self._filepath = path

    @property
    def filename(self) -> str:
        """生成文件名"""
        if self.type == NoteType.FLEETING:
            return f"{self.id[:8]}-{self.id[8:]}.md"
        else:
            slug = self.title.lower().replace(" ", "-")[:50]
            # 移除特殊字符
            slug = re.sub(r"[^\w\-]", "", slug)
            return f"{self.id}-{slug}.md"

    @property
    def filepath(self) -> Path:
        """完整文件路径"""
        # 如果设置了自定义路径，优先使用
        if self._filepath is not None:
            return self._filepath

        from .config import config

        base = config.notes_dir / self.type.value
        return base / self.filename

    def to_markdown(self) -> str:
        """转换为 Markdown 格式"""
        frontmatter = {
            "id": self.id,
            "title": self.title,
            "type": self.type.value,
            "created": self.created.isoformat(),
            "updated": self.updated.isoformat(),
            "tags": self.tags,
            "links": self.links,
            "backlinks": self.backlinks,
        }
        if self.source:
            frontmatter["source"] = self.source

        fm_yaml = yaml.dump(frontmatter, allow_unicode=True, sort_keys=False)

        return f"---\n{fm_yaml}---\n\n# {self.title}\n\n{self.content}\n"

    @classmethod
    def from_markdown(cls, content: str, filepath: Path) -> "Note":
        """从 Markdown 解析"""
        # 解析 frontmatter
        match = re.match(r"^---\n(.*?)\n---\n+(.*)", content, re.DOTALL)
        if not match:
            raise ValueError("Invalid markdown format: missing frontmatter")

        fm = yaml.safe_load(match.group(1))
        body = match.group(2)

        # 提取标题
        title_match = re.search(r"^# (.+)$", body, re.MULTILINE)
        title = title_match.group(1) if title_match else fm.get("title", "Untitled")

        # 提取内容（去除标题）
        content_text = re.sub(r"^# .+\n+", "", body, count=1)

        # 解析时间
        created_str = fm.get("created", datetime.now().isoformat())
        updated_str = fm.get("updated", datetime.now().isoformat())

        if isinstance(created_str, datetime):
            created = created_str
        else:
            created = datetime.fromisoformat(created_str)

        if isinstance(updated_str, datetime):
            updated = updated_str
        else:
            updated = datetime.fromisoformat(updated_str)

        return cls(
            id=fm.get("id", ""),
            title=fm.get("title", title),
            content=content_text.strip(),
            type=NoteType(fm.get("type", "fleeting")),
            created=created,
            updated=updated,
            tags=fm.get("tags", []),
            links=fm.get("links", []),
            backlinks=fm.get("backlinks", []),
            source=fm.get("source"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于 JSON 输出）"""
        return {
            "id": self.id,
            "title": self.title,
            "content": self.content[:200] + "..." if len(self.content) > 200 else self.content,
            "type": self.type.value,
            "created": self.created.isoformat(),
            "updated": self.updated.isoformat(),
            "tags": self.tags,
            "links": self.links,
            "filepath": str(self.filepath),
            "score": self.score,
            "hop": self.hop,
        }
