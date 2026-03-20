"""
全局配置管理 - 多知识库支持

管理 ~/.zk_config.json，存储所有知识库的注册信息和默认设置
"""

import json
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any


logger = logging.getLogger(__name__)


DEFAULT_CONFIG_PATH = Path.home() / ".zk_config.json"
DEFAULT_KB_NAME = "default"
DEFAULT_KB_PATH = Path.home() / ".zettelkasten"


@dataclass
class KnowledgeBaseEntry:
    """知识库条目"""
    name: str
    path: str
    created: str
    description: Optional[str] = None
    last_used: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "KnowledgeBaseEntry":
        return cls(
            name=name,
            path=data.get("path", ""),
            created=data.get("created", datetime.now().isoformat()),
            description=data.get("description"),
            last_used=data.get("last_used"),
        )


@dataclass
class GlobalConfig:
    """全局配置"""
    default: str = DEFAULT_KB_NAME
    knowledge_bases: Dict[str, KnowledgeBaseEntry] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "default": self.default,
            "knowledge_bases": {
                name: kb.to_dict() for name, kb in self.knowledge_bases.items()
            }
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GlobalConfig":
        kbs = {}
        for name, kb_data in data.get("knowledge_bases", {}).items():
            kbs[name] = KnowledgeBaseEntry.from_dict(name, kb_data)
        
        return cls(
            default=data.get("default", DEFAULT_KB_NAME),
            knowledge_bases=kbs,
        )


class GlobalConfigManager:
    """
    全局配置管理器
    
    负责管理 ~/.zk_config.json 的读写操作
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self._config: Optional[GlobalConfig] = None
    
    def _load(self) -> GlobalConfig:
        """加载配置，如果不存在则创建默认配置"""
        if self._config is not None:
            return self._config
        
        if self.config_path.exists():
            try:
                with open(self.config_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                self._config = GlobalConfig.from_dict(data)
                logger.debug(f"Loaded global config from {self.config_path}")
            except Exception as e:
                logger.warning(f"Failed to load config: {e}, creating default")
                self._config = self._create_default_config()
        else:
            self._config = self._create_default_config()
        
        return self._config
    
    def _save(self) -> bool:
        """保存配置到文件"""
        try:
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, 'w', encoding='utf-8') as f:
                json.dump(self._config.to_dict(), f, ensure_ascii=False, indent=2)
            logger.debug(f"Saved global config to {self.config_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            return False
    
    def _create_default_config(self) -> GlobalConfig:
        """创建默认配置"""
        default_kb = KnowledgeBaseEntry(
            name=DEFAULT_KB_NAME,
            path=str(DEFAULT_KB_PATH),
            created=datetime.now().isoformat(),
            description="Default knowledge base",
        )
        
        config = GlobalConfig(
            default=DEFAULT_KB_NAME,
            knowledge_bases={DEFAULT_KB_NAME: default_kb}
        )
        
        # 如果默认知识库已存在，保留它
        if DEFAULT_KB_PATH.exists():
            self._config = config
            self._save()
        
        return config
    
    def get_config(self) -> GlobalConfig:
        """获取当前配置"""
        return self._load()
    
    def get_default_kb_name(self) -> str:
        """获取默认知识库名称"""
        return self._load().default
    
    def get_default_kb_path(self) -> Path:
        """获取默认知识库路径"""
        config = self._load()
        default_name = config.default
        
        if default_name in config.knowledge_bases:
            return Path(config.knowledge_bases[default_name].path)
        
        # 回退到默认路径
        return DEFAULT_KB_PATH
    
    def get_kb_path(self, name: str) -> Optional[Path]:
        """获取指定知识库的路径"""
        config = self._load()
        if name in config.knowledge_bases:
            return Path(config.knowledge_bases[name].path)
        return None
    
    def list_knowledge_bases(self) -> List[KnowledgeBaseEntry]:
        """列出所有知识库"""
        config = self._load()
        return list(config.knowledge_bases.values())
    
    def kb_exists(self, name: str) -> bool:
        """检查知识库是否存在"""
        config = self._load()
        return name in config.knowledge_bases
    
    def add_knowledge_base(
        self, 
        name: str, 
        path: Path, 
        description: Optional[str] = None
    ) -> bool:
        """添加新知识库"""
        config = self._load()
        
        if name in config.knowledge_bases:
            logger.warning(f"Knowledge base '{name}' already exists")
            return False
        
        kb = KnowledgeBaseEntry(
            name=name,
            path=str(path.expanduser().resolve()),
            created=datetime.now().isoformat(),
            description=description or f"Knowledge base: {name}",
        )
        
        config.knowledge_bases[name] = kb
        self._config = config
        return self._save()
    
    def remove_knowledge_base(self, name: str) -> bool:
        """从配置中移除知识库（不删除实际数据）"""
        config = self._load()
        
        if name not in config.knowledge_bases:
            logger.warning(f"Knowledge base '{name}' not found")
            return False
        
        # 不能删除最后一个知识库
        if len(config.knowledge_bases) <= 1:
            logger.error("Cannot remove the last knowledge base")
            return False
        
        del config.knowledge_bases[name]
        
        # 如果删除的是默认知识库，切换到第一个可用的
        if config.default == name:
            config.default = next(iter(config.knowledge_bases.keys()))
        
        self._config = config
        return self._save()
    
    def set_default(self, name: str) -> bool:
        """设置默认知识库"""
        config = self._load()
        
        if name not in config.knowledge_bases:
            logger.warning(f"Knowledge base '{name}' not found")
            return False
        
        config.default = name
        
        # 更新最后使用时间
        config.knowledge_bases[name].last_used = datetime.now().isoformat()
        
        self._config = config
        return self._save()
    
    def rename_knowledge_base(self, old_name: str, new_name: str) -> bool:
        """重命名知识库"""
        config = self._load()
        
        if old_name not in config.knowledge_bases:
            logger.warning(f"Knowledge base '{old_name}' not found")
            return False
        
        if new_name in config.knowledge_bases:
            logger.warning(f"Knowledge base '{new_name}' already exists")
            return False
        
        kb = config.knowledge_bases[old_name]
        kb.name = new_name
        config.knowledge_bases[new_name] = kb
        del config.knowledge_bases[old_name]
        
        # 如果重命名的是默认知识库，更新默认设置
        if config.default == old_name:
            config.default = new_name
        
        self._config = config
        return self._save()
    
    def update_last_used(self, name: str) -> bool:
        """更新知识库最后使用时间"""
        config = self._load()
        
        if name in config.knowledge_bases:
            config.knowledge_bases[name].last_used = datetime.now().isoformat()
            self._config = config
            return self._save()
        
        return False


# 全局配置管理器实例
_global_config_manager: Optional[GlobalConfigManager] = None


def get_global_config_manager() -> GlobalConfigManager:
    """获取全局配置管理器实例"""
    global _global_config_manager
    if _global_config_manager is None:
        _global_config_manager = GlobalConfigManager()
    return _global_config_manager
