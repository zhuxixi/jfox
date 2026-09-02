# Spec: #383 `jfox add` permanent 防重 + `--json` 纯净化

> 状态：DRAFT，待用户确认。调研依据见 `research/infra-and-code-paths.md`。

## 目标

1. `jfox add --type permanent` 落库前双通道查重（标题 + embedding），命中则拒绝并给出结构化结果与逃生舱 `--force`。
2. 根因 A：`--json` 输出模式下抑制 INFO 日志噪声，正常成功路径 stdout（含 `2>&1` 合流后）为纯 JSON。

## 非目标

- 存量重复笔记清理（走 `jfox delete`，#386 已修 backlink 清理）
- `jfox edit` 路径防重（改标题/内容同样可造重复，另开 issue）
- fleeting/literature/session 类型防重
- add 路径内自动 dedup-backfill（开销大，靠已有的 `jfox gem-synth dedup-backfill` 命令 bootstrap）
- NoteAddConfig 的 CLI 配置面（`jfox config set` 不加键；编辑配置文件 + `--force` 够用）
- #294 旧版本丢新键的前向兼容

## 决策表

| # | 决策 | 选择 | 理由 |
|---|------|------|------|
| D1 | 防重范围 | 仅 `--type permanent` | permanent 是唯一无闸门的产生路径；其他类型语义不同 |
| D2 | 标题通道语义 | 任意**非 archived**、任意类型、大小写不敏感同标题 → 命中 | wiki-link 按标题解析不分类型；archived 视同删除 |
| D3 | 标题通道实现 | `get_all_meta()` O(N) 扫描，不用 `find_by_title` | `_by_title` 同标题多条只留其一 + archived 混存不可靠；add 路径已有同量级扫描 |
| D4 | embedding 阈值 | 0.95（config 可调），复用 `dedup_check` | add 是二值拒绝，0.88 误伤相似笔记（issue 实测短文本虚高 0.887） |
| D5 | 短文本跳过 | 正文 ≤50 字符不做 embedding 查重（常量 `_EMBED_DEDUP_MIN_CHARS = 50`） | 短文本区分度差，标题通道兜底；不进 config 防面膨胀 |
| D6 | 命中行为 | 不落库；json 输出 `{"success": false, "skipped": "duplicate", ...}`；退出码 1 | 调用方（agent/脚本）必须能感知失败 |
| D7 | 逃生舱 | `--force` 跳过两通道，仍执行落库后 upsert | 迁移/backfill/明确要重复 |
| D8 | 落库后 | 成功即 `upsert_dedup(kb, id, "permanent", content)`（best-effort） | 后续 add（含同批连发）与 gem_synth 都能查到 |
| D9 | 配置 | `NoteAddConfig(dedup_enabled=True, title_dedup=True, embedding_dedup=True, dedup_threshold=0.95)` 挂 `GlobalConfig`，照 `GemSynthesisConfig` 模式 | 默认全开，可按需关 |
| D10 | 新代码位置 | 新模块 `jfox/add_dedup.py`（查重逻辑 + `DuplicateNoteError`），cli.py 只加钩子和参数 | cli.py 已 4000+ 行；独立模块可单测、无循环依赖 |
| D11 | 根因 A 修法 | 入口处（`cli.main()`）检测 argv 含 `--json` 或 `-f/--format json` → root logger 提到 WARNING；add 的 dim_warning 并入 JSON 字段 | 一处生效覆盖所有命令；日志本就走 stderr，污染源是 INFO 噪声经 `2>&1` 合流 |
| D12 | 残余风险 | WARNING/ERROR 仍走 stderr，`2>&1` 时仍混入 | 正常成功路径不再有输出；彻底纯净化需重设计日志通道，不值 |

## 数据流

```
jfox add --type permanent [--force] [--json]
 └ add() [use_kb(kb)]                      # cli.py
    └ _add_note_impl(...)                  # cli.py:454
       ├ 模板渲染 → final content/title/nt
       ├ [nt==PERMANENT ∧ ¬force ∧ dedup_enabled]      ← 新钩子
       │   ├ title_dedup: get_all_meta() 扫非 archived 同标题 → 命中?
       │   │    raise DuplicateNoteError(matched_by="title")
       │   ├ embedding_dedup ∧ len(content)>50:
       │   │    dedup_check(kb, content, 0.95) → 命中?
       │   │    raise DuplicateNoteError(matched_by="embedding", score)
       ├ create_note → save_note → backlink 回填（不变）
       ├ upsert_dedup(kb, id, "permanent", content)    ← 新，best-effort
       └ 输出：duplicate → success:false/skipped/exit 1
```

## 组件契约

### `jfox/add_dedup.py`（新）

```python
class DuplicateNoteError(Exception):
    """matched_by: "title"|"embedding"; matched_id/matched_title; score: float|None"""

def check_add_duplicate(title, content) -> None:  # raises DuplicateNoteError
    """permanent 落库前查重。读 NoteAddConfig；title 通道扫 note_index；
    embedding 通道复用 gem_synth.dedup.dedup_check。kb 名经 _resolve_kb_name(None)
    在 use_kb 上下文内解析。任何内部异常 → 放行（防重是闸门不是路障）。"""
```

### `jfox/cli.py` 改动

- `add()` 加 `--force` 参数；`_add_note_impl` 加 `force` 形参，模板渲染+类型解析后调 `check_add_duplicate`，`except DuplicateNoteError` → 结构化输出 + `typer.Exit(1)`。
- 保存成功后调 `upsert_dedup`（`nt==PERMANENT` 时，best-effort）。
- `main()` 入口加 JSON 模式日志静默（D11）；add 的 dim_warning stderr print 在 json 模式并入 `result["vector_dimension_warning"]`。

### `jfox/global_config.py` 改动

- `NoteAddConfig` dataclass + `to_dict/from_dict`；`GlobalConfig.note_add` 字段 + 序列化；manager `get/update_note_add_config()`。

### `tests/conftest.py` 改动

- 全局设置 `JFOX_SYNTHESIS_DB` 到 tmp（session 级），隔离真实 synthesis_log.db。

## 降级矩阵

| 条件 | 行为 |
|---|---|
| daemon 不可用 | embedding 通道跳过、upsert 跳过（内部已降级），仅标题通道 |
| `dedup_enabled=false` | 全跳过 |
| `--force` | 两通道跳过，仍 upsert |
| 表空 / 短文本 / dedup_check 异常 | embedding 通道自然放行，不阻塞 |

## 验收标准

1. 复现步骤（issue 原文）第二次 add 被拦截：json 输出 `success:false, skipped:"duplicate"`，exit 1；加 `--force` 成功落库。
2. 同标题仅 archived 命中 → 放行。
3. daemon 停止时 add permanent 正常工作（仅标题通道），不加载本地模型、无秒级延迟。
4. `--json 2>&1` 正常成功路径输出为单段合法 JSON（无 INFO 行）。
5. 新单测 + 快速集成测试全绿（不依赖真实 daemon 的用例用 mock/set_store）。
