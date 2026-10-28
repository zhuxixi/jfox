# `jfox edit --json` 补齐 links / backlinks / 边差异 — 设计

Drafted: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-26T23:20:00+08:00
Revised: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-26T23:40:00+08:00 — 处置 R1-D1/D2/D3

Issue: [#577](https://github.com/zhuxixi/jfox/issues/577)
关联：#502（JSON schema 统一）、#511/#530（wiki-link 解析收敛）、#561/#562（backlinks 窄写）、#573（悬空链接结构化报告，非目标）、#560（形状不同构的兄弟 issue）

## 1. 问题与根因

`jfox edit --json` 的 `note` 只有 `id/title/type/filepath` 四个键，`add` 有 `links`、`show` 有 `links`+`backlinks`。脚本读 `d["note"]["links"]` 得到 `None`，会误判成「链接全丢了」。

根因在输出组装层，不在解析或落盘：`jfox/cli.py:_edit_impl` 已经算出 `resolved_links`（L2055）、写进 `n.links`（L2056）、并用 `old_links`/`new_links` 差值维护了目标笔记的 backlinks（L2063-2079），但 L2081-2089 组装 `result["note"]` 时把这些结果全部丢弃。隔离 KB 实证输出见 `research/01-root-cause.md`。

## 2. 目标

一次 `edit --json` 调用即可自证链接结果，无需再跑 `show`：

- `note.links`：编辑后该笔记的正向链接（解析结果）；
- `note.backlinks`：编辑后该笔记的反向链接；
- `links_added` / `links_removed`：本次编辑新增 / 移除的边。

## 3. 非目标

| 不做 | 理由 |
|---|---|
| 把 `show` 改成也包裹 `note`，或把 `edit` 改成平铺 | #502 非目标明写「不动实体字段位置」，留给 2.0 纯 envelope |
| 结构化 `unresolved_links` | issue 正文列为可选；#573 正在做悬空链接结构化报告，此处另起一套会与 `add` 的 `warnings` 字符串形成新不对称、并让悬空口径分裂 |
| 给 `add` 的 `note` 补 `backlinks` | 同类但无同类误判报告，不混入本次 |
| 改 `--format table` / yaml / csv 分支 | 本次只扩 JSON 字段，控制台输出不变 |
| 改链接解析规则、backlinks 写回机制 | #511/#561 已收敛，本次只读 |

## 4. 输出契约（改后）

```json
{
  "success": true,
  "note": {
    "id": "202610262314393105",
    "title": "Src",
    "type": "permanent",
    "filepath": "/…/202610262314393105-src.md",
    "links": ["202610262314345102"],
    "backlinks": []
  },
  "links_added": ["202610262314345102"],
  "links_removed": [],
  "warnings": "Unresolved links: 999999999999999999"
}
```

字段规则：

| 字段 | 类型 | 出现条件 | 语义 |
|---|---|---|---|
| `note.links` | `string[]` | 恒有 | 编辑后 `Note.links`（`resolve_wiki_links` 输出：已去重、已过滤自链） |
| `note.backlinks` | `string[]` | 恒有 | 编辑后 `Note.backlinks`（加载自 frontmatter，本次编辑不改变它——它反映「谁指向我」） |
| `links_added` | `string[]` | **恒有**（可为空数组） | 相对编辑前新增的目标 ID，按新 links 顺序 |
| `links_removed` | `string[]` | **恒有**（可为空数组） | 相对编辑前移除的目标 ID，按编辑前 `n.links` 的顺序（前提：编辑前快照必须是有序列表，见 §5） |
| `title_changed` | `{old,new}` | 仅标题变化时 | 既有契约，不变 |
| `warnings` | `string` | 仅存在未解析链接时 | 既有契约，不变 |
| `semantic_index_warning` | `string` | 语义组件缺失时 | 既有契约，不变 |

`links_added`/`links_removed` 恒有而不是「非空才出现」，是因为本 issue 的病灶正是「键不存在 → 读成 `None` → 误判」；空数组表达「本次没有边变化」，与「字段缺失」必须在语义上可区分。这一条与仓库里 `warnings`/`title_changed` 的「非空才出现」惯例有意不同，理由记录在此。

未改内容时的行为：除 `content` 以外的编辑（`--title`/`--tag`…）不重新解析链接，`links_added`/`links_removed` 均为 `[]`，`note.links` 仍输出当前 frontmatter 值。

## 5. 组件契约与数据流

```
content ──resolve_wiki_links(self_id=n.id)──► resolved_links (n.links)
                                                    │
old_links (编辑前快照) ──────────────► diff_links(old, new) ──► (links_added, links_removed)
                                                    │
n (Note, 已保存) ─────────────────────► _edit_result_note(n) ──► note{..., links, backlinks}
                                                    │
                                          result = {success, note, links_added, links_removed, …}
```

新增两个模块级纯函数（与 `resolve_wiki_links` 同处 `jfox/cli.py`，测试可直接 import，沿用 `tests/unit/test_wiki_link_resolution.py` 的既有做法）：

1. `diff_links(old_links: Iterable[str], new_links: Iterable[str]) -> Tuple[List[str], List[str]]`
   - 返回 `(added, removed)`；`added` 保持 `new_links` 顺序、`removed` 保持 `old_links` 顺序；
   - 输入可含重复项（用集合判存在，输出按输入遍历，天然去重）；
   - 纯函数：不读配置、不碰磁盘。
2. `_edit_result_note(n: Note) -> Dict[str, Any]`
   - 返回 `{id, title, type, filepath, links, backlinks}`，其中列表是 `list(...)` 拷贝（避免调用方改到 `Note`）；
   - 纯函数：只依赖传入的 `Note`，不做 I/O。

`_edit_impl` 的接线（三处，顺序语义靠第一处兑现）：

1. **编辑前快照改有序**：现有 `old_links = set(n.links)`（L2029）改为
   `old_links_order = list(n.links)` 后再取 `old_links = set(old_links_order)`；
   原 backlinks 维护循环继续用集合（`added_links` / `removed_links`），循环体不变。
   不做这一步，`links_removed` 的顺序承诺在接线层就不可兑现——`diff_links` 只保证「按输入顺序」，
   集合输入等于无序。
2. **差值计算改调用纯函数**：`links_added, links_removed = diff_links(old_links_order, n.links)`，
   其中 `n.links` 即编辑后的有序解析结果（新增边按新顺序输出）。
3. **响应组装**：`"note": _edit_result_note(n)` 替换内联 4 键 dict，并把
   `"links_added"` / `"links_removed"` 无条件写入顶层 `result`（与 `content is None` 分支无关，
   见 §4 末段）。

## 6. 可测性拆分设计与测试边界

| 单元 | 依赖 | 测试层 | 落点（文件名::类名::用例名） | 边界 |
|---|---|---|---|---|
| `diff_links` | 无（纯函数） | `unit` | `tests/unit/test_edit_json_links.py::TestDiffLinks::*` | 不建 KB、不 mock 配置；直接传列表 |
| `_edit_result_note` | `Note` 实例（内存构造） | `unit` | `tests/unit/test_edit_json_links.py::TestEditResultNote::*` | 不写盘；断言键集与列表拷贝隔离 |
| `_edit_impl` JSON 组装 | 临时 KB（patch config，沿用 `test_edit.py` 模式） | `unit` | `tests/unit/test_edit.py::TestEditJSONLinks::*` | 验证「解析 → 落盘 → 响应」串联与 delta 正确性 |
| `jfox edit --json` 端到端 | 真实子进程（`_run_json`，cwd=REPO_ROOT） | `integration` / 契约 | `tests/test_json_schema_contract.py`（`TestContractList` 的 `edit` 条目 + `TestAlreadyCompliantSmoke::test_edit_link_fields_shape`） | 严格 JSON 解析、退出码、键存在性 |

用例名钉死（避免 `-k` 选中空集；R1-D2）：

- `TestDiffLinks::test_added_preserves_new_order`、`::test_removed_preserves_old_order`、
  `::test_duplicates_collapse`、`::test_empty_inputs`
- `TestEditResultNote::test_key_set`、`::test_list_copies_are_independent`
- `TestEditJSONLinks::test_edit_json_links_added`、`::test_edit_json_links_removed`、
  `::test_edit_json_title_only_unchanged`

不引入新的 IO 依赖，故不需要用户实测项兜底。

## 7. 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|----|--------|----------|----------|----------|
| A1 | `diff_links` 纯函数语义 | 自动化验证（unit） | `uv run pytest tests/unit/test_edit_json_links.py::TestDiffLinks` | added 保持新顺序、removed 保持旧顺序、重复输入不产生重复输出、空输入返回两个空列表 |
| A2 | `_edit_result_note` 键集与拷贝语义 | 自动化验证（unit） | `uv run pytest tests/unit/test_edit_json_links.py::TestEditResultNote` | 键恰为 `id,title,type,filepath,links,backlinks`；改返回值不影响原 `Note.links` |
| A3 | `_edit_impl`：本次新增边 | 自动化验证（unit） | `uv run pytest tests/unit/test_edit.py::TestEditJSONLinks::test_edit_json_links_added` | `links_added` 等于新增目标、`links_removed == []`、`note.links` 等于解析结果 |
| A4 | `_edit_impl`：本次移除边 | 自动化验证（unit） | `uv run pytest tests/unit/test_edit.py::TestEditJSONLinks::test_edit_json_links_removed` | `links_removed` 等于被移除目标、`links_added == []` |
| A5 | `_edit_impl`：`content=None`（仅 `--title`）时键恒有 | 自动化验证（unit） | `uv run pytest tests/unit/test_edit.py::TestEditJSONLinks::test_edit_json_title_only_unchanged` | `note.links`/`note.backlinks`/`links_added`/`links_removed` 四键都存在，两个 delta 均为 `[]` |
| A6 | 真实 CLI 的 `edit --json` 契约与 `add`/`show` 对齐 | 自动化验证（integration / 契约） | `uv run pytest "tests/test_json_schema_contract.py::TestContractList::test_success_has_top_level_success[edit]" "tests/test_json_schema_contract.py::TestAlreadyCompliantSmoke::test_edit_link_fields_shape"` | 严格 JSON 可解析；`success:true`；四键存在且为数组；`note.links` 与随后 `show --json` 的 `links` 一致 |
| A7 | 文档与实现不漂移 | 自动化验证（static） | `uv run pytest tests/unit/test_json_schema_contract_doc.py` + `npx --yes markdownlint-cli2` | `docs/json-schemas.md` 的 `edit` 行含新字段与「恒有」表述；markdownlint 通过 |
| A8 | 无回归 | 自动化验证（unit） | `uv run pytest tests/ -m "not embedding and not slow"` | 既有 Fast 集全绿 |

失败分支的覆盖方式：本次不新增失败路径（`edit` 失败的 `{success:false, error}` 形状未改动，已由
`tests/test_json_schema_contract.py::TestErrorContract` 既有 9 条锁定）；失败形状如需扩展，另开 issue。

A6 用完整 node id 而非 `-k "edit"`：实测 `-k "edit"` 当前在该文件上选中 0 个用例
（`53 deselected`），只有等新条目落地才会命中——与 R1-D2 同一类陷阱，故不依赖 `-k`。

无用户实测项：本改动是纯 JSON 字段新增，全部行为可在 `unit` + 契约子进程两层证明（§6），
不存在需要真实部署/外部服务才能观察的语义。

## 8. 兼容性与风险

- **纯增量**：只加键，不改既有的 `success`/`note.id/title/type/filepath`/`title_changed`/`warnings`；旧脚本继续工作。
- **风险 1：某个消费方按精确键集断言**。已检索 `tests/`（`grep "note\]"` 与 `keys()` 组合）未发现对 `edit.note` 做精确集合断言，现有断言都是单键取值；实施时仍以 A6 全量 Fast 集兜底。
- **风险 2：`backlinks` 指向的是加载时的值**。`edit` 不改自身 backlinks（它只改别人指向它的状态），因此 `note.backlinks` 与实际落盘一致；若并发会话同时改动，以文件为准（与 `show` 一致），不在本次引入额外重读。
- **风险 3：字段恒有的约定被后续「按惯例省略空值」改动破坏**。用 A4 的「键必须存在」断言锁住，并在 `docs/json-schemas.md` 该行显式写「恒有（可为空数组）」。

## 9. 改动清单（供计划阶段引用）

| 文件 | 改动 |
|---|---|
| `jfox/cli.py` | 新增 `diff_links`、`_edit_result_note`；`_edit_impl` 使用它们并输出 `links_added`/`links_removed` |
| `docs/json-schemas.md` | 更新 `edit` 行字段表 |
| `CHANGELOG.md` | `[Unreleased] → Fixes` 增加一条 |
| `tests/unit/test_edit_json_links.py` | 新增 `TestDiffLinks`（A1）、`TestEditResultNote`（A2） |
| `tests/unit/test_edit.py` | 新增 `TestEditJSONLinks` 三用例（A3/A4/A5） |
| `tests/test_json_schema_contract.py` | `EXPECTED_SUCCESS_COMMANDS` 加 `edit` 条目（A6）+ `TestAlreadyCompliantSmoke::test_edit_link_fields_shape` |
| `tests/unit/test_json_schema_contract_doc.py` | 补 A7 文档字段断言 |
