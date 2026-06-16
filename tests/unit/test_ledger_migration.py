import json

from jfox.auto_summary.ledger import Ledger


def _write_ledger(path, sessions):
    path.write_text(json.dumps({"version": 1, "sessions": sessions}), encoding="utf-8")


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


def test_migration_skips_bare_key_conflicting_with_prefixed(tmp_path):
    """issue-4: 裸键迁移后与已有 claude: 前缀键冲突，保留 prefixed、跳过裸键"""
    f = tmp_path / "state.json"
    _write_ledger(
        f,
        {
            "abc": {
                "project": "p-bare",
                "processed_at": "2026-01-01T00:00:00",
                "status": "success",
                "note_id": "n-bare",
            },
            "claude:abc": {
                "project": "p-prefixed",
                "processed_at": "2026-01-02T00:00:00",
                "status": "skipped",
            },
        },
    )
    led = Ledger(path=f)
    entries = led.all_entries()
    assert "claude:abc" in entries
    assert entries["claude:abc"].project == "p-prefixed"  # 保留 prefixed
    assert "abc" not in entries  # 裸键迁移冲突被跳过
