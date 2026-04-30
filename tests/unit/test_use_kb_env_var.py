"""
测试类型: 单元测试
目标模块: jfox.config.use_kb
预估耗时: < 1秒
依赖要求: 无外部依赖，使用 mock
"""

import os

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]
from unittest.mock import Mock, patch

from jfox.config import config, use_kb


class TestUseKbEnvVar:
    """测试 use_kb() 对 JFOX_KB 环境变量的支持"""

    def test_env_var_used_when_kb_arg_none(self):
        """当 kb_name 为 None 且 JFOX_KB 设置时，应切换到该知识库"""
        with patch.dict(os.environ, {"JFOX_KB": "work"}):
            with patch("jfox.kb_manager.get_kb_manager") as mock_get_manager:
                mock_manager = Mock()
                mock_manager.config_manager.kb_exists.return_value = True
                mock_manager.config_manager.get_kb_path.return_value = (
                    config.base_dir.parent / "work"
                )
                mock_get_manager.return_value = mock_manager

                with use_kb(None) as _:
                    # 验证确实切换了知识库
                    mock_manager.config_manager.get_kb_path.assert_called_once_with("work")

    def test_cli_arg_overrides_env_var(self):
        """当同时传入 kb_name 和设置 JFOX_KB 时，应优先使用传入的 kb_name"""
        with patch.dict(os.environ, {"JFOX_KB": "work"}):
            with patch("jfox.kb_manager.get_kb_manager") as mock_get_manager:
                mock_manager = Mock()
                mock_manager.config_manager.kb_exists.return_value = True
                mock_manager.config_manager.get_kb_path.return_value = (
                    config.base_dir.parent / "personal"
                )
                mock_get_manager.return_value = mock_manager

                with use_kb("personal") as _:
                    # 验证使用的是传入的 "personal"，而不是环境变量的 "work"
                    mock_manager.config_manager.get_kb_path.assert_called_once_with("personal")

    def test_invalid_jfox_kb_raises_valueerror(self):
        """当 JFOX_KB 指向不存在的知识库时，应抛出 ValueError"""
        with patch.dict(os.environ, {"JFOX_KB": "nonexistent"}):
            with patch("jfox.kb_manager.get_kb_manager") as mock_get_manager:
                mock_manager = Mock()
                mock_manager.config_manager.kb_exists.return_value = False
                mock_get_manager.return_value = mock_manager

                with pytest.raises(ValueError, match="Knowledge base 'nonexistent' not found"):
                    with use_kb(None):
                        pass

    def test_no_env_var_falls_back_to_global_default(self):
        """当没有设置 JFOX_KB 且 kb_name 为 None 时，应直接使用当前默认知识库"""
        with patch.dict(os.environ, {}, clear=True):
            with patch("jfox.kb_manager.get_kb_manager") as mock_get_manager:
                # 不应调用 get_kb_manager，因为没有需要切换的知识库
                original_base_dir = config.base_dir

                with use_kb(None) as _:
                    # 验证没有尝试获取 kb_manager
                    mock_get_manager.assert_not_called()
                    # 验证配置没有被修改
                    assert config.base_dir == original_base_dir
