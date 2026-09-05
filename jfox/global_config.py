"""
全局配置管理 - 多知识库支持

管理 ~/.zk_config.json，存储所有知识库的注册信息和默认设置
"""

import json
import logging
import math
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


_config_path_env = os.environ.get("ZK_CONFIG_PATH", "").strip()
DEFAULT_CONFIG_PATH = Path(_config_path_env or (Path.home() / ".zk_config.json")).expanduser()
DEFAULT_KB_NAME = "default"
DEFAULT_KB_PATH = Path(os.environ.get("ZK_KB_ROOT", str(Path.home() / ".zettelkasten")))


@dataclass
class KnowledgeBaseEntry:
    """知识库条目"""

    name: str
    path: str
    created: str
    description: Optional[str] = None
    last_used: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, name: str, data: Dict[str, Any]) -> "KnowledgeBaseEntry":
        return cls(
            name=name,
            path=data.get("path", ""),
            created=data.get("created", datetime.now().isoformat()),
            description=data.get("description"),
            last_used=data.get("last_used"),
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
        # retain 防御：null/非数字 → 默认 7（避免 int(None) TypeError）
        try:
            retain = int(data.get("retain", 7))
        except (TypeError, ValueError):
            retain = 7
        # backup_root 防御：只接受 str，其余（数字/列表/null）→ None
        raw_root = data.get("backup_root")
        backup_root = raw_root if isinstance(raw_root, str) and raw_root.strip() else None
        return cls(
            enabled=bool(data.get("enabled", False)),
            schedule_time=str(data.get("schedule_time", "08:00")),
            retain=retain,
            backup_root=backup_root,
        )


@dataclass
class AutoSummaryConfig:
    """Claude Code 会话自动总结配置（opt-in，默认关闭）"""

    enabled: bool = False
    interval_minutes: int = 30  # 后台循环每多少分钟扫一次
    idle_threshold_minutes: int = 30  # session 文件 mtime 静默多久才视为已结束
    target_kb: Optional[str] = None  # 写入哪个知识库；None 用 default
    max_session_size_mb: int = 10  # 超过此大小的 session 跳过（避免 token 爆炸）
    min_session_size_kb: int = 5  # 太小的 session 跳过（无实质内容）
    max_per_tick: int = 5  # 每轮最多处理几个 session
    skip_after_days: int = 0  # 0 表示不跳过任何 session；可自行设置上限
    claude_timeout_seconds: int = 120  # claude -p 调用超时
    claude_binary: Optional[str] = None  # claude 命令路径；None 表示从 PATH 解析
    session_sources: List[str] = field(default_factory=lambda: ["claude", "kimi"])  # 启用的扫描来源
    kimi_sessions_dir: Optional[str] = None  # None → ~/.kimi-code/sessions

    # 调度时间窗口配置（Issue #298）
    schedule_enabled: bool = False  # 是否启用运行时间窗口
    schedule_weekday_start_hour: int = 0  # 工作日窗口开始小时（含）
    schedule_weekday_end_hour: int = 6  # 工作日窗口结束小时（不含）
    schedule_weekend_start_hour: int = 0  # 周末窗口开始小时（含）
    schedule_weekend_end_hour: int = 8  # 周末窗口结束小时（不含）
    schedule_timezone: str = "Asia/Shanghai"  # 时间窗口判断时区
    schedule_holiday_provider: Optional[str] = None  # 节假日数据源，预留扩展

    def __post_init__(self) -> None:
        # 把负值/0 当成"用默认值"而非崩溃；空字符串 target_kb 等价于 None
        if self.interval_minutes < 1:
            self.interval_minutes = 30
        if self.idle_threshold_minutes < 1:
            self.idle_threshold_minutes = 30
        if self.max_session_size_mb < 1:
            self.max_session_size_mb = 10
        if self.min_session_size_kb < 0:
            self.min_session_size_kb = 0
        if self.max_per_tick < 1:
            self.max_per_tick = 1
        if self.skip_after_days < 0:
            self.skip_after_days = 0
        if self.claude_timeout_seconds < 30:
            self.claude_timeout_seconds = 30
        # 大小区间健全性：min_kb 不应大于 max_mb*1024
        if self.min_session_size_kb >= self.max_session_size_mb * 1024:
            self.min_session_size_kb = max(0, self.max_session_size_mb * 1024 - 1)
        if isinstance(self.target_kb, str) and not self.target_kb.strip():
            self.target_kb = None

        # 调度窗口小时校验：越界或 start >= end 时回退到默认值，避免 daemon 崩溃。
        # 结束小时允许为 24，表示窗口包含到午夜前的小时（如 [22, 24)）。
        def _clamp_schedule_window(
            start: int, end: int, default_start: int, default_end: int
        ) -> tuple[int, int]:
            if not (0 <= start < 24) or not (0 < end <= 24) or end <= start:
                return default_start, default_end
            return start, end

        cls = self.__class__
        self.schedule_weekday_start_hour, self.schedule_weekday_end_hour = _clamp_schedule_window(
            self.schedule_weekday_start_hour,
            self.schedule_weekday_end_hour,
            cls.schedule_weekday_start_hour,
            cls.schedule_weekday_end_hour,
        )
        self.schedule_weekend_start_hour, self.schedule_weekend_end_hour = _clamp_schedule_window(
            self.schedule_weekend_start_hour,
            self.schedule_weekend_end_hour,
            cls.schedule_weekend_start_hour,
            cls.schedule_weekend_end_hour,
        )
        if not isinstance(self.schedule_timezone, str) or not self.schedule_timezone.strip():
            self.schedule_timezone = "Asia/Shanghai"
        if (
            isinstance(self.schedule_holiday_provider, str)
            and not self.schedule_holiday_provider.strip()
        ):
            self.schedule_holiday_provider = None

        # 运行时 stop_event，由 daemon loop 注入，不序列化
        object.__setattr__(self, "_stop_event", None)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "AutoSummaryConfig":
        if not data:
            return cls()

        def _safe_int(v: Any, default: int) -> int:
            try:
                return int(v)  # type: ignore[arg-type]
            except (TypeError, ValueError):
                return default

        return cls(
            enabled=bool(data.get("enabled", False)),
            interval_minutes=int(data.get("interval_minutes", 30)),
            idle_threshold_minutes=int(data.get("idle_threshold_minutes", 30)),
            target_kb=data.get("target_kb"),
            max_session_size_mb=int(data.get("max_session_size_mb", 10)),
            min_session_size_kb=int(data.get("min_session_size_kb", 5)),
            max_per_tick=int(data.get("max_per_tick", 5)),
            skip_after_days=int(data.get("skip_after_days", 0)),
            claude_timeout_seconds=int(data.get("claude_timeout_seconds", 120)),
            claude_binary=data.get("claude_binary"),
            session_sources=(
                list(data["session_sources"])
                if isinstance(data.get("session_sources"), list)
                else ["claude", "kimi"]
            ),
            kimi_sessions_dir=data.get("kimi_sessions_dir"),
            schedule_enabled=bool(data.get("schedule_enabled", False)),
            schedule_weekday_start_hour=_safe_int(data.get("schedule_weekday_start_hour"), 0),
            schedule_weekday_end_hour=_safe_int(data.get("schedule_weekday_end_hour"), 6),
            schedule_weekend_start_hour=_safe_int(data.get("schedule_weekend_start_hour"), 0),
            schedule_weekend_end_hour=_safe_int(data.get("schedule_weekend_end_hour"), 8),
            schedule_timezone=data.get("schedule_timezone", "Asia/Shanghai") or "Asia/Shanghai",
            schedule_holiday_provider=data.get("schedule_holiday_provider") or None,
        )


@dataclass
class FragmentCaptureConfig:
    """Claude Code Hook 碎片采集配置（默认启用）"""

    enabled: bool = True
    # 纠正信号关键词（命中 → fragment_type=correction）
    correction_keywords: List[str] = field(
        default_factory=lambda: [
            "不对",
            "错了",
            "应该",
            "不要",
            "等等",
            "停",
            "不是",
            "别",
            "换一种",
            "反过来",
        ]
    )
    # 决策信号关键词（命中 → fragment_type=decision）
    decision_keywords: List[str] = field(
        default_factory=lambda: ["用方案", "选", "因为", "理由是", "我决定", "就这样", "先不做"]
    )
    # content 字段截断长度
    max_content_chars: int = 500

    def __post_init__(self) -> None:
        # 与 AutoSummaryConfig 一致：非正值回退到默认，避免 0/负数破坏截断逻辑
        if not isinstance(self.max_content_chars, int) or self.max_content_chars < 1:
            self.max_content_chars = 500

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "FragmentCaptureConfig":
        if not data:
            return cls()
        raw_enabled = data.get("enabled", True)
        if isinstance(raw_enabled, str):
            enabled = raw_enabled.strip().lower() not in ("false", "0", "no", "off", "")
        else:
            enabled = bool(raw_enabled)
        # 安全 int：非数字字符串不应抛 ValueError（否则 GlobalConfigManager._load 的 except
        # 会吞掉异常并重置整份全局配置——auto_summary、KB 列表、默认 KB 全失效）
        raw_max = data.get("max_content_chars", 500)
        try:
            max_content_chars = int(raw_max) if raw_max is not None else 500
        except (TypeError, ValueError):
            max_content_chars = 500
        return cls(
            enabled=enabled,
            correction_keywords=(
                list(data["correction_keywords"])
                if isinstance(data.get("correction_keywords"), list)
                else cls().correction_keywords
            ),
            decision_keywords=(
                list(data["decision_keywords"])
                if isinstance(data.get("decision_keywords"), list)
                else cls().decision_keywords
            ),
            max_content_chars=max_content_chars,
        )


@dataclass
class GemSynthesisConfig:
    """L3 宝石合成配置（opt-in，默认关闭）"""

    enabled: bool = False
    interval_minutes: int = 30  # daemon 循环周期
    anchor_types: List[str] = field(
        default_factory=lambda: ["correction", "decision", "ask_user_question"]
    )
    grounding_top_k: int = 5  # 检索多少条 permanent 笔记做基准
    target_kb: Optional[str] = None  # candidate 写入哪个 KB；None 用 default
    claude_timeout_seconds: int = 180
    claude_binary: Optional[str] = None  # None → 从 PATH 解析
    dedup_enabled: bool = True  # 存盘前用正文 embedding 余弦查重
    dedup_threshold: float = 0.88  # 同事实重复阈值（高）；link-suggest 0.6 是"相关"，dedup 要"同一"
    dedup_merge_enabled: bool = (
        True  # 命中 candidate 时提取增量补入（#309）；False 回 #308 二值跳过
    )

    def __post_init__(self) -> None:
        if self.interval_minutes < 1:
            self.interval_minutes = 30
        if self.grounding_top_k < 1:
            self.grounding_top_k = 5
        if self.claude_timeout_seconds < 30:
            self.claude_timeout_seconds = 180
        # dedup_threshold 是余弦相似度，合法区间 [0, 1]；越界值（>1 永不命中 / <0 无意义）钳到边界。
        # NaN/inf/非数值需先 sanitize：max/min 与 NaN 比较返回 NaN → cosine >= NaN 永假 → dedup 永不触发。
        val = self.dedup_threshold
        if (
            val is None
            or isinstance(val, bool)
            or not isinstance(val, (int, float))
            or math.isnan(val)
            or math.isinf(val)
        ):
            self.dedup_threshold = 0.88
        else:
            self.dedup_threshold = max(0.0, min(1.0, float(val)))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "GemSynthesisConfig":
        if not data:
            return cls()

        # 安全 int：非数字字符串不应抛 ValueError（否则 GlobalConfigManager._load 的 except
        # 会吞掉异常并重置整份全局配置——auto_summary、KB 列表、默认 KB 全失效）。
        # 与 FragmentCaptureConfig / AutoSummaryConfig 保持一致的防御性解析。
        def _safe_int(v, default):
            try:
                return int(v)
            except (TypeError, ValueError):
                return default

        def _safe_float(v, default):
            try:
                return float(v)
            except (TypeError, ValueError):
                return default

        return cls(
            enabled=bool(data.get("enabled", False)),
            interval_minutes=_safe_int(data.get("interval_minutes"), 30),
            anchor_types=(
                list(data["anchor_types"])
                if isinstance(data.get("anchor_types"), list)
                else cls().anchor_types
            ),
            grounding_top_k=_safe_int(data.get("grounding_top_k"), 5),
            target_kb=data.get("target_kb"),
            claude_timeout_seconds=_safe_int(data.get("claude_timeout_seconds"), 180),
            claude_binary=data.get("claude_binary"),
            dedup_enabled=bool(data.get("dedup_enabled", True)),
            dedup_threshold=(
                # bool 先于 _safe_float 拦截（float(True)=1.0 会静默成合法阈值，绕过 __post_init__ 的 bool 守卫）
                0.88
                if isinstance(data.get("dedup_threshold"), bool)
                else _safe_float(data.get("dedup_threshold"), 0.88)
            ),
            dedup_merge_enabled=bool(data.get("dedup_merge_enabled", True)),
        )


@dataclass
class NoteAddConfig:
    """jfox add 落库防重配置（#383：permanent 双通道查重）"""

    dedup_enabled: bool = True  # 总开关；False 时 add 完全跳过防重
    title_dedup: bool = True  # 标题通道：非 archived 同标题（大小写不敏感）拦截
    embedding_dedup: bool = True  # 正文通道：仅 embedding daemon 可用时生效
    dedup_threshold: float = 0.95  # 近逐字级（add 是二值拒绝，严于 gem_synth 的 0.88）

    def __post_init__(self) -> None:
        # 同 GemSynthesisConfig 的 sanitize：非法值回默认，合法值钳到 [0, 1]
        # （NaN 与任何数比较返回 False → cosine >= NaN 永假 → dedup 永不触发，必须挡）
        val = self.dedup_threshold
        if (
            val is None
            or isinstance(val, bool)
            or not isinstance(val, (int, float))
            or math.isnan(val)
            or math.isinf(val)
        ):
            self.dedup_threshold = 0.95
        else:
            self.dedup_threshold = max(0.0, min(1.0, float(val)))

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "NoteAddConfig":
        # 非 dict 值（如手改配置写成字符串）回默认：data.get 会抛 AttributeError，
        # 上层 _load 的宽 except 会重建默认 GlobalConfig，有清空注册表的风险
        if not isinstance(data, dict):
            return cls()
        # 只取已知键，忽略多余键（向前兼容）
        return cls(
            dedup_enabled=data.get("dedup_enabled", True),
            title_dedup=data.get("title_dedup", True),
            embedding_dedup=data.get("embedding_dedup", True),
            dedup_threshold=data.get("dedup_threshold", 0.95),
        )


@dataclass
class GlobalConfig:
    """全局配置"""

    default: str = DEFAULT_KB_NAME
    knowledge_bases: Dict[str, KnowledgeBaseEntry] = field(default_factory=dict)
    auto_summary: AutoSummaryConfig = field(default_factory=AutoSummaryConfig)
    fragment_capture: FragmentCaptureConfig = field(default_factory=FragmentCaptureConfig)
    gem_synthesis: GemSynthesisConfig = field(default_factory=GemSynthesisConfig)
    note_add: NoteAddConfig = field(default_factory=NoteAddConfig)
    backup: BackupConfig = field(default_factory=BackupConfig)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "default": self.default,
            "knowledge_bases": {name: kb.to_dict() for name, kb in self.knowledge_bases.items()},
            "auto_summary": self.auto_summary.to_dict(),
            "fragment_capture": self.fragment_capture.to_dict(),
            "gem_synthesis": self.gem_synthesis.to_dict(),
            "note_add": self.note_add.to_dict(),
            "backup": self.backup.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "GlobalConfig":
        kbs = {}
        for name, kb_data in data.get("knowledge_bases", {}).items():
            kbs[name] = KnowledgeBaseEntry.from_dict(name, kb_data)

        return cls(
            default=data.get("default", DEFAULT_KB_NAME),
            knowledge_bases=kbs,
            auto_summary=AutoSummaryConfig.from_dict(data.get("auto_summary")),
            fragment_capture=FragmentCaptureConfig.from_dict(data.get("fragment_capture")),
            gem_synthesis=GemSynthesisConfig.from_dict(data.get("gem_synthesis")),
            note_add=NoteAddConfig.from_dict(data.get("note_add")),
            backup=BackupConfig.from_dict(data.get("backup")),
        )


class GlobalConfigManager:
    """
    全局配置管理器

    负责管理 ~/.zk_config.json 的读写操作
    """

    def __init__(self, config_path: Optional[Path] = None):
        self.config_path = config_path or DEFAULT_CONFIG_PATH
        self._config: Optional[GlobalConfig] = None

    def reload(self) -> GlobalConfig:
        """强制重新从磁盘加载配置（丢弃进程内缓存）

        daemon 后台循环或跨进程协作中，CLI 可能已修改磁盘上的配置；
        调用此方法使配置从文件重新读取，而非返回旧缓存。
        """
        self._config = None
        return self._load()

    def _load(self) -> GlobalConfig:
        """加载配置，如果不存在则创建默认配置"""
        if self._config is not None:
            return self._config

        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._config = GlobalConfig.from_dict(data)
                # 迁移旧版默认 KB 路径（~/.zettelkasten/ → ~/.zettelkasten/default/）
                self._migrate_default_kb_path()
                logger.debug(f"Loaded global config from {self.config_path}")
            except Exception as e:
                logger.warning(f"Failed to load config: {e}, creating default")
                self._config = self._create_default_config()
        else:
            self._config = self._create_default_config()

        return self._config

    def _migrate_default_kb_path(self):
        """迁移旧版默认 KB 路径：~/.zettelkasten/ → ~/.zettelkasten/default/"""
        if self._config is None:
            return
        default_kb = self._config.knowledge_bases.get(DEFAULT_KB_NAME)
        if default_kb is None:
            return
        old_path = DEFAULT_KB_PATH
        new_path = DEFAULT_KB_PATH / "default"
        # 检查当前路径是否是旧版路径（~/.zettelkasten/ 而非 ~/.zettelkasten/default/）
        try:
            current_resolved = Path(default_kb.path).expanduser().resolve()
            if current_resolved == old_path.resolve():
                if old_path.exists() and not new_path.exists():
                    import shutil

                    new_path.mkdir(parents=True, exist_ok=True)
                    try:
                        # 移动 notes/ 和 .zk/ 目录
                        for subdir in ["notes", ".zk"]:
                            src = old_path / subdir
                            if src.exists():
                                shutil.move(str(src), str(new_path / subdir))
                    except Exception as move_error:
                        # 回滚：移回已迁移的子目录
                        rollback_errors = []
                        for subdir in ["notes", ".zk"]:
                            moved = new_path / subdir
                            if moved.exists():
                                try:
                                    shutil.move(str(moved), str(old_path / subdir))
                                except Exception as rb_err:
                                    rollback_errors.append(
                                        f"Failed to roll back {subdir}: {rb_err}"
                                    )
                        # 清理空的 new_path 目录
                        try:
                            new_path.rmdir()
                        except OSError:
                            logger.debug(f"Could not remove {new_path} during rollback")
                        if rollback_errors:
                            logger.error(
                                f"Migration failed ({move_error}) AND rollback had "
                                f"errors: {'; '.join(rollback_errors)}"
                            )
                        raise
                    logger.info(f"Migrated default KB from {old_path} to {new_path}")
                    # 仅在文件迁移成功后才更新 config
                    default_kb.path = str(new_path)
                    self._save()
                else:
                    # 旧路径已不存在或新路径已存在，仅更新 config 指向
                    default_kb.path = str(new_path)
                    self._save()
        except Exception as e:
            logger.error(
                f"Failed to migrate default KB path from {old_path} to " f"{new_path}: {e}",
                exc_info=True,
            )

    def _save(self) -> bool:
        """原子保存配置到文件（tempfile + os.replace）"""
        try:
            from jfox.utils import atomic_write_json

            atomic_write_json(self.config_path, self._config.to_dict())
            logger.debug(f"Saved global config to {self.config_path}")
            return True
        except Exception as e:
            logger.error(f"Failed to save config: {e}")
            return False

    def _create_default_config(self) -> GlobalConfig:
        """创建默认配置"""
        default_kb = KnowledgeBaseEntry(
            name=DEFAULT_KB_NAME,
            path=str(DEFAULT_KB_PATH / "default"),
            created=datetime.now().isoformat(),
            description="Default knowledge base",
        )

        config = GlobalConfig(
            default=DEFAULT_KB_NAME, knowledge_bases={DEFAULT_KB_NAME: default_kb}
        )

        # 如果默认知识库已存在，保留它
        if DEFAULT_KB_PATH.exists():
            self._config = config
            self._save()

        return config

    def get_config(self) -> GlobalConfig:
        """获取当前配置"""
        return self._load()

    def get_default_kb_name(self) -> str:
        """获取默认知识库名称"""
        return self._load().default

    def get_default_kb_path(self) -> Path:
        """获取默认知识库路径"""
        config = self._load()
        default_name = config.default

        if default_name in config.knowledge_bases:
            return Path(config.knowledge_bases[default_name].path)

        # 回退到默认路径
        return DEFAULT_KB_PATH / "default"

    def get_kb_path(self, name: str) -> Optional[Path]:
        """获取指定知识库的路径"""
        config = self._load()
        if name in config.knowledge_bases:
            return Path(config.knowledge_bases[name].path)
        return None

    def list_knowledge_bases(self) -> List[KnowledgeBaseEntry]:
        """列出所有知识库"""
        config = self._load()
        return list(config.knowledge_bases.values())

    def kb_exists(self, name: str) -> bool:
        """检查知识库是否存在"""
        config = self._load()
        return name in config.knowledge_bases

    def add_knowledge_base(self, name: str, path: Path, description: Optional[str] = None) -> bool:
        """添加新知识库"""
        config = self._load()

        if name in config.knowledge_bases:
            logger.warning(f"Knowledge base '{name}' already exists")
            return False

        resolved_path = path.expanduser().resolve()

        kb = KnowledgeBaseEntry(
            name=name,
            path=str(resolved_path),
            created=datetime.now().isoformat(),
            description=description or f"Knowledge base: {name}",
        )

        config.knowledge_bases[name] = kb
        self._config = config
        return self._save()

    def remove_knowledge_base(self, name: str) -> bool:
        """从配置中移除知识库（不删除实际数据）"""
        config = self._load()

        if name not in config.knowledge_bases:
            logger.warning(f"Knowledge base '{name}' not found")
            return False

        # 不能删除最后一个知识库
        if len(config.knowledge_bases) <= 1:
            logger.error("Cannot remove the last knowledge base")
            return False

        del config.knowledge_bases[name]

        # 如果删除的是默认知识库，切换到第一个可用的
        if config.default == name:
            config.default = next(iter(config.knowledge_bases.keys()))

        self._config = config
        return self._save()

    def set_default(self, name: str) -> bool:
        """设置默认知识库"""
        config = self._load()

        if name not in config.knowledge_bases:
            logger.warning(f"Knowledge base '{name}' not found")
            return False

        config.default = name

        # 更新最后使用时间
        config.knowledge_bases[name].last_used = datetime.now().isoformat()

        self._config = config
        return self._save()

    def rename_knowledge_base(self, old_name: str, new_name: str) -> bool:
        """重命名知识库"""
        config = self._load()

        if old_name not in config.knowledge_bases:
            logger.warning(f"Knowledge base '{old_name}' not found")
            return False

        if new_name in config.knowledge_bases:
            logger.warning(f"Knowledge base '{new_name}' already exists")
            return False

        kb = config.knowledge_bases[old_name]
        kb.name = new_name
        config.knowledge_bases[new_name] = kb
        del config.knowledge_bases[old_name]

        # 如果重命名的是默认知识库，更新默认设置
        if config.default == old_name:
            config.default = new_name

        self._config = config
        return self._save()

    def update_last_used(self, name: str) -> bool:
        """更新知识库最后使用时间（5分钟内不重复写入）"""
        config = self._load()

        if name in config.knowledge_bases:
            existing = config.knowledge_bases[name].last_used
            if existing:
                try:
                    last_time = datetime.fromisoformat(existing)
                    if last_time.tzinfo is not None:
                        last_time = last_time.replace(tzinfo=None)
                    elapsed = (datetime.now() - last_time).total_seconds()
                    if 0 <= elapsed < 300:
                        return True
                except (ValueError, TypeError) as e:
                    logger.warning(f"Invalid last_used format for '{name}': {e}")
            config.knowledge_bases[name].last_used = datetime.now().isoformat()
            self._config = config
            return self._save()

        return False

    def get_auto_summary_config(self) -> AutoSummaryConfig:
        """获取自动总结配置"""
        return self._load().auto_summary

    def update_auto_summary_config(self, **changes: Any) -> bool:
        """更新自动总结配置中的若干字段，未传入的字段保持原样"""
        config = self._load()
        current = asdict(config.auto_summary)
        current.update({k: v for k, v in changes.items() if k in current})
        config.auto_summary = AutoSummaryConfig.from_dict(current)
        self._config = config
        return self._save()

    def get_fragment_capture_config(self) -> FragmentCaptureConfig:
        """获取碎片采集配置"""
        return self._load().fragment_capture

    def update_fragment_capture_config(self, **changes: Any) -> bool:
        """更新碎片采集配置中的若干字段，未传入的字段保持原样"""
        config = self._load()
        current = asdict(config.fragment_capture)
        current.update({k: v for k, v in changes.items() if k in current})
        config.fragment_capture = FragmentCaptureConfig.from_dict(current)
        self._config = config
        return self._save()

    def get_gem_synthesis_config(self) -> GemSynthesisConfig:
        """获取 L3 宝石合成配置"""
        return self._load().gem_synthesis

    def update_gem_synthesis_config(self, **changes: Any) -> bool:
        """更新宝石合成配置中的若干字段，未传入的字段保持原样"""
        config = self._load()
        current = asdict(config.gem_synthesis)
        current.update({k: v for k, v in changes.items() if k in current})
        config.gem_synthesis = GemSynthesisConfig.from_dict(current)
        self._config = config
        return self._save()

    def get_note_add_config(self) -> NoteAddConfig:
        """读取 add 防重配置"""
        return self._load().note_add

    def update_note_add_config(self, **changes: Any) -> bool:
        """更新 add 防重配置中的若干字段，未传入的字段保持原样"""
        config = self._load()
        current = asdict(config.note_add)
        current.update({k: v for k, v in changes.items() if k in current})
        config.note_add = NoteAddConfig.from_dict(current)
        self._config = config
        return self._save()

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


# 全局配置管理器实例
_global_config_manager: Optional[GlobalConfigManager] = None


def get_global_config_manager() -> GlobalConfigManager:
    """获取全局配置管理器实例"""
    global _global_config_manager
    if _global_config_manager is None:
        _global_config_manager = GlobalConfigManager()
    return _global_config_manager
