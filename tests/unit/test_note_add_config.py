"""
测试类型: 单元测试
目标模块: jfox.global_config.NoteAddConfig
预估耗时: < 1秒
"""

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.global_config import GlobalConfig, NoteAddConfig


class TestNoteAddConfig:
    def test_defaults_all_on(self):
        cfg = NoteAddConfig()
        assert cfg.dedup_enabled is True
        assert cfg.title_dedup is True
        assert cfg.embedding_dedup is True
        assert cfg.dedup_threshold == 0.95

    def test_from_dict_none_returns_default(self):
        assert NoteAddConfig.from_dict(None).dedup_enabled is True
        assert NoteAddConfig.from_dict({}).dedup_threshold == 0.95

    def test_roundtrip(self):
        cfg = NoteAddConfig(dedup_enabled=False, dedup_threshold=0.9)
        cfg2 = NoteAddConfig.from_dict(cfg.to_dict())
        assert cfg2.dedup_enabled is False
        assert cfg2.dedup_threshold == 0.9

    def test_threshold_clamped_to_unit_interval(self):
        assert NoteAddConfig(dedup_threshold=1.5).dedup_threshold == 1.0
        assert NoteAddConfig(dedup_threshold=-0.1).dedup_threshold == 0.0

    def test_threshold_invalid_falls_back_to_default(self):
        assert NoteAddConfig(dedup_threshold=float("nan")).dedup_threshold == 0.95
        assert NoteAddConfig(dedup_threshold=float("inf")).dedup_threshold == 0.95
        assert NoteAddConfig(dedup_threshold=None).dedup_threshold == 0.95
        assert NoteAddConfig(dedup_threshold="high").dedup_threshold == 0.95  # type: ignore

    def test_global_config_roundtrip_contains_note_add(self):
        gc = GlobalConfig()
        d = gc.to_dict()
        assert "note_add" in d
        gc2 = GlobalConfig.from_dict(d)
        assert isinstance(gc2.note_add, NoteAddConfig)
        assert gc2.note_add.dedup_threshold == 0.95

    def test_legacy_config_without_note_add_gets_defaults(self):
        gc = GlobalConfig.from_dict({"default": "default"})
        assert gc.note_add.dedup_enabled is True

    def test_from_dict_non_dict_returns_defaults(self):
        """非 dict 值（如手改配置写成字符串）不得炸 from_dict。"""
        cfg = NoteAddConfig.from_dict("enabled")  # type: ignore
        assert cfg.dedup_enabled is True
        assert cfg.dedup_threshold == 0.95

    def test_global_config_tolerates_malformed_note_add(self):
        """note_add 损坏时回默认值，其余配置段（default/KB 注册表）不受牵连。

        回归：旧实现 data.get 在字符串上抛 AttributeError → _load 宽 except
        重建默认 GlobalConfig → 注册表被清空的风险。"""
        gc = GlobalConfig.from_dict(
            {"default": "default", "knowledge_bases": {}, "note_add": "enabled"}
        )
        assert gc.default == "default"
        assert gc.note_add.dedup_enabled is True
