"""
测试类型: 单元测试
目标模块: jfox.global_config
预估耗时: < 1秒
依赖要求: 无外部依赖，使用 mock
"""

import os
import subprocess
import sys
from itertools import cycle

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]
import json
import logging
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from jfox import global_config as gc
from jfox.global_config import (
    DEFAULT_CONFIG_PATH,
    DEFAULT_KB_NAME,
    DEFAULT_KB_PATH,
    AutoSummaryConfig,
    BackupConfig,
    FragmentCaptureConfig,
    GlobalConfig,
    GlobalConfigManager,
    KnowledgeBaseEntry,
    PromptCaptureConfig,
    PromptJudgeConfig,
    get_global_config_manager,
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
            last_used="2024-01-02T00:00:00",
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
            "last_used": "2024-01-02T00:00:00",
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
            name="test_kb", path="/path/to/kb", created="2024-01-01T00:00:00"
        )
        config = GlobalConfig(default="test_kb", knowledge_bases={"test_kb": entry})

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
                    "description": "My KB",
                }
            },
        }

        config = GlobalConfig.from_dict(data)

        assert config.default == "my_kb"
        assert "my_kb" in config.knowledge_bases
        assert config.knowledge_bases["my_kb"].path == "/path/to/my_kb"


def _probe_default_config_path(env):
    """Return DEFAULT_CONFIG_PATH from a fresh Python interpreter."""
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from jfox.global_config import DEFAULT_CONFIG_PATH; " "print(DEFAULT_CONFIG_PATH)",
        ],
        cwd=Path(__file__).resolve().parents[2],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert result.returncode == 0, result.stderr
    return Path(result.stdout.strip())


class TestGlobalConfigManager:
    """测试 GlobalConfigManager 类"""

    def test_pytest_bootstrap_uses_isolated_config_path(self):
        """pytest bootstrap must point the default config path into its temp root."""
        configured_path = os.environ.get("ZK_CONFIG_PATH")

        assert configured_path
        assert DEFAULT_CONFIG_PATH == Path(configured_path)
        assert DEFAULT_CONFIG_PATH.name == "zk_config.json"
        assert DEFAULT_CONFIG_PATH.parent.name.startswith("zk_test_root_")

    def test_default_config_path_uses_environment_override_in_child_process(self, tmp_path):
        """A CLI-like child process must resolve ZK_CONFIG_PATH instead of HOME."""
        home = tmp_path / "home"
        custom_config = tmp_path / "config" / "isolated.json"
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "ZK_CONFIG_PATH": str(custom_config),
            }
        )

        assert _probe_default_config_path(env) == custom_config

    def test_default_config_path_falls_back_to_home_when_override_is_blank(self, tmp_path):
        """A blank override must preserve the existing HOME-based default path."""
        home = tmp_path / "home"
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "ZK_CONFIG_PATH": "   ",
            }
        )

        assert _probe_default_config_path(env) == home / ".zk_config.json"

    def test_default_config_path_falls_back_to_home_when_override_is_unset(self, tmp_path):
        """An unset override must preserve the existing HOME-based default path."""
        home = tmp_path / "home"
        env = os.environ.copy()
        env.pop("ZK_CONFIG_PATH", None)
        env.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
            }
        )

        assert _probe_default_config_path(env) == home / ".zk_config.json"

    def test_cli_child_writes_only_to_environment_config_path(self, tmp_path):
        """CLI KB registration must not create a config file under the child HOME."""
        home = tmp_path / "home"
        kb_root = tmp_path / "kb-root"
        custom_config = tmp_path / "config" / "isolated.json"
        kb_path = kb_root / "isolated"
        kb_root.mkdir(parents=True)
        env = os.environ.copy()
        env.update(
            {
                "HOME": str(home),
                "USERPROFILE": str(home),
                "ZK_KB_ROOT": str(kb_root),
                "ZK_CONFIG_PATH": str(custom_config),
                "PYTHONUTF8": "1",
            }
        )

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "jfox",
                "init",
                "--name",
                "isolated",
                "--path",
                str(kb_path),
                "--no-default",
                "--json",
            ],
            cwd=Path(__file__).resolve().parents[2],
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            check=False,
        )

        assert result.returncode == 0, result.stderr
        assert custom_config.exists()
        assert not (home / ".zk_config.json").exists()
        assert '"isolated"' in custom_config.read_text(encoding="utf-8")

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
                "custom_kb": {"path": "/custom/path", "created": "2024-01-01T00:00:00"}
            },
        }
        temp_config_path.write_text(json.dumps(data), encoding="utf-8")

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
        temp_config_path.write_text("invalid json", encoding="utf-8")

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

        content = temp_config_path.read_text(encoding="utf-8")
        data = json.loads(content)
        assert data["default"] == "test_kb"

    def test_save_handles_errors(self, manager, temp_config_path):
        """测试保存错误处理"""
        # 模拟目录不可写
        with patch.object(Path, "mkdir", side_effect=PermissionError("No permission")):
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
            name="my_kb", path="/path/to/my_kb", created="2024-01-01T00:00:00"
        )
        manager._config = GlobalConfig(default="my_kb", knowledge_bases={"my_kb": entry})

        result = manager.get_default_kb_path()

        assert result == Path("/path/to/my_kb")

    def test_get_default_kb_path_fallback(self, manager):
        """测试获取默认路径回退"""
        manager._config = GlobalConfig(default="nonexistent")

        result = manager.get_default_kb_path()

        assert result == DEFAULT_KB_PATH / "default"

    def test_get_kb_path_existing(self, manager):
        """测试获取存在的知识库路径"""
        entry = KnowledgeBaseEntry(
            name="my_kb", path="/path/to/my_kb", created="2024-01-01T00:00:00"
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
            name="my_kb", path="/path/to/my_kb", created="2024-01-01T00:00:00"
        )
        manager._config = GlobalConfig(knowledge_bases={"my_kb": entry})

        result = manager.list_knowledge_bases()

        assert len(result) == 1
        assert result[0].name == "my_kb"

    def test_kb_exists_true(self, manager):
        """测试知识库存在检查"""
        entry = KnowledgeBaseEntry(
            name="my_kb", path="/path/to/my_kb", created="2024-01-01T00:00:00"
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

        with patch.object(manager, "_save", return_value=True):
            result = manager.add_knowledge_base("new_kb", Path("/path/to/new"), "Description")

        assert result is True
        assert "new_kb" in manager._config.knowledge_bases
        assert manager._config.knowledge_bases["new_kb"].description == "Description"

    def test_add_knowledge_base_duplicate(self, manager):
        """测试添加重复知识库"""
        entry = KnowledgeBaseEntry(
            name="existing", path="/path/to/existing", created="2024-01-01T00:00:00"
        )
        manager._config = GlobalConfig(knowledge_bases={"existing": entry})

        result = manager.add_knowledge_base("existing", Path("/other/path"))

        assert result is False

    def test_remove_knowledge_base_success(self, manager):
        """测试成功移除知识库"""
        entry1 = KnowledgeBaseEntry(name="kb1", path="/path/1", created="2024-01-01T00:00:00")
        entry2 = KnowledgeBaseEntry(name="kb2", path="/path/2", created="2024-01-01T00:00:00")
        manager._config = GlobalConfig(
            default="kb1", knowledge_bases={"kb1": entry1, "kb2": entry2}
        )

        with patch.object(manager, "_save", return_value=True):
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
            default="kb1", knowledge_bases={"kb1": entry1, "kb2": entry2}
        )

        with patch.object(manager, "_save", return_value=True):
            manager.remove_knowledge_base("kb1")

        assert manager._config.default == "kb2"

    def test_set_default_success(self, manager):
        """测试成功设置默认知识库"""
        entry = KnowledgeBaseEntry(name="my_kb", path="/path", created="2024-01-01T00:00:00")
        manager._config = GlobalConfig(knowledge_bases={"my_kb": entry})

        with patch.object(manager, "_save", return_value=True):
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

        with patch.object(manager, "_save", return_value=True):
            manager.set_default("my_kb")

        assert entry.last_used is not None

    def test_rename_knowledge_base_success(self, manager):
        """测试成功重命名知识库"""
        entry = KnowledgeBaseEntry(name="old_name", path="/path", created="2024-01-01T00:00:00")
        manager._config = GlobalConfig(knowledge_bases={"old_name": entry})

        with patch.object(manager, "_save", return_value=True):
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

        with patch.object(manager, "_save", return_value=True):
            manager.rename_knowledge_base("old_name", "new_name")

        assert manager._config.default == "new_name"

    def test_update_last_used_success(self, manager):
        """测试成功更新最后使用时间"""
        entry = KnowledgeBaseEntry(name="my_kb", path="/path", created="2024-01-01T00:00:00")
        manager._config = GlobalConfig(knowledge_bases={"my_kb": entry})

        with patch.object(manager, "_save", return_value=True):
            result = manager.update_last_used("my_kb")

        assert result is True
        assert entry.last_used is not None

    def test_update_last_used_nonexistent(self, manager):
        """测试更新不存在的知识库的最后使用时间"""
        manager._config = GlobalConfig()

        result = manager.update_last_used("nonexistent")

        assert result is False

    def test_update_last_used_throttle_skips_recent(self, manager):
        """5分钟内不重复写入"""
        recent_time = datetime.now().isoformat()
        entry = KnowledgeBaseEntry(
            name="my_kb", path="/path", created="2024-01-01T00:00:00", last_used=recent_time
        )
        manager._config = GlobalConfig(knowledge_bases={"my_kb": entry})

        with patch.object(manager, "_save", return_value=True) as mock_save:
            result = manager.update_last_used("my_kb")

        assert result is True
        mock_save.assert_not_called()  # 跳过写入

    def test_update_last_used_throttle_allows_stale(self, manager):
        """超过5分钟则正常写入"""
        stale_time = "2020-01-01T00:00:00"
        entry = KnowledgeBaseEntry(
            name="my_kb", path="/path", created="2024-01-01T00:00:00", last_used=stale_time
        )
        manager._config = GlobalConfig(knowledge_bases={"my_kb": entry})

        with patch.object(manager, "_save", return_value=True):
            result = manager.update_last_used("my_kb")

        assert result is True
        assert entry.last_used != stale_time

    def test_update_last_used_no_throttle_when_null(self, manager):
        """last_used 为 None 时直接写入"""
        entry = KnowledgeBaseEntry(
            name="my_kb", path="/path", created="2024-01-01T00:00:00", last_used=None
        )
        manager._config = GlobalConfig(knowledge_bases={"my_kb": entry})

        with patch.object(manager, "_save", return_value=True):
            result = manager.update_last_used("my_kb")

        assert result is True
        assert entry.last_used is not None


class TestMigrateDefaultKbPath:
    """测试 _migrate_default_kb_path 迁移逻辑"""

    @pytest.fixture
    def temp_config_path(self, tmp_path):
        return tmp_path / "test_zk_config.json"

    @pytest.fixture
    def old_kb_root(self, tmp_path):
        """模拟 ~/.zettelkasten/ 旧版目录"""
        root = tmp_path / ".zettelkasten"
        root.mkdir()
        return root

    def _make_manager_with_old_path(self, temp_config_path, old_kb_root):
        """创建一个配置管理器，其 default KB 指向旧版路径"""
        manager = GlobalConfigManager(config_path=temp_config_path)
        kb = KnowledgeBaseEntry(
            name=DEFAULT_KB_NAME,
            path=str(old_kb_root),
            created="2024-01-01T00:00:00",
        )
        manager._config = GlobalConfig(
            default=DEFAULT_KB_NAME,
            knowledge_bases={DEFAULT_KB_NAME: kb},
        )
        return manager

    def test_migrate_success_moves_subdirs(self, temp_config_path, old_kb_root):
        """测试成功迁移：notes/ 和 .zk/ 都被移到新路径"""
        (old_kb_root / "notes").mkdir()
        (old_kb_root / "notes" / "test.md").write_text("# test", encoding="utf-8")
        (old_kb_root / ".zk").mkdir()
        (old_kb_root / ".zk" / "index.json").write_text("{}", encoding="utf-8")

        manager = self._make_manager_with_old_path(temp_config_path, old_kb_root)

        with patch("jfox.global_config.DEFAULT_KB_PATH", old_kb_root):
            manager._migrate_default_kb_path()

        new_path = old_kb_root / "default"
        assert (new_path / "notes" / "test.md").exists()
        assert (new_path / ".zk" / "index.json").exists()
        assert manager._config.knowledge_bases[DEFAULT_KB_NAME].path == str(new_path)

    def test_migrate_no_old_path_skips(self, temp_config_path, tmp_path):
        """测试旧路径不存在时跳过迁移，但仍然更新 config"""
        old_kb_root = tmp_path / ".zettelkasten_nonexistent"
        manager = self._make_manager_with_old_path(temp_config_path, old_kb_root)

        with patch("jfox.global_config.DEFAULT_KB_PATH", old_kb_root):
            manager._migrate_default_kb_path()

        new_path = old_kb_root / "default"
        assert not new_path.exists()
        assert manager._config.knowledge_bases[DEFAULT_KB_NAME].path == str(new_path)

    def test_migrate_new_path_already_exists_skips(self, temp_config_path, old_kb_root):
        """测试新路径已存在时跳过文件迁移，但更新 config"""
        new_path = old_kb_root / "default"
        new_path.mkdir(parents=True)

        manager = self._make_manager_with_old_path(temp_config_path, old_kb_root)

        with patch("jfox.global_config.DEFAULT_KB_PATH", old_kb_root):
            manager._migrate_default_kb_path()

        assert manager._config.knowledge_bases[DEFAULT_KB_NAME].path == str(new_path)

    def test_migrate_partial_failure_rolls_back(self, temp_config_path, old_kb_root):
        """测试迁移中途失败时回滚已移动的文件"""
        (old_kb_root / "notes").mkdir()
        (old_kb_root / "notes" / "test.md").write_text("# test", encoding="utf-8")
        (old_kb_root / ".zk").mkdir()

        manager = self._make_manager_with_old_path(temp_config_path, old_kb_root)
        original_path = manager._config.knowledge_bases[DEFAULT_KB_NAME].path

        # 让 shutil.move 在第二次调用时失败（.zk 移动时）
        import shutil as _shutil

        original_move = _shutil.move
        call_count = {"n": 0}

        def failing_move(src, dst):
            call_count["n"] += 1
            if call_count["n"] == 2:
                raise OSError("模拟移动失败")
            return original_move(src, dst)

        with (
            patch("jfox.global_config.DEFAULT_KB_PATH", old_kb_root),
            patch("shutil.move", side_effect=failing_move),
        ):
            manager._migrate_default_kb_path()

        new_path = old_kb_root / "default"
        # 回滚：notes/ 应被移回旧路径
        assert (old_kb_root / "notes" / "test.md").exists()
        # new_path 下不应有残留的 notes/
        assert not (new_path / "notes").exists()
        # new_path 目录应被清理
        assert not new_path.exists()
        # config 不应被更新
        assert manager._config.knowledge_bases[DEFAULT_KB_NAME].path == original_path

    def test_migrate_no_default_kb_is_noop(self, temp_config_path):
        """测试配置中没有 default KB 时不做任何操作"""
        manager = GlobalConfigManager(config_path=temp_config_path)
        manager._config = GlobalConfig()

        manager._migrate_default_kb_path()

        assert len(manager._config.knowledge_bases) == 0

    def test_migrate_none_config_is_noop(self, temp_config_path):
        """测试 _config 为 None 时不做任何操作"""
        manager = GlobalConfigManager(config_path=temp_config_path)
        manager._config = None

        manager._migrate_default_kb_path()

        assert manager._config is None

    def test_migrate_already_new_path_is_noop(self, temp_config_path, tmp_path):
        """测试 config 已经指向新路径时不做任何操作"""
        new_path = tmp_path / ".zettelkasten" / "default"
        manager = GlobalConfigManager(config_path=temp_config_path)
        kb = KnowledgeBaseEntry(
            name=DEFAULT_KB_NAME,
            path=str(new_path),
            created="2024-01-01T00:00:00",
        )
        manager._config = GlobalConfig(
            default=DEFAULT_KB_NAME,
            knowledge_bases={DEFAULT_KB_NAME: kb},
        )

        old_kb_root = tmp_path / ".zettelkasten"

        with patch("jfox.global_config.DEFAULT_KB_PATH", old_kb_root):
            manager._migrate_default_kb_path()

        assert manager._config.knowledge_bases[DEFAULT_KB_NAME].path == str(new_path)


class TestAutoSummaryConfigSchedule:
    """测试 AutoSummaryConfig 调度时间窗口字段"""

    def test_default_schedule_values(self):
        """测试 schedule_* 字段默认值"""
        cfg = AutoSummaryConfig()

        assert cfg.schedule_enabled is False
        assert cfg.schedule_weekday_start_hour == 0
        assert cfg.schedule_weekday_end_hour == 6
        assert cfg.schedule_weekend_start_hour == 0
        assert cfg.schedule_weekend_end_hour == 8
        assert cfg.schedule_timezone == "Asia/Shanghai"
        assert cfg.schedule_holiday_provider is None

    def test_invalid_hour_clamping(self):
        """非法/越界小时在 __post_init__ 中被钳回默认值"""
        cfg = AutoSummaryConfig(
            schedule_enabled=True,
            schedule_weekday_start_hour=25,
            schedule_weekday_end_hour=-1,
            schedule_weekend_start_hour=12,
            schedule_weekend_end_hour=12,
            schedule_timezone="",
        )

        assert cfg.schedule_weekday_start_hour == 0
        assert cfg.schedule_weekday_end_hour == 6
        assert cfg.schedule_weekend_start_hour == 0
        assert cfg.schedule_weekend_end_hour == 8
        assert cfg.schedule_timezone == "Asia/Shanghai"

    def test_from_dict_with_schedule_fields(self):
        """from_dict 正确解析调度字段"""
        cfg = AutoSummaryConfig.from_dict(
            {
                "schedule_enabled": True,
                "schedule_weekday_start_hour": 1,
                "schedule_weekday_end_hour": 5,
                "schedule_weekend_start_hour": 2,
                "schedule_weekend_end_hour": 7,
                "schedule_timezone": "UTC",
            }
        )

        assert cfg.schedule_enabled is True
        assert cfg.schedule_weekday_start_hour == 1
        assert cfg.schedule_weekday_end_hour == 5
        assert cfg.schedule_weekend_start_hour == 2
        assert cfg.schedule_weekend_end_hour == 7
        assert cfg.schedule_timezone == "UTC"

    def test_to_dict_includes_schedule_fields(self):
        """to_dict 包含所有 schedule_* 字段"""
        cfg = AutoSummaryConfig(
            schedule_enabled=True,
            schedule_weekday_start_hour=1,
            schedule_weekday_end_hour=4,
            schedule_weekend_start_hour=2,
            schedule_weekend_end_hour=3,
            schedule_timezone="UTC",
            schedule_holiday_provider="noop",
        )

        data = cfg.to_dict()

        assert data["schedule_enabled"] is True
        assert data["schedule_weekday_start_hour"] == 1
        assert data["schedule_weekday_end_hour"] == 4
        assert data["schedule_weekend_start_hour"] == 2
        assert data["schedule_weekend_end_hour"] == 3
        assert data["schedule_timezone"] == "UTC"
        assert data["schedule_holiday_provider"] == "noop"


class TestGetGlobalConfigManager:
    """测试 get_global_config_manager 函数"""

    def setup_method(self):
        """每个测试前清理全局实例"""
        import jfox.global_config as gc_module

        gc_module._global_config_manager = None

    def teardown_method(self):
        """每个测试后清理全局实例"""
        import jfox.global_config as gc_module

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


class TestFromDictNonDictSection:
    """A1: truthy 非 dict section 不得炸 from_dict，回该类默认配置。"""

    TRUTHY_NON_DICT = [
        pytest.param("enabled", id="str"),
        pytest.param(1, id="int"),
        pytest.param(["x"], id="list"),
        pytest.param(True, id="bool"),
    ]

    @pytest.mark.parametrize("bad", TRUTHY_NON_DICT)
    def test_backup_config(self, bad):
        cfg = BackupConfig.from_dict(bad)  # type: ignore[arg-type]
        assert cfg == BackupConfig()
        assert cfg.enabled is False and cfg.retain == 7

    @pytest.mark.parametrize("bad", TRUTHY_NON_DICT)
    def test_auto_summary_config(self, bad):
        cfg = AutoSummaryConfig.from_dict(bad)  # type: ignore[arg-type]
        assert cfg == AutoSummaryConfig()
        assert cfg.enabled is False and cfg.interval_minutes == 30

    @pytest.mark.parametrize("bad", TRUTHY_NON_DICT)
    def test_fragment_capture_config(self, bad):
        cfg = FragmentCaptureConfig.from_dict(bad)  # type: ignore[arg-type]
        assert cfg == FragmentCaptureConfig()
        assert cfg.enabled is True and cfg.max_content_chars == 500

    @pytest.mark.parametrize("bad", TRUTHY_NON_DICT)
    def test_prompt_capture_config(self, bad):
        cfg = PromptCaptureConfig.from_dict(bad)  # type: ignore[arg-type]
        assert cfg == PromptCaptureConfig()
        assert cfg.enabled is True and cfg.endpoint_url == "http://127.0.0.1:18700/api/prompt"

    @pytest.mark.parametrize("bad", TRUTHY_NON_DICT)
    def test_prompt_judge_config(self, bad):
        cfg = PromptJudgeConfig.from_dict(bad)  # type: ignore[arg-type]
        assert cfg == PromptJudgeConfig()
        assert cfg.runner == "pi" and cfg.model == "ollama/deepseek-v4-pro:0813-cloud"

    @pytest.mark.parametrize(
        "falsy", [pytest.param(None, id="none"), pytest.param({}, id="empty-dict")]
    )
    def test_falsy_inputs_still_return_defaults(self, falsy):
        """None/空 dict 是既有行为，回归保护。"""
        assert BackupConfig.from_dict(falsy) == BackupConfig()
        assert AutoSummaryConfig.from_dict(falsy) == AutoSummaryConfig()
        assert FragmentCaptureConfig.from_dict(falsy) == FragmentCaptureConfig()
        assert PromptCaptureConfig.from_dict(falsy) == PromptCaptureConfig()
        assert PromptJudgeConfig.from_dict(falsy) == PromptJudgeConfig()


class TestGlobalConfigFromDictDefensive:
    """A2: 根级/容器级/entry 级畸形输入不炸、坏局部跳过、好局部保留。"""

    @pytest.mark.parametrize("bad", [[1], "oops", 42, True])
    def test_root_non_dict_returns_default_object(self, bad):
        cfg = GlobalConfig.from_dict(bad)
        assert cfg.default == DEFAULT_KB_NAME
        assert cfg.knowledge_bases == {}

    def test_knowledge_bases_non_dict_preserves_other_sections(self):
        cfg = GlobalConfig.from_dict(
            {
                "default": "work",
                "knowledge_bases": ["broken"],
                "backup": {"enabled": True, "retain": 3},
            }
        )
        assert cfg.default == "work"
        assert cfg.knowledge_bases == {}
        assert cfg.backup.enabled is True
        assert cfg.backup.retain == 3

    def test_malformed_kb_entry_skipped_valid_kept(self):
        cfg = GlobalConfig.from_dict(
            {
                "knowledge_bases": {
                    "bad": "oops",
                    "work": {"path": "/tmp/work", "created": "2024-01-01T00:00:00"},
                }
            }
        )
        assert "bad" not in cfg.knowledge_bases
        assert cfg.knowledge_bases["work"].path == "/tmp/work"


class TestLoadFileLevelFailureLogs:
    """A4: 文件级加载失败记录原始 traceback 并返回默认配置。"""

    def _assert_failure_logged(self, tmp_path, caplog, raw: str):
        cfg_path = tmp_path / "zk_config.json"
        cfg_path.write_text(raw, encoding="utf-8")
        manager = GlobalConfigManager(config_path=cfg_path)
        with caplog.at_level(logging.WARNING, logger="jfox.global_config"):
            config = manager.get_config()
        assert config.default == DEFAULT_KB_NAME
        warnings_ = [r for r in caplog.records if "Failed to load config" in r.message]
        assert warnings_, "expected load-failure warning"
        assert warnings_[0].exc_info is not None

    def test_invalid_json(self, tmp_path, caplog):
        self._assert_failure_logged(tmp_path, caplog, "invalid json")

    def test_root_non_dict(self, tmp_path, caplog):
        self._assert_failure_logged(tmp_path, caplog, "[1, 2, 3]")


class TestBackupCorruptedConfig:
    """A5 备份本体：字节保真、独占不覆盖、失败返回 False 且有 traceback。"""

    def test_preserves_original_bytes(self, tmp_path):
        original = b'{"default": "work"'  # 缺右括号：非法 JSON 也必须可备份
        cfg_path = tmp_path / "zk_config.json"
        cfg_path.write_bytes(original)
        manager = GlobalConfigManager(config_path=cfg_path)

        assert manager._backup_corrupted_config() is True

        backups = list(tmp_path.glob("zk_config.json.corrupt-*"))
        assert len(backups) == 1
        assert backups[0].read_bytes() == original

    def test_never_overwrites_existing_snapshot(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gc, "_utc_corrupt_timestamp", lambda: "20260909T000000Z")
        # cycle 必须先绑定为持久迭代器：lambda 内新建 cycle 会让 next() 永远取首元素
        suffix_cycle = cycle(["dup", "dup", "ok"])
        monkeypatch.setattr(gc, "_corrupt_backup_suffix", lambda: next(suffix_cycle))
        original = b"[1, 2, 3]"
        cfg_path = tmp_path / "zk_config.json"
        cfg_path.write_bytes(original)
        collision = tmp_path / "zk_config.json.corrupt-20260909T000000Z-dup"
        collision.write_bytes(b"OLD")
        manager = GlobalConfigManager(config_path=cfg_path)

        assert manager._backup_corrupted_config() is True

        assert collision.read_bytes() == b"OLD"  # 已有快照未被覆盖
        created = tmp_path / "zk_config.json.corrupt-20260909T000000Z-ok"
        assert created.read_bytes() == original

    def test_suffix_failure_returns_false_with_traceback(self, tmp_path, caplog, monkeypatch):
        original = b'{"bad"'
        cfg_path = tmp_path / "zk_config.json"
        cfg_path.write_bytes(original)

        def _boom():
            raise OSError("suffix generator exploded")

        monkeypatch.setattr(gc, "_corrupt_backup_suffix", _boom)
        manager = GlobalConfigManager(config_path=cfg_path)

        with caplog.at_level(logging.ERROR, logger="jfox.global_config"):
            assert manager._backup_corrupted_config() is False

        errors = [r for r in caplog.records if "backup" in r.getMessage().lower()]
        assert errors and errors[0].exc_info is not None
        assert list(tmp_path.glob("zk_config.json.corrupt-*")) == []


SECTION_CLASSES = {
    "auto_summary": AutoSummaryConfig,
    "fragment_capture": FragmentCaptureConfig,
    "backup": BackupConfig,
    "prompt_capture": PromptCaptureConfig,
    "prompt_judge": PromptJudgeConfig,
}

GOOD_PAYLOAD = {
    "default": "work",
    "knowledge_bases": {
        "work": {"path": "/tmp/work", "created": "2024-01-01T00:00:00"}
    },
    "note_add": {"dedup_enabled": False},
}


class TestLoadMalformedSection:
    """A3: section 级畸形不触发整体回退，注册表/兄弟段/原文件全部保留。

    fixture 安全：default 指向 work 且注册表无 default entry，
    _migrate_default_kb_path 会提前返回，不会合法改写文件（spec §6.3）。
    """

    @pytest.mark.parametrize("section", sorted(SECTION_CLASSES))
    def test_registry_default_and_file_preserved(self, tmp_path, section):
        cfg_path = tmp_path / "zk_config.json"
        payload = dict(GOOD_PAYLOAD)
        payload[section] = "enabled"
        cfg_path.write_text(json.dumps(payload), encoding="utf-8")
        before = cfg_path.read_bytes()

        config = GlobalConfigManager(config_path=cfg_path).get_config()

        assert config.default == "work"
        assert config.knowledge_bases["work"].path == "/tmp/work"
        assert DEFAULT_KB_NAME not in config.knowledge_bases  # 未被整体重置
        assert getattr(config, section) == SECTION_CLASSES[section]()  # 坏段回默认
        assert config.note_add.dedup_enabled is False  # 兄弟段保留
        assert cfg_path.read_bytes() == before  # 原文件未被重写


class TestLoadRecoveryOrchestration:
    """A5 编排 + A6：文件级失败的备份与 persist 门控。"""

    def test_file_failure_backs_up_then_recovers(self, tmp_path):
        original = b'{"default": "work"'
        cfg_path = tmp_path / "zk_config.json"
        cfg_path.write_bytes(original)

        config = GlobalConfigManager(config_path=cfg_path).get_config()

        assert config.default == DEFAULT_KB_NAME
        backups = list(tmp_path.glob("zk_config.json.corrupt-*"))
        assert len(backups) == 1 and backups[0].read_bytes() == original

    def test_two_consecutive_failures_two_distinct_snapshots(self, tmp_path):
        original = b'{"default": "work"'
        cfg_path = tmp_path / "zk_config.json"
        cfg_path.write_bytes(original)
        GlobalConfigManager(config_path=cfg_path).get_config()
        cfg_path.write_bytes(original)  # 恢复坏内容，再次触发（同秒，靠 suffix 区分）
        GlobalConfigManager(config_path=cfg_path).get_config()

        backups = list(tmp_path.glob("zk_config.json.corrupt-*"))
        assert len(backups) == 2
        assert all(b.read_bytes() == original for b in backups)

    def test_normal_load_creates_no_snapshot(self, tmp_path):
        cfg_path = tmp_path / "zk_config.json"
        cfg_path.write_text(json.dumps(GOOD_PAYLOAD), encoding="utf-8")

        assert GlobalConfigManager(config_path=cfg_path).get_config().default == "work"
        assert list(tmp_path.glob("zk_config.json.corrupt-*")) == []

    def test_backup_failure_returns_default_but_keeps_original_file(
        self, tmp_path, caplog, monkeypatch
    ):
        original = b'{"default": "work"'
        cfg_path = tmp_path / "zk_config.json"
        cfg_path.write_bytes(original)

        def _boom():
            raise OSError("backup subsystem exploded")

        monkeypatch.setattr(gc, "_corrupt_backup_suffix", _boom)
        with caplog.at_level(logging.WARNING, logger="jfox.global_config"):
            config = GlobalConfigManager(config_path=cfg_path).get_config()

        assert config.default == DEFAULT_KB_NAME  # 内存默认配置仍可用
        assert cfg_path.read_bytes() == original  # 原文件未被覆盖
        errors = [r for r in caplog.records if "backup" in r.getMessage().lower()]
        assert errors and errors[0].exc_info is not None  # 备份错误有 traceback
        warnings_ = [r for r in caplog.records if "Failed to load config" in r.message]
        assert warnings_ and warnings_[0].exc_info is not None  # 原始异常仍可诊断
        assert list(tmp_path.glob("zk_config.json.corrupt-*")) == []

    def test_create_default_persist_false_never_saves(self, tmp_path, monkeypatch):
        saved: list[bool] = []
        monkeypatch.setattr(GlobalConfigManager, "_save", lambda self: saved.append(True) or True)
        monkeypatch.setattr(gc, "DEFAULT_KB_PATH", tmp_path / "kbroot")  # 存在与否都不得触发保存
        (tmp_path / "kbroot").mkdir()

        config = GlobalConfigManager(config_path=tmp_path / "zk_config.json")._create_default_config(
            persist=False
        )

        assert config.default == DEFAULT_KB_NAME
        assert saved == []
        assert not (tmp_path / "zk_config.json").exists()

    def test_create_default_persist_true_keeps_existing_behavior(self, tmp_path, monkeypatch):
        saved: list[bool] = []
        monkeypatch.setattr(GlobalConfigManager, "_save", lambda self: saved.append(True) or True)
        monkeypatch.setattr(gc, "DEFAULT_KB_PATH", tmp_path / "kbroot")
        (tmp_path / "kbroot").mkdir()

        GlobalConfigManager(config_path=tmp_path / "zk_config.json")._create_default_config(
            persist=True
        )

        assert saved == [True]
