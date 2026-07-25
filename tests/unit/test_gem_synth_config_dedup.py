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


def test_dedup_threshold_nan_sanitized_to_default():
    """NaN: max/min 与 NaN 比较返回 NaN → cosine >= NaN 永假 → dedup 永不触发。
    非有限值（NaN/inf）应回退到默认 0.88。"""
    cfg_nan = GemSynthesisConfig.from_dict({"dedup_threshold": float("nan")})
    assert cfg_nan.dedup_threshold == 0.88
    cfg_inf = GemSynthesisConfig.from_dict({"dedup_threshold": float("inf")})
    assert cfg_inf.dedup_threshold == 0.88
    cfg_ninf = GemSynthesisConfig.from_dict({"dedup_threshold": float("-inf")})
    assert cfg_ninf.dedup_threshold == 0.88


def test_dedup_threshold_bool_sanitized_to_default():
    """bool 经 _safe_float 会变 float(True)=1.0 / float(False)=0.0（合法阈值，静默绕过
    __post_init__ 的 bool 守卫）→ 等于悄悄把 dedup 关到极端阈值。from_dict 应拦 bool→默认 0.88。"""
    assert GemSynthesisConfig.from_dict({"dedup_threshold": True}).dedup_threshold == 0.88
    assert GemSynthesisConfig.from_dict({"dedup_threshold": False}).dedup_threshold == 0.88


def test_dedup_merge_enabled_defaults_true():
    assert GemSynthesisConfig().dedup_merge_enabled is True


def test_dedup_merge_enabled_from_dict():
    cfg = GemSynthesisConfig.from_dict({"dedup_merge_enabled": False})
    assert cfg.dedup_merge_enabled is False


def test_dedup_merge_enabled_missing_uses_default():
    cfg = GemSynthesisConfig.from_dict({})
    assert cfg.dedup_merge_enabled is True
