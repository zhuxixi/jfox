from jfox.global_config import AutoSummaryConfig


def test_default_sources_both_enabled():
    cfg = AutoSummaryConfig()
    assert cfg.session_sources == ["claude", "kimi"]
    assert cfg.kimi_sessions_dir is None


def test_from_dict_legacy_config_gets_default_sources():
    cfg = AutoSummaryConfig.from_dict({"enabled": True})
    assert cfg.enabled is True
    assert cfg.session_sources == ["claude", "kimi"]


def test_roundtrip_preserves_sources():
    cfg = AutoSummaryConfig(session_sources=["claude"], kimi_sessions_dir="/tmp/k")
    cfg2 = AutoSummaryConfig.from_dict(cfg.to_dict())
    assert cfg2.session_sources == ["claude"]
    assert cfg2.kimi_sessions_dir == "/tmp/k"


def test_from_dict_null_session_sources_falls_back():
    """issue-3: session_sources 显式 null 时不能崩，回退默认"""
    cfg = AutoSummaryConfig.from_dict({"session_sources": None})
    assert cfg.session_sources == ["claude", "kimi"]


def test_from_dict_empty_session_sources_preserved():
    """issue-7: session_sources 显式 [] 表示禁用所有来源，不应被 or 短路替换为默认"""
    cfg = AutoSummaryConfig.from_dict({"session_sources": []})
    assert cfg.session_sources == []
