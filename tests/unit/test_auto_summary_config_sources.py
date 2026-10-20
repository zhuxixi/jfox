from jfox.global_config import AutoSummaryConfig


def test_default_sources_both_enabled():
    cfg = AutoSummaryConfig()
    assert cfg.session_sources == ["claude", "kimi", "pi"]
    assert cfg.kimi_sessions_dir is None


def test_from_dict_legacy_config_gets_default_sources():
    cfg = AutoSummaryConfig.from_dict({"enabled": True})
    assert cfg.enabled is True
    assert cfg.session_sources == ["claude", "kimi", "pi"]


def test_roundtrip_preserves_sources():
    cfg = AutoSummaryConfig(session_sources=["claude"], kimi_sessions_dir="/tmp/k")
    cfg2 = AutoSummaryConfig.from_dict(cfg.to_dict())
    assert cfg2.session_sources == ["claude"]
    assert cfg2.kimi_sessions_dir == "/tmp/k"


def test_from_dict_null_session_sources_falls_back():
    """issue-3: session_sources 显式 null 时不能崩，回退默认"""
    cfg = AutoSummaryConfig.from_dict({"session_sources": None})
    assert cfg.session_sources == ["claude", "kimi", "pi"]


def test_from_dict_empty_session_sources_preserved():
    """issue-7: session_sources 显式 [] 表示禁用所有来源，不应被 or 短路替换为默认"""
    cfg = AutoSummaryConfig.from_dict({"session_sources": []})
    assert cfg.session_sources == []


def test_pi_session_dirs_roundtrip():
    cfg = AutoSummaryConfig(pi_session_dirs=["/tmp/pi1", "/tmp/pi2"])
    cfg2 = AutoSummaryConfig.from_dict(cfg.to_dict())
    assert cfg2.pi_session_dirs == ["/tmp/pi1", "/tmp/pi2"]


def test_pi_session_dirs_non_list_becomes_none():
    assert AutoSummaryConfig.from_dict({"pi_session_dirs": "oops"}).pi_session_dirs is None


def test_resolve_pi_session_dirs_prefers_explicit_config():
    from jfox.auto_summary.sources import resolve_pi_session_dirs

    cfg = AutoSummaryConfig(pi_session_dirs=["/tmp/a", "/tmp/b"])
    assert [str(p) for p in resolve_pi_session_dirs(cfg)] == ["/tmp/a", "/tmp/b"]


def test_resolve_pi_session_dirs_respects_env(tmp_path, monkeypatch):
    from jfox.auto_summary.sources import resolve_pi_session_dirs

    monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(tmp_path / "official"))
    monkeypatch.setenv("AGENT_BOARD_ROOT", str(tmp_path / "board"))
    dirs = [str(p) for p in resolve_pi_session_dirs(AutoSummaryConfig())]
    assert dirs == [
        str((tmp_path / "official").resolve()),
        str((tmp_path / "board" / "sessions").resolve()),
    ]


def test_resolve_pi_session_dirs_dedupes(monkeypatch, tmp_path):
    from jfox.auto_summary.sources import resolve_pi_session_dirs

    monkeypatch.setenv("PI_CODING_AGENT_SESSION_DIR", str(tmp_path / "sessions"))
    monkeypatch.setenv("AGENT_BOARD_ROOT", str(tmp_path))
    dirs = resolve_pi_session_dirs(AutoSummaryConfig())
    assert len(dirs) == 1


def test_pi_session_dirs_filters_non_string_elements():
    cfg = AutoSummaryConfig.from_dict({"pi_session_dirs": ["/tmp/ok", 42, "", None]})
    assert cfg.pi_session_dirs == ["/tmp/ok"]


def test_pi_session_dirs_all_invalid_becomes_none():
    cfg = AutoSummaryConfig.from_dict({"pi_session_dirs": [42, None, ""]})
    assert cfg.pi_session_dirs is None
