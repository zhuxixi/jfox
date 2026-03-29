"""Unit tests for kb_manager module - 无需外部依赖"""
import pytest
from unittest.mock import Mock, patch, MagicMock
from pathlib import Path
from datetime import datetime

from zk.kb_manager import (
    KBStats,
    KnowledgeBaseManager,
    get_kb_manager,
)
from zk.global_config import KnowledgeBaseEntry, GlobalConfig


class TestKBStats:
    """测试 KBStats 数据类"""
    
    def test_create_with_all_fields(self):
        """测试创建完整的 KBStats"""
        stats = KBStats(
            name="test_kb",
            path=Path("/path/to/kb"),
            total_notes=42,
            by_type={"fleeting": 10, "literature": 12, "permanent": 20},
            created="2024-01-01T00:00:00",
            last_used="2024-01-02T00:00:00",
            description="Test knowledge base",
            is_current=True
        )
        
        assert stats.name == "test_kb"
        assert stats.path == Path("/path/to/kb")
        assert stats.total_notes == 42
        assert stats.by_type["fleeting"] == 10
        assert stats.is_current is True
    
    def test_create_with_defaults(self):
        """测试创建带有默认值的 KBStats"""
        stats = KBStats(
            name="test_kb",
            path=Path("/path/to/kb"),
            total_notes=0,
            by_type={"fleeting": 0, "literature": 0, "permanent": 0}
        )
        
        assert stats.created is None
        assert stats.last_used is None
        assert stats.description is None
        assert stats.is_current is False


class TestKnowledgeBaseManager:
    """测试 KnowledgeBaseManager 类"""
    
    @pytest.fixture
    def mock_config_manager(self):
        """提供模拟的配置管理器"""
        return Mock()
    
    @pytest.fixture
    def manager(self, mock_config_manager):
        """提供知识库管理器实例"""
        return KnowledgeBaseManager(config_manager=mock_config_manager)
    
    def test_init_uses_provided_config_manager(self, mock_config_manager):
        """测试使用提供的配置管理器初始化"""
        manager = KnowledgeBaseManager(config_manager=mock_config_manager)
        assert manager.config_manager is mock_config_manager
    
    @patch('zk.kb_manager.get_global_config_manager')
    def test_init_uses_default_config_manager(self, mock_get_global):
        """测试使用默认配置管理器初始化"""
        mock_config = Mock()
        mock_get_global.return_value = mock_config
        
        manager = KnowledgeBaseManager()
        
        assert manager.config_manager is mock_config
    
    def test_create_success(self, manager, mock_config_manager):
        """测试成功创建知识库"""
        mock_config_manager.kb_exists.return_value = False
        mock_config_manager.list_knowledge_bases.return_value = []
        mock_config_manager.add_knowledge_base.return_value = True
        mock_config_manager.set_default.return_value = True
        
        with patch('zk.kb_manager.ZKConfig') as mock_zk_config:
            mock_config_instance = Mock()
            mock_zk_config.return_value = mock_config_instance
            
            success, message = manager.create(
                name="new_kb",
                path=Path("/path/to/new_kb"),
                description="Test KB",
                set_as_default=True
            )
        
        assert success is True
        assert "Created" in message
        mock_config_instance.ensure_dirs.assert_called_once()
        mock_config_manager.add_knowledge_base.assert_called_once()
        mock_config_manager.set_default.assert_called_once_with("new_kb")
    
    def test_create_name_already_exists(self, manager, mock_config_manager):
        """测试创建已存在的知识库"""
        mock_config_manager.kb_exists.return_value = True
        
        success, message = manager.create(name="existing_kb")
        
        assert success is False
        assert "already exists" in message
    
    def test_create_path_already_used(self, manager, mock_config_manager, tmp_path):
        """测试使用已被占用的路径创建知识库"""
        mock_config_manager.kb_exists.return_value = False
        
        # 使用临时路径（跨平台兼容）
        existing_path = tmp_path / "existing_kb"
        existing_path.mkdir()
        
        # 模拟返回已存在的知识库
        existing_entry = KnowledgeBaseEntry(
            name="other_kb",
            path=str(existing_path),
            created="2024-01-01T00:00:00"
        )
        mock_config_manager.list_knowledge_bases.return_value = [existing_entry]
        
        success, message = manager.create(
            name="new_kb",
            path=existing_path
        )
        
        assert success is False
        assert "already used" in message.lower()
    
    def test_create_default_path(self, manager, mock_config_manager):
        """测试使用默认路径创建知识库"""
        mock_config_manager.kb_exists.return_value = False
        mock_config_manager.list_knowledge_bases.return_value = []
        mock_config_manager.add_knowledge_base.return_value = True
        
        with patch('zk.kb_manager.ZKConfig') as mock_zk_config:
            mock_config_instance = Mock()
            mock_zk_config.return_value = mock_config_instance
            
            manager.create(name="test_kb")
            
            # 验证使用了默认路径
            call_args = mock_config_manager.add_knowledge_base.call_args
            assert call_args is not None
    
    def test_create_handles_exception(self, manager, mock_config_manager):
        """测试创建知识库时处理异常"""
        mock_config_manager.kb_exists.return_value = False
        mock_config_manager.list_knowledge_bases.return_value = []
        
        with patch('zk.kb_manager.ZKConfig') as mock_zk_config:
            mock_zk_config.side_effect = Exception("Config error")
            
            success, message = manager.create(name="new_kb")
        
        assert success is False
        assert "Config error" in message
    
    def test_remove_success(self, manager, mock_config_manager):
        """测试成功移除知识库"""
        mock_config_manager.kb_exists.return_value = True
        mock_config_manager.get_kb_path.return_value = Path("/path/to/kb")
        mock_config_manager.remove_knowledge_base.return_value = True
        
        success, message = manager.remove(name="test_kb", delete_data=False)
        
        assert success is True
        assert "Removed" in message
        assert "data preserved" in message
    
    def test_remove_with_delete_data(self, manager, mock_config_manager, tmp_path):
        """测试移除并删除数据"""
        kb_path = tmp_path / "test_kb"
        kb_path.mkdir()
        (kb_path / "test_file.txt").write_text("test")
        
        mock_config_manager.kb_exists.return_value = True
        mock_config_manager.get_kb_path.return_value = kb_path
        mock_config_manager.remove_knowledge_base.return_value = True
        
        success, message = manager.remove(name="test_kb", delete_data=True)
        
        assert success is True
        assert "deleted all data" in message
        assert not kb_path.exists()
    
    def test_remove_nonexistent(self, manager, mock_config_manager):
        """测试移除不存在的知识库"""
        mock_config_manager.kb_exists.return_value = False
        
        success, message = manager.remove(name="nonexistent")
        
        assert success is False
        assert "not found" in message
    
    def test_remove_delete_data_fails(self, manager, mock_config_manager, tmp_path):
        """测试删除数据失败的情况"""
        kb_path = tmp_path / "test_kb"
        kb_path.mkdir()
        
        mock_config_manager.kb_exists.return_value = True
        mock_config_manager.get_kb_path.return_value = kb_path
        mock_config_manager.remove_knowledge_base.return_value = True
        
        # 模拟 shutil.rmtree 失败
        with patch('zk.kb_manager.shutil.rmtree', side_effect=PermissionError("Access denied")):
            success, message = manager.remove(name="test_kb", delete_data=True)
        
        assert success is True  # 移除配置仍然成功
        assert "failed to delete data" in message
    
    def test_rename_success(self, manager, mock_config_manager):
        """测试成功重命名知识库"""
        mock_config_manager.kb_exists.side_effect = lambda x: x == "old_name"
        mock_config_manager.rename_knowledge_base.return_value = True
        
        success, message = manager.rename(old_name="old_name", new_name="new_name")
        
        assert success is True
        assert "Renamed" in message
    
    def test_rename_old_not_found(self, manager, mock_config_manager):
        """测试重命名不存在的知识库"""
        mock_config_manager.kb_exists.return_value = False
        
        success, message = manager.rename(old_name="nonexistent", new_name="new_name")
        
        assert success is False
        assert "not found" in message
    
    def test_rename_new_already_exists(self, manager, mock_config_manager):
        """测试重命名为已存在的名称"""
        mock_config_manager.kb_exists.return_value = True
        
        success, message = manager.rename(old_name="old_name", new_name="existing")
        
        assert success is False
        assert "already exists" in message
    
    def test_switch_success(self, manager, mock_config_manager):
        """测试成功切换知识库"""
        mock_config_manager.kb_exists.return_value = True
        mock_config_manager.update_last_used.return_value = True
        mock_config_manager.set_default.return_value = True
        mock_config_manager.get_kb_path.return_value = Path("/path/to/kb")
        
        success, message = manager.switch(name="test_kb")
        
        assert success is True
        assert "Switched to" in message
        mock_config_manager.update_last_used.assert_called_once_with("test_kb")
    
    def test_switch_nonexistent(self, manager, mock_config_manager):
        """测试切换不存在的知识库"""
        mock_config_manager.kb_exists.return_value = False
        
        success, message = manager.switch(name="nonexistent")
        
        assert success is False
        assert "not found" in message
    
    def test_list_all_empty(self, manager, mock_config_manager):
        """测试列出空知识库列表"""
        mock_config_manager.list_knowledge_bases.return_value = []
        mock_config_manager.get_default_kb_name.return_value = "default"
        
        result = manager.list_all()
        
        assert result == []
    
    def test_list_all_with_entries(self, manager, mock_config_manager, tmp_path):
        """测试列出知识库列表"""
        entry = KnowledgeBaseEntry(
            name="test_kb",
            path=str(tmp_path),
            created="2024-01-01T00:00:00"
        )
        mock_config_manager.list_knowledge_bases.return_value = [entry]
        mock_config_manager.get_default_kb_name.return_value = "test_kb"
        
        result = manager.list_all()
        
        assert len(result) == 1
        assert result[0].name == "test_kb"
        assert result[0].is_current is True
    
    def test_get_info_existing(self, manager, mock_config_manager, tmp_path):
        """测试获取存在的知识库信息"""
        entry = KnowledgeBaseEntry(
            name="test_kb",
            path=str(tmp_path),
            created="2024-01-01T00:00:00"
        )
        mock_config_manager.kb_exists.return_value = True
        mock_config_manager.list_knowledge_bases.return_value = [entry]
        mock_config_manager.get_default_kb_name.return_value = "test_kb"
        
        result = manager.get_info(name="test_kb")
        
        assert result is not None
        assert result.name == "test_kb"
        assert result.is_current is True
    
    def test_get_info_nonexistent(self, manager, mock_config_manager):
        """测试获取不存在的知识库信息"""
        mock_config_manager.kb_exists.return_value = False
        
        result = manager.get_info(name="nonexistent")
        
        assert result is None
    
    def test_get_kb_stats_counts_notes(self, manager, mock_config_manager, tmp_path):
        """测试统计笔记数量"""
        # 创建测试目录结构
        notes_dir = tmp_path / "notes"
        fleeting_dir = notes_dir / "fleeting"
        permanent_dir = notes_dir / "permanent"
        fleeting_dir.mkdir(parents=True)
        permanent_dir.mkdir(parents=True)
        
        # 创建一些测试笔记文件
        (fleeting_dir / "note1.md").write_text("content")
        (fleeting_dir / "note2.md").write_text("content")
        (permanent_dir / "note3.md").write_text("content")
        
        entry = KnowledgeBaseEntry(
            name="test_kb",
            path=str(tmp_path),
            created="2024-01-01T00:00:00"
        )
        
        stats = manager._get_kb_stats(entry)
        
        assert stats.total_notes == 3
        assert stats.by_type["fleeting"] == 2
        assert stats.by_type["permanent"] == 1
        assert stats.by_type["literature"] == 0
    
    def test_get_kb_stats_nonexistent_path(self, manager):
        """测试统计不存在路径的知识库"""
        entry = KnowledgeBaseEntry(
            name="test_kb",
            path="/nonexistent/path",
            created="2024-01-01T00:00:00"
        )
        
        stats = manager._get_kb_stats(entry)
        
        assert stats.total_notes == 0
        assert all(count == 0 for count in stats.by_type.values())
    
    def test_get_current_kb_info(self, manager, mock_config_manager, tmp_path):
        """测试获取当前知识库信息"""
        entry = KnowledgeBaseEntry(
            name="current_kb",
            path=str(tmp_path),
            created="2024-01-01T00:00:00"
        )
        mock_config_manager.get_default_kb_name.return_value = "current_kb"
        mock_config_manager.kb_exists.return_value = True
        mock_config_manager.list_knowledge_bases.return_value = [entry]
        
        result = manager.get_current_kb_info()
        
        assert result is not None
        assert result.name == "current_kb"
    
    def test_ensure_default_exists_when_exists(self, manager, mock_config_manager):
        """测试默认知识库已存在时"""
        mock_config_manager.get_default_kb_name.return_value = "default"
        mock_config_manager.kb_exists.return_value = True
        
        result = manager.ensure_default_exists()
        
        assert result is True
        mock_config_manager.kb_exists.assert_called_once_with("default")
    
    def test_ensure_default_exists_when_not_exists(self, manager, mock_config_manager):
        """测试默认知识库不存在时创建"""
        mock_config_manager.get_default_kb_name.return_value = "default"
        mock_config_manager.kb_exists.return_value = False
        mock_config_manager.get_default_kb_path.return_value = Path("/path/to/default")
        
        with patch.object(manager, 'create', return_value=(True, "Created")) as mock_create:
            result = manager.ensure_default_exists()
        
        assert result is True
        mock_create.assert_called_once_with(
            name="default",
            path=Path("/path/to/default"),
            description="Default knowledge base",
            set_as_default=True
        )


class TestGetKbManager:
    """测试 get_kb_manager 函数"""
    
    def setup_method(self):
        """每个测试前清理全局实例"""
        import zk.kb_manager as kb_module
        kb_module._kb_manager = None
    
    def teardown_method(self):
        """每个测试后清理全局实例"""
        import zk.kb_manager as kb_module
        kb_module._kb_manager = None
    
    def test_returns_same_instance(self):
        """测试返回相同实例"""
        manager1 = get_kb_manager()
        manager2 = get_kb_manager()
        
        assert manager1 is manager2
    
    def test_creates_knowledge_base_manager(self):
        """测试创建 KnowledgeBaseManager 实例"""
        manager = get_kb_manager()
        
        assert isinstance(manager, KnowledgeBaseManager)
