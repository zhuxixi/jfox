# Spec: #601 schema 契约静态测试按命令拆分

Drafted: zai-coding-cn/glm-5.3 (selected) · zai-coding-cn/glm-5.3 (physical) @ 2026-11-16T22:30:00+08:00
Revised: zai-coding-cn/glm-5.3 (selected) · zai-coding-cn/glm-5.3 (physical) @ 2026-11-16T22:41:00+08:00（第 1 轮复核后：R1-G1、R1-D1 全部接受并改）

## 目的与理解

`tests/unit/test_json_schema_contract_doc.py` 是「文档防漂移」静态测试的唯一容器：每个改 `--json` 输出的 PR 都在同一文件末尾追加断言，PR 并行时必然内容冲突（#593 已实际撞过一次）。目的：把追加式单文件改为「一命令一文件」的纯新增模式，让未来 PR 在 git 层面零冲突。成功标准：5 条既有断言逐字保留、测试全部通过、旧文件删除、未来新增断言只需新建文件。

## 设计

### 目标布局

```
tests/unit/schema_contract/
├── __init__.py            # 空文件，包标记（bookshelf 子目录同款）
├── test_index.py          # #539 (PR #567) 的 2 条：index status 字段文档化 / 死字段移除
├── test_status.py         # #363 (PR #593) 的 2 条：status backend source 字段 / dimension 可空登记
└── test_edit.py           # #577 (PR #595) 的 1 条：edit links/backlinks 与边差异字段
```

### 每个文件的构成

1. 模块 docstring：保留溯源（来源 issue/PR 号 + 一句话职责）。
2. 各文件自带 `REPO_ROOT` / `DOC` 常量（按 issue 建议复制而非共享 helper——3 行重复可接受，换取零 import 耦合，新文件可整文件复制起步）。**唯一必须非逐字的行**：`REPO_ROOT = Path(__file__).resolve().parents[3]`——新目录比旧文件深一层，`parents[2]` 会指向 `tests/` 导致 `DOC` 落到不存在的 `tests/docs/json-schemas.md`，必须改为 `parents[3]`（第 1 轮复核 R1-G1）。禁止在 `schema_contract/` 下加 conftest.py 共享 DOC——那会漂移掉「复制而非共享」的已决决策。
3. `pytestmark = [pytest.mark.unit, pytest.mark.fast]`——对齐兄弟文件 `test_session_summary_skill_docs.py` 的约定（marker 由 `tests/conftest.py` 动态注册，已验证收集正常；当前旧文件缺这个标记，属顺手修正）。
4. 测试函数**逐字搬运**：函数名、docstring、断言文本一律不改（模块头中 `REPO_ROOT` 的 `parents` 索引是唯一例外，见上）。

### 关键决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 一条契约一文件 vs 一命令一文件 | 一命令一文件 | 文件数不随断言数膨胀；命令是天然聚合粒度 |
| 旧文件删除 vs 转发 shim | 删除 | 转发会留两处可漂移的断言位置，违背拆分初衷 |
| DOC 常量复制 vs 共享 helper | 复制（含 REPO_ROOT 改 parents[3] 这一处必要适配） | issue 原建议；避免为 3 行常量引入共享模块耦合；目录变深是复制策略的唯一代价行 |
| 是否补 pytestmark | 补 | 对齐同类文件约定，纯顺手修正，零行为风险 |
| 文件命名 test_index.py（非 test_index_status.py） | 按命令名 | 与仓库 `test_edit.py`、`test_check.py` 等命名一致 |

### 非目标

- 不改 `docs/json-schemas.md`（被测对象不变）。
- 不动根目录 `tests/test_json_schema_contract.py`（#502 运行时契约测试，另一体系）。
- 不新增/修改任何断言内容；不重构断言写法。
- 不处理其他测试文件的组织问题。

### 风险与回退

- 唯一实质风险是 pytest 收集路径/模块名问题——`tests/unit/bookshelf/` 先例 + `__init__.py` 包隔离已排除；若 CI 仍炸，单 commit revert 即可。
- 未来并行 PR 在**同一命令文件**末尾追加仍可能冲突，但概率从「每 PR 必撞」降到「同命令改动并行才撞」，已是数量级改善。

## 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|----|--------|----------|----------|----------|
| A1 | 旧文件移除、新结构就位 | 自动化验证（static） | `test ! -f tests/unit/test_json_schema_contract_doc.py && ls tests/unit/schema_contract/` | 旧文件不存在；目录含 `__init__.py` + `test_index.py` + `test_status.py` + `test_edit.py` |
| A2 | 5 条测试全保留且通过 | 自动化验证（unit） | `uv run pytest tests/unit/schema_contract/ -q` | 收集数恰为 5，全部 passed |
| A3 | 全仓收集数不变（纯移动，无丢失无重复） | 自动化验证（unit） | 拆分前后各跑 `uv run pytest tests/ --collect-only -q` 取总数比对 | 前后总数一致（净变化 0） |
| A4 | 函数与断言逐字保留 | 自动化验证（static） | `rg -c "^def test_" tests/unit/schema_contract/*.py` 逐文件比对清单：index 2 / status 2 / edit 1；断言字符串与拆分前一致（`git diff` 复核） | 函数名清单与数量吻合；diff 只见移动、新增模块头与 REPO_ROOT `parents[3]` 一行适配 |
| A5 | marker 补齐 | 自动化验证（static） | `rg -lF "pytestmark = [pytest.mark.unit, pytest.mark.fast]" tests/unit/schema_contract/ \| wc -l` | 输出 3（精确匹配 marker 全文，非仅字符串存在——第 1 轮复核 R1-D1） |

无用户实测项：本改动为纯测试文件重组，不触及外部服务与真实 CLI 行为，全部验收可由上述静态/单测命令闭环。

## 可测性拆分设计

被验证对象是「重构不丢不改」本身，拆解为三个正交观察面，各配最低成本层级：

1. **存在性**（A1/A5）：纯文件系统断言 → static 层（`test`/`ls`/`rg`），不起 pytest。
2. **等效性**（A2/A3）：pytest 收集与执行计数 → unit 层；目录级运行（A2）证明新家可跑，全量收集比对（A3）证明无净丢失。
3. **逐字性**（A4）：函数名清单 + `git diff` 人工复核（CR 环节）→ static 层。

由此形成的测试边界：不需要为「测试的搬运」再写新测试——A3 的收集总数不变即是对「无丢失无重复」的形式化证明，A4 的清单比对是对「无篡改」的机械化证明。
