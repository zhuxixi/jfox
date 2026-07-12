"""笔记数据模型"""

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml


def _to_bool(value: Any) -> bool:
    """将 frontmatter 中的值安全转换为 bool，正确处理 YAML 字符串。

    YAML 中 archived: "false" 会被解析为字符串 "false"，
    直接用 bool() 会误判为 True，因此需要显式处理常见假值字符串。
    """
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() not in ("false", "0", "", "no", "off", "null", "none")
    return bool(value)


def _to_float(value, default=None):
    """安全转 float，非数值返回 default。

    YAML 解析出的 confidence 可能是 int（1）、str（"0.9"）或其它；统一成 float，
    保证 dataclass 字段类型一致，避免后续比较/序列化歧义。
    """
    if value is None:
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


class NoteType(Enum):
    """笔记类型"""

    FLEETING = "fleeting"  # 闪念笔记
    LITERATURE = "literature"  # 文献笔记
    PERMANENT = "permanent"  # 永久笔记
    SESSION = "session"  # AI Agent 会话记录
    CANDIDATE = "candidate"  # AI 合成的候选知识宝石（破损级，待 L5 审阅）


class GemLevel(str, Enum):
    """知识宝石等级（碎裂→破损→完整→完美→无暇）。L3 仅产出 FLAWED。"""

    CHIPPED = "chipped"  # 碎裂 — raw 碎片（fragments.db，非笔记）
    FLAWED = "flawed"  # 破损 — L3 合成的 candidate
    NORMAL = "normal"  # 完整 — L4/L5 成熟后
    FLAWLESS = "flawless"  # 完美
    PERFECT = "perfect"  # 无暇 — 晋升 permanent 的候选终态


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
    topic: Optional[str] = None  # 会话主题（session 类型）
    archived: bool = False  # 是否已归档（软删除标记）
    reject_reason: Optional[str] = None  # candidate reject 原因（供复盘）

    # candidate 字段：生命周期（gem_level/confidence/knowledge_type/status）仅 type=CANDIDATE 时序列化；
    # 溯源（source_fragments/grounded_by）跨类型保留——非空时写，promoted permanent 仍可追溯到来源碎片（#249）
    gem_level: Optional[str] = None
    confidence: Optional[float] = None
    source_fragments: List[int] = field(default_factory=list)  # 碎片溯源（跨类型保留）
    grounded_by: List[str] = field(default_factory=list)  # 参考笔记溯源（跨类型保留）
    knowledge_type: Optional[str] = None  # factual/procedural/preference/constraint
    status: Optional[str] = None  # pending → (L5) promoted/rejected

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
        elif self.type == NoteType.SESSION:
            source = self.topic or self.title or "untitled"
            slug = re.sub(r"[^\w\-]", "", source.lower().replace(" ", "-"))[:50]
            return f"{self.id}-{slug}.md"
        else:
            slug = self.title.lower().replace(" ", "-")[:50]
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
        if self.topic:
            frontmatter["topic"] = self.topic
        if self.archived:
            frontmatter["archived"] = self.archived

        # candidate 生命周期字段（仅 type=CANDIDATE 时写入 frontmatter）
        if self.type == NoteType.CANDIDATE:
            frontmatter["gem_level"] = self.gem_level or GemLevel.FLAWED.value
            if self.confidence is not None:
                frontmatter["confidence"] = self.confidence
            if self.knowledge_type:
                frontmatter["knowledge_type"] = self.knowledge_type
            if self.status:
                frontmatter["status"] = self.status
            if self.reject_reason:
                frontmatter["reject_reason"] = self.reject_reason
        # 溯源字段（跨类型保留：candidate 合成产出 + promoted permanent 都可追溯到来源碎片，#249）
        if self.source_fragments:
            frontmatter["source_fragments"] = self.source_fragments
        if self.grounded_by:
            frontmatter["grounded_by"] = self.grounded_by

        fm_yaml = yaml.dump(frontmatter, allow_unicode=True, sort_keys=False)

        return f"---\n{fm_yaml}---\n\n# {self.title}\n\n{self.content}\n"

    @classmethod
    def from_markdown(cls, content: str, filepath: Optional[Path] = None) -> "Note":
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
            topic=fm.get("topic"),
            archived=_to_bool(fm.get("archived", False)),
            reject_reason=fm.get("reject_reason"),
            gem_level=fm.get("gem_level"),
            confidence=_to_float(fm.get("confidence")),
            source_fragments=fm.get("source_fragments", []),
            grounded_by=fm.get("grounded_by", []),
            knowledge_type=fm.get("knowledge_type"),
            status=fm.get("status"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于 JSON 输出）"""
        d = {
            "id": self.id,
            "title": self.title,
            "content": self.content[:200] + "..." if len(self.content) > 200 else self.content,
            "type": self.type.value,
            "created": self.created.isoformat(),
            "updated": self.updated.isoformat(),
            "tags": self.tags,
            "links": self.links,
            "filepath": str(self.filepath),
            "archived": self.archived,
            "score": self.score,
            "hop": self.hop,
            "topic": self.topic,
        }
        # candidate 生命周期字段（仅 type=CANDIDATE 时输出）
        if self.type == NoteType.CANDIDATE:
            d["gem_level"] = self.gem_level or GemLevel.FLAWED.value
            if self.confidence is not None:
                d["confidence"] = self.confidence
            if self.knowledge_type:
                d["knowledge_type"] = self.knowledge_type
            if self.status:
                d["status"] = self.status
            if self.reject_reason:
                d["reject_reason"] = self.reject_reason
        # 溯源字段（跨类型输出，与 to_markdown 保持一致）
        if self.source_fragments:
            d["source_fragments"] = self.source_fragments
        if self.grounded_by:
            d["grounded_by"] = self.grounded_by
        return d

    def to_show_dict(self, raw_markdown: Optional[str] = None) -> Dict[str, Any]:
        """转换为 show --json 专用的完整字典。

        Args:
            raw_markdown: 笔记文件的完整原始 Markdown 内容（含 frontmatter）。
                如果未提供，则使用 to_markdown() 重新生成。

        Returns:
            包含完整字段的字典，schema 与 Issue #278 一致。
        """
        content = raw_markdown if raw_markdown is not None else self.to_markdown()
        # content_body: 去掉 frontmatter 后的 Markdown 主体
        body_match = re.match(r"^---\n.*?\n---\n+(.*)", content, re.DOTALL)
        content_body = body_match.group(1) if body_match else content

        d: Dict[str, Any] = {
            "id": self.id,
            "title": self.title,
            "type": self.type.value,
            "created": self.created.isoformat(),
            "updated": self.updated.isoformat(),
            "tags": self.tags,
            "links": self.links,
            "backlinks": self.backlinks,
            "topic": self.topic,
            "path": str(self.filepath),
            "content": content,
            "content_body": content_body,
        }
        # 可选附加字段（与 to_markdown 一致）
        if self.source:
            d["source"] = self.source
        if self.archived:
            d["archived"] = self.archived
        # candidate 专属字段
        if self.type == NoteType.CANDIDATE:
            d["gem_level"] = self.gem_level or GemLevel.FLAWED.value
            if self.confidence is not None:
                d["confidence"] = self.confidence
            if self.source_fragments:
                d["source_fragments"] = self.source_fragments
            if self.grounded_by:
                d["grounded_by"] = self.grounded_by
            if self.knowledge_type:
                d["knowledge_type"] = self.knowledge_type
            if self.status:
                d["status"] = self.status
        return d
