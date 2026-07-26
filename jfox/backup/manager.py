"""KB 滚动备份/恢复核心逻辑。

BackupCoordinator：进程级 quiesce 标志，daemon 内备份时兄弟 loop（gem_synth/
auto_summary）检查它跳过写 tick。BackupManager：tar 打包 + sha256 清单 + 校验
+ 滚动保留 + 可逆恢复。纯 stdlib，不 import 重模块（chromadb 等），避免 CLI
启动增重。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from typing import Iterator

from jfox.utils import atomic_write_json


class BackupCoordinator:
    """进程级备份进行中标志（仅同进程可见，daemon 内 backup_loop 用）。

    gem_synth_loop / auto_summary_loop 在写 tick 前检查 is_running()，置位时跳过，
    使备份期间 ChromaDB 无并发写。手动 CLI 备份是独立进程，本标志对其无效——
    那种情况下调用方应另停 daemon（见 restore / cli.run）。
    """

    _running: bool = False

    @classmethod
    def is_running(cls) -> bool:
        return cls._running

    @classmethod
    @contextmanager
    def quiesce(cls) -> Iterator[None]:
        cls._running = True
        try:
            yield
        finally:
            cls._running = False


class DaemonController:
    """embedding daemon 停启抽象。便于测试注入 no-op，避免单测触碰真实 daemon。

    restore 是独立 CLI 进程，需停 daemon 拿干净快照；backup（daemon 内 loop）
    不停 daemon、走 quiesce 标志，不用本类。
    """

    def stop(self) -> bool:
        """停 daemon，返回原先是否在跑。无 daemon 返回 False。"""
        raise NotImplementedError

    def start(self) -> None:
        """起 daemon（best-effort）。"""
        raise NotImplementedError


class SubprocessDaemonController(DaemonController):
    """默认实现：subprocess 调 `jfox daemon stop/start`。"""

    def stop(self) -> bool:
        import subprocess

        try:
            r = subprocess.run(
                ["jfox", "daemon", "status"],
                capture_output=True,
                text=True,
                timeout=15,
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

    def start(self) -> None:
        import subprocess

        try:
            subprocess.run(["jfox", "daemon", "start"], timeout=60)
        except Exception:
            pass


@contextmanager
def _fcntl_lock(lock_path: Path) -> Iterator[None]:
    """阻塞式文件锁，防 loop tick 与手动 run 撞车。

    阻塞而非 LOCK_NB：日备份场景并发概率极低，对方几秒内完成；flock 绑定 fd，
    进程崩溃即释放，不会永久锁死。
    """
    import fcntl

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
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
        daemon_controller: DaemonController | None = None,
    ):
        self.backup_root = Path(backup_root)
        self.kb_root = Path(kb_root)
        self.config_path = Path(config_path)
        self.retain = max(1, retain)
        self.daily_dir = self.backup_root / "daily"
        self._daemon_controller = daemon_controller or SubprocessDaemonController()

    # --------------------------------------------------------------------------
    # 备份
    # --------------------------------------------------------------------------
    def backup(self) -> Path:
        """打一份自包含 tar.gz + manifest，返回归档路径。失败抛异常。"""
        with _fcntl_lock(self.backup_root / ".lock"):
            with BackupCoordinator.quiesce():
                return self._do_backup()

    def _do_backup(self) -> Path:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        self.daily_dir.mkdir(parents=True, exist_ok=True)
        archive = self.daily_dir / f"jfox-{ts}.tar.gz"
        # 同秒内多次备份（测试或手动连点）：加序号保证文件名唯一
        n = 2
        while archive.exists():
            archive = self.daily_dir / f"jfox-{ts}-{n}.tar.gz"
            n += 1

        fd, tmp = tempfile.mkstemp(suffix=".tar.gz", dir=str(self.daily_dir))
        os.close(fd)
        try:
            self._write_tar(tmp, ts)
            self._assert_tar_ok(tmp)
            sha = self._sha256(tmp)
            manifest = self._build_manifest(archive.name, sha, tmp)
            os.replace(tmp, archive)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise

        atomic_write_json(self._manifest_path(archive), manifest)
        self._rotate()
        return archive

    def _write_tar(self, out_path: str, ts: str) -> None:
        root = f"jfox-backup-{ts}"
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
        # jfox-xxx.tar.gz -> jfox-xxx.manifest.json
        return archive.with_name(archive.name[: -len(".tar.gz")] + ".manifest.json")

    def _rotate(self) -> None:
        archives = sorted(self.daily_dir.glob("jfox-*.tar.gz"))
        for old in archives[: max(0, len(archives) - self.retain)]:
            old.unlink(missing_ok=True)
            self._manifest_path(old).unlink(missing_ok=True)

    # --------------------------------------------------------------------------
    # 恢复
    # --------------------------------------------------------------------------
    def restore(self, snapshot: Path, yes: bool = False) -> None:
        """从快照恢复。先停 daemon→rename 当前态旁置→校验 sha256→解压→起 daemon。

        任何步骤失败都 rename 回，真实 KB 不被破坏。daemon 停启 best-effort
        （沙箱/无 daemon 环境下跳过）。
        """
        snapshot = Path(snapshot)
        if not snapshot.exists():
            raise FileNotFoundError(f"快照不存在: {snapshot}")
        mpath = self._manifest_path(snapshot)
        if not mpath.exists():
            raise FileNotFoundError(f"清单缺失: {mpath}")

        daemon_was_running = self._daemon_controller.stop()
        try:
            self._restore_body(snapshot, mpath)
        finally:
            if daemon_was_running:
                self._daemon_controller.start()

    def _restore_body(self, snapshot: Path, mpath: Path) -> None:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        aside_kb = self.kb_root.with_name(self.kb_root.name + f".pre-restore-{ts}")
        aside_cfg = self.config_path.with_name(self.config_path.name + f".pre-restore-{ts}")

        # 1. 校验 sha256（先于 rename，避免无谓挪动）
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        if self._sha256(str(snapshot)) != manifest.get("archive_sha256"):
            raise ValueError("归档 sha256 与清单不符，拒绝恢复")

        # 2. rename 当前态旁置
        renamed_kb = False
        if self.kb_root.exists():
            self.kb_root.rename(aside_kb)
            renamed_kb = True
        renamed_cfg = False
        if self.config_path.exists():
            self.config_path.rename(aside_cfg)
            renamed_cfg = True

        try:
            # 3. 解压到位
            self._extract(snapshot)
        except Exception:
            # 回退：把旁置的当前态挪回
            if renamed_kb and aside_kb.exists():
                aside_kb.rename(self.kb_root)
            if renamed_cfg and aside_cfg.exists():
                aside_cfg.rename(self.config_path)
            raise

        # 4. 保留最近 1 份恢复前保险，更旧的清掉
        self._rotate_pre_restore(self.kb_root, ".pre-restore-")
        self._rotate_pre_restore(self.config_path, ".pre-restore-")

    def _extract(self, snapshot: Path) -> None:
        with tarfile.open(snapshot, "r:gz") as tar:
            members = tar.getmembers()
            root = members[0].name.split("/")[0] if members else ""
            for m in members:
                rel = m.name[len(root) + 1 :] if root and m.name.startswith(root + "/") else m.name
                if not rel:
                    continue
                if rel.startswith("zettelkasten/"):
                    m.name = rel[len("zettelkasten/") :]
                    if m.name:
                        tar.extract(m, path=str(self.kb_root))
                elif rel == "zk_config.json":
                    m.name = "zk_config.json"
                    tar.extract(m, path=str(self.config_path.parent))

    def _rotate_pre_restore(self, target: Path, marker: str) -> None:
        sibs = sorted(
            target.parent.glob(target.name + marker + "*"),
            key=lambda p: p.stat().st_mtime,
        )
        for old in sibs[:-1]:
            if old.is_dir():
                shutil.rmtree(old, ignore_errors=True)
            else:
                old.unlink(missing_ok=True)

    # --------------------------------------------------------------------------
    # list / verify
    # --------------------------------------------------------------------------
    def list_snapshots(self) -> list[dict]:
        out: list[dict] = []
        for archive in sorted(self.daily_dir.glob("jfox-*.tar.gz"), reverse=True):
            mpath = self._manifest_path(archive)
            manifest = json.loads(mpath.read_text(encoding="utf-8")) if mpath.exists() else None
            out.append(
                {
                    "archive": archive.name,
                    "size": archive.stat().st_size,
                    "created": manifest.get("created") if manifest else None,
                    "ok": self.verify(archive),
                }
            )
        return out

    def verify(self, archive: Path) -> bool:
        archive = Path(archive)
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
