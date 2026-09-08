# Spec: #481 from_dict 对非 dict 值设防，畸形配置不再清空注册表

- issue: zhuxixi/jfox#481
- 修订日期: 2026-09-09
- 状态: draft（已按 spec review 修订，等待用户确认）
- 调研: `/home/elling/.claude/github-issue-driven/zhuxixi/jfox/issue-481/research/from_dict-defense-gap.md`

## 1. 根因报告（systematic-debugging Phase 1-3 已闭环）

**根因是配置解析器把 truthy 非 dict 值当成 dict 使用，异常随后被 `_load()` 的恢复逻辑转化成配置覆盖。**

已在 main（`5bfb828` 之后）实测 8 条 `AttributeError` 路径：

| # | 路径 | 现象 |
|---|------|------|
| 1 | `BackupConfig.from_dict("enabled")` | `'str' object has no attribute 'get'` |
| 2 | `AutoSummaryConfig.from_dict("enabled")` | 同上 |
| 3 | `FragmentCaptureConfig.from_dict("enabled")` | 同上 |
| 4 | `PromptCaptureConfig.from_dict("enabled")` | 同上 |
| 5 | `PromptJudgeConfig.from_dict("enabled")` | 同上 |
| 6 | `GlobalConfig.from_dict([])` | `'list' object has no attribute 'get'` |
| 7 | `GlobalConfig.from_dict({"knowledge_bases": []})` | `'list' object has no attribute 'items'` |
| 8 | `GlobalConfig.from_dict({"knowledge_bases": {"work": "oops"}})` | `'str' object has no attribute 'get'` |

**完整清空链还包含一个当前代码中的立即保存路径。**

```text
畸形配置
  → from_dict 抛 AttributeError/ValueError
  → GlobalConfigManager._load() 的宽 except 捕获
  → _create_default_config()
  → 若 DEFAULT_KB_PATH.exists()，_create_default_config() 内立即调用 _save()
  → 否则也可能在后续 mutator 中调用 _save()
  → 原配置中的 KB 注册表和 default 选择被覆盖
```

因此“后续 mutator 才保存”不是唯一路径；`jfox/global_config.py:664-667` 的默认配置创建逻辑可能在 `_load()` 异常分支中立即覆盖原文件。

**issue 原清单已过时。** `GemSynthesisConfig` 已由 #498（commit `5bfb828`，retire gem synth pipeline）移除；当前实际处理 5 个子配置类：`BackupConfig`、`AutoSummaryConfig`、`FragmentCaptureConfig`、`PromptCaptureConfig`、`PromptJudgeConfig`。`NoteAddConfig` 已由 #383（commit `8154909`）修复。

## 2. 设计边界与 API 契约

本次明确区分“section 级解析”和“文件级恢复”两个边界：

### 2.1 `from_dict()` 的契约

`BackupConfig`、`AutoSummaryConfig`、`FragmentCaptureConfig`、`PromptCaptureConfig`、`PromptJudgeConfig` 的 `from_dict()` 对**整个 section 的顶层值**负责：

- `None`、空 dict 保持现有行为，返回该类默认配置；
- truthy 非 dict（字符串、数字、列表、布尔值等）不得抛异常，返回该类默认配置；
- section 内部字段类型校验不在本 issue 全量扩展范围内；已有 `_safe_*` 或 `__post_init__` 行为保持不变；
- 不承诺“未来任意 from_dict 字段缺陷都不会触发异常”，未来异常由 `_load()` 的文件级备份与恢复兜底。

`GlobalConfig.from_dict()` 的契约为：

- 运行时接收来自 JSON 的任意值；直接收到非 dict 根值时不得抛异常，返回一个默认 `GlobalConfig` 对象；该方法只负责内存解析，不负责文件备份和持久化；实现时应让参数类型标注反映这一运行时契约（例如使用 `Any`），避免把不受信任的 JSON 值误标成必为 dict；
- `knowledge_bases` 非 dict 时忽略整个注册表 section，但继续解析并保留其他顶层配置；
- 单个 KB entry 非 dict 时跳过该 entry，继续保留其他合法 entry；不构造 `path=""` 的伪 entry；
- 合法字段和既有兼容逻辑保持不变。

### 2.2 `GlobalConfigManager._load()` 的契约

`_load()` 负责文件级 I/O 与恢复：

- `json.load()` 失败、JSON 根值非 dict、或 dict 内部解析仍抛出未覆盖异常时，视为文件级加载失败；
- 失败时记录包含 traceback 的 warning；
- 在任何默认配置持久化之前，先备份原文件的原始字节；
- 备份成功后才允许沿用现有 `_create_default_config()` 的自动保存行为；
- 备份失败时仍返回内存中的默认配置，但**不得继续自动覆盖原配置文件**；备份异常另行记录，不覆盖最初的加载异常；
- 加载成功（包括 section 级非 dict 被安全回默认）不得生成 `.corrupt-*` 备份。

## 3. 设计

### 3.1 五个子配置类增加顶层类型守卫

在以下 5 个 `from_dict()` 中，将现有：

```python
if not data:
    return cls()
```

改为：

```python
if not isinstance(data, dict):
    return cls()
```

实现必须保持各类现有字段解析、默认值和 `__post_init__` 语义，不借本次机会重写字段级解析逻辑。

该修改镜像 #383 对 `NoteAddConfig` 的既有修复，解决的是 section 顶层为 truthy 非 dict 时调用 `data.get()` 的问题。

### 3.2 `GlobalConfig.from_dict()` 的根级、容器级和 entry 级防御

解析流程采用“坏局部跳过、好局部保留”：

```python
if not isinstance(data, dict):
    data = {}

raw_kbs = data.get("knowledge_bases", {})
kbs = {}
if isinstance(raw_kbs, dict):
    for name, kb_data in raw_kbs.items():
        if isinstance(kb_data, dict):
            kbs[name] = KnowledgeBaseEntry.from_dict(name, kb_data)
        else:
            # warning：跳过单个畸形 entry
            pass
else:
    # warning：忽略整个畸形 knowledge_bases section
    pass
```

具体决策：

- 根级非 dict 在 `from_dict()` 层返回默认对象，保证该纯解析入口不抛异常；
- `_load()` 在 `json.load()` 后再次检查根值类型。根级非 dict 属于整个文件无法按配置格式解释的情况，交由文件级恢复流程处理，而不是让它静默变成空注册表；
- entry 级不调用 `KnowledgeBaseEntry.from_dict()` 处理非 dict。返回一个 `path=""` 的默认 entry 会污染注册表，因此只跳过该 entry；
- 可记录 warning，但 warning 不改变返回值；测试不依赖 warning 文案，只验证行为。

### 3.3 `_load()` 的日志与恢复

保留宽 `except Exception`，但增强日志并明确恢复顺序：

```python
try:
    with open(self.config_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict):
        raise ValueError(f"config root is {type(data).__name__}, expected dict")
    self._config = GlobalConfig.from_dict(data)
    self._migrate_default_kb_path()
    logger.debug(...)
except Exception as e:
    logger.warning("Failed to load config: %s, creating default", e, exc_info=True)
    backup_ok = self._backup_corrupted_config()
    self._config = self._create_default_config(persist=backup_ok)
```

上面代码表达的是行为契约，具体命名可在 plan 阶段确定：

- `exc_info=True` 是必须项，确保 `caplog` 能观察到原始 traceback；
- 不收窄 `except Exception`。JSON 损坏和历史配置异常仍需要保留当前“回默认”的恢复能力；本次通过 section 守卫和备份降低其数据损失风险；
- `_create_default_config()` 增加一个表示是否持久化的内部参数（默认保持现有行为）。加载失败时，只有备份成功才允许触发现有的自动 `_save()`；备份失败则只返回内存默认配置，避免在无法留存原文件时继续覆盖原文件；
- 备份失败时的日志必须包含备份操作异常的 traceback；它不能替换或吞掉 `_load()` 原始异常，也不能阻止 `_load()` 返回默认配置。

### 3.4 坏文件备份：正式要求

坏文件备份不是可选项，而是本 issue 的最后一道数据保护。新增私有 I/O 方法（名称可在 plan 阶段确定），契约如下：

1. 备份对象是 `config_path.read_bytes()` 得到的**原始字节**，不重新解析、不重新序列化；非法 JSON 也必须可以备份。
2. 备份必须发生在 `_create_default_config()` 及其潜在 `_save()` 之前。
3. 备份文件位于配置文件同一目录，命名形如：

   ```text
   zk_config.json.corrupt-<UTC timestamp>-<unique suffix>
   ```

4. 创建备份必须使用“不覆盖”语义（例如独占创建 `xb`，发生名称冲突时重新生成 suffix）；同一秒内多次失败也不能覆盖已有备份。
5. 本 issue 不自动删除历史 `.corrupt-*` 文件。配置文件很小，保留每次失败的原始快照优先于误删证据；后续清理策略另立 issue。
6. 读取原文件或创建备份失败时，方法返回失败状态并记录带 traceback 的 error；不得抛出备份异常覆盖最初的加载异常。
7. 备份失败时 `_load()` 仍返回默认配置，但不得自动保存默认配置到原 `config_path`；原文件必须保持原样，等待用户根据日志和现场修复。

## 4. 文件范围

生产代码只修改：

- `jfox/global_config.py`

测试新增或调整集中在：

- `tests/unit/test_global_config.py`

既有消费者测试作为回归门禁运行，不为本 issue 进行无关重构：

- `tests/unit/test_backup.py`
- `tests/unit/test_prompt_capture.py`
- `tests/unit/test_prompt_runner.py`
- `tests/unit/test_fragment_config.py`
- `tests/unit/test_auto_summary_config_sources.py`
- `tests/unit/test_note_add_config.py`

## 5. 验收矩阵

本 issue 的行为均可在 unit 层用直接解析、临时配置文件和 `caplog` 验证，不设置用户实测项。自动化测试必须覆盖以下稳定 ID：

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|----|--------|----------|----------|----------|
| A1 | 5 个子配置类接收 truthy 非 dict section | 自动化验证（unit） | `uv run pytest tests/unit/test_global_config.py -q`，参数化覆盖 `str`、`int`、`list`、`bool` | 所有类均不抛异常，并返回与 `cls()` 等价的默认配置 |
| A2 | `GlobalConfig.from_dict()` 根级非 dict 不抛；`knowledge_bases` 非 dict 不牵连其他顶层配置；单个坏 entry 被跳过 | 自动化验证（unit） | 同上，分别测试根值、容器值和混合合法/非法 entry | 根级调用返回默认对象；容器坏时其他配置保留；坏 entry 不进入注册表，合法 entry 保留 |
| A3 | section 级畸形输入不触发 `_load()` 整体回退，也不重写原文件 | 自动化验证（unit） | `GlobalConfigManager(config_path=tmp_path / "zk_config.json").get_config()`；对 5 个 section 分别注入 truthy 非 dict | `default`、合法 KB 注册表和其他合法 section 保留；无异常；读取前后原文件字节不变 |
| A4 | 文件级加载失败记录原始 traceback，并返回默认配置 | 自动化验证（unit） | 使用非法 JSON 和 JSON 根值为 list 的临时配置文件，配合 `caplog` 调用 `get_config()` | 返回默认配置；对应 warning 的 `record.exc_info` 非空；不因日志处理再次抛异常 |
| A5 | 文件级失败先备份原始文件，备份不覆盖已有快照 | 自动化验证（unit） | 对非法 JSON、合法非 dict 根值分别测试；每次失败前重新写入原始坏字节并用新的 manager 或 `reload()` 触发；读取 `.corrupt-*` 文件 | 每次备份的 `read_bytes()` 与该次失败前原文件字节完全一致；至少生成两个不重名快照；正常加载不生成快照 |
| A6 | 备份失败时仍可恢复内存默认，但不覆盖原文件 | 自动化验证（unit） | 模拟 `_backup_corrupted_config()` 返回失败或底层 I/O 异常，调用 `get_config()` | `get_config()` 返回默认配置；原配置文件字节保持不变；备份错误有 traceback 日志；原始加载异常仍可诊断 |
| A7 | 既有配置消费者行为不回归 | 自动化验证（unit） | `uv run pytest tests/unit/test_global_config.py tests/unit/test_note_add_config.py tests/unit/test_fragment_config.py tests/unit/test_auto_summary_config_sources.py tests/unit/test_backup.py tests/unit/test_prompt_capture.py tests/unit/test_prompt_runner.py -q` | 全部测试通过 |

## 6. 可测性拆分设计（实现硬约束）

实现必须保持“纯解析逻辑”和“文件恢复 I/O”分离，不得把备份、保存或 manager 状态写入 `from_dict()`。

### 6.1 纯解析边界

- 5 个子配置类的 `from_dict()`：直接接收内存值，测试 truthy 非 dict、`None`、空 dict 和合法 dict；不访问文件系统、不依赖全局 manager 状态。
- `GlobalConfig.from_dict()`：直接测试根级、`knowledge_bases` 容器级和 entry 级输入；合法 entry 与畸形 entry 混合测试，验证局部跳过行为。直接传入根级非 dict 时，断言返回默认对象且不抛异常；不把该直接调用与 manager 的文件级恢复结果混为一谈。
- 这些测试可用 pytest 参数化，但每个类的默认值断言必须明确，不能只断言“不抛异常”。

### 6.2 文件恢复边界

- `_backup_corrupted_config()`：单独测试原始字节复制、独占创建、名称冲突不覆盖、I/O 失败返回状态；该方法不负责创建默认配置。测试 I/O 失败时应确认方法返回失败而不是抛出备份异常。
- `_create_default_config(persist=...)`：单独测试 `persist=True` 保持现有默认配置创建/保存行为，`persist=False` 不写配置文件；即使 `DEFAULT_KB_PATH` 存在也必须满足该约束。
- `_load()`：只测试编排关系——加载失败时先调用备份，再按备份结果决定是否持久化；使用 `tmp_path` 和 `caplog`，不接触真实 `~/.zk_config.json`。
### 6.3 管理层回归边界

A3 必须断言两层结果：

1. 内存结果：`default`、合法 KB entry、其他 section 正确保留；
2. 持久化结果：section 级安全回退不会触发默认配置保存，原文件字节不被清空或重写。

A3 的临时配置必须使用不会触发既有默认 KB 路径迁移的 fixture（例如将 `default` 指向临时的 `work` entry，或显式 patch `_migrate_default_kb_path()`）；否则 `_load()` 的历史迁移逻辑可能合法地改写配置，不能把该改写归因于本 issue。

A4-A6 使用真正的文件级失败（非法 JSON、根级非 dict、模拟备份失败），不要用 section 级非 dict 作为 traceback 或备份测试触发条件，因为修复后这类输入应该在解析层正常返回。

## 7. 非目标

- 不恢复或重新引入已被 #498 移除的 `GemSynthesisConfig`；
- 不扩展所有 section 内部字段的类型校验，不处理例如 `AutoSummaryConfig` 内部 `int("not-an-int")` 或 `PromptJudgeConfig.__post_init__()` 的其他既有异常；
- 不修 #294 的旧版本保存导致未知键丢失问题；
- 不收窄 `_load()` 的 `except Exception`；
- 不改变 `KnowledgeBaseEntry.from_dict()` 的签名和内部语义，entry 防御放在 `GlobalConfig.from_dict()` 调用点；
- 不做存量配置修复或交互式迁移工具；
- 不改变 `_save()` 现有的原子写入机制；
- 不设置 `.corrupt-*` 自动清理策略；
- 不测试 CLI 子进程或 daemon，unit 层已足以证明本次解析和恢复行为。

## 8. 风险与明确取舍

- truthy 非 dict 从“抛异常并触发文件级恢复”变为“该 section 回默认、其他 section 保留”；这是本 issue 的目标行为变化。
- `knowledge_bases` 容器整体损坏时，无法从非 dict 值恢复其中的 KB，因此只保证其他顶层配置保留；单个 entry 损坏时则保证其他合法 entry 保留。
- 根级非 dict 与 section 级非 dict 的恢复策略不同：直接调用 `GlobalConfig.from_dict()` 时返回内存默认对象；经 `GlobalConfigManager._load()` 读取文件时按文件级失败处理，先备份，再按备份结果决定是否保存默认配置。
- 文件级恢复仍可能让当前进程使用默认配置；本次优先保证原文件不被无备份覆盖，配置修复由用户或后续工具完成。
- 保留所有 `.corrupt-*` 快照会增加少量磁盘文件，但能保留每次失败的原始证据；清理策略不在本 issue 范围内。
