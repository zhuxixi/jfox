import json

from jfox.auto_summary.ledger import Ledger


def _write_ledger(path, sessions):
    path.write_text(
        json.dumps({"version": 1, "sessions": sessions}), encoding="utf-8"
    )


def test_legacy_bare_key_migrated_to_claude_prefix(tmp_path):
    f = tmp_path / "state.json"
    _write_ledger(
        f,
        {
            "abc-123": {
                "project": "p",
                "processed_at": "2026-01-01T00:00:00",
                "status": "success",
                "note_id": "n1",
            }
        },
    )
    led = Ledger(path=f)
    assert "claude:abc-123" in led.all_entries()
    assert "abc-123" not in led.all_entries()
    assert led.is_done("claude:abc-123")


def test_prefixed_key_not_double_prefixed(tmp_path):
    f = tmp_path / "state.json"
    _write_ledger(
        f,
        {
            "kimi:xyz": {
                "project": "p",
                "processed_at": "2026-01-01T00:00:00",
                "status": "skipped",
            }
        },
    )
    led = Ledger(path=f)
    assert "kimi:xyz" in led.all_entries()
    assert "claude:kimi:xyz" not in led.all_entries()
