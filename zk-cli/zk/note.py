"""笔记 CRUD 操作"""

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from .models import Note, NoteType
from .config import config
from .vector_store import get_vector_store

logger = logging.getLogger(__name__)


def generate_id() -> str:
    """生成时间戳 ID"""
    return datetime.now().strftime("%Y%m%d%H%M%S")


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
        with open(note.filepath, 'w', encoding='utf-8') as f:
            f.write(note.to_markdown())
        
        logger.info(f"Saved note to {note.filepath}")
        
        # 添加到向量索引
        if add_to_index:
            vector_store = get_vector_store()
            vector_store.add_note(note)
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to save note: {e}")
        return False


def load_note(filepath: Path) -> Optional[Note]:
    """从文件加载笔记"""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            content = f.read()
        
        return Note.from_markdown(content, filepath)
        
    except Exception as e:
        logger.error(f"Failed to load note from {filepath}: {e}")
        return None


def load_note_by_id(note_id: str) -> Optional[Note]:
    """通过 ID 加载笔记"""
    # 在所有类型目录中搜索
    for note_type in NoteType:
        dir_path = config.notes_dir / note_type.value
        if not dir_path.exists():
            continue
        
        for filepath in dir_path.glob(f"{note_id}*.md"):
            return load_note(filepath)
    
    return None


def list_notes(
    note_type: Optional[NoteType] = None,
    limit: Optional[int] = None,
) -> List[Note]:
    """列出笔记"""
    notes = []
    
    types_to_list = [note_type] if note_type else list(NoteType)
    
    for nt in types_to_list:
        dir_path = config.notes_dir / nt.value
        if not dir_path.exists():
            continue
        
        for filepath in sorted(dir_path.glob("*.md"), reverse=True):
            note = load_note(filepath)
            if note:
                notes.append(note)
            
            if limit and len(notes) >= limit:
                break
        
        if limit and len(notes) >= limit:
            break
    
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
        vector_store = get_vector_store()
        vector_store.delete_note(note_id)
        
        return True
        
    except Exception as e:
        logger.error(f"Failed to delete note {note_id}: {e}")
        return False


def get_stats() -> Dict[str, Any]:
    """获取知识库统计"""
    stats = {
        "total": 0,
        "by_type": {},
        "vector_store": {},
    }
    
    # 统计各类型笔记数量
    for note_type in NoteType:
        dir_path = config.notes_dir / note_type.value
        if dir_path.exists():
            count = len(list(dir_path.glob("*.md")))
            stats["by_type"][note_type.value] = count
            stats["total"] += count
    
    # 向量存储统计
    try:
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
) -> List[Dict[str, Any]]:
    """搜索笔记"""
    vector_store = get_vector_store()
    return vector_store.search(query, top_k=top_k, note_type=note_type)
