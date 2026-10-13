# Spec: 修复 moc add-member 末尾路径换行丢失/成员行粘连（#547）

Drafted: zai/glm-5.3 (selected) · zai/glm-5.3 (physical) @ 2026-10-12T08:58+08:00
Revised: kimi-coding/k3 (selected) · kimi-coding/k3 (physical) @ 2026-10-13T08:12+08:00 — 第 2 轮复核收敛（0 真缺口）；R2-D1~D4 四条细化全部「接受并改」：§3.2 行号 514→515、§1 输出契约补 remove no-match 豁免、A10/U1 写明两次须用不同成员、§5 直测清单挂验收 ID。

> 本 spec 为 2026-10-12 重建版（前序 v1/v2 及存档丢失，GitHub 评论摘要保留）。
> 前序复核已裁定的有效结论（D2 越界语义、A8 空正文验收、\n\n 结尾口径）已并入。
> 根因证据链与复现输出：`research/01-root-cause.md`、`research/repro547_e2e.py`、
> `research/e2e-before.log`；历史先例：`research/02-history-and-precedent.md`。

## 0. 根因摘要

`jfox/moc/draft.py` 纯函数层按「文件表示」（`splitlines(keepends=True)`，每行自带尾换行）
设计插入逻辑；真实调用链 `_add_member_impl → _exact_load → Note.from_markdown`
（`jfox/models.py:223` `content=content.strip()`）传入「内存表示」——**末行永远无尾换行**。
三个出错路径（`_insert_into_section` 主分支/else 分支、`_append_new_group`）在文件尾附近
把本应作为空行的 `ending` 错位成前一行换行，或让新行直接粘连。

- S1：末尾分组首次插成员，标题后空行丢失（`分组\n- [[`）；
- S2：末尾分组第二次插成员，成员行粘连（`]]- [[`）；
- S3：末尾新建组，新组标题前缺空行分隔（`]]\n## 新组`）。
- 对照组：非末尾分组（插入点前一行带换行）行为正常；`remove_member_lines` 只删不插，不受影响。

## 1. 行表示契约（术语）

- **文件表示**：`splitlines(keepends=True)` 的行列表，每行（含末行）自带尾换行
  （`\n` 或 `\r\n`）。`"".join(lines)` 即磁盘正文。
- **内存表示**：`Note.content` 经 `from_markdown strip()` 后的字符串——末行无尾换行。
- **宽容输入契约（本 spec 确立）**：`upsert_member_line` / `remove_member_lines` 接受
  两种表示的任意一种作为 `content` 输入；**输出一律为文件表示**（末行带尾换行）——
  两款豁免（D6）：upsert 的幂等分支（canonical 行已存在，draft.py:424-437）与 remove 的
  无匹配早退分支（draft.py:523-525）均**原样返回入参字符串**（不经 `"".join(lines)`），
  其输出表示与输入一致，不受本契约约束（R2-D2）。
  落盘端 `to_markdown()`（`models.py:185`）固定在 content 后补一个 `\n`，
  因此完整文件以 `\n\n` 结尾（承前序 R1-D2 裁定）；下次加载 `strip()` 剥回内存表示，
  环路稳定收敛、无累积。

## 2. 决策表

| ID | 决策 | 理由 |
|----|------|------|
| D1 | 修复层级：纯函数层入口规范化（仅 `jfox/moc/draft.py`），不动 `models.py` 的 `strip()` 全局契约，不动 CLI 层 | `strip()` 影响全部笔记类型不可动；入口规范化一处修复覆盖三个出错路径（S3 即逐点修补的漏网证明） |
| D2 | 越界/空语义：`content=""`（空正文，含纯空白 strip 后）→ `_normalize_lines` 对空列表 no-op；upsert 依既定选组规则建组（「其他」或显式组），`_append_new_group` 空列表分支已安全（短路），行为显式化并锁定（A8）；`_detect_ending` 空列表返回 `"\n"` 维持现状 | 承前序 R1-G1 裁定：越界语义必须显式定义，不能靠隐式正确 |
| D3 | 输出表示：文件表示（末行带尾换行）；完整落盘以 `\n\n` 结尾 | 与 `to_markdown` 补 `\n` 环路兼容；承前序裁定 |
| D4 | CRLF：规范化补的 `ending` 跟随 `_detect_ending` 检测到的首个换行风格；CRLF 正文末行补 `\r\n` | 保持既有 `_detect_ending` 语义 |
| D5 | `remove_member_lines` 入口同样走规范化 | 契约统一 + 防御（当前 remove 不受 strip 影响，测试锁定不回归） |
| D6 | 幂等路径不规范化改写：canonical 行已存在时提前返回原 `content`、`changed=False`，保持既有语义 | 避免规范化引发伪 `changed` 与无谓落盘 |

## 3. 变更设计（数据流与组件契约）

### 3.1 新增纯函数（draft.py）

```python
def _normalize_lines(content: str) -> tuple[List[str], str]:
    """宽容输入契约：文件/内存表示均接受；返回每行自带尾换行的行列表与 ending。

    - lines = content.splitlines(keepends=True)
    - ending = _detect_ending(lines)
    - lines 非空且 lines[-1] 不以 \n 结尾 → lines[-1] += ending（内存表示 → 文件表示）
    - 空列表 no-op（D2）
    """
```

### 3.2 调用点改造（draft.py 内，共 2 处）

`upsert_member_line` 与 `remove_member_lines` 的入口两行

```python
lines = content.splitlines(keepends=True)
ending = _detect_ending(lines)
```

统一改为 `lines, ending = _normalize_lines(content)`。

**remove 侧说明**：`remove_member_lines` 现入口只有一行 `lines = content.splitlines(keepends=True)`
（draft.py:515），函数体无任何 `ending` 消费点（只删不插）。其改造为
`lines, _ = _normalize_lines(content)`——仅借规范化恢复「每行带尾换行」不变量，**不引入
`ending` 变量**（避免照抄产生未使用变量，R1-D1 裁定）。

**时序（重要）**：规范化只作用于行列表层，不改写 `content` 参数本身。

- `upsert_member_line` 的幂等分支（canonical 行已存在）返回
  `MemberUpsertResult(content=<原参数>, changed=False)`——该返回值是入参字符串原样、
  不经 `"".join(lines)`，因此幂等路径输出不受规范化影响（D6 由代码时序天然成立，A4 锁定）；
- legacy 改写分支与插入分支均返回 `"".join(lines)`——经规范化的行列表，输出文件表示。

其余逻辑（`_scan_body` / `_insert_into_section` / `_append_new_group` / 选组 /
legacy 处理）**零改动**——不变量「每行带尾换行」恢复后，既有逻辑即正确。

### 3.3 测试助手改造（tests/unit/test_moc_draft.py）

`_doc(*lines, stripped=False)`：

- 默认（`stripped=False`）：`"\n".join(lines) + "\n"`，文件表示，现有测试零改动；
- `stripped=True`：`"\n".join(lines).strip()`——与 `from_markdown` 的
  `content_text.strip()`（models.py:223）**同函数同语义**（剥两端所有空白）；
  对本 spec 构造的无首尾空白样例与 `rstrip("\n")` 等价，但对尾随空格 / `\r`
  样例不产生假等价分叉（R1-D3 裁定）。

### 3.4 端到端数据流（改后）

CLI `_add_member_impl` → `_exact_load`（内存表示）→ `upsert_member_line`
→ `_normalize_lines`（补末行换行）→ 既有插入逻辑 → join（文件表示）→
`moc.content = ...` → `update_note → to_markdown（+\n）` → 盘上 `\n\n` 结尾 →
下次加载 `strip()` 收敛内存表示 → 循环稳定。

## 4. 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|----|--------|----------|----------|----------|
| A1 | S1 修复 | 自动化（unit） | `_doc("## 末尾空分组", stripped=True)`（模拟 strip 后末行无换行的空分组正文）经 `upsert_member_line(content, note_id, title, tags, group="末尾空分组", legacy_title_unique=True)`（伪调用，签名为 draft.py:393 真实签名） | 输出含 `## 末尾空分组\n\n- [[<id>\|<title>]]\n`（标题与成员间有空行、末行带 `\n`） |
| A2 | S2 修复 | 自动化（unit） | 对 A1 输出模拟落盘再加载 `(out + "\n").strip()` 后第二次 upsert（同签名、同组、另一成员） | 输出含 `]]\n- [[`（两成员行各自独立成行）且无 `]]- [[` 子串 |
| A3 | S3 修复 | 自动化（unit） | `_doc("## A", "", "- [[m1\|一]]", stripped=True)` 上以显式新组建组 | 输出含 `]]\n\n## B\n`（新组标题前空行） |
| A4 | 幂等不回归 | 自动化（unit） | canonical 行已存在时 upsert | `changed=False` 且返回 `content` 与入参原样相等（D6） |
| A5 | 对照组回归 | 自动化（unit） | 现有全部 upsert 用例不改动 | 全部通过（非末尾分组行为不变） |
| A6 | CRLF 跟随 | 自动化（unit） | CRLF 正文、末行无换行 | 规范化补 `\r\n`；新插入行 ending 为 `\r\n` |
| A7 | legacy 路径回归 | 自动化（unit） | 唯一标题 legacy 行 canonicalize + 歧义标题保留 | 与现行为一致（改写/保留 + `ambiguous_legacy` 标志） |
| A8 | 空正文语义 | 自动化（unit） | `content=""` 与 `"   "`（strip 幂等输入）各 upsert 一次 | 不抛异常；建组（「其他」或显式组）；输出文件表示 |
| A9 | remove 回归 + no-match 豁免 | 自动化（unit） | 现有 remove 用例 + 内存表示输入的新用例 + 无匹配行早退用例 | 删除行为与现一致；内存表示输入下删行不粘连；**无匹配早退时返回入参原样（内存表示）、`changed=False`**（D6 豁免，R2-D2） |
| A10 | e2e 磁盘字节 + D3 收敛 | 自动化（integration） | temp KB：structure 笔记（正文末行为 `## 末尾空分组` 标题行，经 content-file 传入）连续两次 `moc add-member <moc> <member_a> --group 末尾空分组` 与 `moc add-member <moc> <member_b> --group 末尾空分组`（**两次成员笔记不同**——同成员第二次命中 canonical 幂等分支 draft.py:424-437 提前返回，断言永假，R2-D3）后读盘，并用 `load_note` 重载 | 盘上正文含 `## 末尾空分组\n\n- [[` 且含 `]]\n- [[`（标题后空行存在、两成员行各自独立）；反断言：不含 `]]- [[` 子串；**盘上文件正文区以 `]]\n\n` 结尾**（content 尾换行 + to_markdown 补 `\n`，D3 收敛态锁定，R1-D4）；load_note 重载后 `note.content` 与第二次 upsert 输出经 `strip()` 相等（环路收敛、无累积漂移） |
| U1 | 真实 CLI 目检 | 用户实测 | **时机**：A1~A10 全绿且 PR 合入 main 后执行。**载体**：在含修复 commit 的 repo checkout 上用 `uv run jfox …` 执行（不得用全局 / PyPI 安装的旧版，否则命中不含修复的安装、结果不可归因；如走发版验收则升级后先 `jfox --version` 核对版本号）。**隔离与清理**：用临时命名 KB（`--kb <临时名>`）或建可删除的测试 MOC；连续两次 `jfox moc add-member <moc> <note_a> --group X --json` 与 `<note_b>`（**两次用不同成员笔记**），前后 `jfox show <moc> --json` + 打开 .md 目检；验收后删除测试 MOC / 注销临时 KB | 正文列表结构完整、成员行独立、标题后空行存在；事后测试产物已回收 |

## 5. 可测性拆分设计（硬约束）

- **`_normalize_lines`（新增，纯函数，零 I/O）**：独立 unit 直测——空串、纯空白、
  单行无换行、多行末行无换行、已有换行（no-op 断言输出列表与输入相等）、CRLF、
  混合换行风格取首个。（该清单即 A6/A8 的用例展开：空串/纯空白 → A8；CRLF/混合风格取首个/
  已有换行 no-op → A6 扩展；单行与多行末行无换行 → A1~A3 输入构造基础，R2-D4）
  测试边界：只测字符串变换，不涉及 Note/文件。
- **`upsert_member_line`（既有纯函数）**：A1~A4、A6~A8 全部走它，测试边界同上；
  用例输入用 `_doc(..., stripped=True)` 构造内存表示。
- **`remove_member_lines`（既有纯函数）**：A9 边界同上。
- **e2e（A10）**：`tests/integration/` 新增（或并入既有 moc 集成测试），用
  `temp_knowledge_base` + `ZKCLI` 子进程真实落盘，读磁盘字节断言；测试边界：
  跨 CLI 进程与文件系统，不 mock。
- **实现不得把 `_normalize_lines` 内联进 `upsert_member_line` 主体**（保持独立可测），
  也不得在 CLI 层（`moc/cli.py`）做规范化（层次错位）。

## 6. 非目标

- 不改 `models.py` 的 `strip()` / `to_markdown` 全局契约（影响全部笔记类型）。
- 不修 #458（标题含 `#` 的 wiki-link 截断）、#470（edit links 不去重）——不同根因。
- 不提供脏数据 migrate 命令：已粘连的 `]]- [[` 行是单行文本，规范化不拆行；
  受损 MOC 需手动修复或 `moc update` 重建（后续可另开 issue）。
- 不改 `moc create/update` 的整体渲染路径（不经过 upsert 插入，无此 bug）。

## 7. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 输出尾部多一个 `\n` 改变文件 diff 噪音 | 只影响 add-member 触碰的 MOC；`\n\n` 结尾是稳定收敛态，一次变更后不再抖动 |
| `_doc()` 改动破坏现有测试 | 默认参数行为不变（A5 锁定），新参数仅新用例使用 |
| 隐藏调用方依赖「内存表示输出」 | 全仓检索 `upsert_member_line\|remove_member_lines` 调用点仅 `moc/cli.py`（调研已核）；spec 契约显式化 |
| CRLF 环境未覆盖 | A6 锁定；CI Linux + Windows 双跑（Fast job） |
