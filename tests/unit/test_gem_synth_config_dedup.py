from jfox.global_config import GemSynthesisConfig


def test_defaults():
    cfg = GemSynthesisConfig()
    assert cfg.dedup_enabled is True
    assert cfg.dedup_threshold == 0.88


def test_from_dict_reads_dedup_fields():
    cfg = GemSynthesisConfig.from_dict({"dedup_enabled": False, "dedup_threshold": 0.92})
    assert cfg.dedup_enabled is False
    assert cfg.dedup_threshold == 0.92


def test_from_dict_missing_uses_defaults():
    cfg = GemSynthesisConfig.from_dict({})
    assert cfg.dedup_enabled is True
    assert cfg.dedup_threshold == 0.88


def test_dedup_threshold_clamped_to_0_1():
    """threshold >1（永不命中）/ <0（无意义）应被钳到 [0, 1] 边界。"""
    cfg_high = GemSynthesisConfig.from_dict({"dedup_threshold": 1.5})
    assert cfg_high.dedup_threshold == 1.0
    cfg_low = GemSynthesisConfig.from_dict({"dedup_threshold": -0.5})
    assert cfg_low.dedup_threshold == 0.0
