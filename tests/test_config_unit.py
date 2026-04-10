"""Unit tests for config module"""
import pytest
from unittest.mock import Mock, patch, mock_open
from pathlib import Path
import yaml

from jfox.config import (
    get_default_kb_path,
    ZKConfig,
    get_config,
    use_kb,
)


class TestGetDefaultKBPath:
    """测试 get_default_kb_path 函数"""
    
    def test_uses_global_config(self):
        """测试使用全局配置获取路径"""
        with patch('jfox.global_config.get_global_config_manager') as mock_get:
            mock_manager = Mock()
            mock_manager.get_default_kb_path.return_value = Path("/test/path")
            mock_get.return_value = mock_manager
            
            result = get_default_kb_path()
            
            assert result == Path("/test/path")
    
    def test_falls_back_to_home(self):
        """测试全局配置失败时回退到 home 目录"""
        with patch('jfox.global_config.get_global_config_manager') as mock_get:
            mock_get.side_effect = Exception("Config error")
            
            result = get_default_kb_path()
            
            assert result == Path.home() / ".zettelkasten" / "default"


class TestZKConfig:
    """测试 ZKConfig 类"""
    
    def test_default_values(self):
        """测试默认值"""
        with patch('jfox.config.get_default_kb_path', return_value=Path("/default")):
            config = ZKConfig()
            
            assert config.embedding_model == "sentence-transformers/all-MiniLM-L6-v2"
            assert config.embedding_dimension == 384
            assert config.device == "auto"
            assert config.batch_size == 32
            assert config.default_semantic_top == 5
            assert config.default_graph_hops == 2
            assert config.similarity_threshold == 0.7
            assert config.auto_sync is True
            assert config.sync_interval == 30
    
    def test_post_init_sets_paths(self):
        """测试 __post_init__ 设置路径"""
        config = ZKConfig(base_dir=Path("/test"))
        
        assert config.notes_dir == Path("/test/notes")
        assert config.zk_dir == Path("/test/.zk")
        assert config.chroma_dir == Path("/test/.zk/chroma_db")
    
    def test_ensure_dirs_creates_directories(self, tmp_path):
        """测试 ensure_dirs 创建目录"""
        config = ZKConfig(base_dir=tmp_path)
        config.ensure_dirs()
        
        assert (tmp_path / "notes" / "fleeting").exists()
        assert (tmp_path / "notes" / "literature").exists()
        assert (tmp_path / "notes" / "permanent").exists()
        assert (tmp_path / ".zk").exists()
        assert (tmp_path / ".zk" / "chroma_db").exists()
        assert (tmp_path / ".zk" / "cache").exists()
    
    def test_save_writes_yaml(self, tmp_path):
        """测试 save 方法写入 YAML 文件"""
        config = ZKConfig(base_dir=tmp_path)
        config.zk_dir = tmp_path / ".zk"
        config.zk_dir.mkdir(parents=True, exist_ok=True)
        
        config.save()
        
        config_file = config.zk_dir / "config.yaml"
        assert config_file.exists()
        
        # 验证内容
        with open(config_file, 'r', encoding='utf-8') as f:
            data = yaml.safe_load(f)
        
        assert data["embedding_model"] == "sentence-transformers/all-MiniLM-L6-v2"
        assert data["batch_size"] == 32
    
    def test_save_with_custom_path(self, tmp_path):
        """测试使用自定义路径保存"""
        config = ZKConfig(base_dir=tmp_path)
        custom_path = tmp_path / "custom_config.yaml"
        
        config.save(path=custom_path)
        
        assert custom_path.exists()
    
    def test_load_from_default_path(self, tmp_path):
        """测试从默认路径加载"""
        # 先创建一个配置文件
        zk_dir = tmp_path / ".zk"
        zk_dir.mkdir(parents=True, exist_ok=True)
        config_file = zk_dir / "config.yaml"
        
        config_data = {
            "base_dir": str(tmp_path),
            "embedding_model": "custom-model",
            "batch_size": 64,
        }
        with open(config_file, 'w', encoding='utf-8') as f:
            yaml.dump(config_data, f)
        
        with patch('jfox.config.get_default_kb_path', return_value=tmp_path):
            config = ZKConfig.load()
        
        assert config.embedding_model == "custom-model"
        assert config.batch_size == 64
    
    def test_load_with_custom_path(self, tmp_path):
        """测试从自定义路径加载"""
        config_file = tmp_path / "config.yaml"
        
        config_data = {
            "base_dir": str(tmp_path),
            "device": "gpu",
        }
        with open(config_file, 'w', encoding='utf-8') as f:
            yaml.dump(config_data, f)
        
        with patch('jfox.config.get_default_kb_path', return_value=tmp_path):
            config = ZKConfig.load(path=config_file)
        
        assert config.device == "gpu"
    
    def test_load_returns_default_if_file_not_exists(self, tmp_path):
        """测试文件不存在时返回默认配置"""
        with patch('jfox.config.get_default_kb_path', return_value=tmp_path):
            config = ZKConfig.load()
        
        assert config.embedding_model == "sentence-transformers/all-MiniLM-L6-v2"
        assert config.base_dir == tmp_path
    
    def test_for_kb_classmethod(self):
        """测试 for_kb 类方法"""
        config = ZKConfig.for_kb(Path("/custom/kb"))
        
        assert config.base_dir == Path("/custom/kb")
        assert config.notes_dir == Path("/custom/kb/notes")


class TestGetConfig:
    """测试 get_config 函数"""
    
    def test_returns_zkconfig_instance(self):
        """测试返回 ZKConfig 实例"""
        with patch('jfox.config.ZKConfig.load') as mock_load:
            mock_config = Mock(spec=ZKConfig)
            mock_load.return_value = mock_config
            
            result = get_config()
            
            assert result is mock_config


class TestUseKB:
    """测试 use_kb 上下文管理器"""
    
    def test_no_kb_name_yields_immediately(self):
        """测试无知识库名称时直接 yield"""
        with use_kb(None) as result:
            assert result is None
    
    def test_use_kb_switches_config(self):
        """测试 use_kb 切换配置"""
        from jfox.config import config
        
        original_dir = config.base_dir
        
        with patch('jfox.kb_manager.get_kb_manager') as mock_get_manager:
            mock_manager = Mock()
            mock_manager.config_manager.kb_exists.return_value = True
            mock_manager.config_manager.get_kb_path.return_value = Path("/switched/kb")
            mock_get_manager.return_value = mock_manager
            
            with use_kb("test_kb"):
                # 验证配置已切换
                assert config.base_dir == Path("/switched/kb")
                assert config.notes_dir == Path("/switched/kb/notes")
            
            # 验证配置已恢复
            assert config.base_dir == original_dir
    
    def test_use_kb_raises_if_kb_not_found(self):
        """测试知识库不存在时抛出异常"""
        with patch('jfox.kb_manager.get_kb_manager') as mock_get_manager:
            mock_manager = Mock()
            mock_manager.config_manager.kb_exists.return_value = False
            mock_get_manager.return_value = mock_manager
            
            with pytest.raises(ValueError) as exc_info:
                with use_kb("nonexistent"):
                    pass
            
            assert "not found" in str(exc_info.value)
    
    def test_use_kb_resets_search_indices(self):
        """测试 use_kb 重置搜索索引"""
        from jfox.config import config
        
        with patch('jfox.kb_manager.get_kb_manager') as mock_get_manager:
            mock_manager = Mock()
            mock_manager.config_manager.kb_exists.return_value = True
            mock_manager.config_manager.get_kb_path.return_value = Path("/test/kb")
            mock_get_manager.return_value = mock_manager
            
            with patch('jfox.bm25_index.reset_bm25_index') as mock_reset_bm25:
                with patch('jfox.search_engine.reset_search_engine') as mock_reset_search:
                    with use_kb("test_kb"):
                        pass
                    
                    mock_reset_bm25.assert_called_once()
                    mock_reset_search.assert_called_once()
    
    def test_use_kb_handles_reset_errors(self):
        """测试 use_kb 处理重置索引错误"""
        from jfox.config import config
        
        with patch('jfox.kb_manager.get_kb_manager') as mock_get_manager:
            mock_manager = Mock()
            mock_manager.config_manager.kb_exists.return_value = True
            mock_manager.config_manager.get_kb_path.return_value = Path("/test/kb")
            mock_get_manager.return_value = mock_manager
            
            with patch('jfox.bm25_index.reset_bm25_index', side_effect=Exception("Reset error")):
                # 应该不抛出异常
                with use_kb("test_kb"):
                    pass
