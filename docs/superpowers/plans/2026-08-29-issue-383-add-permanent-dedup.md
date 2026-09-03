# #383 add permanent 防重 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `jfox add --type permanent` 落库前双通道查重（标题 + embedding）命中即拒绝，`--json` 模式输出纯净化。

**Architecture:** 新模块 `jfox/add_dedup.py` 承载查重闸门（复用 `gem_synth/dedup.py` 的 `dedup_check`/`upsert_dedup`，embedding 通道用 `is_daemon_running` 前置闸门防本地模型加载），`cli.py` 的 `add()` 挂钩子 + `--force` 逃生舱，`global_config.py` 加 `NoteAddConfig`，CLI 入口对 JSON 模式抑制 INFO 日志。

**Tech Stack:** Python 3.10+ / Typer / pytest。无新依赖。

**Spec:** `docs/superpowers/specs/2026-08-29-issue-383-add-permanent-dedup-design.md`

## Global Constraints

- 行宽 100 字符，black 格式，ruff 检查通过
- 注释用中文，commit message 用英文 conventional commits（feat/fix/test/chore/docs）
- 快速测试不得加载真实 embedding 模型（用 stub backend / monkeypatch），不得写真实 `~/.zk_config.json` / `~/.zettelkasten/synthesis_log.db`
- `git add` 按文件列出，禁止 `git add -A` / `git add .`
- Work from: `/home/elling/git-repo/github/jfox/.pi/worktrees/issue-383-add-permanent-dedup`（禁止碰主仓 checkout）

---

### Task 1: NoteAddConfig 配置模型

**Files:**

- Modify: `jfox/global_config.py`（GemSynthesisConfig 类之后、GlobalConfig 之前插入新类；GlobalConfig 加字段；manager 加方法）
- Test: `tests/unit/test_note_add_config.py`

**Interfaces:**

- Consumes: 无（首个任务）
- Produces: `NoteAddConfig`（字段 `dedup_enabled: bool = True`、`title_dedup: bool = True`、`embedding_dedup: bool = True`、`dedup_threshold: float = 0.95`；方法 `to_dict()`、`from_dict(data)`）；`GlobalConfig.note_add` 字段；`GlobalConfigManager.get_note_add_config() -> NoteAddConfig`、`update_note_add_config(**changes) -> bool`

- [ ] **Step 1: Write the failing test**

```python
"""
测试类型: 单元测试
目标模块: jfox.global_config.NoteAddConfig
预估耗时: < 1秒
"""

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.global_config import GlobalConfig, NoteAddConfig


class TestNoteAddConfig:
    def test_defaults_all_on(self):
        cfg = NoteAddConfig()
        assert cfg.dedup_enabled is True
        assert cfg.title_dedup is True
        assert cfg.embedding_dedup is True
        assert cfg.dedup_threshold == 0.95

    def test_from_dict_none_returns_default(self):
        assert NoteAddConfig.from_dict(None).dedup_enabled is True
        assert NoteAddConfig.from_dict({}).dedup_threshold == 0.95

    def test_roundtrip(self):
        cfg = NoteAddConfig(dedup_enabled=False, dedup_threshold=0.9)
        cfg2 = NoteAddConfig.from_dict(cfg.to_dict())
        assert cfg2.dedup_enabled is False
        assert cfg2.dedup_threshold == 0.9

    def test_threshold_clamped_to_unit_interval(self):
        assert NoteAddConfig(dedup_threshold=1.5).dedup_threshold == 1.0
        assert NoteAddConfig(dedup_threshold=-0.1).dedup_threshold == 0.0

    def test_threshold_invalid_falls_back_to_default(self):
        assert NoteAddConfig(dedup_threshold=float("nan")).dedup_threshold == 0.95
        assert NoteAddConfig(dedup_threshold=float("inf")).dedup_threshold == 0.95
        assert NoteAddConfig(dedup_threshold=None).dedup_threshold == 0.95
        assert NoteAddConfig(dedup_threshold="high").dedup_threshold == 0.95  # type: ignore

    def test_global_config_roundtrip_contains_note_add(self):
        gc = GlobalConfig()
        d = gc.to_dict()
        assert "note_add" in d
        gc2 = GlobalConfig.from_dict(d)
        assert isinstance(gc2.note_add, NoteAddConfig)
        assert gc2.note_add.dedup_threshold == 0.95

    def test_legacy_config_without_note_add_gets_defaults(self):
        gc = GlobalConfig.from_dict({"default": "default"})
        assert gc.note_add.dedup_enabled is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_note_add_config.py -v`
Expected: FAIL，`ImportError: cannot import name 'NoteAddConfig'`

- [ ] **Step 3: Write minimal implementation**

在 `jfox/global_config.py` 的 `class GemSynthesisConfig` 定义结束之后、`class GlobalConfig` 之前插入（照抄 GemSynthesisConfig 的 sanitize 模式；文件顶部已有 `math`、`asdict`、`dataclass`、`field`、`Dict`、`Any`、`Optional` 导入）：

```python
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
        if not data:
            return cls()
        # 只取已知键，忽略多余键（向前兼容）
        return cls(
            dedup_enabled=data.get("dedup_enabled", True),
            title_dedup=data.get("title_dedup", True),
            embedding_dedup=data.get("embedding_dedup", True),
            dedup_threshold=data.get("dedup_threshold", 0.95),
        )
```

`GlobalConfig` 改三处（字段、to_dict、from_dict，均照 gem_synthesis 相邻行模式）：

```python
    # 字段区（gem_synthesis 行后加）
    note_add: NoteAddConfig = field(default_factory=NoteAddConfig)
    # to_dict 里（gem_synthesis 行后加）
    "note_add": self.note_add.to_dict(),
    # from_dict 里（gem_synthesis=... 行后加）
    note_add=NoteAddConfig.from_dict(data.get("note_add")),
```

`GlobalConfigManager` 照 `get_gem_synthesis_config`/`update_gem_synthesis_config`（约 716-725 行）的镜像加两个方法：

```python
    def get_note_add_config(self) -> NoteAddConfig:
        """读取 add 防重配置"""
        return self._load().note_add

    def update_note_add_config(self, **changes: Any) -> bool:
        """更新 add 防重配置（白名单合并，未知键报错由 _save 统一处理）"""
        config = self._load()
        current = asdict(config.note_add)
        current.update(changes)
        config.note_add = NoteAddConfig.from_dict(current)
        return self._save(config)
```

注意：若 `update_gem_synthesis_config` 实际实现与上述模式有出入（如返回值、校验方式），以邻接方法为准做镜像。

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_note_add_config.py -v`
Expected: 7 passed

- [ ] **Step 5: Commit**

```bash
git add jfox/global_config.py tests/unit/test_note_add_config.py
git commit -m "feat(config): add NoteAddConfig for add-path dedup settings (#383)"
```

---

### Task 2: jfox/add_dedup.py 查重模块

**Files:**

- Create: `jfox/add_dedup.py`
- Test: `tests/unit/test_add_dedup.py`

**Interfaces:**

- Consumes: Task 1 的 `NoteAddConfig`（经 `_load_note_add_config()` 间接读取）；`jfox.gem_synth.dedup` 的 `dedup_check(kb, content, threshold) -> Optional[DedupHit]`、`upsert_dedup(kb, note_id, note_type, content) -> bool`、`DedupStore(db_path)`、`set_store()`、`_resolve_kb_name(kb)`；`jfox.note_index.get_note_index(cfg) -> NoteIndex`（`get_all_meta() -> List[NoteMeta]`、`find_by_id(id) -> Optional[NoteMeta]`，NoteMeta 有 `.id/.title/.archived`）
- Produces: `DuplicateNoteError(matched_id, matched_title, matched_by, score)`（`matched_by` 取 `"title"` 或 `"embedding"`）、`check_add_duplicate(title, content, *, cfg=None) -> None`（命中 raise，其余放行）、`record_added_permanent(note_id, content, *, cfg=None) -> None`、模块级可 monkeypatch 的 `_daemon_available()` / `_load_note_add_config()`、常量 `_EMBED_DEDUP_MIN_CHARS = 50`

- [ ] **Step 1: Write the failing test**

```python
"""
测试类型: 单元测试
目标模块: jfox.add_dedup
预估耗时: < 2秒

不依赖真实 embedding 模型 / daemon：
- embedding 通道用确定性 stub backend（同文本 → 同单位向量 → cosine=1.0）
- dedup store 用 set_store 注入临时路径
- 配置/daemon 探测用 monkeypatch，不写真实 ~/.zk_config.json
"""

import hashlib
from datetime import datetime

import numpy as np
import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.add_dedup import (
    DuplicateNoteError,
    check_add_duplicate,
    record_added_permanent,
)
from jfox.config import ZKConfig
from jfox.global_config import NoteAddConfig
from jfox.gem_synth.dedup import DedupStore, set_store
from jfox.models import Note, NoteType

_EXISTING_CONTENT = "这是一段已经存在的永久笔记正文，用于验证 embedding 通道，长度超过五十个字符。"


def _deterministic_encode(text: str) -> np.ndarray:
    """同文本 → 同单位向量（cosine=1.0）；不同文本 → 近正交。"""
    parts = [hashlib.sha256(f"{i}:{text}".encode()).digest()[:8] for i in range(4)]
    vec = np.concatenate([np.frombuffer(p, dtype=np.uint8) for p in parts]).astype(np.float32)
    return vec / (np.linalg.norm(vec) + 1e-12)


class _StubBackend:
    """替换 embedding_backend.get_backend 的确定性桩（duck-typing encode_single）。"""

    def encode_single(self, text: str):
        return _deterministic_encode(text)


@pytest.fixture
def kb_cfg(temp_kb):
    """含一条 permanent 笔记的临时知识库（返回 ZKConfig，标题中英文各一）。"""
    cfg = ZKConfig(base_dir=temp_kb)
    cfg.ensure_dirs()
    notes = [
        Note(
            id="20260829001",
            title="已有笔记",
            content=_EXISTING_CONTENT,
            type=NoteType.PERMANENT,
            created=datetime(2026, 8, 29, 0, 1),
            updated=datetime(2026, 8, 29, 0, 1),
        ),
        Note(
            id="20260829002",
            title="Zoloz K8s Namespaces",
            content="english titled note body",
            type=NoteType.PERMANENT,
            created=datetime(2026, 8, 29, 0, 2),
            updated=datetime(2026, 8, 29, 0, 2),
        ),
    ]
    for n in notes:
        note_dir = cfg.notes_dir / n.type.value
        note_dir.mkdir(parents=True, exist_ok=True)
        (note_dir / f"{n.id}.md").write_text(n.to_markdown(), encoding="utf-8")
    return cfg


@pytest.fixture
def archived_kb(temp_kb):
    """同标题笔记只有一条且 frontmatter 标记 archived: true 的临时知识库。"""
    cfg = ZKConfig(base_dir=temp_kb)
    cfg.ensure_dirs()
    note_dir = cfg.notes_dir / "permanent"
    note_dir.mkdir(parents=True, exist_ok=True)
    md = (
        "---\n"
        "id: '20260829009'\n"
        "title: 归档旧笔记\n"
        "type: permanent\n"
        "created: '2026-08-29T00:09:00'\n"
        "updated: '2026-08-29T00:09:00'\n"
        "archived: true\n"
        "tags: []\n"
        "links: []\n"
        "backlinks: []\n"
        "---\n\n# 归档旧笔记\n\n正文。\n"
    )
    (note_dir / "20260829009.md").write_text(md, encoding="utf-8")
    return cfg


@pytest.fixture
def dedup_env(tmp_path, monkeypatch):
    """临时 dedup store + daemon 探测 True + stub backend + 默认配置。"""
    store = DedupStore(db_path=tmp_path / "synthesis_test.db")
    set_store(store)
    monkeypatch.setattr("jfox.add_dedup._daemon_available", lambda: True)
    monkeypatch.setattr("jfox.embedding_backend.get_backend", lambda: _StubBackend())
    monkeypatch.setattr("jfox.add_dedup._load_note_add_config", lambda: NoteAddConfig())
    yield store
    set_store(None)
    store.close()


class TestTitleChannel:
    def test_same_title_blocked(self, kb_cfg, dedup_env):
        with pytest.raises(DuplicateNoteError) as ei:
            check_add_duplicate("已有笔记", "完全不同的新正文内容" * 3, cfg=kb_cfg)
        assert ei.value.matched_by == "title"
        assert ei.value.matched_id == "20260829001"
        assert ei.value.score is None

    def test_title_case_insensitive(self, kb_cfg, dedup_env):
        with pytest.raises(DuplicateNoteError) as ei:
            check_add_duplicate("ZOLOZ K8S NAMESPACES", "新正文" * 10, cfg=kb_cfg)
        assert ei.value.matched_id == "20260829002"

    def test_archived_title_not_blocked(self, archived_kb, dedup_env):
        check_add_duplicate("归档旧笔记", "全新正文" * 10, cfg=archived_kb)  # 不抛即通过

    def test_different_title_passes(self, kb_cfg, dedup_env):
        check_add_duplicate("全新标题", _EXISTING_CONTENT + "改写若干字避免逐字相同", cfg=kb_cfg)


class TestEmbeddingChannel:
    def test_same_content_different_title_blocked(self, kb_cfg, dedup_env):
        record_added_permanent("20260829001", _EXISTING_CONTENT, cfg=kb_cfg)
        with pytest.raises(DuplicateNoteError) as ei:
            check_add_duplicate("全新标题", _EXISTING_CONTENT, cfg=kb_cfg)
        assert ei.value.matched_by == "embedding"
        assert ei.value.matched_id == "20260829001"
        assert ei.value.score >= 0.95

    def test_different_content_passes(self, kb_cfg, dedup_env):
        record_added_permanent("20260829001", _EXISTING_CONTENT, cfg=kb_cfg)
        check_add_duplicate("全新标题", "毫不相关的另一段长正文" * 5, cfg=kb_cfg)

    def test_short_content_skips_embedding(self, kb_cfg, dedup_env):
        short = "短内容"  # ≤50 字符，embedding 通道按设计跳过
        record_added_permanent("20260829001", short, cfg=kb_cfg)
        check_add_duplicate("全新标题", short, cfg=kb_cfg)  # 不抛即通过

    def test_daemon_down_skips_embedding(self, kb_cfg, dedup_env, monkeypatch):
        record_added_permanent("20260829001", _EXISTING_CONTENT, cfg=kb_cfg)
        monkeypatch.setattr("jfox.add_dedup._daemon_available", lambda: False)
        check_add_duplicate("全新标题", _EXISTING_CONTENT, cfg=kb_cfg)  # 降级放行

    def test_title_channel_disabled_uses_embedding_only(self, kb_cfg, dedup_env, monkeypatch):
        monkeypatch.setattr(
            "jfox.add_dedup._load_note_add_config",
            lambda: NoteAddConfig(title_dedup=False),
        )
        record_added_permanent("20260829001", _EXISTING_CONTENT, cfg=kb_cfg)
        # 同标题 + 同正文（已灌表）：标题通道关闭后由 embedding 通道兜住
        with pytest.raises(DuplicateNoteError) as ei:
            check_add_duplicate("已有笔记", _EXISTING_CONTENT, cfg=kb_cfg)
        assert ei.value.matched_by == "embedding"


class TestConfigSwitches:
    def test_dedup_disabled_passes_everything(self, kb_cfg, dedup_env, monkeypatch):
        monkeypatch.setattr(
            "jfox.add_dedup._load_note_add_config",
            lambda: NoteAddConfig(dedup_enabled=False),
        )
        record_added_permanent("20260829001", _EXISTING_CONTENT, cfg=kb_cfg)
        check_add_duplicate("已有笔记", _EXISTING_CONTENT, cfg=kb_cfg)  # 不抛即通过


class TestGateNotRoadblock:
    def test_internal_error_passes(self, kb_cfg, dedup_env, monkeypatch):
        def _boom(cfg=None):
            raise RuntimeError("index exploded")

        monkeypatch.setattr("jfox.note_index.get_note_index", _boom)
        check_add_duplicate("已有笔记", _EXISTING_CONTENT, cfg=kb_cfg)  # 放行


class TestRecordAddedPermanent:
    def test_daemon_down_is_noop(self, kb_cfg, dedup_env, monkeypatch):
        monkeypatch.setattr("jfox.add_dedup._daemon_available", lambda: False)
        record_added_permanent("20260829001", _EXISTING_CONTENT, cfg=kb_cfg)
        assert dedup_env.count() == 0

    def test_writes_to_store(self, kb_cfg, dedup_env):
        record_added_permanent("20260829001", _EXISTING_CONTENT, cfg=kb_cfg)
        assert dedup_env.count() == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_add_dedup.py -v`
Expected: FAIL，`ModuleNotFoundError: No module named 'jfox.add_dedup'`

- [ ] **Step 3: Write minimal implementation**

创建 `jfox/add_dedup.py`：

```python
"""add 落库防重（#383）：permanent 笔记创建前的双通道查重闸门。

通道一（标题）：非 archived 同标题（大小写不敏感、不限类型）→ 拦截。
    wiki-link 按标题解析，同标题笔记会导致链接分裂，所以不限笔记类型。
通道二（embedding）：复用 gem_synth.dedup 的正文余弦查重，仅 embedding
    daemon 可用时生效——daemon 不在时 dedup._embed 会退回本地模型加载
    （秒级延迟），必须用 is_daemon_running 前置闸门挡掉。

设计原则：防重是闸门不是路障——除明确命中外，任何内部异常都放行。
"""

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# 短文本跳过 embedding 查重：区分度差，标题通道已兜底（#383 建议值）
_EMBED_DEDUP_MIN_CHARS = 50


class DuplicateNoteError(Exception):
    """add 防重命中。matched_by: "title" | "embedding"；score 仅 embedding 通道有值。"""

    def __init__(
        self,
        matched_id: str,
        matched_title: str,
        matched_by: str,
        score: Optional[float] = None,
    ):
        self.matched_id = matched_id
        self.matched_title = matched_title
        self.matched_by = matched_by
        self.score = score
        detail = f"cosine={score:.3f}" if score is not None else "title match"
        super().__init__(f"已存在重复笔记[{matched_by}] {matched_id} {matched_title!r} ({detail})")


def _load_note_add_config():
    """读取 add 防重全局配置。独立函数便于测试 monkeypatch（避免写真实配置文件）。"""
    from .global_config import get_global_config_manager

    return get_global_config_manager().get_note_add_config()


def _daemon_available() -> bool:
    """embedding daemon 是否在跑。独立函数便于测试 monkeypatch。"""
    try:
        from .daemon.process import is_daemon_running

        return is_daemon_running()
    except Exception:
        return False


def check_add_duplicate(
    title: Optional[str],
    content: str,
    *,
    cfg=None,
) -> None:
    """permanent 落库前查重；命中 raise DuplicateNoteError，其余情况一律放行。

    cfg: 可选 ZKConfig（测试注入临时知识库）；None 用当前 use_kb 上下文。
    """
    try:
        conf = _load_note_add_config()
        if not conf.dedup_enabled:
            return

        from .note_index import get_note_index

        idx = get_note_index(cfg)

        # 通道一：标题（零成本，先查；O(N) 扫描——_by_title 单值映射在
        # 同标题多条 + archived 混存时不可靠，add 路径已有同量级扫描）
        if title and conf.title_dedup:
            title_lower = title.lower()
            for meta in idx.get_all_meta():
                if meta.archived:
                    continue
                if meta.title.lower() == title_lower:
                    raise DuplicateNoteError(meta.id, meta.title, "title")

        # 通道二：正文 embedding（仅 daemon 可用时，防本地模型加载）
        if conf.embedding_dedup and len(content.strip()) > _EMBED_DEDUP_MIN_CHARS:
            if _daemon_available():
                from .gem_synth.dedup import _resolve_kb_name, dedup_check

                kb_name = cfg.base_dir.name if cfg is not None else _resolve_kb_name(None)
                hit = dedup_check(kb_name, content, threshold=conf.dedup_threshold)
                if hit is not None:
                    matched_meta = idx.find_by_id(hit.note_id)
                    matched_title = matched_meta.title if matched_meta else ""
                    raise DuplicateNoteError(
                        hit.note_id, matched_title, "embedding", score=hit.score
                    )
    except DuplicateNoteError:
        raise
    except Exception as e:  # 闸门不是路障：查重自身故障一律放行
        logger.warning("add 防重检查失败，放行: %s", e)
        return


def record_added_permanent(note_id: str, content: str, *, cfg=None) -> None:
    """落库成功后灌 dedup 表（best-effort），让后续 add 与 gem_synth 都能查到。

    仅 daemon 可用时执行（理由同 check_add_duplicate 通道二）；失败仅 warning。
    """
    try:
        if not _daemon_available():
            return
        from .gem_synth.dedup import _resolve_kb_name, upsert_dedup

        kb_name = cfg.base_dir.name if cfg is not None else _resolve_kb_name(None)
        upsert_dedup(kb_name, note_id, "permanent", content)
    except Exception as e:
        logger.warning("add 后 dedup 灌表失败 note=%s: %s", note_id, e)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_add_dedup.py -v`
Expected: 13 passed

- [ ] **Step 5: Commit**

```bash
git add jfox/add_dedup.py tests/unit/test_add_dedup.py
git commit -m "feat(dedup): add add-path duplicate gate module (#383)"
```

---

### Task 3: cli.py add 命令集成

**Files:**

- Modify: `jfox/cli.py`（`add()` 约 692 行加 `--force`；`_add_note_impl()` 约 454 行加 `force` 形参 + 两处钩子；`add()` 异常分支加 DuplicateNoteError 处理）
- Test: `tests/test_add_dedup_cli.py`

**Interfaces:**

- Consumes: Task 2 的 `DuplicateNoteError`（属性 `.matched_id/.matched_title/.matched_by/.score`）、`check_add_duplicate(title, content)`、`record_added_permanent(note_id, content)`
- Produces: CLI 行为——`jfox add --type permanent` 命中防重时 JSON 输出 `{"success": false, "skipped": "duplicate", "duplicate": {"matched_id", "matched_title", "matched_by", "score"}}` 且退出码 1；`--force` 跳过查重强制落库

- [ ] **Step 1: Write the failing test**

```python
"""
测试类型: 集成测试（CLI 子进程）
目标: jfox add permanent 防重端到端（#383）

子进程无 daemon → embedding 通道自动降级，标题通道覆盖主路径。
"""

import pytest

pytestmark = [pytest.mark.integration]


class TestAddDedupCLI:
    def test_title_duplicate_blocked(self, cli):
        r1 = cli._run("add", "第一条内容", "--title", "Dup-Title-X", "--type", "permanent")
        assert r1.success
        r2 = cli._run("add", "第二条不同内容", "--title", "Dup-Title-X", "--type", "permanent")
        assert r2.returncode == 1
        assert r2.data is not None
        assert r2.data["success"] is False
        assert r2.data["skipped"] == "duplicate"
        assert r2.data["duplicate"]["matched_by"] == "title"
        assert r2.data["duplicate"]["matched_id"] == r1.data["note"]["id"]

    def test_force_bypasses_duplicate(self, cli):
        r1 = cli._run("add", "内容一", "--title", "Dup-Title-F", "--type", "permanent")
        assert r1.success
        r2 = cli._run(
            "add", "内容二", "--title", "Dup-Title-F", "--type", "permanent", "--force"
        )
        assert r2.success
        assert r2.data["success"] is True

    def test_fleeting_not_checked(self, cli):
        cli._run("add", "fleeting 内容", "--title", "Dup-Title-G")
        r2 = cli._run("add", "fleeting 内容", "--title", "Dup-Title-G")
        assert r2.success

    def test_different_title_permanent_passes(self, cli):
        cli._run("add", "正文一", "--title", "Dup-Title-H", "--type", "permanent")
        r2 = cli._run("add", "正文二", "--title", "Dup-Title-H2", "--type", "permanent")
        assert r2.success
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_add_dedup_cli.py -v`
Expected: `test_title_duplicate_blocked` FAIL（第二次 add 仍然 success）；其余三条 PASS（它们断言现状行为，是回归保护）

- [ ] **Step 3: Write minimal implementation**

`jfox/cli.py` 三处改动：

(a) `add()` 命令签名（`topic` 参数行后）加：

```python
    force: bool = typer.Option(
        False, "--force", help="跳过防重检查，强制创建（迁移/回填/明确要重复时用）"
    ),
```

调用改为 `_add_note_impl(content, title, note_type, tags, source, output_format, template, topic, force)`。

`add()` 的 `try` 块内、`except typer.Exit:` 之后、`except Exception as e:` 之前插入专属分支：

```python
    except DuplicateNoteError as e:
        dup_info = {
            "matched_id": e.matched_id,
            "matched_title": e.matched_title,
            "matched_by": e.matched_by,
            "score": e.score,
        }
        if output_format == "json":
            print(
                output_json(
                    {"success": False, "skipped": "duplicate", "duplicate": dup_info}
                )
            )
        else:
            console.print(
                f"[yellow]⚠[/yellow] 已存在重复笔记（{e.matched_by}）："
                f"[bold]{e.matched_title}[/bold]（id: {e.matched_id}），已跳过创建。"
                "使用 --force 可强制创建。"
            )
        raise typer.Exit(1)
```

`cli.py` 顶部 import 区（与其他 jfox 子模块 import 相邻处）加：

```python
from .add_dedup import DuplicateNoteError
```

(b) `_add_note_impl()` 签名加形参 `force: bool = False`（追加到 `topic` 之后），并在「session 类型必须提供 --topic」检查之后、「从内容中提取维基链接」之前插入：

```python
    # #383 permanent 落库前防重（--force 跳过；内部故障一律放行）
    if nt == NoteType.PERMANENT and not force:
        from .add_dedup import check_add_duplicate

        check_add_duplicate(title, content)
```

(c) `_add_note_impl()` 的 `if note.save_note(new_note):` 块内、`result = {...}` 构造之前（backlink 回填逻辑完成后）加：

```python
        # #383 落库成功后灌 dedup 表（daemon 可用时），后续 add 与 gem_synth 都能查到
        if nt == NoteType.PERMANENT:
            from .add_dedup import record_added_permanent

            record_added_permanent(new_note.id, content)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_add_dedup_cli.py -v`
Expected: 4 passed

再跑既有 add 相关测试确认无回归：

Run: `uv run pytest tests/test_core_workflow.py -m "not slow and not embedding" -q`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/cli.py tests/test_add_dedup_cli.py
git commit -m "feat(add): duplicate gate for permanent notes with --force escape (#383)"
```

---

### Task 4: --json 模式日志纯净化（根因 A）

**Files:**

- Modify: `jfox/cli.py`（`main()` 约 4104 行加 JSON 检测；`_add_note_impl()` JSON 分支的 dim_warning stderr print 改并入结果字段）
- Test: `tests/unit/test_json_mode.py`（新建）+ `tests/test_add_dedup_cli.py` 追加 TestJsonPurity 类

**Interfaces:**

- Consumes: 无
- Produces: `_json_mode_requested(argv: List[str]) -> bool`；CLI 行为——JSON 模式下 root logger 提到 WARNING，`--json 2>&1` 合流后正常成功路径为单段合法 JSON

- [ ] **Step 1: Write the failing test**

`tests/unit/test_json_mode.py`：

```python
"""
测试类型: 单元测试
目标模块: jfox.cli._json_mode_requested
预估耗时: < 1秒
"""

import pytest

pytestmark = [pytest.mark.unit, pytest.mark.fast]

from jfox.cli import _json_mode_requested


class TestJsonModeRequested:
    @pytest.mark.parametrize(
        "argv,expected",
        [
            (["jfox", "add", "--json"], True),
            (["jfox", "search", "x", "--json"], True),
            (["jfox", "add", "-f", "json"], True),
            (["jfox", "add", "--format", "json"], True),
            (["jfox", "add", "--format=json"], True),
            (["jfox", "add", "--format", "table"], False),
            (["jfox", "add"], False),
            (["jfox", "list"], False),
        ],
    )
    def test_detection(self, argv, expected):
        assert _json_mode_requested(argv) is expected
```

`tests/test_add_dedup_cli.py` 末尾追加：

```python
import json
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent


class TestJsonPurity:
    def test_add_json_output_pure_even_with_2to1_merge(self, cli):
        """--json 2>&1 合流后输出仍是单段合法 JSON（#383 根因 A 回归测试）。"""
        cmd = [
            sys.executable,
            "-m",
            "jfox",
            "add",
            "纯净输出测试正文",
            "--title",
            "Json-Pure-1",
            "--type",
            "permanent",
            "--json",
            "--kb",
            cli.kb_name,
        ]
        r = subprocess.run(
            cmd, capture_output=True, text=True, stderr=subprocess.STDOUT, cwd=str(REPO_ROOT)
        )
        assert r.returncode == 0
        data = json.loads(r.stdout)  # 混入任何 INFO 行都会在这里抛 JSONDecodeError
        assert data["success"] is True
        assert "Saved note" not in r.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_json_mode.py tests/test_add_dedup_cli.py::TestJsonPurity -v`
Expected: `_json_mode_requested` 导入失败（ImportError）；TestJsonPurity FAIL（stdout 含 INFO 日志行 → JSONDecodeError）

- [ ] **Step 3: Write minimal implementation**

`jfox/cli.py`（`main()` 之前）加：

```python
def _json_mode_requested(argv: List[str]) -> bool:
    """检测 argv 是否请求 JSON 输出（--json / -f json / --format json / --format=json）。

    日志 handler 本就走 stderr，但管道 `jfox ... --json 2>&1 | jq` 会把 stderr
    合进被解析流——INFO 噪声（Saved note / 索引写入等）让对端 JSON 解析失败，
    agent 误判失败后 fallback 重跑产生重复笔记（#383 根因 A）。JSON 模式下
    把 root logger 提到 WARNING，保证正常成功路径合流后仍是纯 JSON。
    """
    if "--json" in argv or "--format=json" in argv:
        return True
    for flag in ("-f", "--format"):
        if flag in argv:
            i = argv.index(flag)
            if i + 1 < len(argv) and argv[i + 1] == "json":
                return True
    return False
```

`main()` 开头（`os.environ.setdefault(...)` 之前）加：

```python
    import sys

    # JSON 模式抑制 INFO 日志（#383 根因 A）
    if _json_mode_requested(sys.argv):
        logging.getLogger().setLevel(logging.WARNING)
```

（`logging` 顶部已有；`sys` 顶部已有则不重复 import。）

`_add_note_impl()` 的 `if output_format == "json":` 分支，把「先 print JSON 再 stderr print dim_warning」改为「dim_warning 并入结果字段后一次输出」：

```python
        if output_format == "json":
            dim_warning = get_vector_store().last_dimension_warning
            if dim_warning:
                # 并入 JSON 字段而非 stderr print：stderr 在 2>&1 管道里同样污染解析流
                result["vector_dimension_warning"] = dim_warning
            print(output_json(result))
```

（原 JSON 分支里 `from .vector_store import get_vector_store` 与 dim_warning 获取逻辑保持，仅移动位置；table 分支不动。）

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/unit/test_json_mode.py tests/test_add_dedup_cli.py -v`
Expected: 全部 PASS

- [ ] **Step 5: Commit**

```bash
git add jfox/cli.py tests/unit/test_json_mode.py tests/test_add_dedup_cli.py
git commit -m "fix(cli): pure JSON output in json mode by quieting INFO logs (#383 root cause A)"
```

---

### Task 5: conftest 隔离 JFOX_SYNTHESIS_DB

**Files:**

- Modify: `tests/conftest.py`（顶部 ZK_KB_ROOT 设置之后加一行）
- Test: `tests/unit/test_add_dedup.py` 追加一个测试

**Interfaces:**

- Consumes: `jfox.gem_synth.paths.default_synthesis_db_path()` 已支持 `JFOX_SYNTHESIS_DB` env 覆盖
- Produces: 测试进程与 CLI 子进程的 DedupStore 默认路径都指向临时目录，不再写真实 `~/.zettelkasten/synthesis_log.db`

- [ ] **Step 1: Write the failing test**

`tests/unit/test_add_dedup.py` 末尾追加：

```python
def test_synthesis_db_env_override(tmp_path, monkeypatch):
    """JFOX_SYNTHESIS_DB 覆盖 synthesis db 路径（conftest 全局隔离的依据）。"""
    from jfox.gem_synth.paths import default_synthesis_db_path

    p = tmp_path / "s.db"
    monkeypatch.setenv("JFOX_SYNTHESIS_DB", str(p))
    assert default_synthesis_db_path() == p.resolve()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/unit/test_add_dedup.py::test_synthesis_db_env_override -v`
Expected: PASS（此测试验证 paths.py 既有行为，作为 conftest 改动的行为锚点；若 FAIL 说明 paths.py 行为与预期不符，停下排查）

- [ ] **Step 3: Modify conftest**

`tests/conftest.py` 顶部 `os.environ["ZK_KB_ROOT"] = str(_TEST_ROOT)` 之后加：

```python
# 隔离真实 synthesis db（#383 关联项）：测试进程与 CLI 子进程都指向临时路径，
# 防 DedupStore 默认单例写真实 ~/.zettelkasten/synthesis_log.db
os.environ.setdefault("JFOX_SYNTHESIS_DB", str(_TEST_ROOT / "synthesis_test.db"))
```

- [ ] **Step 4: Run tests to verify no regression**

Run: `uv run pytest tests/unit/test_add_dedup.py tests/unit/test_note_add_config.py -v && uv run pytest tests/unit/ -m "fast" -q`
Expected: 全部 PASS（gem_synth 相关单测若有失败，检查是否依赖真实 db 路径——不该依赖）

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/unit/test_add_dedup.py
git commit -m "test: isolate JFOX_SYNTHESIS_DB to temp dir in conftest (#383)"
```

---

### Task 6: README 文档

**Files:**

- Modify: `README.md`（`jfox add` 命令文档节）

**Interfaces:**

- Consumes: Task 3/4 的最终行为
- Produces: 用户可发现的 `--force` 与防重行为说明

- [ ] **Step 1: 定位并修改**

在 `README.md` 中 grep `jfox add` 的命令文档节（参数表或示例处），在参数说明中加入：

```markdown
| `--force` | 跳过防重检查，强制创建（迁移/回填/明确要重复时用） |
```

并在该节合适位置加一段行为说明：

```markdown
**防重保护**：`--type permanent` 落库前会做双通道查重——① 标题通道：已存在
（非归档）同标题笔记即拦截；② 正文通道：embedding daemon 在跑时按正文余弦
相似度（阈值 0.95，可在全局配置 `note_add.dedup_threshold` 调整）拦截近逐字
重复。命中时不落库，JSON 输出 `{"success": false, "skipped": "duplicate", ...}`
且退出码为 1。存量历史笔记可用 `jfox gem-synth dedup-backfill` 灌入查重库。
```

- [ ] **Step 2: lint 验证**

Run: `npx --yes markdownlint-cli2`
Expected: 无新增违规（README.md 通过）

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: document add dedup gate and --force flag (#383)"
```

---

## 收尾（全部 Task 完成后）

1. `uv run ruff check jfox/ tests/` + `uv run black --check jfox/ tests/`
2. `uv run pytest tests/unit/test_note_add_config.py tests/unit/test_add_dedup.py tests/unit/test_json_mode.py tests/test_add_dedup_cli.py -v` 全绿
3. `uv run pytest tests/ -m "not embedding and not slow" -q` 快速套无回归（若个别既有测试因环境失败，对比 main 分支同命令确认非本 PR 引入）
4. 后续走 github-issue-driven 步 8-10：本地 CR → PR → Zima CR → 合并
