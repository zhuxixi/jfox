"""#539 index_state 状态文件读写单测（.zk/index_state.json）。"""

import json
from datetime import datetime
from pathlib import Path

from jfox.index_state import build_rebuild_state, load_index_state, save_index_state


class _CfgStub:
    """仅提供 zk_dir 属性的最小配置桩（鸭子类型）。"""

    def __init__(self, root: Path):
        self.zk_dir = root / ".zk"


def test_load_missing_returns_none(tmp_path):
    assert load_index_state(_CfgStub(tmp_path)) is None


def test_load_corrupt_json_returns_none(tmp_path):
    cfg = _CfgStub(tmp_path)
    cfg.zk_dir.mkdir(parents=True)
    (cfg.zk_dir / "index_state.json").write_text("{broken", encoding="utf-8")
    assert load_index_state(cfg) is None


def test_load_non_dict_returns_none(tmp_path):
    cfg = _CfgStub(tmp_path)
    cfg.zk_dir.mkdir(parents=True)
    (cfg.zk_dir / "index_state.json").write_text("[1, 2]", encoding="utf-8")
    assert load_index_state(cfg) is None


def test_save_then_load_roundtrip(tmp_path):
    cfg = _CfgStub(tmp_path)
    state = build_rebuild_state(semantic=False, notes=3, now=datetime(2026, 10, 9, 21, 0, 0))
    assert save_index_state(state, cfg) is True
    assert load_index_state(cfg) == state


def test_save_atomic_leaves_no_temp_files(tmp_path):
    cfg = _CfgStub(tmp_path)
    save_index_state(build_rebuild_state(semantic=True, notes=1), cfg)
    assert [p for p in cfg.zk_dir.iterdir() if p.suffix == ".tmp"] == []
    assert (
        json.loads((cfg.zk_dir / "index_state.json").read_text(encoding="utf-8"))["semantic"]
        is True
    )


def test_build_rebuild_state_shape():
    s = build_rebuild_state(semantic=True, notes=9, now=datetime(2026, 10, 9, 8, 0, 0))
    assert s == {"last_rebuild": "2026-10-09T08:00:00", "semantic": True, "notes": 9}
