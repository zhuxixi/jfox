# from_dict 非 dict 设防 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 `~/.zk_config.json` 畸形 section 触发 `_load()` 整体重置并清空 KB 注册表的问题；文件级失败先备份原文件字节再恢复默认配置。

**Architecture:** 三层防御——5 个子配置类 `from_dict()` 顶层 isinstance 守卫（section 级）；`GlobalConfig.from_dict()` 根级/容器级/entry 级守卫（结构级）；`_load()` 根级校验 + traceback 日志 + `.corrupt-*` 字节备份 + `persist` 门控（文件级）。纯解析逻辑与文件恢复 I/O 严格分离。

**Tech Stack:** Python 3.10+ / dataclasses / pytest（parametrize + caplog + tmp_path + monkeypatch）/ uv。

**Spec:** `docs/superpowers/specs/2026-09-09-from-dict-non-dict-guard-design.md`（验收 ID A1-A7，本 plan 每 task 引用）

**Work from:** `/home/elling/git-repo/github/jfox/.pi/worktrees/issue-481-from-dict-non-dict-guard`（下称 `$WT`；所有路径相对 `$WT`）

## Global Constraints

- 生产代码只改 `jfox/global_config.py`；测试只改 `tests/unit/test_global_config.py`（spec §4）
- 不重写字段级解析逻辑；不收窄 `_load()` 的 `except Exception`；不改 `KnowledgeBaseEntry.from_dict()`（spec §7）
- 备份用原始字节（`read_bytes`），不重新序列化；备份文件独占创建（`xb`），冲突重试，不覆盖已有快照（spec §3.4）
- 备份失败必须返回失败状态而非抛异常；`_load()` 据此禁止默认配置覆盖原文件（spec §3.3/§3.4）
- 保留宽 except 恢复能力：JSON 损坏/根级非 dict/未覆盖异常 → warning（含 `exc_info=True`）+ 备份 + 默认配置（spec §2.2）
- 测试不接触真实 `~/.zk_config.json`：一律 `GlobalConfigManager(config_path=tmp_path / "zk_config.json")`（spec §6.2）
- git add 按文件，不用 `git add -A`；commit message 用 conventional commits
- 测试命令一律 `uv run pytest ...`（在 `$WT` 下执行）；快速单文件测试可自主运行，全量/集成测试不自跑

---

### Task 1: 5 个子配置类 `from_dict` 顶层 isinstance 守卫（验收 A1）

**Files:**

- Modify: `jfox/global_config.py`（`BackupConfig.from_dict` ~:86、`AutoSummaryConfig.from_dict` ~:190、`FragmentCaptureConfig.from_dict` ~:263、`PromptCaptureConfig.from_dict` ~:314、`PromptJudgeConfig.from_dict` ~:405，各 1 处守卫行）
- Test: `tests/unit/test_global_config.py`（新增 import + 1 个测试类）

**Interfaces:**

- Consumes: 无（首个 task）
- Produces: 5 个类 `from_dict(Optional[Dict])` 对 truthy 非 dict 输入返回 `cls()`；签名不变，供 Task 2/5 的 manager 级测试依赖

- [ ] **Step 1: 写失败测试**

在 `tests/unit/test_global_config.py` 顶部 import 区补充（保持既有 import 不动）：

```python
from jfox.global_config import BackupConfig
from jfox.global_config import FragmentCaptureConfig
from jfox.global_config import PromptCaptureConfig
from jfox.global_config import PromptJudgeConfig
```

文件末尾追加：

```python
class TestFromDictNonDictSection:
    """A1: truthy 非 dict section 不得炸 from_dict，回该类默认配置。"""

    TRUTHY_NON_DICT = [
        pytest.param("enabled", id="str"),
        pytest.param(1, id="int"),
        pytest.param(["x"], id="list"),
        pytest.param(True, id="bool"),
    ]

    @pytest.mark.parametrize("bad", TRUTHY_NON_DICT)
    def test_backup_config(self, bad):
        cfg = BackupConfig.from_dict(bad)  # type: ignore[arg-type]
        assert cfg == BackupConfig()
        assert cfg.enabled is False and cfg.retain == 7

    @pytest.mark.parametrize("bad", TRUTHY_NON_DICT)
    def test_auto_summary_config(self, bad):
        cfg = AutoSummaryConfig.from_dict(bad)  # type: ignore[arg-type]
        assert cfg == AutoSummaryConfig()
        assert cfg.enabled is False and cfg.interval_minutes == 30

    @pytest.mark.parametrize("bad", TRUTHY_NON_DICT)
    def test_fragment_capture_config(self, bad):
        cfg = FragmentCaptureConfig.from_dict(bad)  # type: ignore[arg-type]
        assert cfg == FragmentCaptureConfig()
        assert cfg.enabled is True and cfg.max_content_chars == 500

    @pytest.mark.parametrize("bad", TRUTHY_NON_DICT)
    def test_prompt_capture_config(self, bad):
        cfg = PromptCaptureConfig.from_dict(bad)  # type: ignore[arg-type]
        assert cfg == PromptCaptureConfig()
        assert cfg.enabled is True and cfg.endpoint_url == "http://127.0.0.1:18700/api/prompt"

    @pytest.mark.parametrize("bad", TRUTHY_NON_DICT)
    def test_prompt_judge_config(self, bad):
        cfg = PromptJudgeConfig.from_dict(bad)  # type: ignore[arg-type]
        assert cfg == PromptJudgeConfig()
        assert cfg.runner == "pi" and cfg.model == "ollama/deepseek-v4-pro:0813-cloud"

    @pytest.mark.parametrize("falsy", [pytest.param(None, id="none"), pytest.param({}, id="empty-dict")])
    def test_falsy_inputs_still_return_defaults(self, falsy):
        """None/空 dict 是既有行为，回归保护。"""
        assert BackupConfig.from_dict(falsy) == BackupConfig()
        assert AutoSummaryConfig.from_dict(falsy) == AutoSummaryConfig()
        assert FragmentCaptureConfig.from_dict(falsy) == FragmentCaptureConfig()
        assert PromptCaptureConfig.from_dict(falsy) == PromptCaptureConfig()
        assert PromptJudgeConfig.from_dict(falsy) == PromptJudgeConfig()
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd $WT && uv run pytest tests/unit/test_global_config.py::TestFromDictNonDictSection -q`
Expected: 20 个 param 用例 FAIL（`AttributeError: ... object has no attribute 'get'`），2 个 falsy 用例 PASS

- [ ] **Step 3: 最小实现**

`jfox/global_config.py` 中 5 处，每处把：

```python
        if not data:
            return cls()
```

改成（各处注释第二行按所属类微调，模式一致）：

```python
        # 非 dict 值（如手改配置写成字符串）回默认：data.get 会抛 AttributeError，
        # 上层 _load 的宽 except 会重建默认 GlobalConfig，有清空注册表的风险（#481）
        if not isinstance(data, dict):
            return cls()
```

注意 `NoteAddConfig.from_dict`（~:474）已是该形态，不要动。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd $WT && uv run pytest tests/unit/test_global_config.py::TestFromDictNonDictSection -q`
Expected: 22 passed

- [ ] **Step 5: Commit**

```bash
cd $WT && git add jfox/global_config.py tests/unit/test_global_config.py
git commit -m "fix(config): guard sub-config from_dict against non-dict sections (#481)"
```

---

### Task 2: `GlobalConfig.from_dict` 三级守卫（验收 A2）

**Files:**

- Modify: `jfox/global_config.py`（`GlobalConfig.from_dict` ~:513-535；顺带消除 `fragment_capture` 的重复解析）
- Test: `tests/unit/test_global_config.py`（新增 1 个测试类）

**Interfaces:**

- Consumes: Task 1 的子配置守卫（`FragmentCaptureConfig.from_dict` 对非 dict 已安全）
- Produces: `GlobalConfig.from_dict(data: Any) -> GlobalConfig`——根级非 dict 返回 `cls()` 等价默认对象；`knowledge_bases` 非 dict 忽略该 section；坏 entry 跳过。供 Task 5 的 `_load` 调用

- [ ] **Step 1: 写失败测试**

`tests/unit/test_global_config.py` 末尾追加（`gc` 为模块引用，供后续 task 复用）：

```python
from jfox import global_config as gc


class TestGlobalConfigFromDictDefensive:
    """A2: 根级/容器级/entry 级畸形输入不炸、坏局部跳过、好局部保留。"""

    @pytest.mark.parametrize("bad", [[1], "oops", 42, True])
    def test_root_non_dict_returns_default_object(self, bad):
        cfg = GlobalConfig.from_dict(bad)
        assert cfg.default == DEFAULT_KB_NAME
        assert cfg.knowledge_bases == {}

    def test_knowledge_bases_non_dict_preserves_other_sections(self):
        cfg = GlobalConfig.from_dict(
            {
                "default": "work",
                "knowledge_bases": ["broken"],
                "backup": {"enabled": True, "retain": 3},
            }
        )
        assert cfg.default == "work"
        assert cfg.knowledge_bases == {}
        assert cfg.backup.enabled is True
        assert cfg.backup.retain == 3

    def test_malformed_kb_entry_skipped_valid_kept(self):
        cfg = GlobalConfig.from_dict(
            {
                "knowledge_bases": {
                    "bad": "oops",
                    "work": {"path": "/tmp/work", "created": "2024-01-01T00:00:00"},
                }
            }
        )
        assert "bad" not in cfg.knowledge_bases
        assert cfg.knowledge_bases["work"].path == "/tmp/work"
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd $WT && uv run pytest tests/unit/test_global_config.py::TestGlobalConfigFromDictDefensive -q`
Expected: 6 个用例全部 FAIL（root 4 个参数 + 容器 + entry，均抛 AttributeError）

- [ ] **Step 3: 实现**

替换 `GlobalConfig.from_dict` 整个方法体（含签名类型标注改为 `Any`，见 spec §2.1）：

```python
    @classmethod
    def from_dict(cls, data: Any) -> "GlobalConfig":
        # 根级非 dict：纯解析入口不抛异常，回默认对象（文件级恢复由 _load 负责）
        if not isinstance(data, dict):
            logger.warning(
                f"Ignoring non-dict global config root: {type(data).__name__}"
            )
            data = {}
        kbs: Dict[str, KnowledgeBaseEntry] = {}
        raw_kbs = data.get("knowledge_bases", {})
        if isinstance(raw_kbs, dict):
            for name, kb_data in raw_kbs.items():
                if isinstance(kb_data, dict):
                    kbs[name] = KnowledgeBaseEntry.from_dict(name, kb_data)
                else:
                    # 坏 entry 跳过：回默认会造出 path="" 的伪 entry 污染注册表
                    logger.warning(f"Skipping malformed KB entry {name!r}: not a dict")
        else:
            logger.warning(
                f"Ignoring malformed knowledge_bases: {type(raw_kbs).__name__}"
            )

        fragment_capture = FragmentCaptureConfig.from_dict(data.get("fragment_capture"))
        return cls(
            default=data.get("default", DEFAULT_KB_NAME),
            knowledge_bases=kbs,
            auto_summary=AutoSummaryConfig.from_dict(data.get("auto_summary")),
            fragment_capture=fragment_capture,
            backup=BackupConfig.from_dict(data.get("backup")),
            note_add=NoteAddConfig.from_dict(data.get("note_add")),
            prompt_capture=PromptCaptureConfig.from_dict(
                data.get("prompt_capture")
                if data.get("prompt_capture") is not None
                # 兼容：无新 section 时从旧 fragment_capture.enabled 继承
                else {"enabled": fragment_capture.enabled}
            ),
            prompt_judge=PromptJudgeConfig.from_dict(data.get("prompt_judge")),
        )
```

- [ ] **Step 4: 跑测试确认通过 + 既有用例回归**

Run: `cd $WT && uv run pytest tests/unit/test_global_config.py -q`
Expected: 全部 passed（含既有 `TestGlobalConfig`）

- [ ] **Step 5: Commit**

```bash
cd $WT && git add jfox/global_config.py tests/unit/test_global_config.py
git commit -m "fix(config): harden GlobalConfig.from_dict root/container/entry levels (#481)"
```

---

### Task 3: `_load` 根级校验 + traceback 日志（验收 A4）

**Files:**

- Modify: `jfox/global_config.py`（`_load` ~:558-577）
- Test: `tests/unit/test_global_config.py`（新增 1 个测试类；顶部需 `import logging`，若未有则补）

**Interfaces:**

- Consumes: Task 2 的 `GlobalConfig.from_dict(data: Any)`
- Produces: `_load()` 对「非法 JSON / 根级非 dict / 未覆盖解析异常」统一进入 except 分支并记 `exc_info=True` 的 warning。本 task 尚不改恢复行为（`_create_default_config` 无 persist 参数），A4 的验收在本 task 完成

- [ ] **Step 1: 写失败测试**

```python
class TestLoadFileLevelFailureLogs:
    """A4: 文件级加载失败记录原始 traceback 并返回默认配置。"""

    def _assert_failure_logged(self, tmp_path, caplog, raw: str):
        cfg_path = tmp_path / "zk_config.json"
        cfg_path.write_text(raw, encoding="utf-8")
        manager = GlobalConfigManager(config_path=cfg_path)
        with caplog.at_level(logging.WARNING, logger="jfox.global_config"):
            config = manager.get_config()
        assert config.default == DEFAULT_KB_NAME
        warnings_ = [r for r in caplog.records if "Failed to load config" in r.message]
        assert warnings_, "expected load-failure warning"
        assert warnings_[0].exc_info is not None

    def test_invalid_json(self, tmp_path, caplog):
        self._assert_failure_logged(tmp_path, caplog, "invalid json")

    def test_root_non_dict(self, tmp_path, caplog):
        self._assert_failure_logged(tmp_path, caplog, "[1, 2, 3]")
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd $WT && uv run pytest tests/unit/test_global_config.py::TestLoadFileLevelFailureLogs -q`
Expected: 2 FAIL——`assert warnings_[0].exc_info is not None`（现状日志无 traceback；root=list 用例现状也进 except，只是无 exc_info）

- [ ] **Step 3: 实现**

`_load` 的 try 块改为（except 分支本 task 只加 `exc_info=True`，备份接线留给 Task 5）：

```python
        if self.config_path.exists():
            try:
                with open(self.config_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if not isinstance(data, dict):
                    raise ValueError(
                        f"config root is {type(data).__name__}, expected dict"
                    )
                self._config = GlobalConfig.from_dict(data)
                # 迁移旧版默认 KB 路径（~/.zettelkasten/ → ~/.zettelkasten/default/）
                self._migrate_default_kb_path()
                logger.debug(f"Loaded global config from {self.config_path}")
            except Exception as e:
                logger.warning(
                    f"Failed to load config: {e}, creating default", exc_info=True
                )
                self._config = self._create_default_config()
```

- [ ] **Step 4: 跑测试确认通过 + 既有回归**

Run: `cd $WT && uv run pytest tests/unit/test_global_config.py -q`
Expected: 全部 passed（既有 `test_load_handles_corrupted_file` 不受影响）

- [ ] **Step 5: Commit**

```bash
cd $WT && git add jfox/global_config.py tests/unit/test_global_config.py
git commit -m "fix(config): validate config root type and log load failures with traceback (#481)"
```

---

### Task 4: `_backup_corrupted_config` 字节备份方法（验收 A5 的备份本体）

**Files:**

- Modify: `jfox/global_config.py`（模块顶部 import 区 + 新增模块级助手 2 个 + manager 新私有方法；放在 `_save` 之后）
- Test: `tests/unit/test_global_config.py`（新增 1 个测试类；需 `from itertools import cycle`）

**Interfaces:**

- Consumes: 无
- Produces（Task 5 依赖，签名精确如下）:
  - `_utc_corrupt_timestamp() -> str`（模块级，格式 `%Y%m%dT%H%M%SZ`，UTC）
  - `_corrupt_backup_suffix() -> str`（模块级，8 位 hex）
  - `GlobalConfigManager._backup_corrupted_config(self) -> bool`：读原文件字节 → 独占写 `<name>.corrupt-<ts>-<suffix>`；任何失败记 ERROR（含 exc_info）并返回 False，绝不抛异常

- [ ] **Step 1: 写失败测试**

```python
class TestBackupCorruptedConfig:
    """A5 备份本体：字节保真、独占不覆盖、失败返回 False 且有 traceback。"""

    def test_preserves_original_bytes(self, tmp_path):
        original = b'{"default": "work"'  # 缺右括号：非法 JSON 也必须可备份
        cfg_path = tmp_path / "zk_config.json"
        cfg_path.write_bytes(original)
        manager = GlobalConfigManager(config_path=cfg_path)

        assert manager._backup_corrupted_config() is True

        backups = list(tmp_path.glob("zk_config.json.corrupt-*"))
        assert len(backups) == 1
        assert backups[0].read_bytes() == original

    def test_never_overwrites_existing_snapshot(self, tmp_path, monkeypatch):
        monkeypatch.setattr(gc, "_utc_corrupt_timestamp", lambda: "20260909T000000Z")
        monkeypatch.setattr(
            gc, "_corrupt_backup_suffix", lambda: next(cycle(["dup", "dup", "ok"]))
        )
        original = b"[1, 2, 3]"
        cfg_path = tmp_path / "zk_config.json"
        cfg_path.write_bytes(original)
        collision = tmp_path / "zk_config.json.corrupt-20260909T000000Z-dup"
        collision.write_bytes(b"OLD")
        manager = GlobalConfigManager(config_path=cfg_path)

        assert manager._backup_corrupted_config() is True

        assert collision.read_bytes() == b"OLD"  # 已有快照未被覆盖
        created = tmp_path / "zk_config.json.corrupt-20260909T000000Z-ok"
        assert created.read_bytes() == original

    def test_suffix_failure_returns_false_with_traceback(self, tmp_path, caplog, monkeypatch):
        original = b'{"bad"'
        cfg_path = tmp_path / "zk_config.json"
        cfg_path.write_bytes(original)

        def _boom():
            raise OSError("suffix generator exploded")

        monkeypatch.setattr(gc, "_corrupt_backup_suffix", _boom)
        manager = GlobalConfigManager(config_path=cfg_path)

        with caplog.at_level(logging.ERROR, logger="jfox.global_config"):
            assert manager._backup_corrupted_config() is False

        errors = [r for r in caplog.records if "backup" in r.getMessage().lower()]
        assert errors and errors[0].exc_info is not None
        assert list(tmp_path.glob("zk_config.json.corrupt-*")) == []
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd $WT && uv run pytest tests/unit/test_global_config.py::TestBackupCorruptedConfig -q`
Expected: 3 FAIL——`AttributeError: 'GlobalConfigManager' object has no attribute '_backup_corrupted_config'`

- [ ] **Step 3: 实现**

模块顶部 import 区：`from datetime import datetime` 改为 `from datetime import datetime, timezone`，并新增 `import uuid`。

`_is_valid_time` 函数附近（模块级）新增：

```python
def _utc_corrupt_timestamp() -> str:
    """坏配置备份名的 UTC 时间戳（可被测试 monkeypatch 固定）"""
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _corrupt_backup_suffix() -> str:
    """坏配置备份名的唯一后缀（可被测试 monkeypatch 固定）"""
    return uuid.uuid4().hex[:8]
```

`GlobalConfigManager._save` 方法之后新增：

```python
    def _backup_corrupted_config(self) -> bool:
        """文件级加载失败时先把原文件字节备份为 .corrupt-* 快照。

        契约（spec §3.4）：备份原始字节而非重新序列化；独占创建、冲突重试、
        绝不覆盖已有快照；任何失败记 ERROR（含 traceback）并返回 False，
        不得抛异常——调用方据此决定是否允许默认配置覆盖原文件。
        """
        try:
            original = self.config_path.read_bytes()
        except Exception as e:
            logger.error(f"Failed to read corrupted config for backup: {e}", exc_info=True)
            return False
        for _ in range(5):
            try:
                candidate = self.config_path.parent / (
                    f"{self.config_path.name}.corrupt-"
                    f"{_utc_corrupt_timestamp()}-{_corrupt_backup_suffix()}"
                )
                with open(candidate, "xb") as f:
                    f.write(original)
                logger.warning(f"Backed up corrupted config to {candidate}")
                return True
            except FileExistsError:
                continue  # 同秒冲突：换后缀重试，绝不覆盖
            except Exception as e:
                logger.error(f"Failed to write config backup: {e}", exc_info=True)
                return False
        logger.error("Failed to write config backup: suffix collisions exhausted")
        return False
```

- [ ] **Step 4: 跑测试确认通过**

Run: `cd $WT && uv run pytest tests/unit/test_global_config.py::TestBackupCorruptedConfig -q`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
cd $WT && git add jfox/global_config.py tests/unit/test_global_config.py
git commit -m "feat(config): byte-faithful .corrupt-* snapshot before default-config recovery (#481)"
```

---

### Task 5: `_create_default_config(persist)` + `_load` 恢复编排（验收 A3、A6、A5 编排部分）

**Files:**

- Modify: `jfox/global_config.py`（`_create_default_config` ~:651-669、`_load` except/else 分支）
- Test: `tests/unit/test_global_config.py`（新增 2 个测试类）

**Interfaces:**

- Consumes: Task 4 的 `_backup_corrupted_config() -> bool`
- Produces: `_create_default_config(self, persist: bool = True) -> GlobalConfig`；`_load()` except 分支顺序 = warning 日志 → 备份 → `persist=backup_ok` 的默认配置恢复

- [ ] **Step 1: 写失败测试**

```python
SECTION_CLASSES = {
    "auto_summary": AutoSummaryConfig,
    "fragment_capture": FragmentCaptureConfig,
    "backup": BackupConfig,
    "prompt_capture": PromptCaptureConfig,
    "prompt_judge": PromptJudgeConfig,
}

GOOD_PAYLOAD = {
    "default": "work",
    "knowledge_bases": {
        "work": {"path": "/tmp/work", "created": "2024-01-01T00:00:00"}
    },
    "note_add": {"dedup_enabled": False},
}


class TestLoadMalformedSection:
    """A3: section 级畸形不触发整体回退，注册表/兄弟段/原文件全部保留。

    fixture 安全：default 指向 work 且注册表无 default entry，
    _migrate_default_kb_path 会提前返回，不会合法改写文件（spec §6.3）。
    """

    @pytest.mark.parametrize("section", sorted(SECTION_CLASSES))
    def test_registry_default_and_file_preserved(self, tmp_path, section):
        cfg_path = tmp_path / "zk_config.json"
        payload = dict(GOOD_PAYLOAD)
        payload[section] = "enabled"
        cfg_path.write_text(json.dumps(payload), encoding="utf-8")
        before = cfg_path.read_bytes()

        config = GlobalConfigManager(config_path=cfg_path).get_config()

        assert config.default == "work"
        assert config.knowledge_bases["work"].path == "/tmp/work"
        assert DEFAULT_KB_NAME not in config.knowledge_bases  # 未被整体重置
        assert getattr(config, section) == SECTION_CLASSES[section]()  # 坏段回默认
        assert config.note_add.dedup_enabled is False  # 兄弟段保留
        assert cfg_path.read_bytes() == before  # 原文件未被重写


class TestLoadRecoveryOrchestration:
    """A5 编排 + A6：文件级失败的备份与 persist 门控。"""

    def test_file_failure_backs_up_then_recovers(self, tmp_path):
        original = b'{"default": "work"'
        cfg_path = tmp_path / "zk_config.json"
        cfg_path.write_bytes(original)

        config = GlobalConfigManager(config_path=cfg_path).get_config()

        assert config.default == DEFAULT_KB_NAME
        backups = list(tmp_path.glob("zk_config.json.corrupt-*"))
        assert len(backups) == 1 and backups[0].read_bytes() == original

    def test_two_consecutive_failures_two_distinct_snapshots(self, tmp_path):
        original = b'{"default": "work"'
        cfg_path = tmp_path / "zk_config.json"
        cfg_path.write_bytes(original)
        GlobalConfigManager(config_path=cfg_path).get_config()
        cfg_path.write_bytes(original)  # 恢复坏内容，再次触发（同秒，靠 suffix 区分）
        GlobalConfigManager(config_path=cfg_path).get_config()

        backups = list(tmp_path.glob("zk_config.json.corrupt-*"))
        assert len(backups) == 2
        assert all(b.read_bytes() == original for b in backups)

    def test_normal_load_creates_no_snapshot(self, tmp_path):
        cfg_path = tmp_path / "zk_config.json"
        cfg_path.write_text(json.dumps(GOOD_PAYLOAD), encoding="utf-8")

        assert GlobalConfigManager(config_path=cfg_path).get_config().default == "work"
        assert list(tmp_path.glob("zk_config.json.corrupt-*")) == []

    def test_backup_failure_returns_default_but_keeps_original_file(
        self, tmp_path, caplog, monkeypatch
    ):
        original = b'{"default": "work"'
        cfg_path = tmp_path / "zk_config.json"
        cfg_path.write_bytes(original)

        def _boom():
            raise OSError("backup subsystem exploded")

        monkeypatch.setattr(gc, "_corrupt_backup_suffix", _boom)
        with caplog.at_level(logging.WARNING, logger="jfox.global_config"):
            config = GlobalConfigManager(config_path=cfg_path).get_config()

        assert config.default == DEFAULT_KB_NAME  # 内存默认配置仍可用
        assert cfg_path.read_bytes() == original  # 原文件未被覆盖
        errors = [r for r in caplog.records if "backup" in r.getMessage().lower()]
        assert errors and errors[0].exc_info is not None  # 备份错误有 traceback
        warnings_ = [r for r in caplog.records if "Failed to load config" in r.message]
        assert warnings_ and warnings_[0].exc_info is not None  # 原始异常仍可诊断
        assert list(tmp_path.glob("zk_config.json.corrupt-*")) == []

    def test_create_default_persist_false_never_saves(self, tmp_path, monkeypatch):
        saved: list[bool] = []
        monkeypatch.setattr(GlobalConfigManager, "_save", lambda self: saved.append(True) or True)
        monkeypatch.setattr(gc, "DEFAULT_KB_PATH", tmp_path / "kbroot")  # 存在与否都不得触发保存
        (tmp_path / "kbroot").mkdir()

        config = GlobalConfigManager(config_path=tmp_path / "zk_config.json")._create_default_config(
            persist=False
        )

        assert config.default == DEFAULT_KB_NAME
        assert saved == []
        assert not (tmp_path / "zk_config.json").exists()

    def test_create_default_persist_true_keeps_existing_behavior(self, tmp_path, monkeypatch):
        saved: list[bool] = []
        monkeypatch.setattr(GlobalConfigManager, "_save", lambda self: saved.append(True) or True)
        monkeypatch.setattr(gc, "DEFAULT_KB_PATH", tmp_path / "kbroot")
        (tmp_path / "kbroot").mkdir()

        GlobalConfigManager(config_path=tmp_path / "zk_config.json")._create_default_config(
            persist=True
        )

        assert saved == [True]
```

- [ ] **Step 2: 跑测试确认失败**

Run: `cd $WT && uv run pytest "tests/unit/test_global_config.py::TestLoadMalformedSection" "tests/unit/test_global_config.py::TestLoadRecoveryOrchestration" -q`
Expected: A3 5 个 FAIL（现状整体重置：`work` entry 丢失 / default 变 default / 文件被重写）；编排类 5 个 FAIL（现状无备份、无 persist 参数——`TypeError: _create_default_config() got an unexpected keyword argument 'persist'` 或快照断言失败）。注意 `test_backup_failure_returns_default_but_keeps_original_file` 现状也 FAIL：现状会在 DEFAULT_KB_PATH 存在时直接 `_save()` 覆盖原文件

- [ ] **Step 3: 实现**

`_create_default_config` 加 `persist` 参数（默认 True 保持既有行为）：

```python
    def _create_default_config(self, persist: bool = True) -> GlobalConfig:
        """创建默认配置

        persist=False 供加载失败但备份未成功时使用：返回内存默认配置，
        但不落盘覆盖原文件（spec §3.3）。
        """
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
        if persist and DEFAULT_KB_PATH.exists():
            self._config = config
            self._save()

        return config
```

`_load` except 分支改为（warning 行 Task 3 已就位，此处只加备份与 persist）：

```python
            except Exception as e:
                logger.warning(
                    f"Failed to load config: {e}, creating default", exc_info=True
                )
                backup_ok = self._backup_corrupted_config()
                self._config = self._create_default_config(persist=backup_ok)
```

else 分支（文件不存在）保持 `self._create_default_config()` 不变（默认 persist=True，既有行为）。

- [ ] **Step 4: 跑测试确认通过**

Run: `cd $WT && uv run pytest tests/unit/test_global_config.py -q`
Expected: 全部 passed

- [ ] **Step 5: Commit**

```bash
cd $WT && git add jfox/global_config.py tests/unit/test_global_config.py
git commit -m "fix(config): gate default-config persistence on corrupt-file backup success (#481)"
```

---

### Task 6: 回归门禁（验收 A7）+ 收尾

**Files:**

- 无新改动；跑 spec §4 全部受影响测试文件

**Interfaces:**

- Consumes: Task 1-5 全部产物
- Produces: A7 通过证据（本地 CR 与 PR 描述引用）

- [ ] **Step 1: 跑全部受影响测试**

Run: `cd $WT && uv run pytest tests/unit/test_global_config.py tests/unit/test_note_add_config.py tests/unit/test_fragment_config.py tests/unit/test_auto_summary_config_sources.py tests/unit/test_backup.py tests/unit/test_prompt_capture.py tests/unit/test_prompt_runner.py -q`
Expected: 全部 passed，0 failed

- [ ] **Step 2: 快速 sanity——全 fast unit 套件（受影响面外溢检查）**

Run: `cd $WT && uv run pytest tests/unit -q -m "not embedding and not slow" -x --timeout=120`
Expected: 全部 passed（若出现与本改动无关的已知 env 噪音失败，记录并按「已知噪音」过滤，不静默忽略）

- [ ] **Step 3: 本地快速 CR**

按 github-issue-driven 步 8：用 pi 原生 `workflow` 工具 `code-review` 模式（或 `requesting-code-review` skill）对 worktree diff 做 CR；按 spec 验收矩阵 A1-A7 逐项对账

- [ ] **Step 4: 汇报并请求 push/PR 许可（🚪 停点）**

向用户汇报：验收矩阵对账结果 + CR 结论；**等用户明确许可后才 push / 开 PR / 打 `zima:needs-review`**

---

## Spec 覆盖对照（plan ↔ spec 验收 ID）

| Spec 验收 | Plan Task |
|---|---|
| A1 子配置类非 dict 回默认 | Task 1 |
| A2 根级/容器/entry 三级守卫 | Task 2 |
| A3 section 级畸形不清空不重写 | Task 5 |
| A4 文件级失败 traceback 日志 | Task 3 |
| A5 备份字节保真 + 不覆盖快照 | Task 4（本体）+ Task 5（编排） |
| A6 备份失败不覆盖原文件 | Task 5 |
| A7 消费者回归 | Task 6 |
