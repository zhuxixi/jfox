"""KB 备份/恢复测试（全 temp_kb + 临时 backup_root 沙箱，不碰真实 KB）。"""

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
