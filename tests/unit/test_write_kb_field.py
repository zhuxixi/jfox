"""写入类命令的 --json 必须带实际写入库名（#584）。"""

import logging


def _reset_global_config_cache() -> None:
    """重置全局配置/KB 管理器单例，让进程内读到子进程刚注册的 KB。

    （同 tests/integration/test_index_status_persist.py 的既有模式）
    """
    import jfox.global_config as gc_module
    import jfox.kb_manager as kb_module

    if gc_module._global_config_manager is not None:
        gc_module._global_config_manager._config = None
    gc_module._global_config_manager = None
    kb_module._kb_manager = None


class TestCurrentKbName:
    def test_resolves_registered_name_by_path(self, cli):
        from jfox.config import current_kb_name, use_kb

        # 反查依赖 use_kb 改写的 active base_dir（模块级 config 是 import 时快照）
        _reset_global_config_cache()
        with use_kb(cli.kb_name):
            assert current_kb_name() == cli.kb_name


class TestAddJsonKbField:
    def test_add_json_contains_kb(self, cli):
        result = cli.add("kb 字段测试内容", title="kb-field-probe")
        assert result.success
        assert result.json()["kb"] == cli.kb_name

    def test_add_duplicate_json_contains_kb(self, cli):
        # #383 防重仅守 permanent（fleeting 允许同名），duplicate 路径需显式类型
        assert cli.add("重复内容探针", title="dup-probe", note_type="permanent").success
        dup = cli.add("重复内容探针", title="dup-probe", note_type="permanent")
        assert not dup.success
        assert dup.json()["skipped"] == "duplicate"
        assert dup.json()["kb"] == cli.kb_name


class TestTestKbWarning:
    def test_write_to_test_kb_without_explicit_kb_warns(self, caplog):
        from utils.temp_kb import temp_kb_registered

        from jfox.cli import _add_note_impl
        from jfox.config import use_kb

        with temp_kb_registered("test_warning_probe") as kb_name:
            with use_kb(kb_name):
                with caplog.at_level(logging.WARNING):
                    _add_note_impl("warning 探针", "warning-probe", "fleeting", None, None, "json")
        assert any("测试知识库" in r.message for r in caplog.records)
