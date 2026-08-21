"""测试延迟导入：轻量命令不应加载重依赖模块"""

import subprocess
import sys

import pytest


class TestLazyImport:
    """验证 CLI 模块的延迟导入行为

    注：模块重载断言必须跑在 subprocess 里——删除 sys.modules 再 re-import
    会造成模块对象分裂（旧引用 vs 新对象），浅恢复无法还原，污染同进程的
    其他测试（如 test_moc_generate 的写盘 fixture）。subprocess 模式与
    test_moc_cli.py 的 lazy 契约测试一致。
    """

    def test_note_module_no_chromadb_at_import(self):
        """导入 note 模块不应触发 chromadb 导入"""
        script = '''
import sys
import jfox.note  # noqa: F401
print("chromadb" in sys.modules)
'''
        result = subprocess.run(
            [sys.executable, "-c", script], check=True, capture_output=True, text=True
        )
        assert result.stdout.strip() == "False"

    def test_cli_module_no_heavy_deps_at_import(self):
        """导入 cli 模块不应触发 chromadb/networkx/watchdog 导入"""
        script = '''
import sys
import jfox.cli  # noqa: F401
print("chromadb" in sys.modules, "networkx" in sys.modules, "watchdog" in sys.modules)
'''
        result = subprocess.run(
            [sys.executable, "-c", script], check=True, capture_output=True, text=True
        )
        assert result.stdout.strip() == "False False False"

    def test_hf_offline_env_set_by_main(self):
        """验证 HF 离线环境变量在调用 main() 前设置"""
        # main() 内部设置 HF 环境变量，验证函数定义存在且包含 setdefault 调用
        import inspect
        import os

        from jfox.cli import main

        source = inspect.getsource(main)
        assert "HF_HUB_OFFLINE" in source, "main() should set HF_HUB_OFFLINE environment variable"
        assert (
            "TRANSFORMERS_OFFLINE" in source
        ), "main() should set TRANSFORMERS_OFFLINE environment variable"

        # 同时验证导入 cli 模块本身不会设置环境变量（不影响测试环境）
        assert (
            os.environ.get("HF_HUB_OFFLINE") is None
        ), "HF_HUB_OFFLINE should NOT be set at module import time (only in main())"
