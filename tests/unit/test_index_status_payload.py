"""#539 _index_status_payload 组装纯函数单测。"""

from jfox.cli import _index_status_payload


def test_payload_fields_and_none_state():
    vs = {"total_notes": 5, "persist_directory": "/tmp/x"}
    bm25 = {"indexed": 4, "version": 2, "index_path": "p", "index_exists": True}
    payload = _index_status_payload(vs, bm25, None)
    assert set(payload) == {"vector_store", "bm25_indexed", "last_rebuild"}
    assert payload["vector_store"] is vs
    assert payload["bm25_indexed"] == 4
    assert payload["last_rebuild"] is None


def test_payload_with_state():
    state = {"last_rebuild": "2026-10-09T21:00:00", "semantic": False, "notes": 7}
    payload = _index_status_payload({}, {"indexed": 7}, state)
    assert payload["bm25_indexed"] == 7
    assert payload["last_rebuild"] == "2026-10-09T21:00:00"


def test_payload_missing_indexed_key_defaults_zero():
    payload = _index_status_payload({}, {}, None)
    assert payload["bm25_indexed"] == 0
