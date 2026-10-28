"""写入类命令的 --json 必须带实际写入库名（#584）。"""

import json
import logging
import os
from pathlib import Path


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
    def test_write_to_test_kb_without_explicit_kb_warns(self, caplog, monkeypatch):
        from utils.temp_kb import temp_kb_registered

        from jfox.cli import _add_note_impl
        from jfox.config import use_kb

        # CR-A4 后 JFOX_KB 显式设置会豁免告警，须确保测试环境无该变量
        monkeypatch.delenv("JFOX_KB", raising=False)
        with temp_kb_registered("test_warning_probe") as kb_name:
            with use_kb(kb_name):
                with caplog.at_level(logging.WARNING):
                    _add_note_impl("warning 探针", "warning-probe", "fleeting", None, None, "json")
        assert any("测试知识库" in r.message for r in caplog.records)


class TestKbWarningJsonField:
    """CR-B1：--json 下 logger.warning 被入口 logging.disable 全静默，
    测试库告警必须并入成功 result 的 kb_warning 字段才能被 agent/自动化读到。"""

    def test_add_json_includes_kb_warning_direct(self, capsys, monkeypatch):
        """进程内直调 _add_note_impl：断言 JSON 组装含 kb_warning（table/logger 侧见 TestTestKbWarning）。"""
        from utils.temp_kb import temp_kb_registered

        from jfox.cli import _add_note_impl
        from jfox.config import use_kb

        monkeypatch.delenv("JFOX_KB", raising=False)
        with temp_kb_registered("test_json_warn_direct") as kb_name:
            with use_kb(kb_name):
                _add_note_impl("json 告警探针", "json-warn-probe", "fleeting", None, None, "json")
                out = json.loads(capsys.readouterr().out)
        assert out["success"] is True
        assert out["kb"] == kb_name
        assert kb_name in out["kb_warning"]

    def test_add_json_includes_kb_warning_via_subprocess(self, monkeypatch):
        """CLI 子进程级（ZKCLI._run("add", ..., "--json")）：无 --kb、无 JFOX_KB、
        current KB 是注册的 test_* 库时，stdout 纯 JSON 且带 kb_warning。

        _run 只在 init 过的实例上自动追加 --kb，故用未 init 的裸实例；
        当前库指向测试库靠「把该库设为全局配置 default」实现，
        用配置文件快照在 finally 里完整还原。
        """
        from utils.jfox_cli import ZKCLI
        from utils.temp_kb import temp_kb_registered

        from jfox.kb_manager import get_kb_manager

        monkeypatch.delenv("JFOX_KB", raising=False)
        config_path = Path(os.environ["ZK_CONFIG_PATH"])
        snapshot = config_path.read_text(encoding="utf-8")
        _reset_global_config_cache()
        try:
            with temp_kb_registered("test_json_warn_subproc") as kb_name:
                assert get_kb_manager().config_manager.set_default(kb_name)
                bare = ZKCLI()  # 未 init：_run 不追加 --kb，JFOX_KB 也未设
                result = bare.add("子进程 kb_warning 探针", title="kb-warning-subproc")
                assert result.success
                assert result.data is not None, f"stdout 不是纯 JSON: {result.stdout!r}"
                assert result.json()["kb"] == kb_name
                assert kb_name in result.json()["kb_warning"]
        finally:
            config_path.write_text(snapshot, encoding="utf-8")
            _reset_global_config_cache()

    def test_edit_json_includes_kb_warning(self, caplog, capsys, monkeypatch):
        """_edit_impl 同型：JSON result 带 kb_warning，logger.warning 保留给 table 模式。"""
        from utils.temp_kb import temp_kb_registered

        from jfox.cli import _add_note_impl, _edit_impl
        from jfox.config import use_kb

        monkeypatch.delenv("JFOX_KB", raising=False)
        with temp_kb_registered("test_edit_warn_probe") as kb_name:
            with use_kb(kb_name):
                _add_note_impl("编辑告警探针", "edit-warn-probe", "fleeting", None, None, "json")
                note_id = json.loads(capsys.readouterr().out)["id"]
                with caplog.at_level(logging.WARNING):
                    _edit_impl(
                        note_id, "编辑告警探针更新正文", None, None, None, None, None, "json"
                    )
                out = json.loads(capsys.readouterr().out)
        assert out["success"] is True
        assert out["kb"] == kb_name
        assert kb_name in out["kb_warning"]
        assert any("测试知识库" in r.message for r in caplog.records)


class TestJfoxKbEnvExemption:
    """CR-A4：JFOX_KB 显式设置与 --kb 一样豁免测试库告警。"""

    def test_jfox_kb_env_no_warning_via_subprocess(self, monkeypatch):
        from utils.jfox_cli import ZKCLI
        from utils.temp_kb import temp_kb_registered

        with temp_kb_registered("test_envkb_probe") as kb_name:
            monkeypatch.setenv("JFOX_KB", kb_name)
            bare = ZKCLI()  # 无 --kb，仅 JFOX_KB 指向测试库
            result = bare.add("JFOX_KB 豁免探针", title="jfox-kb-env-probe")
            assert result.success
            assert result.data is not None, f"stdout 不是纯 JSON: {result.stdout!r}"
            assert result.json()["kb"] == kb_name
            assert "kb_warning" not in result.json()

    def test_jfox_kb_env_no_warning_direct(self, caplog, capsys, monkeypatch):
        from utils.temp_kb import temp_kb_registered

        from jfox.cli import _add_note_impl
        from jfox.config import use_kb

        with temp_kb_registered("test_envkb_direct") as kb_name:
            monkeypatch.setenv("JFOX_KB", kb_name)
            with use_kb(kb_name):
                with caplog.at_level(logging.WARNING):
                    _add_note_impl("env 豁免探针", "envkb-probe", "fleeting", None, None, "json")
                    out = json.loads(capsys.readouterr().out)
        assert out["success"] is True
        assert "kb_warning" not in out
        assert not any("测试知识库" in r.message for r in caplog.records)
