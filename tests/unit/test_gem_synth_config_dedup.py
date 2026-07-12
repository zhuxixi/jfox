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
