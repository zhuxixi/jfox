"""L3 宝石合成配置测试。"""

from jfox.global_config import GemSynthesisConfig


def test_defaults():
    cfg = GemSynthesisConfig()
    assert cfg.enabled is False  # 默认关闭，opt-in
    assert cfg.interval_minutes == 30
    assert cfg.anchor_types == ["correction", "decision", "ask_user_question"]
    assert cfg.grounding_top_k == 5
    assert cfg.target_kb is None


def test_from_dict_empty():
    assert GemSynthesisConfig.from_dict({}).enabled is False


def test_from_dict_explicit():
    cfg = GemSynthesisConfig.from_dict({"enabled": True, "grounding_top_k": 8})
    assert cfg.enabled is True and cfg.grounding_top_k == 8


def test_roundtrip():
    cfg = GemSynthesisConfig(grounding_top_k=7)
    assert GemSynthesisConfig.from_dict(cfg.to_dict()).grounding_top_k == 7
