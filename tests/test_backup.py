"""KB 备份/恢复测试（全 temp_kb + 临时 backup_root 沙箱，不碰真实 KB）。"""

import json
import tarfile

import pytest

# =============================================================================
# helpers
# =============================================================================


class _NoOpDaemonController:
    """测试用：不碰真实 daemon。"""

    def stop(self) -> bool:
        return False

    def start(self) -> None:
        pass


def _make_manager(tmp_path):
    """构造一个指向沙箱的 BackupManager（不碰真实 ~/.zettelkasten / daemon）。"""
    from jfox.backup.manager import BackupManager

    kb = tmp_path / "kb"
    (kb / "notes" / "fleeting").mkdir(parents=True)
    (kb / "notes" / "fleeting" / "a.md").write_text("# A\nhello", encoding="utf-8")
    cfg = tmp_path / ".zk_config.json"
    cfg.write_text(json.dumps({"default": "default"}), encoding="utf-8")
    return BackupManager(
        backup_root=tmp_path / "backups",
        kb_root=kb,
        config_path=cfg,
        retain=3,
        daemon_controller=_NoOpDaemonController(),
    )


def _manifest_path(archive):
    return archive.with_name(archive.name[: -len(".tar.gz")] + ".manifest.json")


# =============================================================================
# Task 1: BackupConfig + global_config 接线
# =============================================================================


def test_backup_config_defaults():
    from jfox.global_config import BackupConfig

    cfg = BackupConfig()
    assert cfg.enabled is False
    assert cfg.schedule_time == "08:00"
    assert cfg.retain == 7
    assert cfg.backup_root is None


def test_backup_config_roundtrip():
    from jfox.global_config import BackupConfig

    cfg = BackupConfig(enabled=True, schedule_time="03:30", retain=5, backup_root="/tmp/x")
    d = cfg.to_dict()
    assert d["enabled"] is True and d["schedule_time"] == "03:30"
    cfg2 = BackupConfig.from_dict(d)
    assert cfg2.schedule_time == "03:30" and cfg2.retain == 5


def test_backup_config_rejects_bad_time():
    from jfox.global_config import BackupConfig

    cfg = BackupConfig(schedule_time="99:99")  # 非法时间回退默认
    assert cfg.schedule_time == "08:00"


def test_global_config_has_backup_section():
    from jfox.global_config import GlobalConfig

    gc = GlobalConfig()
    assert hasattr(gc, "backup")
    d = gc.to_dict()
    assert "backup" in d
    gc2 = GlobalConfig.from_dict(d)
    assert gc2.backup.schedule_time == "08:00"


# =============================================================================
# Task 2: BackupManager 核心（tar + sha256 + 校验 + 轮转 + quiesce）
# =============================================================================


def test_backup_creates_archive_and_manifest(tmp_path):
    mgr = _make_manager(tmp_path)
    archive = mgr.backup()
    assert archive.exists()
    assert archive.name.endswith(".tar.gz")
    mpath = _manifest_path(archive)
    assert mpath.exists()
    data = json.loads(mpath.read_text(encoding="utf-8"))
    assert len(data["archive_sha256"]) == 64
    assert data["archive"] == archive.name
    assert data["file_count"] >= 1


def test_backup_archive_is_valid_tar_with_notes(tmp_path):
    mgr = _make_manager(tmp_path)
    archive = mgr.backup()
    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
    assert any("zettelkasten" in n for n in names)
    assert any("zk_config.json" in n for n in names)


def test_retention_rotates(tmp_path):
    mgr = _make_manager(tmp_path)  # retain=3
    for _ in range(5):
        mgr.backup()  # 同秒内靠唯一序号保证文件名不同
    archives = list((tmp_path / "backups" / "daily").glob("jfox-*.tar.gz"))
    assert len(archives) == 3  # 只留 retain 份


def test_backup_quiesce_flag_resets(tmp_path):
    from jfox.backup.manager import BackupCoordinator

    assert BackupCoordinator.is_running() is False
    mgr = _make_manager(tmp_path)
    mgr.backup()
    assert BackupCoordinator.is_running() is False  # 备份结束后标志复位


def test_quiesce_makes_siblings_skip():
    """BackupCoordinator.is_running() 为 True 时，模拟兄弟 loop 的检查应跳过"""
    from jfox.backup.manager import BackupCoordinator

    def fake_sibling_tick():
        if BackupCoordinator.is_running():
            return "skip"
        return "write"

    assert fake_sibling_tick() == "write"
    with BackupCoordinator.quiesce():
        assert fake_sibling_tick() == "skip"
    assert fake_sibling_tick() == "write"


# =============================================================================
# Task 3: 可逆恢复
# =============================================================================


def test_restore_roundtrip(tmp_path):
    mgr = _make_manager(tmp_path)
    archive = mgr.backup()
    # 破坏当前 KB
    (tmp_path / "kb" / "notes" / "fleeting" / "a.md").unlink()
    assert not (tmp_path / "kb" / "notes" / "fleeting" / "a.md").exists()
    # 恢复（沙箱内 _maybe_stop_daemon 返回 False，不实际停启 daemon）
    mgr.restore(archive, yes=True)
    assert (tmp_path / "kb" / "notes" / "fleeting" / "a.md").read_text(
        encoding="utf-8"
    ) == "# A\nhello"
    # 恢复前保险存在
    assert list((tmp_path / "kb").parent.glob("kb.pre-restore-*"))


def test_restore_aborts_on_corrupt_archive(tmp_path):
    mgr = _make_manager(tmp_path)
    archive = mgr.backup()
    # 篡改归档内容（sha256 对不上）
    archive.write_bytes(archive.read_bytes() + b"\x00corrupt")
    (tmp_path / "kb" / "notes" / "fleeting" / "a.md").write_text("CURRENT", encoding="utf-8")
    with pytest.raises(Exception):
        mgr.restore(archive, yes=True)
    # 当前态未被破坏
    assert (tmp_path / "kb" / "notes" / "fleeting" / "a.md").read_text(
        encoding="utf-8"
    ) == "CURRENT"


# =============================================================================
# Task 4: schedule 定点判断
# =============================================================================


def test_should_run_now_due():
    from datetime import datetime

    from jfox.backup.schedule import should_run_now

    # 现在 08:30，调度 08:00，今天没跑过 → 该跑
    now = datetime(2026, 7, 26, 8, 30)
    assert should_run_now("08:00", last_run_ts=None, now=now) is True


def test_should_run_now_already_done_today():
    from datetime import datetime

    from jfox.backup.schedule import should_run_now

    now = datetime(2026, 7, 26, 9, 0)
    last = datetime(2026, 7, 26, 8, 0).isoformat()  # 今天已跑
    assert should_run_now("08:00", last_run_ts=last, now=now) is False


def test_should_run_now_before_time():
    from datetime import datetime

    from jfox.backup.schedule import should_run_now

    now = datetime(2026, 7, 26, 7, 0)  # 还没到 08:00
    assert should_run_now("08:00", last_run_ts=None, now=now) is False


def test_should_run_now_yesterday_last_run():
    from datetime import datetime

    from jfox.backup.schedule import should_run_now

    now = datetime(2026, 7, 26, 8, 30)
    last = datetime(2026, 7, 25, 8, 0).isoformat()  # 昨天跑的
    assert should_run_now("08:00", last_run_ts=last, now=now) is True


# =============================================================================
# Task 6: CLI
# =============================================================================


class _FakeGlobalMgr:
    """假全局配置管理器，避免 CLI 测试触碰真实 ~/.zk_config.json。"""

    def __init__(self, cfg=None):
        from jfox.global_config import BackupConfig

        self._cfg = cfg or BackupConfig()
        self.updates = {}

    def get_backup_config(self):
        return self._cfg

    def update_backup_config(self, **changes):
        self.updates.update(changes)
        return True


def test_backup_enable_writes_config(monkeypatch):
    from typer.testing import CliRunner

    from jfox.backup import cli as backup_cli

    fake = _FakeGlobalMgr()
    monkeypatch.setattr(backup_cli, "get_global_config_manager", lambda: fake)
    runner = CliRunner()
    r = runner.invoke(backup_cli.backup_app, ["enable", "--time", "03:00", "--retain", "5"])
    assert r.exit_code == 0, r.stdout
    assert fake.updates == {"enabled": True, "schedule_time": "03:00", "retain": 5}


def test_backup_status_runs(monkeypatch):
    from typer.testing import CliRunner

    from jfox.backup import cli as backup_cli
    from jfox.global_config import BackupConfig

    fake = _FakeGlobalMgr(BackupConfig(enabled=True, schedule_time="08:00", retain=7))
    monkeypatch.setattr(backup_cli, "get_global_config_manager", lambda: fake)
    runner = CliRunner()
    r = runner.invoke(backup_cli.backup_app, ["status"])
    assert r.exit_code == 0, r.stdout
    assert "08:00" in r.stdout


def test_backup_disable_writes_config(monkeypatch):
    from typer.testing import CliRunner

    from jfox.backup import cli as backup_cli

    fake = _FakeGlobalMgr()
    monkeypatch.setattr(backup_cli, "get_global_config_manager", lambda: fake)
    runner = CliRunner()
    r = runner.invoke(backup_cli.backup_app, ["disable"])
    assert r.exit_code == 0, r.stdout
    assert fake.updates == {"enabled": False}
