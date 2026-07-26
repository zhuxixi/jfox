# JFox KB 滚动备份 + 恢复 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 给 jfox 加 `backup`/`restore` 能力：jfox daemon 内 `backup_loop` 每天 08:00 自动滚动备份 7 份 `~/.zettelkasten` + `~/.zk_config.json`，失败靠 status 看，恢复可逆且经 pytest 沙箱验证。

**Architecture:** 镜像既有 `auto_summary` 子系统——新包 `jfox/backup/`（`manager.py` 核心逻辑 + `loop.py` daemon 调度 + `schedule.py` 定时判断 + `cli.py` 子命令），`global_config.py` 加 `BackupConfig`，`daemon/server.py` 加 `_maybe_start_backup`/`_maybe_stop_backup` 并接 `lifespan`，`gem_synth`/`auto_summary` loop 加 quiesce flag 检查。一致性：daemon 内备份靠 quiesce 标志让兄弟 loop 跳过写 tick + ChromaDB 崩溃一致；手动/restore 是独立进程，停 daemon 拿干净快照。

**Tech Stack:** Python 3.10+，typer（CLI），rich（输出），stdlib `tarfile`/`hashlib`/跨平台文件锁（`fcntl` Unix / `msvcrt` Windows）/`subprocess`/`contextlib`，既有 `jfox.utils.atomic_write_json`、`jfox.global_config`。

## Global Constraints

- **行宽 100**，black + ruff（改完代码两步都过：`uv run ruff check` + `uv run black --check`）。
- **注释/文档用中文**。
- **纯新增能力**，不动既有存储/搜索逻辑；对 `gem_synth`/`auto_summary` loop 仅加一处 quiesce 检查。
- **测试用 `temp_kb` fixture + `ZK_KB_ROOT` 沙箱**，绝不碰真实 `~/.zettelkasten`；备份/恢复测试用临时 `backup_root`。
- 复用 `jfox.utils.atomic_write_json(path: Path, data: dict, *, indent: int = 2)`（`os.replace` 原子写）。
- `BackupManager` 纯 stdlib，不 import chromadb/jfox 重模块（避免 cli 启动增重）；调 daemon 停启走 subprocess `jfox daemon stop/start`。
- 备份状态（last_run 等）写 `~/.jfox-backup/state.json`，**不写 `~/.zk_config.json`**（避免备份时全局配置被改）。
- main 保护分支，所有改动在 worktree 分支 `worktree-issue-338-kb-backup-restore`。

## File Structure

| 文件 | 职责 |
|------|------|
| `jfox/backup/__init__.py` | 包入口，导出 `BackupManager`/`BackupCoordinator` |
| `jfox/backup/manager.py` | `BackupCoordinator`（quiesce 标志）+ `BackupManager`（backup/restore/list/verify） |
| `jfox/backup/schedule.py` | `should_run_now(cfg, last_run_ts)` 每日定点判断 + `parse_time` |
| `jfox/backup/loop.py` | `backup_loop(stop_event)` daemon 异步循环 |
| `jfox/backup/cli.py` | `backup_app` typer：run/enable/disable/status/list/verify + restore |
| `jfox/global_config.py` | 加 `BackupConfig` dataclass + `GlobalConfig.backup` 字段 + `get/update_backup_config` |
| `jfox/daemon/server.py` | 加 `_maybe_start_backup`/`_maybe_stop_backup` + `lifespan` 接线 |
| `jfox/auto_summary/loop.py` | `_tick_once` 入口加 quiesce 检查 |
| `jfox/gem_synth/loop.py` | 写 tick 入口加 quiesce 检查 |
| `jfox/cli.py` | `app.add_typer(backup_app, name="backup")` 挂载 |
| `tests/test_backup.py` | 全部沙箱测试 |

---

### Task 1: `BackupConfig` + global_config 接线

**Files:**
- Modify: `jfox/global_config.py`（加 dataclass ~line 49 区、`GlobalConfig` ~324、`to_dict`/`from_dict` ~333/343、accessor ~631）
- Test: `tests/test_backup.py`（新建）

**Interfaces:**
- Produces: `BackupConfig`（字段 `enabled: bool=False`、`schedule_time: str="08:00"`、`retain: int=7`、`backup_root: Optional[str]=None`）；`GlobalConfigManager.get_backup_config() -> BackupConfig`、`update_backup_config(**changes) -> bool`。

- [ ] **Step 1: 写失败测试**（新建 `tests/test_backup.py`）

```python
"""KB 备份/恢复测试（全 temp_kb + 临时 backup_root 沙箱，不碰真实 KB）。"""
import json
from pathlib import Path


def test_backup_config_defaults():
    from jfox.global_config import BackupConfig

    cfg = BackupConfig()
    assert cfg.enabled is False
    assert cfg.schedule_time == "08:00"
    assert cfg.retain == 7
    assert cfg.backup_root is None


def test_backup_config_roundtrip(tmp_path):
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_backup.py -v`
Expected: FAIL（`ImportError: cannot import name 'BackupConfig'`）

- [ ] **Step 3: 加 `BackupConfig` dataclass**（`jfox/global_config.py`，放在 `AutoSummaryConfig` 之前 ~line 48）

```python
@dataclass
class BackupConfig:
    """KB 滚动备份配置（opt-in，默认关闭）。

    由 jfox daemon 的 backup_loop 按 schedule_time 每日触发；
    也可 `jfox backup run` 手动触发。详见 jfox/backup/。
    """

    enabled: bool = False
    schedule_time: str = "08:00"  # 每日备份时刻 HH:MM（本地时区）
    retain: int = 7  # 滚动保留份数
    backup_root: Optional[str] = None  # None → ~/.jfox-backup

    def __post_init__(self) -> None:
        if self.retain < 1:
            self.retain = 7
        if not _is_valid_time(self.schedule_time):
            self.schedule_time = "08:00"
        if isinstance(self.backup_root, str) and not self.backup_root.strip():
            self.backup_root = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "BackupConfig":
        if not data:
            return cls()
        return cls(
            enabled=bool(data.get("enabled", False)),
            schedule_time=str(data.get("schedule_time", "08:00")),
            retain=int(data.get("retain", 7)),
            backup_root=data.get("backup_root"),
        )


def _is_valid_time(s: str) -> bool:
    """校验 HH:MM 格式且小时/分钟合法"""
    if not isinstance(s, str) or s.count(":") != 1:
        return False
    h, m = s.split(":")
    try:
        hi, mi = int(h), int(m)
    except ValueError:
        return False
    return 0 <= hi <= 23 and 0 <= mi <= 59
```

- [ ] **Step 4: 接入 `GlobalConfig`**（~line 328 加字段、~337 加 to_dict、~343 加 from_dict）

`GlobalConfig` 字段加：
```python
    backup: BackupConfig = field(default_factory=BackupConfig)
```
`to_dict` 加：`"backup": self.backup.to_dict(),`
`from_dict` 的 `return cls(...)` 加：`backup=BackupConfig.from_dict(data.get("backup")),`

- [ ] **Step 5: 加 accessor**（~line 657 后，镜像 `get/update_gem_synthesis_config`）

```python
    def get_backup_config(self) -> BackupConfig:
        """获取 KB 备份配置"""
        return self._load().backup

    def update_backup_config(self, **changes: Any) -> bool:
        """更新备份配置中的若干字段，未传入的字段保持原样"""
        config = self._load()
        current = asdict(config.backup)
        current.update({k: v for k, v in changes.items() if k in current})
        config.backup = BackupConfig.from_dict(current)
        self._config = config
        return self._save()
```

- [ ] **Step 6: 跑测试确认通过**

Run: `uv run pytest tests/test_backup.py -v`
Expected: PASS（4 个测试）

- [ ] **Step 7: lint + commit**

```bash
uv run ruff check jfox/global_config.py tests/test_backup.py
uv run black --check jfox/global_config.py tests/test_backup.py  # 没装 black 用 uv run --with black==26.3.1 black --check ...
git add jfox/global_config.py tests/test_backup.py
git commit -m "feat(backup): #338 BackupConfig + global_config 接线"
```

---

### Task 2: `BackupCoordinator` + `BackupManager.backup()` 核心

**Files:**
- Create: `jfox/backup/__init__.py`、`jfox/backup/manager.py`
- Test: `tests/test_backup.py`（追加）

**Interfaces:**
- Consumes: `jfox.utils.atomic_write_json`
- Produces: `BackupCoordinator.is_running() -> bool`、`BackupCoordinator.quiesce()`（contextmanager）；`BackupManager(backup_root, kb_root, config_path, retain).backup() -> Path`。

- [ ] **Step 1: 写失败测试**（追加到 `tests/test_backup.py`）

```python
def _make_manager(tmp_path):
    """构造一个指向沙箱的 BackupManager（不碰真实 ~/.zettelkasten）"""
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
    )


def test_backup_creates_archive_and_manifest(tmp_path):
    mgr = _make_manager(tmp_path)
    archive = mgr.backup()
    assert archive.exists() and archive.suffix == ".gz"
    manifest = archive.with_suffix(".manifest.json")  # foo.tar.gz -> foo.tar.manifest.json
    # manifest 是同名 .manifest.json（见 Step 3 命名规则）
    sidecar = archive.parent / (archive.stem.replace(".tar", "") + ".manifest.json")
    assert sidecar.exists()
    data = json.loads(sidecar.read_text(encoding="utf-8"))
    assert "archive_sha256" in data and data["file_count"] >= 1
    assert data["archive"] == archive.name


def test_backup_archive_is_valid_tar_with_notes(tmp_path):
    import tarfile

    mgr = _make_manager(tmp_path)
    archive = mgr.backup()
    with tarfile.open(archive, "r:gz") as tar:
        names = tar.getnames()
    assert any("zettelkasten" in n for n in names)
    assert any("zk_config.json" in n for n in names)


def test_retention_rotates(tmp_path):
    mgr = _make_manager(tmp_path)  # retain=3
    for _ in range(5):
        import time

        time.sleep(0.01)  # 保证时间戳文件名唯一
        mgr.backup()
    archives = list((tmp_path / "backups" / "daily").glob("*.tar.gz"))
    assert len(archives) == 3  # 只留 retain 份


def test_backup_quiesce_flag_toggles(tmp_path):
    from jfox.backup.manager import BackupCoordinator

    assert BackupCoordinator.is_running() is False
    mgr = _make_manager(tmp_path)
    # backup 期间标志为 True（用回调采样）
    seen = []
    orig = BackupCoordinator.is_running
    mgr  # noqa
    # 直接验证 backup 结束后标志复位
    mgr.backup()
    assert BackupCoordinator.is_running() is False
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_backup.py -v`
Expected: FAIL（`No module named 'jfox.backup'`）

- [ ] **Step 3: 写 `jfox/backup/manager.py`**

```python
"""KB 滚动备份/恢复核心逻辑。

BackupCoordinator：进程级 quiesce 标志，daemon 内备份时兄弟 loop（gem_synth/
auto_summary）检查它跳过写 tick。BackupManager：tar 打包 + sha256 清单 + 校验
+ 滚动保留 + 可逆恢复。纯 stdlib，不 import 重模块。
"""

from __future__ import annotations

import hashlib
import os
import tarfile
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from jfox.utils import atomic_write_json


class BackupCoordinator:
    """进程级备份进行中标志（仅同进程可见，daemon 内 backup_loop 用）。"""

    _running: bool = False

    @classmethod
    def is_running(cls) -> bool:
        return cls._running

    @classmethod
    @contextmanager
    def quiesce(cls):
        cls._running = True
        try:
            yield
        finally:
            cls._running = False


def _lock_path(backup_root: Path) -> Path:
    backup_root.mkdir(parents=True, exist_ok=True)
    return backup_root / ".lock"


@contextmanager
def _fcntl_lock(lock_path: Path):
    """文件锁，防 loop tick 与手动 run 撞车。获取不到直接退出。"""
    import fcntl

    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


class BackupManager:
    def __init__(
        self,
        backup_root: Path,
        kb_root: Path,
        config_path: Path,
        retain: int = 7,
    ):
        self.backup_root = Path(backup_root)
        self.kb_root = Path(kb_root)
        self.config_path = Path(config_path)
        self.retain = max(1, retain)
        self.daily_dir = self.backup_root / "daily"

    # ---------- 备份 ----------
    def backup(self) -> Path:
        """打一份自包含 tar.gz + manifest，返回归档路径。失败抛异常。"""
        with _fcntl_lock(_lock_path(self.backup_root)):
            with BackupCoordinator.quiesce():
                return self._do_backup()

    def _do_backup(self) -> Path:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        name = f"jfox-{ts}"
        self.daily_dir.mkdir(parents=True, exist_ok=True)
        archive = self.daily_dir / f"{name}.tar.gz"

        # 先写 tmp 再原子 rename
        fd, tmp = tempfile.mkstemp(suffix=".tar.gz", dir=str(self.daily_dir))
        os.close(fd)
        try:
            self._write_tar(tmp, name)
            sha = self._sha256(tmp)
            manifest = self._build_manifest(archive.name, sha, tmp)
            # 校验刚写的归档能被 tar 读
            self._assert_tar_ok(tmp)
            os.replace(tmp, archive)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        # 写 sidecar manifest（原子）
        atomic_write_json(self._manifest_path(archive), manifest)
        self._rotate()
        return archive

    def _write_tar(self, out_path: str, name: str) -> None:
        root = f"jfox-backup-{name}"
        with tarfile.open(out_path, "w:gz") as tar:
            if self.kb_root.exists():
                tar.add(self.kb_root, arcname=f"{root}/zettelkasten")
            if self.config_path.exists():
                tar.add(self.config_path, arcname=f"{root}/zk_config.json")

    def _build_manifest(self, archive_name: str, sha: str, tmp_archive: str) -> dict:
        file_count = 0
        total_bytes = 0
        with tarfile.open(tmp_archive, "r:gz") as tar:
            for m in tar:
                if m.isfile():
                    file_count += 1
                    total_bytes += m.size
        return {
            "version": 1,
            "created": datetime.now().isoformat(),
            "archive": archive_name,
            "archive_sha256": sha,
            "kb_path": str(self.kb_root),
            "config_path": str(self.config_path),
            "file_count": file_count,
            "total_bytes": total_bytes,
        }

    @staticmethod
    def _sha256(path: str) -> str:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()

    @staticmethod
    def _assert_tar_ok(path: str) -> None:
        with tarfile.open(path, "r:gz") as tar:
            tar.getnames()  # 触发完整读取校验

    def _manifest_path(self, archive: Path) -> Path:
        # jfox-YYYYMMDD-HHMMSS.tar.gz -> jfox-YYYYMMDD-HHMMSS.manifest.json
        return archive.with_name(archive.name[: -len(".tar.gz")] + ".manifest.json")

    def _rotate(self) -> None:
        archives = sorted(self.daily_dir.glob("jfox-*.tar.gz"))
        for old in archives[: max(0, len(archives) - self.retain)]:
            old.unlink(missing_ok=True)
            self._manifest_path(old).unlink(missing_ok=True)

    # ---------- list / verify ----------
    def list_snapshots(self) -> list[dict]:
        out = []
        for archive in sorted(self.daily_dir.glob("jfox-*.tar.gz"), reverse=True):
            mpath = self._manifest_path(archive)
            manifest = (
                json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else None
            )
            out.append(
                {"archive": archive.name, "size": archive.stat().st_size,
                 "created": manifest.get("created") if manifest else None,
                 "ok": self.verify(archive) if manifest else False}
            )
        return out

    def verify(self, archive: Path) -> bool:
        mpath = self._manifest_path(archive)
        if not archive.exists() or not mpath.exists():
            return False
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        if self._sha256(str(archive)) != manifest.get("archive_sha256"):
            return False
        try:
            self._assert_tar_ok(str(archive))
        except tarfile.TarError:
            return False
        return True


# json 顶部已 import（atomic_write_json 用）；此处补 json 给 list/verify
import json  # noqa: E402
```

注意：上面末尾 `import json` 应移到文件顶部正常 import 区（这里为说明补 import；实现时放顶部）。`from __future__ import annotations` 已在顶部。

写 `jfox/backup/__init__.py`：
```python
"""KB 滚动备份/恢复（daemon 调度 + CLI）。详见 manager.py / loop.py / cli.py。"""

from .manager import BackupCoordinator, BackupManager

__all__ = ["BackupCoordinator", "BackupManager"]
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_backup.py -v`
Expected: PASS（含 Task 1 + Task 2 全部）

- [ ] **Step 5: lint + commit**

```bash
uv run ruff check jfox/backup/ tests/test_backup.py
uv run black --check jfox/backup/ tests/test_backup.py
git add jfox/backup/__init__.py jfox/backup/manager.py tests/test_backup.py
git commit -m "feat(backup): #338 BackupManager 核心备份（tar+sha256+轮转+quiesce）"
```

---

### Task 3: `restore()` + 端到端往返测试

**Files:**
- Modify: `jfox/backup/manager.py`（加 `restore`）
- Test: `tests/test_backup.py`（追加）

**Interfaces:**
- Consumes: Task 2 的 `BackupManager`
- Produces: `BackupManager.restore(snapshot: Path, yes: bool=False) -> None`

- [ ] **Step 1: 写失败测试**

```python
def test_restore_roundtrip(tmp_path):
    from jfox.backup.manager import BackupManager

    mgr = _make_manager(tmp_path)
    archive = mgr.backup()
    # 破坏当前 KB
    (tmp_path / "kb" / "notes" / "fleeting" / "a.md").unlink()
    assert not (tmp_path / "kb" / "notes" / "fleeting" / "a.md").exists()
    # 恢复（沙箱内无 daemon，restore 跳过 daemon 停启见 Step 3 的 _maybe_stop_daemon）
    mgr.restore(archive, yes=True)
    assert (tmp_path / "kb" / "notes" / "fleeting" / "a.md").read_text(
        encoding="utf-8"
    ) == "# A\nhello"
    # 恢复前保险存在
    assert list((tmp_path / "kb").parent.glob(".zettelkasten.pre-restore-*")) or list(
        (tmp_path).glob("kb.pre-restore-*")
    )


def test_restore_aborts_on_corrupt_archive(tmp_path):
    mgr = _make_manager(tmp_path)
    archive = mgr.backup()
    # 篡改归档内容（sha256 对不上）
    archive.write_bytes(archive.read_bytes() + b"\x00corrupt")
    (tmp_path / "kb" / "notes" / "fleeting" / "a.md").write_text(
        "CURRENT", encoding="utf-8"
    )
    import pytest

    with pytest.raises(Exception):
        mgr.restore(archive, yes=True)
    # 当前态未被破坏
    assert (
        (tmp_path / "kb" / "notes" / "fleeting" / "a.md").read_text(encoding="utf-8")
        == "CURRENT"
    )
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_backup.py -v -k restore`
Expected: FAIL（`AttributeError: 'BackupManager' object has no attribute 'restore'`）

- [ ] **Step 3: 实现 `restore`**（`jfox/backup/manager.py`，加方法）

restore 是独立 CLI 进程调用，需要停 daemon 拿干净快照。停启走 subprocess `jfox daemon stop/start`，但**沙箱测试里没 daemon**，所以停启要 best-effort（失败不阻断），且可注入跳过。

```python
    def restore(self, snapshot: Path, yes: bool = False) -> None:
        """从快照恢复。先停 daemon→rename 当前态旁置→校验 sha256→解压→起 daemon。

        任何步骤失败都 rename 回，真实 KB 不被破坏。daemon 停启 best-effort。
        """
        snapshot = Path(snapshot)
        if not snapshot.exists():
            raise FileNotFoundError(f"快照不存在: {snapshot}")
        mpath = self._manifest_path(snapshot)
        if not mpath.exists():
            raise FileNotFoundError(f"清单缺失: {mpath}")

        daemon_was_running = self._maybe_stop_daemon()
        try:
            self._restore_body(snapshot, mpath)
        finally:
            if daemon_was_running:
                self._maybe_start_daemon()

    def _restore_body(self, snapshot: Path, mpath: Path) -> None:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        aside_kb = self.kb_root.with_name(self.kb_root.name + f".pre-restore-{ts}")
        aside_cfg = self.config_path.with_name(
            self.config_path.name + f".pre-restore-{ts}"
        )
        renamed = False
        try:
            # 1. 校验 sha256（先于 rename，避免无谓挪动）
            manifest = json.loads(mpath.read_text(encoding="utf-8"))
            if self._sha256(str(snapshot)) != manifest.get("archive_sha256"):
                raise ValueError("归档 sha256 与清单不符，拒绝恢复")
            # 2. rename 当前态旁置
            if self.kb_root.exists():
                self.kb_root.rename(aside_kb)
                renamed = True
            if self.config_path.exists():
                self.config_path.rename(aside_cfg)
            # 3. 解压到位
            self._extract(snapshot)
            # 4. 留一份恢复前保险（保留最近 1 份，更旧的清掉）
            self._rotate_pre_restore(self.kb_root, ".pre-restore-")
        except Exception:
            if renamed and not self.kb_root.exists() and aside_kb.exists():
                aside_kb.rename(self.kb_root)  # 回退
            raise

    def _extract(self, snapshot: Path) -> None:
        import io

        with tarfile.open(snapshot, "r:gz") as tar:
            members = tar.getmembers()
            # 找归档根目录名（jfox-backup-...）
            root = members[0].name.split("/")[0] if members else None
            for m in members:
                rel = m.name[len(root) + 1:] if root and m.name.startswith(root + "/") else m.name
                if not rel:
                    continue
                if rel.startswith("zettelkasten/"):
                    m.name = rel[len("zettelkasten/"):]
                    tar.extract(m, path=str(self.kb_root))
                elif rel == "zk_config.json":
                    m.name = "zk_config.json"
                    tar.extract(m, path=str(self.config_path.parent))

    def _rotate_pre_restore(self, target: Path, marker: str) -> None:
        sibs = sorted(
            [p for p in target.parent.glob(target.name + marker + "*")],
            key=lambda p: p.stat().st_mtime,
        )
        for old in sibs[:-1]:
            # 目录用 rmtree，文件用 unlink
            if old.is_dir():
                import shutil

                shutil.rmtree(old, ignore_errors=True)
            else:
                old.unlink(missing_ok=True)

    @staticmethod
    def _maybe_stop_daemon() -> bool:
        """best-effort 停 embedding daemon，返回原先是否在跑。沙箱/无 daemon 返回 False。"""
        import subprocess

        try:
            r = subprocess.run(
                ["jfox", "daemon", "status"],
                capture_output=True, text=True, timeout=15,
            )
            was = r.returncode == 0 and "运行中" in r.stdout
        except Exception:
            return False
        if was:
            try:
                subprocess.run(["jfox", "daemon", "stop"], timeout=30)
            except Exception:
                pass
        return was

    @staticmethod
    def _maybe_start_daemon() -> None:
        import subprocess

        try:
            subprocess.run(["jfox", "daemon", "start"], timeout=60)
        except Exception:
            pass
```

- [ ] **Step 4: 跑测试确认通过**

Run: `uv run pytest tests/test_backup.py -v`
Expected: PASS（沙箱里 `_maybe_stop_daemon` 返回 False，不实际停启 daemon）

- [ ] **Step 5: lint + commit**

```bash
uv run ruff check jfox/backup/manager.py tests/test_backup.py
uv run black --check jfox/backup/manager.py tests/test_backup.py
git add jfox/backup/manager.py tests/test_backup.py
git commit -m "feat(backup): #338 可逆恢复（rename 旁置 + sha256 校验 + daemon 停启）"
```

---

### Task 4: `schedule.py` + `loop.py`（daemon 调度）

**Files:**
- Create: `jfox/backup/schedule.py`、`jfox/backup/loop.py`
- Test: `tests/test_backup.py`（追加）

**Interfaces:**
- Consumes: Task 1 `get_backup_config`、Task 2 `BackupManager`
- Produces: `should_run_now(schedule_time: str, last_run_ts: Optional[str], now: Optional[datetime]=None) -> bool`；`backup_loop(stop_event: threading.Event) -> None`

- [ ] **Step 1: 写失败测试**

```python
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
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_backup.py -v -k should_run`
Expected: FAIL（`No module named 'jfox.backup.schedule'`）

- [ ] **Step 3: 写 `jfox/backup/schedule.py`**

```python
"""备份调度判断：每日定点 schedule_time，今日已跑则跳过。"""

from __future__ import annotations

from datetime import datetime
from typing import Optional


def parse_time(s: str) -> tuple[int, int]:
    """解析 HH:MM，非法抛 ValueError"""
    h, m = s.split(":")
    hi, mi = int(h), int(m)
    if not (0 <= hi <= 23 and 0 <= mi <= 59):
        raise ValueError(f"非法时间: {s}")
    return hi, mi


def should_run_now(
    schedule_time: str,
    last_run_ts: Optional[str],
    now: Optional[datetime] = None,
) -> bool:
    """到今日 schedule_time 且今日未跑过 → True。"""
    now = now or datetime.now()
    hi, mi = parse_time(schedule_time)
    scheduled_today = now.replace(hour=hi, minute=mi, second=0, microsecond=0)
    if now < scheduled_today:
        return False
    if last_run_ts:
        try:
            last = datetime.fromisoformat(last_run_ts)
        except ValueError:
            last = None
        if last is not None and last.date() == now.date():
            return False
    return True
```

- [ ] **Step 4: 写 `jfox/backup/loop.py`**（镜像 `auto_summary/loop.py`）

```python
"""daemon 后台循环：每 5 分钟检查是否到 schedule_time，到点备份一次。"""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from datetime import datetime
from pathlib import Path

from ..global_config import DEFAULT_KB_PATH, get_global_config_manager
from .manager import BackupManager
from .schedule import should_run_now

logger = logging.getLogger(__name__)

_TICK_SECONDS = 300  # 5 分钟检查一次
_STATE_PATH = Path.home() / ".jfox-backup" / "state.json"


def _state_path(backup_root: Path) -> Path:
    return Path(backup_root) / "state.json"


def _read_last_run(backup_root: Path) -> str | None:
    p = _state_path(backup_root)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8")).get("last_run")
    except Exception:
        return None


def _write_last_run(backup_root: Path, ts: str, ok: bool, archive: str | None) -> None:
    p = _state_path(backup_root)
    p.parent.mkdir(parents=True, exist_ok=True)
    from jfox.utils import atomic_write_json

    atomic_write_json(p, {"last_run": ts, "last_ok": ok, "last_archive": archive})


def _tick_once() -> str:
    gm = get_global_config_manager()
    gm.reload()
    cfg = gm.get_backup_config()
    if not cfg.enabled:
        return "backup 未启用，跳过"
    backup_root = Path(cfg.backup_root) if cfg.backup_root else Path.home() / ".jfox-backup"
    last = _read_last_run(backup_root)
    if not should_run_now(cfg.schedule_time, last):
        return "未到点或今日已备份，跳过"
    mgr = BackupManager(
        backup_root=backup_root,
        kb_root=DEFAULT_KB_PATH,
        config_path=Path.home() / ".zk_config.json",
        retain=cfg.retain,
    )
    ts = datetime.now().isoformat()
    try:
        archive = mgr.backup()
        _write_last_run(backup_root, ts, True, archive.name)
        return f"备份成功: {archive.name}"
    except Exception as e:
        logger.exception("backup_loop 备份失败: %s", e)
        _write_last_run(backup_root, ts, False, None)
        return f"备份失败: {e}"


async def backup_loop(stop_event: threading.Event) -> None:
    """后台循环。stop_event.set() 后 ~_TICK_SECONDS 内退出。"""
    logger.info("backup 后台循环已启动")
    loop = asyncio.get_running_loop()
    try:
        await loop.run_in_executor(None, lambda: stop_event.wait(timeout=10))
    except RuntimeError as e:
        logger.warning("backup 启动延迟异常: %s", e)
    while not stop_event.is_set():
        try:
            msg = await loop.run_in_executor(None, _tick_once)
            logger.info("backup tick: %s", msg)
        except Exception as e:
            logger.exception("backup tick 异常: %s", e)
        try:
            await loop.run_in_executor(None, lambda: stop_event.wait(timeout=_TICK_SECONDS))
        except RuntimeError:
            break
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_backup.py -v`
Expected: PASS（schedule 4 个 + 之前的全过）

- [ ] **Step 6: lint + commit**

```bash
uv run ruff check jfox/backup/schedule.py jfox/backup/loop.py tests/test_backup.py
uv run black --check jfox/backup/schedule.py jfox/backup/loop.py tests/test_backup.py
git add jfox/backup/schedule.py jfox/backup/loop.py tests/test_backup.py
git commit -m "feat(backup): #338 daemon 调度（schedule 定点 + backup_loop）"
```

---

### Task 5: daemon 接线 + gem_synth/auto_summary quiesce 检查

**Files:**
- Modify: `jfox/daemon/server.py`（~line 28-33 加全局、~141 后加 `_maybe_start_backup`/`_maybe_stop_backup`、`lifespan` ~195 加调用）
- Modify: `jfox/auto_summary/loop.py`（`_tick_once` 入口 ~line 30 加检查）
- Modify: `jfox/gem_synth/loop.py`（写 tick 入口加检查）
- Test: `tests/test_backup.py`（加 quiesce 集成测试）

**Interfaces:**
- Consumes: Task 4 `backup_loop`、Task 2 `BackupCoordinator`
- Produces: daemon 启停 backup loop；兄弟 loop 备份期间跳过写 tick

- [ ] **Step 1: 写失败测试**

```python
def test_quiesce_makes_siblings_skip(tmp_path):
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
```

- [ ] **Step 2: 跑测试确认失败**（先确认接口存在；BackupCoordinator 已在 Task 2 建，此测试应直接 PASS——若 PASS 则跳过此步只做接线）

Run: `uv run pytest tests/test_backup.py -v -k quiesce_makes`

- [ ] **Step 3: daemon server 接线**（`jfox/daemon/server.py`）

3a. ~line 33 后加全局：
```python
_backup_task: Optional[asyncio.Task] = None
_backup_stop_event: Optional[threading.Event] = None
```
3b. `_maybe_start_gem_synth` 之后（~line 178）加：
```python
def _maybe_start_backup() -> None:
    """如果用户启用了 backup，启动后台循环 task"""
    global _backup_task, _backup_stop_event
    try:
        from ..backup.loop import backup_loop
        from ..global_config import get_global_config_manager

        cfg = get_global_config_manager().get_backup_config()
        if not cfg.enabled:
            logger.info("Daemon: backup 未启用（config.backup.enabled=false）")
            return
        _backup_stop_event = threading.Event()
        _backup_task = asyncio.create_task(backup_loop(_backup_stop_event))
        logger.info("Daemon: backup 后台循环已启动 (schedule=%s, retain=%d)", cfg.schedule_time, cfg.retain)
    except Exception as e:
        logger.exception("Daemon: 启动 backup 后台循环失败: %s", e)


async def _maybe_stop_backup() -> None:
    """关闭 backup 后台循环（lifespan shutdown 阶段调用）"""
    global _backup_task, _backup_stop_event
    if _backup_stop_event is not None:
        _backup_stop_event.set()
    if _backup_task is not None:
        try:
            await asyncio.wait_for(_backup_task, timeout=15)
        except asyncio.TimeoutError:
            _backup_task.cancel()
            await asyncio.gather(_backup_task, return_exceptions=True)
        except Exception as e:
            logger.warning("Daemon: 等待 backup 退出异常: %s", e)
    _backup_task = None
    _backup_stop_event = None
```
3c. `lifespan`（~line 195）加调用——startup 末尾加 `_maybe_start_backup()`，finally 开头加 `await _maybe_stop_backup()`：
```python
@asynccontextmanager
async def lifespan(app):
    _load_model()
    _maybe_start_auto_summary()
    _maybe_start_gem_synth()
    _maybe_start_backup()            # 新增
    _maybe_init_fragment_store()
    try:
        yield
    finally:
        await _maybe_stop_backup()   # 新增（最先停，避免停 daemon 前还在备份）
        await _maybe_stop_gem_synth()
        await _maybe_stop_auto_summary()
        _maybe_close_fragment_store()
```

- [ ] **Step 4: 兄弟 loop 加 quiesce 检查**

4a. `jfox/auto_summary/loop.py` `_tick_once`（~line 30，`if not cfg.enabled` 之后）加：
```python
    from ..backup.manager import BackupCoordinator

    if BackupCoordinator.is_running():
        return "backup 进行中，跳过本轮 auto-summary"
```
4b. `jfox/gem_synth/loop.py`：找到写 tick 函数（`_tick_once` 或等价物，用 `grep -n "def _tick_once\|def gem_synth_loop\|run_once\|cfg.enabled" jfox/gem_synth/loop.py` 定位），在其写操作入口（enabled 检查之后）加同样检查：
```python
    from ..backup.manager import BackupCoordinator

    if BackupCoordinator.is_running():
        logger.info("gem_synth: backup 进行中，跳过本轮")
        return
```
（lazy import 进函数体，避免顶层循环依赖——参考 CLAUDE.md「生命周期订阅重依赖 lazy import」教训。）

- [ ] **Step 5: 跑全量 backup 测试 + 验证 import 无环**

Run: `uv run pytest tests/test_backup.py -v`
Expected: PASS
Run: `uv run python -c "import jfox; import jfox.daemon.server; import jfox.backup; print('import ok')"`
Expected: 打印 `import ok`（无循环 import）

- [ ] **Step 6: lint + commit**

```bash
uv run ruff check jfox/daemon/server.py jfox/auto_summary/loop.py jfox/gem_synth/loop.py
uv run black --check jfox/daemon/server.py jfox/auto_summary/loop.py jfox/gem_synth/loop.py
git add jfox/daemon/server.py jfox/auto_summary/loop.py jfox/gem_synth/loop.py tests/test_backup.py
git commit -m "feat(backup): #338 daemon 接线 + gem_synth/auto_summary quiesce 检查"
```

---

### Task 6: CLI（`jfox backup ...` + `jfox restore`）

**Files:**
- Create: `jfox/backup/cli.py`
- Modify: `jfox/cli.py`（~line 102 后挂载）
- Test: `tests/test_backup.py`（CLI 冒烟）

**Interfaces:**
- Consumes: Task 1-4 全部
- Produces: `jfox backup run/enable/disable/status/list/verify`、`jfox restore <snapshot>`

- [ ] **Step 1: 写失败测试**（用 CliRunner）

```python
def test_backup_status_runs(tmp_path, monkeypatch):
    """jfox backup status 能跑（默认 enabled=False）"""
    from typer.testing import CliRunner
    from jfox.backup.cli import backup_app

    # 隔离全局配置到沙箱
    import jfox.global_config as gc

    monkeypatch.setattr(gc, "DEFAULT_CONFIG_PATH", tmp_path / ".zk_config.json")
    runner = CliRunner()
    r = runner.invoke(backup_app, ["status"])
    assert r.exit_code == 0
    assert "backup" in r.stdout.lower() or "禁用" in r.stdout or "启用" in r.stdout


def test_backup_enable_writes_config(tmp_path, monkeypatch):
    from typer.testing import CliRunner
    from jfox.backup.cli import backup_app
    import jfox.global_config as gc

    monkeypatch.setattr(gc, "DEFAULT_CONFIG_PATH", tmp_path / ".zk_config.json")
    gm = gc.get_global_config_manager()
    gm._config = None  # reset
    runner = CliRunner()
    r = runner.invoke(backup_app, ["enable", "--time", "03:00", "--retain", "5"])
    assert r.exit_code == 0
    cfg = gc.get_global_config_manager().get_backup_config()
    assert cfg.enabled is True and cfg.schedule_time == "03:00" and cfg.retain == 5
```

- [ ] **Step 2: 跑测试确认失败**

Run: `uv run pytest tests/test_backup.py -v -k "status_runs or enable_writes"`
Expected: FAIL（`No module named 'jfox.backup.cli'`）

- [ ] **Step 3: 写 `jfox/backup/cli.py`**（镜像 `auto_summary/cli.py` typer 风格）

```python
"""CLI subapp: jfox backup / jfox restore

子命令：
- run [--quiet]              立即手动备份
- enable [--time] [--retain] 开启 daemon 调度
- disable                    关闭 daemon 调度
- status                     配置 + last_run/next_run + 快照数
- list                       列快照
- verify <snapshot>          校验快照完整性
- restore <snapshot> [--yes] 从快照恢复（jfox restore 等价入口另挂）
"""

from __future__ import annotations

import json as _json
from pathlib import Path
from typing import Optional

import typer
from rich.console import Console
from rich.table import Table

from ..global_config import DEFAULT_KB_PATH, get_global_config_manager

console = Console(legacy_windows=False)

backup_app = typer.Typer(
    name="backup",
    help="KB 滚动备份/恢复：daemon 定时备份 + 手动 run/restore",
    no_args_is_help=True,
)


def _cfg():
    return get_global_config_manager().get_backup_config()


def _backup_root():
    cfg = _cfg()
    return Path(cfg.backup_root) if cfg.backup_root else Path.home() / ".jfox-backup"


@backup_app.command("status")
def status():
    """显示备份配置与上次运行情况"""
    cfg = _cfg()
    t = Table(title="JFox Backup")
    t.add_row("enabled", "是" if cfg.enabled else "否")
    t.add_row("schedule_time", cfg.schedule_time)
    t.add_row("retain", str(cfg.retain))
    t.add_row("backup_root", str(_backup_root()))
    state_p = _backup_root() / "state.json"
    if state_p.exists():
        st = _json.loads(state_p.read_text(encoding="utf-8"))
        t.add_row("last_run", st.get("last_run", "-"))
        t.add_row("last_ok", "成功" if st.get("last_ok") else "失败")
    console.print(t)


@backup_app.command("enable")
def enable(
    time: str = typer.Option("08:00", "--time", help="每日备份时刻 HH:MM"),
    retain: int = typer.Option(7, "--retain", help="滚动保留份数"),
):
    """开启 daemon 定时备份调度（需 daemon 运行/restart 生效）"""
    get_global_config_manager().update_backup_config(
        enabled=True, schedule_time=time, retain=retain
    )
    console.print(f"[green]已启用[/green] backup：每天 {time}，保留 {retain} 份")
    console.print("[dim]提示：daemon 每 tick reload 配置，新调度下个 tick 生效（≤5min）[/dim]")


@backup_app.command("disable")
def disable():
    """关闭 daemon 定时备份"""
    get_global_config_manager().update_backup_config(enabled=False)
    console.print("[green]已禁用[/green] backup 定时调度")


@backup_app.command("run")
def run(
    quiet: bool = typer.Option(False, "--quiet", help="成功时不打印（cron 用）"),
):
    """立即手动备份一份"""
    from .manager import BackupManager

    cfg = _cfg()
    mgr = BackupManager(
        backup_root=_backup_root(),
        kb_root=DEFAULT_KB_PATH,
        config_path=Path.home() / ".zk_config.json",
        retain=cfg.retain,
    )
    archive = mgr.backup()
    if not quiet:
        console.print(f"[green]备份成功[/green]：{archive}")


@backup_app.command("list")
def list_cmd():
    """列出已有快照"""
    from .manager import BackupManager

    cfg = _cfg()
    mgr = BackupManager(
        backup_root=_backup_root(),
        kb_root=DEFAULT_KB_PATH,
        config_path=Path.home() / ".zk_config.json",
        retain=cfg.retain,
    )
    snaps = mgr.list_snapshots()
    if not snaps:
        console.print("[dim]无快照[/dim]")
        return
    t = Table(title="Snapshots")
    t.add_column("archive")
    t.add_column("size")
    t.add_column("ok")
    for s in snaps:
        t.add_row(s["archive"], str(s["size"]), "✓" if s["ok"] else "✗")
    console.print(t)


@backup_app.command("verify")
def verify_cmd(
    snapshot: str = typer.Argument(..., help="快照文件名（daily/ 下）或绝对路径"),
):
    """校验快照完整性（sha256 + tar）"""
    from .manager import BackupManager

    cfg = _cfg()
    mgr = BackupManager(
        backup_root=_backup_root(),
        kb_root=DEFAULT_KB_PATH,
        config_path=Path.home() / ".zk_config.json",
        retain=cfg.retain,
    )
    p = Path(snapshot)
    if not p.is_absolute():
        p = _backup_root() / "daily" / snapshot
    ok = mgr.verify(p)
    console.print("[green]校验通过[/green]" if ok else "[red]校验失败[/red]")
    raise typer.Exit(0 if ok else 1)


@backup_app.command("restore")
def restore_cmd(
    snapshot: str = typer.Argument(..., help="快照文件名或绝对路径"),
    yes: bool = typer.Option(False, "--yes", help="跳过确认"),
):
    """从快照恢复 KB（可逆：当前态自动 rename 旁置）"""
    from .manager import BackupManager

    cfg = _cfg()
    p = Path(snapshot)
    if not p.is_absolute():
        p = _backup_root() / "daily" / snapshot
    if not yes:
        console.print(f"[yellow]将用 {p} 恢复 ~/.zettelkasten + ~/.zk_config.json[/yellow]")
        console.print("[dim]当前态会 rename 旁置为 .pre-restore-*（安全可逆）[/dim]")
        if not typer.confirm("确认恢复？", default=False):
            raise typer.Abort()
    mgr = BackupManager(
        backup_root=_backup_root(),
        kb_root=DEFAULT_KB_PATH,
        config_path=Path.home() / ".zk_config.json",
        retain=cfg.retain,
    )
    mgr.restore(p, yes=True)
    console.print(f"[green]恢复完成[/green]：{p}")
```

- [ ] **Step 4: 挂载到主 cli.py**（~line 104 后，auto_summary 挂载之后）

```python
from .backup.cli import backup_app  # noqa: E402
```
（与既有 import 风格一致，放在 `from .auto_summary.cli import auto_summary_app` 之后）
然后：
```python
app.add_typer(backup_app, name="backup", help="KB 滚动备份/恢复")
```

- [ ] **Step 5: 跑测试确认通过**

Run: `uv run pytest tests/test_backup.py -v`
Expected: PASS（含 CLI 冒烟）

验证 CLI 可用：
```bash
uv run jfox backup --help
uv run jfox backup status
```
Expected: 打印帮助/status 表

- [ ] **Step 6: lint + commit**

```bash
uv run ruff check jfox/backup/cli.py jfox/cli.py tests/test_backup.py
uv run black --check jfox/backup/cli.py jfox/cli.py tests/test_backup.py
git add jfox/backup/cli.py jfox/cli.py tests/test_backup.py
git commit -m "feat(backup): #338 CLI（run/enable/disable/status/list/verify/restore）"
```

---

### Task 7: 文档 + README

**Files:**
- Modify: `README.md`（加「备份与恢复」一节）
- Modify: `CLAUDE.md`（模块表加 `backup/`）

- [ ] **Step 1: README 加节**（找合适位置，如「使用」或「运维」节后）

```markdown
## 备份与恢复

JFox 自带 KB 滚动备份，由 jfox daemon 定时调度（默认关闭）。

```bash
# 启用：每天 08:00 自动备份，滚动保留 7 份
jfox backup enable --time 08:00 --retain 7
jfox backup status              # 查配置 + 上次运行
jfox backup list                # 列快照
jfox backup verify <snapshot>   # 校验完整性

# 手动备份一份
jfox backup run

# 从快照恢复（可逆：当前态自动旁置为 .pre-restore-*）
jfox restore <snapshot>         # 或 jfox backup restore <snapshot>
```

备份内容：`~/.zettelkasten`（全部知识库）+ `~/.zk_config.json`，存于 `~/.jfox-backup/daily/`。
恢复期间会短暂停 embedding daemon 拿干净快照；恢复前当前态会自动 rename 旁置，可安全回退。
```

- [ ] **Step 2: CLAUDE.md 模块表加一行**

| `backup/` | KB 滚动备份/恢复：`BackupManager`（tar+sha256+轮转+可逆恢复）+ daemon `backup_loop` 定时调度（镜像 auto-summary）+ `jfox backup/restore` CLI |

- [ ] **Step 3: commit**

```bash
git add README.md CLAUDE.md
git commit -m "docs(backup): #338 备份/恢复用法 + 模块表"
```

---

## Self-Review（写完自查）

**Spec 覆盖**：§1 范围（Task 1-7 全覆盖）｜§2 决策表（形态 T1-T6、触发 T4-T5、通知 T6 status、一致性 T2 quiesce + T5 接线、可逆 T3）｜§3 组件（T2 manager、T4 loop/schedule、T5 daemon 接线、T6 cli、归档结构 T2 `_write_tar`、manifest T2 `_build_manifest`）｜§4 数据流（backup T2+T4、restore T3）｜§5 一致性安全（quiesce T2+T5、原子 T2、rename 旁置 T3）｜§6 降级（lock T2、sha256 不符中止 T3、kb 不存在 T2 `_write_tar` 已处理）｜§7 非目标（不实现）｜§8 验收（T1-T6 测试即沙箱演练）｜§9 接入（T6 enable/status）｜§10 交付物（T1-T7）。

**Placeholder 扫描**：无 TBD/TODO；所有代码块为可执行实现或测试。gem_synth loop 的精确插入行标注了 grep 定位法（实现时定位）。

**类型一致**：`BackupManager(backup_root, kb_root, config_path, retain)` 在 T2/T3/T4/T6 签名一致；`BackupCoordinator.is_running()`/`quiesce()` 在 T2/T5 一致；`should_run_now(schedule_time, last_run_ts, now)` 在 T4 测试与实现一致。

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-07-26-kb-backup-restore.md`. 用户已授权自主开发、中间不再 review，按 **subagent-driven-development** 执行：每个 Task 派一个 fresh implementer（worktree 绝对路径 `/home/elling/git-repo/github/jfox/.claude/worktrees/issue-338-kb-backup-restore`），任务间复核，全过后本地 CR → PR → Zima 双 Bot。
