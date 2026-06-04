"""验证 auto-summary 默认配置：skip_after_days=0"""
from jfox.global_config import AutoSummaryConfig


def test_skip_after_days_default_is_zero():
    """默认值应为 0（不跳过任何 session）"""
    cfg = AutoSummaryConfig()
    assert cfg.skip_after_days == 0


def test_skip_after_days_from_dict_empty():
    """from_dict 空输入也应得到 0"""
    cfg = AutoSummaryConfig.from_dict({})
    assert cfg.skip_after_days == 0


def test_skip_after_days_from_dict_explicit():
    """显式传入仍生效"""
    cfg = AutoSummaryConfig.from_dict({"skip_after_days": 14})
    assert cfg.skip_after_days == 14


def test_skip_after_days_negative_clamped():
    """负值被 clamp 为 0"""
    cfg = AutoSummaryConfig(skip_after_days=-1)
    assert cfg.skip_after_days == 0
