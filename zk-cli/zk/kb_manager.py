"""
知识库管理器 - 高级知识库操作

提供知识库的创建、删除、统计等功能
"""

import shutil
import logging
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import List, Optional, Dict, Any

from .global_config import (
    GlobalConfigManager, 
    KnowledgeBaseEntry, 
    get_global_config_manager,
    DEFAULT_KB_PATH
)
from .config import ZKConfig


logger = logging.getLogger(__name__)


@dataclass
class KBStats:
    """知识库统计信息"""
    name: str
    path: Path
    total_notes: int
    by_type: Dict[str, int]
    created: Optional[str] = None
    last_used: Optional[str] = None
    description: Optional[str] = None
    is_current: bool = False


class KnowledgeBaseManager:
    """
    知识库管理器
    
    提供知识库的完整生命周期管理：
    - 创建、删除、重命名
    - 统计信息
    - 切换默认知识库
    """
    
    def __init__(self, config_manager: Optional[GlobalConfigManager] = None):
        self.config_manager = config_manager or get_global_config_manager()
    
    def create(
        self, 
        name: str, 
        path: Optional[Path] = None,
        description: Optional[str] = None,
        set_as_default: bool = False
    ) -> tuple[bool, str]:
        """
        创建新知识库
        
        Args:
            name: 知识库名称
            path: 存储路径（默认 ~/.zettelkasten/<name>/）
            description: 描述
            set_as_default: 是否设为默认
            
        Returns:
            (success, message)
        """
        # 检查名称是否已存在
        if self.config_manager.kb_exists(name):
            return False, f"Knowledge base '{name}' already exists"
        
        # 确定路径（统一管理到 ~/.zettelkasten/ 下）
        if path is None:
            if name == "default":
                path = DEFAULT_KB_PATH
            else:
                path = DEFAULT_KB_PATH / name

        path = path.expanduser().resolve()
        
        # 检查路径是否已被其他知识库使用
        for kb in self.config_manager.list_knowledge_bases():
            if Path(kb.path) == path:
                return False, f"Path '{path}' is already used by another knowledge base"
        
        # 创建目录结构
        try:
            config = ZKConfig(base_dir=path)
            config.ensure_dirs()
            
            # 添加到配置
            if not self.config_manager.add_knowledge_base(name, path, description):
                return False, "Failed to register knowledge base"
            
            # 设为默认（如果需要）
            if set_as_default:
                self.config_manager.set_default(name)
            
            return True, f"Created knowledge base '{name}' at {path}"
            
        except Exception as e:
            logger.error(f"Failed to create knowledge base: {e}")
            return False, str(e)
    
    def remove(
        self, 
        name: str, 
        delete_data: bool = False
    ) -> tuple[bool, str]:
        """
        移除知识库
        
        Args:
            name: 知识库名称
            delete_data: 是否删除实际数据
            
        Returns:
            (success, message)
        """
        if not self.config_manager.kb_exists(name):
            return False, f"Knowledge base '{name}' not found"
        
        # 获取路径
        path = self.config_manager.get_kb_path(name)
        
        # 从配置中移除
        if not self.config_manager.remove_knowledge_base(name):
            return False, "Failed to unregister knowledge base"
        
        # 删除数据（如果需要）
        if delete_data and path and path.exists():
            try:
                shutil.rmtree(path)
                return True, f"Removed knowledge base '{name}' and deleted all data"
            except Exception as e:
                return True, f"Removed knowledge base '{name}' but failed to delete data: {e}"
        
        return True, f"Removed knowledge base '{name}' (data preserved at {path})"
    
    def rename(self, old_name: str, new_name: str) -> tuple[bool, str]:
        """
        重命名知识库
        
        Args:
            old_name: 原名称
            new_name: 新名称
            
        Returns:
            (success, message)
        """
        if not self.config_manager.kb_exists(old_name):
            return False, f"Knowledge base '{old_name}' not found"
        
        if self.config_manager.kb_exists(new_name):
            return False, f"Knowledge base '{new_name}' already exists"
        
        if self.config_manager.rename_knowledge_base(old_name, new_name):
            return True, f"Renamed '{old_name}' to '{new_name}'"
        
        return False, "Failed to rename knowledge base"
    
    def switch(self, name: str) -> tuple[bool, str]:
        """
        切换默认知识库
        
        Args:
            name: 知识库名称
            
        Returns:
            (success, message)
        """
        if not self.config_manager.kb_exists(name):
            return False, f"Knowledge base '{name}' not found"
        
        # 更新最后使用时间
        self.config_manager.update_last_used(name)
        
        if self.config_manager.set_default(name):
            path = self.config_manager.get_kb_path(name)
            return True, f"Switched to '{name}' ({path})"
        
        return False, "Failed to switch knowledge base"
    
    def list_all(self) -> List[KBStats]:
        """
        列出所有知识库及其统计信息
        
        Returns:
            知识库统计信息列表
        """
        entries = self.config_manager.list_knowledge_bases()
        current = self.config_manager.get_default_kb_name()
        
        stats_list = []
        for entry in entries:
            stats = self._get_kb_stats(entry)
            stats.is_current = (entry.name == current)
            stats_list.append(stats)
        
        return stats_list
    
    def get_info(self, name: str) -> Optional[KBStats]:
        """
        获取知识库详细信息
        
        Args:
            name: 知识库名称
            
        Returns:
            知识库统计信息，不存在则返回 None
        """
        if not self.config_manager.kb_exists(name):
            return None
        
        entries = self.config_manager.list_knowledge_bases()
        for entry in entries:
            if entry.name == name:
                stats = self._get_kb_stats(entry)
                stats.is_current = (name == self.config_manager.get_default_kb_name())
                return stats
        
        return None
    
    def _get_kb_stats(self, entry: KnowledgeBaseEntry) -> KBStats:
        """获取知识库统计信息"""
        path = Path(entry.path)
        
        # 统计笔记数量
        total = 0
        by_type = {"fleeting": 0, "literature": 0, "permanent": 0}
        
        if path.exists():
            notes_dir = path / "notes"
            if notes_dir.exists():
                for note_type in ["fleeting", "literature", "permanent"]:
                    type_dir = notes_dir / note_type
                    if type_dir.exists():
                        count = len(list(type_dir.glob("*.md")))
                        by_type[note_type] = count
                        total += count
        
        return KBStats(
            name=entry.name,
            path=path,
            total_notes=total,
            by_type=by_type,
            created=entry.created,
            last_used=entry.last_used,
            description=entry.description,
            is_current=False,
        )
    
    def get_current_kb_info(self) -> Optional[KBStats]:
        """获取当前默认知识库信息"""
        current_name = self.config_manager.get_default_kb_name()
        return self.get_info(current_name)
    
    def ensure_default_exists(self) -> bool:
        """
        确保默认知识库存在，如果不存在则创建
        
        Returns:
            是否成功
        """
        default_name = self.config_manager.get_default_kb_name()
        
        if not self.config_manager.kb_exists(default_name):
            # 创建默认知识库
            path = self.config_manager.get_default_kb_path()
            success, _ = self.create(
                name=default_name,
                path=path,
                description="Default knowledge base",
                set_as_default=True
            )
            return success
        
        return True


# 全局知识库管理器实例
_kb_manager: Optional[KnowledgeBaseManager] = None


def get_kb_manager() -> KnowledgeBaseManager:
    """获取知识库管理器实例"""
    global _kb_manager
    if _kb_manager is None:
        _kb_manager = KnowledgeBaseManager()
    return _kb_manager
