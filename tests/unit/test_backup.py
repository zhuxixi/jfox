"""KB 备份/恢复测试（全 temp_kb + 临时 backup_root 沙箱，不碰真实 KB）。"""

import json
import tarfile

import pytest

# =============================================================================
# helpers
# =============================================================================


class _NoOpDaemonController:
    """测试用：不碰真实 daemon。"""

    def is_running(self) -> bool:
        return False

    def stop(self) -> None:
        pass

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


def test_restore_rolls_back_on_extract_failure(tmp_path, monkeypatch):
    """解压中途失败时，原始 KB 必须完好（rollback 把旁置态挪回，清理半成品）"""
    mgr = _make_manager(tmp_path)
    archive = mgr.backup()
    original = (tmp_path / "kb" / "notes" / "fleeting" / "a.md").read_text(encoding="utf-8")

    def _boom(snapshot):
        raise RuntimeError("模拟解压中途失败")

    monkeypatch.setattr(mgr, "_extract", _boom)
    with pytest.raises(RuntimeError):
        mgr.restore(archive, yes=True)
    # 原始 KB 完好（没有被半成品覆盖、旁置态已挪回）
    assert (tmp_path / "kb" / "notes" / "fleeting" / "a.md").read_text(encoding="utf-8") == original


def test_restore_aborts_when_daemon_wont_stop(tmp_path):
    """daemon 在跑但停不掉时，restore 必须中止、KB 未动"""
    from jfox.backup.manager import BackupManager

    class _StubbornDaemon:
        def is_running(self):
            return True

        def stop(self):
            raise RuntimeError("停不下来")

        def start(self):
            pass

    mgr_noop = _make_manager(tmp_path)
    archive = mgr_noop.backup()  # 合法快照（_make_manager 已建 kb + cfg）

    mgr = BackupManager(
        backup_root=tmp_path / "backups",
        kb_root=mgr_noop.kb_root,
        config_path=mgr_noop.config_path,
        retain=3,
        daemon_controller=_StubbornDaemon(),
    )
    with pytest.raises(RuntimeError):
        mgr.restore(archive, yes=True)
    # KB 原样未动（没被挪走、没被解压覆盖）
    assert (mgr_noop.kb_root / "notes" / "fleeting" / "a.md").read_text(
        encoding="utf-8"
    ) == "# A\nhello"


def test_safe_member_rejects_traversal_and_special_types():
    """_safe_member 拒绝 symlink/device/路径越界，只放行常规文件/目录"""
    import tarfile

    from jfox.backup.manager import BackupManager

    reg = tarfile.TarInfo("x")
    reg.type = tarfile.REGTYPE
    sym = tarfile.TarInfo("evil")
    sym.type = tarfile.SYMTYPE

    assert BackupManager._safe_member(sym, "ok") is False  # symlink 拒绝
    assert BackupManager._safe_member(reg, "../evil") is False  # .. 越界
    assert BackupManager._safe_member(reg, "/etc/passwd") is False  # 绝对路径
    assert BackupManager._safe_member(reg, "notes/a.md") is True  # 干净相对路径


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


# =============================================================================
# CR 防御补充：parse_time 段数 / from_dict null 防御 / 失败重试 / 路径穿越
# =============================================================================


def test_parse_time_rejects_bad_segments():
    """parse_time 拒绝无冒号 / 多段 / 非数字（避免 split 解包 ValueError）"""
    from jfox.backup.schedule import parse_time

    with pytest.raises(ValueError):
        parse_time("12")  # 无冒号
    with pytest.raises(ValueError):
        parse_time("12:30:45")  # 三段
    with pytest.raises(ValueError):
        parse_time("ab:cd")  # 非数字


def test_backup_config_from_dict_null_retain():
    """from_dict 对 retain=null / 非数字不崩，回退默认 7"""
    from jfox.global_config import BackupConfig

    assert BackupConfig.from_dict({"retain": None}).retain == 7
    assert BackupConfig.from_dict({"retain": "notanint"}).retain == 7
    assert BackupConfig.from_dict({"backup_root": 123}).backup_root is None  # 非 str → None


def test_should_run_now_retries_after_failure():
    """今日已跑但失败 → 允许重试（last_ok=False）；成功则跳过"""
    from datetime import datetime

    from jfox.backup.schedule import should_run_now

    now = datetime(2026, 7, 26, 12, 0)
    last = datetime(2026, 7, 26, 8, 0).isoformat()
    assert should_run_now("08:00", last, now=now, last_ok=False) is True
    assert should_run_now("08:00", last, now=now, last_ok=True) is False


def test_resolve_snapshot_rejects_traversal(tmp_path, monkeypatch):
    """相对快照名含 .. 逃逸 daily/ 应被拒（非零退出）"""
    from typer.testing import CliRunner

    from jfox.backup import cli as backup_cli
    from jfox.global_config import BackupConfig

    fake = _FakeGlobalMgr(BackupConfig(backup_root=str(tmp_path / "backups")))
    monkeypatch.setattr(backup_cli, "get_global_config_manager", lambda: fake)
    runner = CliRunner()
    r = runner.invoke(backup_cli.backup_app, ["verify", "../../etc/passwd"])
    assert r.exit_code != 0  # BadParameter → 非零退出
