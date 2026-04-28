"""笔记 CRUD 操作"""

import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .config import ZKConfig, config
from .models import Note, NoteType

logger = logging.getLogger(__name__)


def generate_id() -> str:
    """
    生成唯一 ID

    格式: 时间戳 + 4位随机数 (共18位)
    例如: 202603242325281234
    """
    import random

    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    random_suffix = random.randint(0, 9999)
    return f"{timestamp}{random_suffix:04d}"


def create_note(
    content: str,
    title: Optional[str] = None,
    note_type: NoteType = NoteType.FLEETING,
    tags: Optional[List[str]] = None,
    links: Optional[List[str]] = None,
    source: Optional[str] = None,
) -> Note:
    """创建新笔记"""
    note_id = generate_id()
    now = datetime.now()

    # 如果没有标题，从内容提取
    if title is None:
        title = content[:50] + "..." if len(content) > 50 else content

    note = Note(
        id=note_id,
        title=title,
        content=content,
        type=note_type,
        created=now,
        updated=now,
        tags=tags or [],
        links=links or [],
        backlinks=[],
        source=source,
    )

    return note


def save_note(note: Note, add_to_index: bool = True) -> bool:
    """保存笔记到文件"""
    try:
        # 确保目录存在
        note.filepath.parent.mkdir(parents=True, exist_ok=True)

        # 写入文件
        with open(note.filepath, "w", encoding="utf-8") as f:
            f.write(note.to_markdown())

        logger.info(f"Saved note to {note.filepath}")

        # 添加到向量索引
        if add_to_index:
            from .vector_store import get_vector_store

            vector_store = get_vector_store()
            vector_store.add_note(note)

            # 添加到 BM25 索引
            try:
                from .bm25_index import get_bm25_index

                bm25_index = get_bm25_index()
                content = f"{note.title} {note.content}"
                bm25_index.add_document(note.id, content)
            except Exception as e:
                logger.warning(f"Failed to add note to BM25 index: {e}")

        return True

    except Exception as e:
        logger.error(f"Failed to save note: {e}")
        return False


def load_note(filepath: Path) -> Optional[Note]:
    """从文件加载笔记"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        return Note.from_markdown(content, filepath)

    except Exception as e:
        logger.error(f"Failed to load note from {filepath}: {e}")
        return None


def load_note_by_id(note_id: str, cfg: Optional[ZKConfig] = None) -> Optional[Note]:
    """
    通过 ID 加载笔记

    Args:
        note_id: 笔记 ID
        cfg: 可选的配置对象，默认使用全局 config

    Returns:
        Note 对象或 None
    """
    use_config = cfg or config

    # 在所有类型目录中搜索
    for note_type in NoteType:
        dir_path = use_config.notes_dir / note_type.value
        if not dir_path.exists():
            continue

        # 尝试两种文件名模式：
        # 1. {id}*.md — literature/permanent 笔记（{id}-{slug}.md）
        # 2. {id[:8]}-{id[8:]}*.md — fleeting 笔记（YYYYMMDD-HHMMSSNNNN.md）
        for filepath in dir_path.glob(f"{note_id}*.md"):
            return load_note(filepath)
        # fleeting 笔记文件名格式：YYYYMMDD-HHMMSSNNNN.md
        if len(note_id) > 8:
            for filepath in dir_path.glob(f"{note_id[:8]}-{note_id[8:]}*.md"):
                return load_note(filepath)

    return None


def list_notes(
    note_type: Optional[NoteType] = None,
    limit: Optional[int] = None,
    cfg: Optional[ZKConfig] = None,
    tags: Optional[List[str]] = None,
) -> List[Note]:
    """
    列出笔记

    Args:
        note_type: 笔记类型筛选
        limit: 数量限制
        cfg: 可选的配置对象，默认使用全局 config
        tags: 标签筛选列表（AND 逻辑）

    Returns:
        笔记列表
    """
    use_config = cfg or config
    notes = []

    types_to_list = [note_type] if note_type else list(NoteType)

    for nt in types_to_list:
        dir_path = use_config.notes_dir / nt.value
        if not dir_path.exists():
            continue

        for filepath in sorted(dir_path.glob("*.md"), reverse=True):
            note = load_note(filepath)
            if note:
                notes.append(note)

    # 标签过滤（AND 逻辑）—— 先过滤再截断，避免 limit + tags 组合时数量不足
    if tags:
        notes = [n for n in notes if all(t in n.tags for t in tags)]

    # 截断到 limit
    if limit:
        notes = notes[:limit]

    # 标签过滤（AND 逻辑）
    if tags:
        notes = [n for n in notes if all(t in n.tags for t in tags)]

    return notes


def delete_note(note_id: str) -> bool:
    """删除笔记"""
    note = load_note_by_id(note_id)
    if not note:
        logger.warning(f"Note {note_id} not found")
        return False

    try:
        # 删除文件
        note.filepath.unlink()
        logger.info(f"Deleted note file: {note.filepath}")

        # 从向量索引删除
        from .vector_store import get_vector_store

        vector_store = get_vector_store()
        vector_store.delete_note(note_id)

        # 从 BM25 索引删除
        try:
            from .bm25_index import get_bm25_index

            bm25_index = get_bm25_index()
            bm25_index.remove_document(note_id)
        except Exception as e:
            logger.warning(f"Failed to remove note from BM25 index: {e}")

        return True

    except Exception as e:
        logger.error(f"Failed to delete note {note_id}: {e}")
        return False


def update_note(note_obj: Note, add_to_index: bool = True) -> bool:
    """
    更新已有笔记

    处理：查找旧文件 → 更新 updated 时间戳 → 写入新文件 → 删除旧文件（如路径变化）→ 更新索引

    Args:
        note_obj: 已修改的 Note 对象（必须已有 id）
        add_to_index: 是否更新搜索索引

    Returns:
        是否更新成功
    """
    # 查找当前文件路径（可能标题改了，按 ID 查）
    old_filepath = find_note_file(config, note_obj.id)
    if not old_filepath:
        logger.warning(f"Note {note_obj.id} file not found on disk")
        return False

    try:
        # 更新时间戳
        note_obj.updated = datetime.now()

        # 写入新文件（filepath 属性根据当前字段生成）
        note_obj.filepath.parent.mkdir(parents=True, exist_ok=True)
        with open(note_obj.filepath, "w", encoding="utf-8") as f:
            f.write(note_obj.to_markdown())

        # 如果文件路径变了（标题修改导致重命名），删除旧文件
        if old_filepath != note_obj.filepath and old_filepath.exists():
            old_filepath.unlink()
            logger.info(f"Renamed note file: {old_filepath} -> {note_obj.filepath}")

        logger.info(f"Updated note {note_obj.id}")

        # 更新索引
        if add_to_index:
            # 先删除旧索引，再添加新索引
            try:
                from .vector_store import get_vector_store

                vector_store = get_vector_store()
                vector_store.delete_note(note_obj.id)
                vector_store.add_note(note_obj)
            except Exception as e:
                logger.warning(f"Failed to update vector store index: {e}")

            try:
                from .bm25_index import get_bm25_index

                bm25_index = get_bm25_index()
                bm25_index.remove_document(note_obj.id)
                content = f"{note_obj.title} {note_obj.content}"
                bm25_index.add_document(note_obj.id, content)
            except Exception as e:
                logger.warning(f"Failed to update BM25 index: {e}")

        return True

    except Exception as e:
        logger.error(f"Failed to update note {note_obj.id}: {e}")
        return False


def get_stats(cfg: Optional[ZKConfig] = None) -> Dict[str, Any]:
    """
    获取知识库统计

    Args:
        cfg: 可选的配置对象，默认使用全局 config

    Returns:
        统计信息字典
    """
    use_config = cfg or config

    stats = {
        "total": 0,
        "by_type": {},
        "vector_store": {},
    }

    # 统计各类型笔记数量
    for note_type in NoteType:
        dir_path = use_config.notes_dir / note_type.value
        if dir_path.exists():
            count = len(list(dir_path.glob("*.md")))
            stats["by_type"][note_type.value] = count
            stats["total"] += count

    # 向量存储统计
    try:
        from .vector_store import get_vector_store

        vector_store = get_vector_store()
        stats["vector_store"] = vector_store.get_stats()
    except Exception as e:
        logger.warning(f"Failed to get vector store stats: {e}")
        stats["vector_store"] = {"error": str(e)}

    return stats


def search_notes(
    query: str,
    top_k: int = 5,
    note_type: Optional[str] = None,
    mode: str = "hybrid",
    tags: Optional[List[str]] = None,
) -> List[Dict[str, Any]]:
    """
    搜索笔记

    Args:
        query: 搜索查询
        top_k: 返回结果数量
        note_type: 笔记类型筛选
        mode: 搜索模式 - "hybrid"(混合), "semantic"(语义), "keyword"(关键词)
        tags: 标签筛选列表（AND 逻辑）

    Returns:
        搜索结果列表
    """
    from .search_engine import SearchMode, get_search_engine

    search_engine = get_search_engine()

    # 转换模式
    mode_map = {
        "hybrid": SearchMode.HYBRID,
        "semantic": SearchMode.SEMANTIC,
        "keyword": SearchMode.KEYWORD,
    }
    search_mode = mode_map.get(mode.lower(), SearchMode.HYBRID)

    return search_engine.search(
        query, top_k=top_k, mode=search_mode, note_type=note_type, tags=tags
    )


def extract_keywords(content: str, max_keywords: int = 10) -> List[str]:
    """
    从内容中提取关键词

    简单实现：提取长度在 2-20 之间的单词/词组，排除常见停用词

    Args:
        content: 文本内容
        max_keywords: 最大关键词数量

    Returns:
        关键词列表
    """
    import re

    # 常见中文和英文停用词
    stopwords = {
        "the",
        "a",
        "an",
        "is",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "must",
        "shall",
        "can",
        "need",
        "dare",
        "ought",
        "used",
        "to",
        "of",
        "in",
        "for",
        "on",
        "with",
        "at",
        "by",
        "from",
        "as",
        "into",
        "through",
        "during",
        "before",
        "after",
        "above",
        "below",
        "between",
        "under",
        "and",
        "but",
        "or",
        "yet",
        "so",
        "if",
        "because",
        "although",
        "though",
        "while",
        "where",
        "when",
        "that",
        "which",
        "who",
        "whom",
        "whose",
        "what",
        "this",
        "these",
        "those",
        "i",
        "you",
        "he",
        "she",
        "it",
        "we",
        "they",
        "me",
        "him",
        "her",
        "us",
        "them",
        "my",
        "your",
        "his",
        "its",
        "our",
        "their",
        "这里",
        "那里",
        "这个",
        "那个",
        "什么",
        "怎么",
        "为什么",
        "因为",
        "所以",
        "但是",
        "如果",
        "虽然",
        "而且",
        "或者",
        "和",
        "与",
        "的",
        "了",
        "在",
        "是",
        "我",
        "你",
        "他",
        "她",
        "它",
        "们",
        "有",
        "没有",
        "一个",
        "一种",
        "一些",
        "可以",
        "需要",
        "应该",
        "能够",
        "已经",
        "现在",
        "今天",
        "明天",
        "昨天",
        "这样",
        "那样",
        "如何",
        "谁",
        "哪",
        "哪些",
        "哪里",
        "什么时候",
        "怎样",
        "非常",
        "很",
        "太",
        "最",
        "更",
        "比较",
        "相当",
        "真的",
        "确实",
        "当然",
        "可能",
        "也许",
        "大概",
        "一定",
        "必须",
        "得",
        "地",
        "着",
        "过",
        "把",
        "被",
        "让",
        "给",
        "向",
        "从",
        "到",
        "对于",
        "关于",
        "由于",
        "根据",
        "按照",
        "通过",
        "随着",
        "除了",
        "包括",
        "涉及",
        "有关",
        "学习",
        "使用",
        "实现",
        "添加",
        "创建",
        "记录",
        "今天",
        "一下",
    }

    # 提取潜在关键词（2-20 个字符的词组）
    # 匹配中文字符串或英文单词
    pattern = r"[\u4e00-\u9fff]{2,10}|[a-zA-Z][a-zA-Z0-9_]{1,15}"
    matches = re.findall(pattern, content.lower())

    # 统计词频
    word_counts = {}
    for word in matches:
        if word not in stopwords and len(word) >= 2:
            word_counts[word] = word_counts.get(word, 0) + 1

    # 按词频排序，返回前 max_keywords 个
    sorted_words = sorted(word_counts.items(), key=lambda x: x[1], reverse=True)
    return [word for word, count in sorted_words[:max_keywords]]


def suggest_links(
    content: str,
    top_k: int = 5,
    threshold: float = 0.6,
    exclude_ids: Optional[List[str]] = None,
    cfg: Optional[ZKConfig] = None,
) -> List[Dict[str, Any]]:
    """
    根据内容推荐可以链接的已有笔记

    使用语义相似度 + 关键词匹配的混合策略

    Args:
        content: 输入内容
        top_k: 返回建议数量
        threshold: 相似度阈值（0-1）
        exclude_ids: 要排除的笔记 ID 列表
        cfg: 可选的配置对象，默认使用全局 config

    Returns:
        建议链接的笔记列表，按置信度排序
    """
    exclude_ids = exclude_ids or []
    suggestions = []
    seen_ids = set(exclude_ids)

    # 1. 语义搜索 - 获取相似笔记
    try:
        semantic_results = search_notes(content, top_k=top_k * 2)
        for r in semantic_results:
            note_id = r.get("id")
            if note_id and note_id not in seen_ids:
                score = r.get("score", 0)
                if score >= threshold:
                    suggestions.append(
                        {
                            "id": note_id,
                            "title": r.get("metadata", {}).get("title", "Untitled"),
                            "type": r.get("metadata", {}).get("type", "unknown"),
                            "score": round(score, 3),
                            "match_type": "semantic",
                            "preview": (
                                r.get("document", "")[:150] + "..." if r.get("document") else ""
                            ),
                        }
                    )
                    seen_ids.add(note_id)
    except Exception as e:
        logger.warning(f"Semantic search failed in suggest_links: {e}")

    # 2. 关键词匹配 - 作为补充
    try:
        keywords = extract_keywords(content, max_keywords=5)
        if keywords:
            all_notes = list_notes(limit=200, cfg=cfg)  # 获取足够多的笔记用于匹配

            for note in all_notes:
                if note.id in seen_ids:
                    continue

                # 计算关键词匹配分数
                note_text = f"{note.title} {' '.join(note.tags)} {note.content[:500]}"
                note_text_lower = note_text.lower()

                match_count = 0
                for kw in keywords:
                    if kw.lower() in note_text_lower:
                        match_count += 1

                if match_count > 0:
                    # 关键词匹配分数 (0.3 - 0.6)
                    keyword_score = 0.3 + (match_count / len(keywords)) * 0.3

                    # 如果分数达到阈值且结果数量不足，添加
                    if keyword_score >= threshold * 0.5 and len(suggestions) < top_k * 2:
                        suggestions.append(
                            {
                                "id": note.id,
                                "title": note.title,
                                "type": note.type.value,
                                "score": round(keyword_score, 3),
                                "match_type": "keyword",
                                "matched_keywords": [
                                    kw for kw in keywords if kw.lower() in note_text_lower
                                ],
                                "preview": note.content[:150] + "..." if note.content else "",
                            }
                        )
                        seen_ids.add(note.id)
    except Exception as e:
        logger.warning(f"Keyword matching failed in suggest_links: {e}")

    # 3. 按分数排序并返回前 top_k 个
    suggestions.sort(key=lambda x: x["score"], reverse=True)
    return suggestions[:top_k]


def find_note_file(config_obj, note_id: str) -> Optional[Path]:
    """
    通过 ID 查找笔记文件路径

    Args:
        config_obj: ZKConfig 配置对象
        note_id: 笔记 ID

    Returns:
        文件路径或 None
    """
    for note_type in NoteType:
        dir_path = config_obj.notes_dir / note_type.value
        if not dir_path.exists():
            continue

        # 尝试两种文件名模式：
        # 1. {id}*.md — literature/permanent 笔记（{id}-{slug}.md）
        # 2. {id[:8]}-{id[8:]}*.md — fleeting 笔记（YYYYMMDD-HHMMSSNNNN.md）
        for filepath in dir_path.glob(f"{note_id}*.md"):
            return filepath
        if len(note_id) > 8:
            for filepath in dir_path.glob(f"{note_id[:8]}-{note_id[8:]}*.md"):
                return filepath

    return None


class NoteManager:
    """笔记管理器类，用于面向对象的操作"""

    @staticmethod
    def load_note(filepath: Path) -> Optional[Note]:
        """从文件加载笔记"""
        return load_note_static(filepath)

    @staticmethod
    def find_note_file(config_obj, note_id: str) -> Optional[Path]:
        """通过 ID 查找笔记文件路径"""
        return find_note_file(config_obj, note_id)


def load_note_static(filepath: Path) -> Optional[Note]:
    """从文件加载笔记（静态版本）"""
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            content = f.read()

        return Note.from_markdown(content, filepath)

    except Exception as e:
        logger.error(f"Failed to load note from {filepath}: {e}")
        return None
