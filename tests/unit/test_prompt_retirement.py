"""旧 gem-synth 自动合成退役回归测试（#399 Task 8）。

验证退役后：
1. import jfox 不再触发 gem_synth 生命周期注册
2. gem_synth 合成模块不再存在
3. daemon lifespan 不创建 gem-synth task
4. jfox fragments list/show 仍可读历史数据
5. candidates / prompts 命令仍注册
6. INTERNAL_SOURCES 含 prompt-judge（防反馈循环）
"""

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]


def test_gem_synth_modules_removed():
    """旧合成运行时模块已删除。"""
    for mod in (
        "jfox.gem_synth.loop",
        "jfox.gem_synth.synthesizer",
        "jfox.gem_synth.anchors",
        "jfox.gem_synth.dedup",
        "jfox.gem_synth.llm",
        "jfox.gem_synth.lifecycle",
        "jfox.gem_synth.store",
        "jfox.gem_synth.paths",
    ):
        with pytest.raises(ImportError):
            __import__(mod)


def test_import_jfox_no_gem_synth_hooks():
    """import jfox 不触发 gem_synth 生命周期订阅。"""
    import jfox
    import jfox.note as note_mod

    _ = jfox  # 触发包初始化
    # note 生命周期钩子表中不应有 gem_synth 模块的回调
    for event, cbs in note_mod._LIFECYCLE_HOOKS.items():
        for cb in cbs:
            mod = getattr(cb, "__module__", "")
            assert "gem_synth" not in mod, f"{event} 仍有 gem_synth 订阅: {mod}"


def test_daemon_has_no_gem_synth_wiring():
    """daemon server 不再有 gem-synth 启停函数。"""
    import jfox.daemon.server as srv

    assert not hasattr(srv, "_maybe_start_gem_synth")
    assert not hasattr(srv, "_maybe_stop_gem_synth")
    assert not hasattr(srv, "_gem_synth_task")


def test_cli_still_registers_candidates_and_prompts():
    """candidates / prompts 命令保留；gem-synth 子命令组退役。"""
    from jfox.cli import app

    names = [c.name for c in app.registered_groups]
    assert "candidates" in names
    assert "prompts" in names
    assert "gem-synth" not in names


def test_fragments_cli_still_available():
    """jfox fragments（历史只读）命令保留。"""
    from jfox.cli import app

    names = [c.name for c in app.registered_groups]
    assert "fragments" in names


def test_fragment_store_read_history(tmp_path):
    """FragmentStore 仍能读历史 session_fragments 行。"""
    from jfox.fragment.store import FragmentStore

    store = FragmentStore(db_path=tmp_path / "fragments.db")
    store.insert(
        session_id="s1",
        fragment_type="decision",
        source_event="Stop",
        content="历史决策",
        metadata={"k": "v"},
    )
    rows = store.query(session_id="s1")
    assert len(rows) == 1
    assert rows[0]["content"] == "历史决策"


def test_internal_sources_include_prompt_judge():
    """INTERNAL_SOURCES 含 prompt-judge，防判断输出再被采集（反馈循环）。"""
    from jfox.prompts.service import INTERNAL_SOURCES

    assert "prompt-judge" in INTERNAL_SOURCES
    assert "gem-synth" in INTERNAL_SOURCES  # 历史标记继续过滤


def test_gem_synthesis_config_retired():
    """gem_synthesis 运行时配置退役：GlobalConfig 不再有该字段（兼容加载旧 JSON）。"""

    from jfox.global_config import GlobalConfig, GlobalConfigManager

    # 旧配置 JSON（含 gem_synthesis 节）能加载（忽略未知节，向后兼容）
    old_json = {
        "version": 1,
        "current_kb": "default",
        "gem_synthesis": {"enabled": True, "interval_minutes": 30},
    }
    cfg = GlobalConfig.from_dict(old_json)
    assert not hasattr(cfg, "gem_synthesis") or cfg.gem_synthesis is None

    # manager 不再提供 gem synthesis 访问
    assert not hasattr(GlobalConfigManager, "get_gem_synthesis_config")


def test_old_synthesis_db_untouched(tmp_path):
    """退役不触碰历史合成数据库文件。"""
    import sqlite3

    db = tmp_path / "gem_synth.db"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE synthesis_log (id INTEGER PRIMARY KEY, status TEXT)")
    conn.execute("INSERT INTO synthesis_log (status) VALUES ('success')")
    conn.commit()
    conn.close()

    import jfox  # noqa: F401 — 触发任何包级初始化

    conn = sqlite3.connect(db)
    rows = conn.execute("SELECT * FROM synthesis_log").fetchall()
    conn.close()
    assert rows == [(1, "success")]  # 数据原样
