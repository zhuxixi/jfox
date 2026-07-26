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

    def is_running(self) -> bool:
        """daemon 是否在跑"""
        raise NotImplementedError

    def stop(self) -> None:
        """停 daemon（假定在跑）；停不掉抛异常，让 restore 拒绝继续"""
        raise NotImplementedError

    def start(self) -> None:
        """起 daemon（best-effort）"""
        raise NotImplementedError


class SubprocessDaemonController(DaemonController):
    """默认实现：subprocess 调 `jfox daemon status/stop/start`。"""

    def is_running(self) -> bool:
        return self._probe_running()

    def stop(self) -> None:
        import subprocess

        try:
            subprocess.run(["jfox", "daemon", "stop"], timeout=30)
        except Exception as e:
            raise RuntimeError(f"停 daemon 失败: {e}") from e
        # 关键：验证确已停止；否则抛异常让 restore 拒绝继续——
        # 不让在 daemon 仍持有 ChromaDB/SQLite 时挪走 kb_root（Windows rename
        # 被打开目录会直接失败，POSIX 上 daemon fd 继续写旧位）。
        if self._probe_running():
            raise RuntimeError("daemon 停不下来，拒绝继续 restore")

    def start(self) -> None:
        import subprocess

        try:
            subprocess.run(["jfox", "daemon", "start"], timeout=60)
        except Exception:
            pass

    @staticmethod
    def _probe_running() -> bool:
        """探测 daemon 是否在跑。优先解析 status 输出，回退「运行中」字样"""
        import subprocess

        try:
            r = subprocess.run(
                ["jfox", "daemon", "status"],
                capture_output=True,
                text=True,
                timeout=15,
            )
        except Exception:
            return False
        if r.returncode != 0:
            return False
        # 尝试 json（若 status 支持 --format json）；否则回退中文状态字
        try:
            data = json.loads(r.stdout)
            return bool(
                data.get("running")
                or data.get("status") in ("running", "运行中")
                or data.get("状态") == "运行中"
            )
        except (ValueError, json.JSONDecodeError):
            return "运行中" in r.stdout


def _acquire_lock(fd: int) -> None:
    """跨平台阻塞式独占锁。Unix fcntl.flock，Windows msvcrt.locking"""
    try:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_EX)
        return
    except ImportError:
        pass
    import msvcrt
    import time

    while True:
        try:
            msvcrt.locking(fd, msvcrt.LK_LOCK, 1)
            return
        except OSError:
            time.sleep(0.1)


def _release_lock(fd: int) -> None:
    try:
        import fcntl

        fcntl.flock(fd, fcntl.LOCK_UN)
        return
    except ImportError:
        pass
    import msvcrt

    try:
        msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
    except OSError:
        pass


@contextmanager
def _file_lock(lock_path: Path) -> Iterator[None]:
    """跨平台阻塞式文件锁，防 loop tick 与手动 run 撞车。

    锁绑定 fd，进程崩溃即释放，不会永久锁死。
    """
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 0o644)
    try:
        _acquire_lock(fd)
        yield
    finally:
        _release_lock(fd)
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
        with _file_lock(self.backup_root / ".lock"):
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
        # 按 mtime 排序（文件名序在 -N 后缀同秒场景下会误排，见 CR #11）
        archives = sorted(self.daily_dir.glob("jfox-*.tar.gz"), key=lambda p: p.stat().st_mtime)
        for old in archives[: max(0, len(archives) - self.retain)]:
            old.unlink(missing_ok=True)
            self._manifest_path(old).unlink(missing_ok=True)

    # --------------------------------------------------------------------------
    # 恢复
    # --------------------------------------------------------------------------
    def restore(self, snapshot: Path, yes: bool = False) -> None:
        """从快照恢复。先停 daemon→rename 当前态旁置→校验 sha256→解压→起 daemon。

        daemon 停不掉则中止（拒绝在 daemon 持有 ChromaDB 时挪走 KB）；解压失败
        清理半成品 + rename 回，真实 KB 不被破坏。
        """
        snapshot = Path(snapshot)
        if not snapshot.exists():
            raise FileNotFoundError(f"快照不存在: {snapshot}")
        mpath = self._manifest_path(snapshot)
        if not mpath.exists():
            raise FileNotFoundError(f"清单缺失: {mpath}")

        was_running = self._daemon_controller.is_running()
        if was_running:
            self._daemon_controller.stop()  # 停不掉抛 → restore 中止，KB 未动
        try:
            self._restore_body(snapshot, mpath)
        finally:
            if was_running:
                self._daemon_controller.start()

    def _restore_body(self, snapshot: Path, mpath: Path) -> None:
        ts = datetime.now().strftime("%Y%m%d-%H%M%S")
        aside_kb = self.kb_root.with_name(self.kb_root.name + f".pre-restore-{ts}")
        aside_cfg = self.config_path.with_name(self.config_path.name + f".pre-restore-{ts}")

        # 1. 校验 sha256（先于 rename，避免无谓挪动）
        manifest = json.loads(mpath.read_text(encoding="utf-8"))
        if self._sha256(str(snapshot)) != manifest.get("archive_sha256"):
            raise ValueError("归档 sha256 与清单不符，拒绝恢复")

        # 2. rename 当前态旁置（两步同 try，任一失败回滚已做的）
        renamed_kb = False
        renamed_cfg = False
        try:
            if self.kb_root.exists():
                self.kb_root.rename(aside_kb)
                renamed_kb = True
            if self.config_path.exists():
                self.config_path.rename(aside_cfg)
                renamed_cfg = True
        except Exception:
            if renamed_kb and aside_kb.exists():
                aside_kb.rename(self.kb_root)
            raise

        try:
            # 3. 解压到位
            self._extract(snapshot)
        except Exception:
            # 回退：先清理可能写了一半的 kb_root/config，再把旁置的当前态挪回
            # （否则 rename 覆盖已存在的目录/文件会失败，导致新旧两空）
            if self.kb_root.exists():
                shutil.rmtree(self.kb_root, ignore_errors=True)
            if renamed_kb and aside_kb.exists():
                aside_kb.rename(self.kb_root)
            if self.config_path.exists():
                try:
                    self.config_path.unlink()
                except OSError:
                    pass
            if renamed_cfg and aside_cfg.exists():
                aside_cfg.rename(self.config_path)
            raise

        # 4. 保留最近 1 份恢复前保险，更旧的清掉
        self._rotate_pre_restore(self.kb_root, ".pre-restore-")
        self._rotate_pre_restore(self.config_path, ".pre-restore-")

    def _extract(self, snapshot: Path) -> None:
        """解压归档到 kb_root / config_path。成员经安全净化（PEP 706 tar-slip 防护）"""
        with tarfile.open(snapshot, "r:gz") as tar:
            members = tar.getmembers()
            root = members[0].name.split("/")[0] if members else ""
            for m in members:
                rel = m.name[len(root) + 1 :] if root and m.name.startswith(root + "/") else m.name
                if not rel:
                    continue
                if rel.startswith("zettelkasten/"):
                    dest_rel = rel[len("zettelkasten/") :]
                    dest_root = self.kb_root
                elif rel == "zk_config.json":
                    dest_rel = "zk_config.json"
                    dest_root = self.config_path.parent
                else:
                    continue
                if not self._safe_member(m, dest_rel):
                    continue
                m.name = dest_rel
                if dest_rel:
                    tar.extract(m, path=str(dest_root))

    @staticmethod
    def _safe_member(m: tarfile.TarInfo, dest_rel: str) -> bool:
        """只放行常规文件/目录；拒绝 symlink/hardlink/device 与路径越界（..、绝对、盘符）"""
        if not (m.isfile() or m.isdir()):
            return False
        norm = dest_rel.replace("\\", "/")
        if norm.startswith("/"):
            return False
        # Windows 盘符（C:、D: …）
        if len(norm) >= 2 and norm[1] == ":":
            return False
        if any(part == ".." for part in norm.split("/")):
            return False
        return True

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
