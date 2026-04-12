"""测试延迟导入：轻量命令不应加载重依赖模块"""

import sys

import pytest


class TestLazyImport:
    """验证 CLI 模块的延迟导入行为"""

    @pytest.fixture(autouse=True)
    def _preserve_sys_modules(self):
        """保存并恢复 sys.modules，避免测试间的模块状态污染"""
        original = sys.modules.copy()
        yield
        # 恢复：删除新增的模块，恢复被删除的模块
        current = set(sys.modules.keys())
        for mod in current - set(original.keys()):
            del sys.modules[mod]
        sys.modules.update(original)

    def test_note_module_no_chromadb_at_import(self):
        """导入 note 模块不应触发 chromadb 导入"""
        # 移除可能已缓存的模块
        for mod in list(sys.modules.keys()):
            if "chromadb" in mod:
                del sys.modules[mod]

        # 重新导入 note
        if "jfox.note" in sys.modules:
            del sys.modules["jfox.note"]
        if "jfox.vector_store" in sys.modules:
            del sys.modules["jfox.vector_store"]

        import jfox.note  # noqa: F401

        # chromadb 不应被导入
        assert "chromadb" not in sys.modules, (
            "chromadb should not be imported when importing jfox.note"
        )

    def test_cli_module_no_heavy_deps_at_import(self):
        """导入 cli 模块不应触发 chromadb/networkx/watchdog 导入"""
        # 移除可能已缓存的模块
        for mod in list(sys.modules.keys()):
            if any(
                pkg in mod
                for pkg in ("chromadb", "networkx", "watchdog", "sentence_transformers")
            ):
                del sys.modules[mod]

        # 重新导入相关模块
        for mod in list(sys.modules.keys()):
            if mod.startswith("jfox.") and mod not in (
                "jfox",
                "jfox.__init__",
                "jfox.__main__",
            ):
                del sys.modules[mod]

        import jfox.cli  # noqa: F401

        # 重依赖不应被导入
        assert "chromadb" not in sys.modules, (
            "chromadb should not be imported at jfox.cli module level"
        )
        assert "networkx" not in sys.modules, (
            "networkx should not be imported at jfox.cli module level"
        )
        assert "watchdog" not in sys.modules, (
            "watchdog should not be imported at jfox.cli module level"
        )

    def test_hf_offline_env_set(self):
        """验证 HF 离线环境变量在导入 cli 后已设置"""
        import os

        import jfox.cli  # noqa: F401

        # setdefault 会在用户未设置时生效
        assert os.environ.get("HF_HUB_OFFLINE") == "1", (
            "HF_HUB_OFFLINE should be set to '1' after importing jfox.cli"
        )
        assert os.environ.get("TRANSFORMERS_OFFLINE") == "1", (
            "TRANSFORMERS_OFFLINE should be set to '1' after importing jfox.cli"
        )
