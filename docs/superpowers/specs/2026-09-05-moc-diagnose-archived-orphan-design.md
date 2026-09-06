# Spec: fix #499 — moc diagnose 孤儿三分（archived 不再误报）

> 状态：draft，等用户确认后进 worktree。
> 调研依据：`research/root-cause-and-plan-a.md` + issue #499 实测数据。

## 1. 问题

`jfox moc diagnose` 的 coverage 孤儿判定把三类不同成因的 vector 条目混为同一计数：

| 成因 | 磁盘状态 | 期望语义 | 现状 |
|------|---------|---------|------|
| archived | 存在，frontmatter `archived: true` | 正常（有意归档，可搜索） | ❌ 计入 vector_orphans |
| ghost | 不存在 | 索引死条目（真孤儿） | ✅ 计入 |
| duplicate | 存在，vector 重复条目 | 索引异常（真孤儿） | ✅ 计入 |

后果：恒有 archived permanent 的 KB（如 office_hour 的 10 条）持续收到假警报，误导用户白跑全量 rebuild（CPU ~10 分钟）。`index verify` 口径（`indexed_ids - file_ids`，只判磁盘不存在）不受影响，两者语义应一致。

## 2. 方案（issue 方案 A：细分孤儿成因）

### 2.1 数据流（改后）

```
note_index.get_all_meta()
  → permanent_meta: 全量 permanent dict（含 archived）        [新增，派生自同一数据源]
  → live_meta = permanent_meta 去掉 archived                 [语义不变]
  → filesystem_count = len(live_meta)                        [不变：944]

vector_store.get_all_embeddings("permanent") → vector_ids    [不变：954，真实总数]

对每条 vector_id（循环内，metadata 校验逻辑不动）:
  classify_vector_id(id, permanent_meta):
    "ghost"    → true_orphan += 1
    "archived" → archived_count += 1
    "live"     → 已在 seen_live_ids → true_orphan += 1 (duplicate)
                 未见 → records.append(...) + seen.add

coverage.vector            = len(vector_ids)                 [不变：真实总数 954]
coverage.vector_orphans    = true_orphan                     [语义收窄：ghost+duplicate]
coverage.archived_in_index = archived_count                  [新增字段]

警告: true_orphan > 0 → "Vector index contains N permanent orphan(s)"（文案不变，语义收窄）
      archived > 0   → 不发警告（archived 是正常状态，不产生噪音）
```

### 2.2 可测性拆分设计（实现硬约束）

| 单元 | 形态 | 测试方式 | 边界 |
|------|------|---------|------|
| `classify_vector_id(note_id, permanent_meta) -> Literal["ghost","archived","live"]` | **纯函数**（cluster.py 模块级） | 直接单测三分类 + 空 dict 边界，零 mock | 不做 IO、不看 seen 状态；duplicate 判定不在此函数（依赖循环内有序状态） |
| duplicate 计数 + records 构建 | 留在 `diagnose_moc_density` 循环 | 沿用现有 mock 架构（`_permanent_meta` helper + MagicMock note_index + fake vector_store） | metadata 校验副作用（raise MocDiagnoseError）不抽出 |
| `CoverageReport.archived_in_index: int = 0` | dataclass 字段 | diagnose 层集成断言 + cli payload 断言 | 默认 0，向后兼容 |
| JSON 透传 | `moc/cli.py` coverage dict 加一项 | test_moc_cli.py payload 断言（现有模式 L130-157） | table 输出不动 |

## 3. 改动清单

1. `jfox/moc/cluster.py`
   - 新增模块级纯函数 `classify_vector_id`
   - `diagnose_moc_density`：构造 `permanent_meta`（全量）→ 派生 `live_meta`；循环内改用三分判定；`coverage.archived_in_index` 赋值；警告门控不变（真孤儿才触发，文案不变）
2. `jfox/moc/cli.py`：coverage JSON dict 加 `"archived_in_index"` 透传
3. `tests/unit/test_moc_cluster.py`：
   - 更新固化 bug 的断言（L230 `vector_orphans == 2` → `== 1` ghost + `archived_in_index == 1`；L311 同；L542 `== len(vector_ids) - 2`（=10，含 1 live-dup + 4 archived + 5 ghost）→ `== 6`（1 live-dup + 5 ghost）+ `archived_in_index == 4`）
   - 新增：`classify_vector_id` 纯函数测试；duplicate 计真孤儿测试；仅 archived 时无 orphan 警告测试；filesystem 降级时 `archived_in_index == 0` 测试
4. `tests/unit/test_moc_cli.py`：payload 含 `archived_in_index`

已核实无需改动的引用方（关键字传参构造 `CoverageReport`，新字段有默认值不 break）：`test_moc_update_cli.py`（L43/L144）、`test_moc_integration.py`（L97）、`test_moc_create_cli.py`（L41）。`formatters.py` 不涉及 moc coverage。

## 4. 决策表

| 决策点 | 选择 | 理由 |
|--------|------|------|
| archived 在 coverage.vector 计数 | 保留（954 真实总数） | coverage 反映索引真实内容；与 verify 口径可对账 |
| archived 是否发提示性警告 | 不发 | 恒有 archived 的库会变成新的恒定噪音，违背「消除误导」初衷；JSON 字段足够程序化可查 |
| table 输出是否加列 | 不加 | 最小改动；孤儿信号已由 warnings 承载 |
| duplicate（live id 重复出现） | 真孤儿 | 是索引异常而非归档状态，维持现状 |
| archived duplicate（archived id 重复出现） | `archived_in_index` 如实计数 | classify 先判 archived；重复行反映索引真实行数，archived 本身非异常 |
| `vector_orphans` 数值语义 | 收窄为 ghost+duplicate | bug fix 本质（office_hour: 10 → 0）；旧消费者按 0 处理无碍 |
| BM25 coverage | 不动 | 已是 live-only 且无孤儿警告，不在本 issue 范围 |
| rebuild 是否索引 archived | 不动 | 方案 C 行为变更，需单独评审（可另开 issue） |

## 5. 降级与非目标

- **降级**：filesystem scope 不可用（`get_all_meta()` 异常 → `permanent_meta={}`，`filesystem_count=None`）时，分类循环不执行，`vector_orphans == 0`、`archived_in_index == 0`，保留现有 "orphan verification skipped" 警告——与现状一致。
- **非目标**：不改 clustering 成员构建（archived 已正确排除）；不改 jfox-moc SKILL.md 文案（`vector_orphans` 语义收窄后「异常偏高 → 修复索引」仍然正确）；不动 BM25；不做 rebuild 索引排除。

## 6. 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|----|--------|----------|----------|----------|
| A1 | `classify_vector_id` 三分类 | 自动化验证（unit） | `uv run pytest tests/unit/test_moc_cluster.py -k classify_vector_id -v` | ghost/archived/live 三分类断言全过 |
| A2 | 计数分离：archived 不入 vector_orphans，单列 archived_in_index | 自动化验证（unit） | `uv run pytest tests/unit/test_moc_cluster.py -v` | archived 场景：`vector_orphans==0` 且 `archived_in_index==N`；ghost/duplicate 场景计入 `vector_orphans` |
| A3 | 警告门控：仅真孤儿触发 orphan 警告 | 自动化验证（unit） | `uv run pytest tests/unit/test_moc_cluster.py -k "warning or warn" -v` | 仅 archived 时 warnings 无 orphan 条目；含 ghost 时警告数正确 |
| A4 | JSON payload 含 archived_in_index | 自动化验证（unit） | `uv run pytest tests/unit/test_moc_cli.py -v` | `payload["coverage"]["archived_in_index"]` 断言通过 |
| A5 | filesystem 降级路径 | 自动化验证（unit） | `uv run pytest tests/unit/test_moc_cluster.py -k filesystem_failure -v` | 降级时 `archived_in_index==0`（现有测试补此断言），skipped 警告保留 |
| A6 | MOC 全量回归 | 自动化验证（unit+integration） | `uv run pytest tests/unit/test_moc_cluster.py tests/unit/test_moc_cli.py tests/unit/test_moc_integration.py -v` | 全部通过 |
| A7 | 静态检查 | 自动化验证（static） | `uv run ruff check jfox/ tests/ && uv run black --check jfox/moc/ tests/unit/test_moc_cluster.py tests/unit/test_moc_cli.py` | 无违规 |
| U1 | 真实 KB（office_hour）假警报消除 | 用户实测 | 安装修复版后 `uv run jfox moc diagnose --json --kb office_hour`，对比 coverage 段 | `vector_orphans==0`（或仅剩真孤儿）、`archived_in_index==10`、无 orphan 警告；可由 agent 在本机代跑（diagnose 只读无风险），执行时机 = 实现完成后 |

## 7. 向后兼容性

- JSON：仅增量字段，不破坏现有消费者（agent/脚本按 key 取值）。
- `vector_orphans` 数值变小是期望的行为修正；jfox-moc SKILL.md 的消费逻辑（异常偏高→修复索引）语义仍成立。
- table：新增一行条件性 info（仅 `archived_in_index > 0` 时），无 archived 的库输出零变化。
