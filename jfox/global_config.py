"""
全局配置管理 - 多知识库支持

管理 ~/.zk_config.json，存储所有知识库的注册信息和默认设置
"""

import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


DEFAULT_CONFIG_PATH = Path.home() / ".zk_config.json"
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
        # 运行时 stop_event，由 daemon loop 注入，不序列化
        object.__setattr__(self, "_stop_event", None)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Optional[Dict[str, Any]]) -> "AutoSummaryConfig":
        if not data:
            return cls()
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
        raw_max = data.get("max_content_chars", 500)
        max_content_chars = int(raw_max) if raw_max is not None else 500
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
class GlobalConfig:
    """全局配置"""

    default: str = DEFAULT_KB_NAME
    knowledge_bases: Dict[str, KnowledgeBaseEntry] = field(default_factory=dict)
    auto_summary: AutoSummaryConfig = field(default_factory=AutoSummaryConfig)
    fragment_capture: FragmentCaptureConfig = field(default_factory=FragmentCaptureConfig)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "default": self.default,
            "knowledge_bases": {name: kb.to_dict() for name, kb in self.knowledge_bases.items()},
            "auto_summary": self.auto_summary.to_dict(),
            "fragment_capture": self.fragment_capture.to_dict(),
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


# 全局配置管理器实例
_global_config_manager: Optional[GlobalConfigManager] = None


def get_global_config_manager() -> GlobalConfigManager:
    """获取全局配置管理器实例"""
    global _global_config_manager
    if _global_config_manager is None:
        _global_config_manager = GlobalConfigManager()
    return _global_config_manager
