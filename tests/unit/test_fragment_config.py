"""验证 FragmentCaptureConfig 默认值与可配置关键词。"""

from jfox.global_config import FragmentCaptureConfig


def test_defaults():
    cfg = FragmentCaptureConfig()
    assert cfg.enabled is True
    assert "不对" in cfg.correction_keywords
    assert "我决定" in cfg.decision_keywords
    assert cfg.max_content_chars == 500


def test_from_dict_empty_uses_defaults():
    cfg = FragmentCaptureConfig.from_dict({})
    assert cfg.enabled is True
    assert "错了" in cfg.correction_keywords


def test_from_dict_explicit_keywords():
    cfg = FragmentCaptureConfig.from_dict(
        {"correction_keywords": ["错啦"], "decision_keywords": ["就这么定"]}
    )
    assert cfg.correction_keywords == ["错啦"]
    assert cfg.decision_keywords == ["就这么定"]


def test_from_dict_disable():
    cfg = FragmentCaptureConfig.from_dict({"enabled": False})
    assert cfg.enabled is False


def test_to_dict_roundtrip():
    cfg = FragmentCaptureConfig(correction_keywords=["x"])
    d = cfg.to_dict()
    assert d["correction_keywords"] == ["x"]
    assert FragmentCaptureConfig.from_dict(d).correction_keywords == ["x"]
