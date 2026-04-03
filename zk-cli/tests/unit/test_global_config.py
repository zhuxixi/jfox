"""
测试类型: 单元测试
目标模块: zk.global_config
预估耗时: < 1秒
依赖要求: 无外部依赖，使用 mock
"""
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]
import json
import os
from unittest.mock import Mock, patch, mock_open, MagicMock
from pathlib import Path
from datetime import datetime

from zk.global_config import (
    KnowledgeBaseEntry,
    GlobalConfig,
    GlobalConfigManager,
    get_global_config_manager,
    DEFAULT_CONFIG_PATH,
    DEFAULT_KB_NAME,
    DEFAULT_KB_PATH,
)


class TestKnowledgeBaseEntry:
    """测试 KnowledgeBaseEntry 数据类"""
    
    def test_to_dict(self):
        """测试转换为字典"""
        entry = KnowledgeBaseEntry(
            name="test_kb",
            path="/path/to/kb",
            created="2024-01-01T00:00:00",
            description="Test description",
            last_used="2024-01-02T00:00:00"
        )
        
        result = entry.to_dict()
        
        assert result["name"] == "test_kb"
        assert result["path"] == "/path/to/kb"
        assert result["created"] == "2024-01-01T00:00:00"
        assert result["description"] == "Test description"
        assert result["last_used"] == "2024-01-02T00:00:00"
    
    def test_from_dict(self):
        """测试从字典创建"""
        data = {
            "path": "/path/to/kb",
            "created": "2024-01-01T00:00:00",
            "description": "Test description",
            "last_used": "2024-01-02T00:00:00"
        }
        
        entry = KnowledgeBaseEntry.from_dict("test_kb", data)
        
        assert entry.name == "test_kb"
        assert entry.path == "/path/to/kb"
        assert entry.created == "2024-01-01T00:00:00"
        assert entry.description == "Test description"
        assert entry.last_used == "2024-01-02T00:00:00"
    
    def test_from_dict_with_defaults(self):
        """测试从字典创建时使用默认值"""
        data = {"path": "/path/to/kb"}
        
        entry = KnowledgeBaseEntry.from_dict("test_kb", data)
        
        assert entry.name == "test_kb"
        assert entry.path == "/path/to/kb"
        assert entry.created is not None  # 应该有默认时间
        assert entry.description is None
        assert entry.last_used is None


class TestGlobalConfig:
    """测试 GlobalConfig 数据类"""
    
    def test_default_values(self):
        """测试默认值"""
        config = GlobalConfig()
        
        assert config.default == DEFAULT_KB_NAME
        assert config.knowledge_bases == {}
    
    def test_to_dict_empty(self):
        """测试空配置转字典"""
        config = GlobalConfig()
        
        result = config.to_dict()
        
        assert result["default"] == DEFAULT_KB_NAME
        assert result["knowledge_bases"] == {}
    
    def test_to_dict_with_entries(self):
        """测试有条目时转字典"""
        entry = KnowledgeBaseEntry(
            name="test_kb",
            path="/path/to/kb",
            created="2024-01-01T00:00:00"
        )
        config = GlobalConfig(
            default="test_kb",
            knowledge_bases={"test_kb": entry}
        )
        
        result = config.to_dict()
        
        assert result["default"] == "test_kb"
        assert "test_kb" in result["knowledge_bases"]
        assert result["knowledge_bases"]["test_kb"]["path"] == "/path/to/kb"
    
    def test_from_dict_empty(self):
        """测试从空字典创建"""
        data = {}
        
        config = GlobalConfig.from_dict(data)
        
        assert config.default == DEFAULT_KB_NAME
        assert config.knowledge_bases == {}
    
    def test_from_dict_with_data(self):
        """测试从完整字典创建"""
        data = {
            "default": "my_kb",
            "knowledge_bases": {
                "my_kb": {
                    "path": "/path/to/my_kb",
                    "created": "2024-01-01T00:00:00",
                    "description": "My KB"
                }
            }
        }
        
        config = GlobalConfig.from_dict(data)
        
        assert config.default == "my_kb"
        assert "my_kb" in config.knowledge_bases
        assert config.knowledge_bases["my_kb"].path == "/path/to/my_kb"


class TestGlobalConfigManager:
    """测试 GlobalConfigManager 类"""
    
    @pytest.fixture
    def temp_config_path(self, tmp_path):
        """提供临时配置文件路径"""
        return tmp_path / "test_zk_config.json"
    
    @pytest.fixture
    def manager(self, temp_config_path):
        """提供配置管理器实例"""
        return GlobalConfigManager(config_path=temp_config_path)
    
    def test_init_with_default_path(self):
        """测试使用默认路径初始化"""
        manager = GlobalConfigManager()
        assert manager.config_path == DEFAULT_CONFIG_PATH
    
    def test_init_with_custom_path(self, temp_config_path):
        """测试使用自定义路径初始化"""
        manager = GlobalConfigManager(config_path=temp_config_path)
        assert manager.config_path == temp_config_path
    
    def test_load_creates_default_config_when_file_not_exists(self, manager, temp_config_path):
        """测试文件不存在时创建默认配置"""
        config = manager._load()
        
        assert config.default == DEFAULT_KB_NAME
        assert DEFAULT_KB_NAME in config.knowledge_bases
    
    def test_load_existing_config(self, manager, temp_config_path):
        """测试加载现有配置"""
        # 先创建一个配置文件
        data = {
            "default": "custom_kb",
            "knowledge_bases": {
                "custom_kb": {
                    "path": "/custom/path",
                    "created": "2024-01-01T00:00:00"
                }
            }
        }
        temp_config_path.write_text(json.dumps(data), encoding='utf-8')
        
        config = manager._load()
        
        assert config.default == "custom_kb"
        assert "custom_kb" in config.knowledge_bases
    
    def test_load_uses_cache(self, manager):
        """测试使用缓存的配置"""
        # 第一次加载
        config1 = manager._load()
        # 第二次加载应该返回相同对象
        config2 = manager._load()
        
        assert config1 is config2
    
    def test_load_handles_corrupted_file(self, manager, temp_config_path):
        """测试处理损坏的配置文件"""
        temp_config_path.write_text("invalid json", encoding='utf-8')
        
        config = manager._load()
        
        # 应该返回默认配置
        assert config.default == DEFAULT_KB_NAME
    
    def test_save_creates_directories(self, manager, temp_config_path):
        """测试保存时创建目录"""
        nested_path = temp_config_path.parent / "nested" / "config.json"
        manager.config_path = nested_path
        manager._config = GlobalConfig()
        
        result = manager._save()
        
        assert result is True
        assert nested_path.parent.exists()
    
    def test_save_writes_correct_data(self, manager, temp_config_path):
        """测试保存正确的数据"""
        manager._config = GlobalConfig(default="test_kb")
        
        manager._save()
        
        content = temp_config_path.read_text(encoding='utf-8')
        data = json.loads(content)
        assert data["default"] == "test_kb"
    
    def test_save_handles_errors(self, manager, temp_config_path):
        """测试保存错误处理"""
        # 模拟目录不可写
        with patch.object(Path, 'mkdir', side_effect=PermissionError("No permission")):
            manager._config = GlobalConfig()
            result = manager._save()
            assert result is False
    
    def test_get_default_kb_name(self, manager):
        """测试获取默认知识库名称"""
        manager._config = GlobalConfig(default="my_kb")
        
        result = manager.get_default_kb_name()
        
        assert result == "my_kb"
    
    def test_get_default_kb_path_with_existing_kb(self, manager):
        """测试获取现有知识库路径"""
        entry = KnowledgeBaseEntry(
            name="my_kb",
            path="/path/to/my_kb",
            created="2024-01-01T00:00:00"
        )
        manager._config = GlobalConfig(default="my_kb", knowledge_bases={"my_kb": entry})
        
        result = manager.get_default_kb_path()
        
        assert result == Path("/path/to/my_kb")
    
    def test_get_default_kb_path_fallback(self, manager):
        """测试获取默认路径回退"""
        manager._config = GlobalConfig(default="nonexistent")
        
        result = manager.get_default_kb_path()
        
        assert result == DEFAULT_KB_PATH
    
    def test_get_kb_path_existing(self, manager):
        """测试获取存在的知识库路径"""
        entry = KnowledgeBaseEntry(
            name="my_kb",
            path="/path/to/my_kb",
            created="2024-01-01T00:00:00"
        )
        manager._config = GlobalConfig(knowledge_bases={"my_kb": entry})
        
        result = manager.get_kb_path("my_kb")
        
        assert result == Path("/path/to/my_kb")
    
    def test_get_kb_path_nonexistent(self, manager):
        """测试获取不存在的知识库路径"""
        manager._config = GlobalConfig()
        
        result = manager.get_kb_path("nonexistent")
        
        assert result is None
    
    def test_list_knowledge_bases_empty(self, manager):
        """测试列出空知识库列表"""
        manager._config = GlobalConfig()
        
        result = manager.list_knowledge_bases()
        
        assert result == []
    
    def test_list_knowledge_bases_with_entries(self, manager):
        """测试列出有条目的知识库列表"""
        entry = KnowledgeBaseEntry(
            name="my_kb",
            path="/path/to/my_kb",
            created="2024-01-01T00:00:00"
        )
        manager._config = GlobalConfig(knowledge_bases={"my_kb": entry})
        
        result = manager.list_knowledge_bases()
        
        assert len(result) == 1
        assert result[0].name == "my_kb"
    
    def test_kb_exists_true(self, manager):
        """测试知识库存在检查"""
        entry = KnowledgeBaseEntry(
            name="my_kb",
            path="/path/to/my_kb",
            created="2024-01-01T00:00:00"
        )
        manager._config = GlobalConfig(knowledge_bases={"my_kb": entry})
        
        assert manager.kb_exists("my_kb") is True
    
    def test_kb_exists_false(self, manager):
        """测试知识库不存在检查"""
        manager._config = GlobalConfig()
        
        assert manager.kb_exists("nonexistent") is False
    
    def test_add_knowledge_base_success(self, manager):
        """测试成功添加知识库"""
        manager._config = GlobalConfig()
        
        with patch.object(manager, '_save', return_value=True):
            result = manager.add_knowledge_base("new_kb", Path("/path/to/new"), "Description")
        
        assert result is True
        assert "new_kb" in manager._config.knowledge_bases
        assert manager._config.knowledge_bases["new_kb"].description == "Description"
    
    def test_add_knowledge_base_duplicate(self, manager):
        """测试添加重复知识库"""
        entry = KnowledgeBaseEntry(
            name="existing",
            path="/path/to/existing",
            created="2024-01-01T00:00:00"
        )
        manager._config = GlobalConfig(knowledge_bases={"existing": entry})
        
        result = manager.add_knowledge_base("existing", Path("/other/path"))
        
        assert result is False
    
    def test_remove_knowledge_base_success(self, manager):
        """测试成功移除知识库"""
        entry1 = KnowledgeBaseEntry(name="kb1", path="/path/1", created="2024-01-01T00:00:00")
        entry2 = KnowledgeBaseEntry(name="kb2", path="/path/2", created="2024-01-01T00:00:00")
        manager._config = GlobalConfig(
            default="kb1",
            knowledge_bases={"kb1": entry1, "kb2": entry2}
        )
        
        with patch.object(manager, '_save', return_value=True):
            result = manager.remove_knowledge_base("kb2")
        
        assert result is True
        assert "kb2" not in manager._config.knowledge_bases
    
    def test_remove_knowledge_base_nonexistent(self, manager):
        """测试移除不存在的知识库"""
        manager._config = GlobalConfig()
        
        result = manager.remove_knowledge_base("nonexistent")
        
        assert result is False
    
    def test_remove_last_knowledge_base_fails(self, manager):
        """测试不能移除最后一个知识库"""
        entry = KnowledgeBaseEntry(name="only", path="/path", created="2024-01-01T00:00:00")
        manager._config = GlobalConfig(knowledge_bases={"only": entry})
        
        result = manager.remove_knowledge_base("only")
        
        assert result is False
    
    def test_remove_default_kb_switches_default(self, manager):
        """测试移除默认知识库时切换默认"""
        entry1 = KnowledgeBaseEntry(name="kb1", path="/path/1", created="2024-01-01T00:00:00")
        entry2 = KnowledgeBaseEntry(name="kb2", path="/path/2", created="2024-01-01T00:00:00")
        manager._config = GlobalConfig(
            default="kb1",
            knowledge_bases={"kb1": entry1, "kb2": entry2}
        )
        
        with patch.object(manager, '_save', return_value=True):
            manager.remove_knowledge_base("kb1")
        
        assert manager._config.default == "kb2"
    
    def test_set_default_success(self, manager):
        """测试成功设置默认知识库"""
        entry = KnowledgeBaseEntry(name="my_kb", path="/path", created="2024-01-01T00:00:00")
        manager._config = GlobalConfig(knowledge_bases={"my_kb": entry})
        
        with patch.object(manager, '_save', return_value=True):
            result = manager.set_default("my_kb")
        
        assert result is True
        assert manager._config.default == "my_kb"
    
    def test_set_default_nonexistent(self, manager):
        """测试设置不存在的知识库为默认"""
        manager._config = GlobalConfig()
        
        result = manager.set_default("nonexistent")
        
        assert result is False
    
    def test_set_default_updates_last_used(self, manager):
        """测试设置默认时更新最后使用时间"""
        entry = KnowledgeBaseEntry(name="my_kb", path="/path", created="2024-01-01T00:00:00")
        manager._config = GlobalConfig(knowledge_bases={"my_kb": entry})
        
        with patch.object(manager, '_save', return_value=True):
            manager.set_default("my_kb")
        
        assert entry.last_used is not None
    
    def test_rename_knowledge_base_success(self, manager):
        """测试成功重命名知识库"""
        entry = KnowledgeBaseEntry(name="old_name", path="/path", created="2024-01-01T00:00:00")
        manager._config = GlobalConfig(knowledge_bases={"old_name": entry})
        
        with patch.object(manager, '_save', return_value=True):
            result = manager.rename_knowledge_base("old_name", "new_name")
        
        assert result is True
        assert "old_name" not in manager._config.knowledge_bases
        assert "new_name" in manager._config.knowledge_bases
        assert manager._config.knowledge_bases["new_name"].name == "new_name"
    
    def test_rename_knowledge_base_nonexistent(self, manager):
        """测试重命名不存在的知识库"""
        manager._config = GlobalConfig()
        
        result = manager.rename_knowledge_base("nonexistent", "new_name")
        
        assert result is False
    
    def test_rename_knowledge_base_duplicate_name(self, manager):
        """测试重命名为已存在的名称"""
        entry1 = KnowledgeBaseEntry(name="existing", path="/path/1", created="2024-01-01T00:00:00")
        entry2 = KnowledgeBaseEntry(name="other", path="/path/2", created="2024-01-01T00:00:00")
        manager._config = GlobalConfig(knowledge_bases={"existing": entry1, "other": entry2})
        
        result = manager.rename_knowledge_base("other", "existing")
        
        assert result is False
    
    def test_rename_default_kb_updates_default(self, manager):
        """测试重命名默认知识库时更新默认设置"""
        entry = KnowledgeBaseEntry(name="old_name", path="/path", created="2024-01-01T00:00:00")
        manager._config = GlobalConfig(default="old_name", knowledge_bases={"old_name": entry})
        
        with patch.object(manager, '_save', return_value=True):
            manager.rename_knowledge_base("old_name", "new_name")
        
        assert manager._config.default == "new_name"
    
    def test_update_last_used_success(self, manager):
        """测试成功更新最后使用时间"""
        entry = KnowledgeBaseEntry(name="my_kb", path="/path", created="2024-01-01T00:00:00")
        manager._config = GlobalConfig(knowledge_bases={"my_kb": entry})
        
        with patch.object(manager, '_save', return_value=True):
            result = manager.update_last_used("my_kb")
        
        assert result is True
        assert entry.last_used is not None
    
    def test_update_last_used_nonexistent(self, manager):
        """测试更新不存在的知识库的最后使用时间"""
        manager._config = GlobalConfig()
        
        result = manager.update_last_used("nonexistent")
        
        assert result is False


class TestGetGlobalConfigManager:
    """测试 get_global_config_manager 函数"""
    
    def setup_method(self):
        """每个测试前清理全局实例"""
        import zk.global_config as gc_module
        gc_module._global_config_manager = None
    
    def teardown_method(self):
        """每个测试后清理全局实例"""
        import zk.global_config as gc_module
        gc_module._global_config_manager = None
    
    def test_returns_same_instance(self):
        """测试返回相同实例"""
        manager1 = get_global_config_manager()
        manager2 = get_global_config_manager()
        
        assert manager1 is manager2
    
    def test_creates_new_instance(self):
        """测试创建新实例"""
        manager = get_global_config_manager()
        
        assert isinstance(manager, GlobalConfigManager)
