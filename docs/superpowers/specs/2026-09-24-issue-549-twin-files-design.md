# #549 spec：加载笔记按真实磁盘路径读写（消除同 ID 双文件）

- 状态：**confirmed v2（用户已批准并实现完成；整分支终审 Ready to merge: Yes）**
- v2 变更（review 修订）：① U1 重设计为受控演练（v1 的「incident 复刻」在笔记已规范化后验证不了任何东西）；② 补 `update_note` 成功后重钉 pin 契约；③ 补 `save_note` 就地写边界（改 title/topic/type 须走 update_note）；④ A7 补无入链前置；⑤ A3 定为 integration；⑥ 防回归注释列为交付物。
- issue：zhuxixi/jfox#549
- 调研依据：`research/root-cause-and-fix-verification.md`（含原型实验 E1–E3）

## 1. 背景与现状

一个 bug 类：**「笔记磁盘文件名 ≠ 按当前字段现算的规则名」时，jfox 的读写路径会指向错误位置**。写面产生同 ID 双文件，读/删面直接失败。

- 触发预置条件：磁盘名 ≠ 规则派生名（外部改标题未同步改名 / legacy slug 漂移 / KB 迁移）。
- 当前知识库实测：**0 条**处于触发态（issue 里的双文件已被清理，`index verify` duplicate_ids 为空）。真实库今天实弹命中过一条永久笔记（incident）。
- 根因链（HEAD 核实）：`models.py` `filename` 三分支 → `from_markdown` 丢弃 filepath（`_filepath` 恒 None）→ `filepath` property 现算 → `save_note` 无旧文件比对。
- 站点图（8 处，见调研文件 §4）：写面 4 处（`add` 回填、`edit` 回填、`rebuild --backlinks`、MOC 成员回填），读/删面 4 处（`show`、`delete`、MOC ghost 检查、`list --paths`）。
- 站点图复核（v2，已逐个读码）：`prompts/judge.py:130`、`prompts/actions.py:252`、`auto_summary/runner.py:651`、`moc/generate.py:79` 四个 `save_note` 站点均构造全新对象（无加载路径），不属本类。
- 仓库已有同类修复范式（#392 A2/A3 → #422）：delete/promote 的 target 清理用「`find_note_file` 真实路径 + 重读 fresh + `_atomic_write(actual_path)`」。

## 2. 目标与非目标

**目标（三个症状一次消掉）**

1. 写面：对 stale 名笔记的任何写入**就地落在真实文件**，不再产生双文件。
2. 读面：`show` 能读 stale 名笔记；`list --paths` 输出真实路径；MOC 成员检查不再误判 ghost。
3. 删面：`delete` 能删掉 stale 名笔记的真实文件。
4. 行为不变：`edit --title` 改名、改 type 跨目录移动等既有「规范化写」语义**原样保留**。

**非目标**

- 存量双文件修复（当前 0 条；如需另行处理）。
- 对已有 stale 名笔记做批量规范化改名（无必要，就地读写即可；update_note 触碰时会自然自愈）。
- 清理 `moc/cli.py:589`、`redirect.py:420` 的既有绕法（保留，注释已记录根因；本次不动以缩小 diff）。
- 并发丢更新（#392 A3 范畴，本修复只解决路径正确性，不改变各站点的并发语义）。
- legacy 文件名的自动迁移（#407/#408 已按读面对账解决）。

## 3. 设计

### 3.1 核心决策：路径语义两分法

| 语义 | 方法 | 写盘目标 | 用途 |
|------|------|----------|------|
| **就地写** | `save_note` | `note.filepath`（加载时钉住的真实路径） | backlink 回填、rebuild、MOC 成员回填 |
| **规范化写** | `update_note` | **规则派生路径**（按当前 type+title/topic 现算）+ 删旧文件 | `edit`、promote/archive/reject、MOC 保存 |

### 3.2 决策表

| 场景 | 期望行为 | 机制 |
|------|----------|------|
| `from_markdown(content, filepath)` | `filepath` 属性 === 传入的真实路径 | 构造后钉 `_filepath` |
| `from_markdown(content)`（无 filepath） | `filepath` = 规则派生（现状） | pin 保持 None |
| `save_note`（回填/重建） | 就地写真实文件，无新文件 | filepath 已钉 |
| `update_note`（edit/promote/archive/moc save） | 写规则派生名；旧文件不存在则不动；不同则删旧 | 目标路径改用 `expected_filepath` |
| stale 名笔记被 `update_note` 触碰 | 规范化为规则名（自愈，单文件） | 同上 |
| `delete_note` | 删真实文件 | filepath 已钉（**无需改代码**） |
| `show` / `list --paths` | 读/输出真实路径 | filepath 已钉（**无需改代码**） |
| MOC 成员回填（`moc/generate.py:109/140`） | 就地写真实文件 | filepath 已钉（**无需改代码**） |
| MOC ghost 检查（`moc/generate.py:51`） | stale 名成员不再误判 ghost | filepath 已钉（**无需改代码**） |

### 3.3 组件契约

- `Note.filename -> str`（既有，纯函数）：三分支规则名。
- `Note.expected_filepath -> Path`（**新增，纯**）：`config.notes_dir / type.value / filename`——规则派生路径，永不看 pin。
- `Note.filepath -> Path`（调整 docstring）：pin 优先，否则 `expected_filepath`。
- `Note.from_markdown(content, filepath=None) -> Note`（调整）：filepath 非 None 时钉 `_filepath`（coerce 为 `Path`）。
- `note.save_note(note, add_to_index=True) -> bool`（docstring 明确就地写语义，逻辑不变）。**契约边界**：就地写不保证文件名随字段变——**改 title/topic/type 的意图必须走 `update_note`**；对加载的笔记 `save_note` 只会写回加载路径。
- `note.update_note(note_obj, add_to_index=True) -> bool`（调整）：写盘与改名判据改用 `note_obj.expected_filepath`；`find_note_file` 找旧路径与删旧逻辑不变；docstring 补「规范化写」语义。**写盘成功后必须把 `note_obj._filepath` 重钉为刚写入的路径**——否则同对象随后的 `save_note` 会按陈旧 pin 写回旧路径、复活双文件（v1 遗漏；原型用 finally 恢复旧 pin 掩盖了此点）。

### 3.4 数据流

```
磁盘文件 --load_note--> from_markdown(content, path)
                          └─ 钉 _filepath = path
save_note(note)  →  _atomic_write(note.filepath)            # 就地
update_note(note) → _atomic_write(note.expected_filepath)   # 规范化
                    + unlink(find_note_file(id)) if 不同且存在
```

## 4. 可测性拆分设计

- **纯函数层（unit，无需 IO/KB）**：`Note.expected_filepath` 三分支（fleeting / session(topic 优先，空 topic 回退 title) / 其余）；`Note.filepath` 的 pin/非 pin 两态；`from_markdown` 有/无 filepath 的钉与不钉。测试文件 `tests/unit/test_note_path_rules.py`。
- **IO 层（integration，temp KB + mock embedding）**：CLI 级复现矩阵（下表 A4–A8）。夹具手法复用 `tests/unit/test_delete_backlink_cleanup.py:655-695`（`os.rename` 到 `{id}-renamed.md` 制造发散名），不新增抽象层。
- **护栏（回归）**：既有 `tests/unit/test_edit.py:72-82`（改标题→改名）、`:373-390`（改 type→跨目录）必须保持绿。
- 命名约束：测试文件/用例名避开子串 `search|semantic|embedding|vector|query|suggest`（`-m "not embedding"` 过滤口径）；用例标题全局唯一（#483 闸门）。
- 副作用隔离：不改 `models.py` 的 IO 面（models 保持无 IO）；`note.py` 保持「IO + 路径语义」，不引入新模块。

## 5. 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|----|--------|----------|----------|----------|
| A1 | `expected_filepath`/`filename` 三分支与 pin 两态 | 自动化（unit） | `uv run pytest tests/unit/test_note_path_rules.py -m "not embedding"` | 全绿 |
| A2 | `from_markdown` 钉/不钉 | 自动化（unit） | 同上 | 全绿 |
| A3 | `update_note` 写规则名 + 删旧（stale 名自愈，单文件）+ 成功后重钉 pin | 自动化（integration） | `uv run pytest tests/integration/test_stale_name_single_file.py`（含自愈用例与「同对象 update 后再 save_note 不复活旧文件」用例） | 全绿，单文件 |
| A4 | `add` 回填 stale 名笔记：无新文件、backlinks 落真实文件 | 自动化（integration） | `uv run pytest tests/integration/test_stale_name_single_file.py` | 断言 `glob(id*)` 唯一 + backlinks 含链接者 |
| A5 | `edit` 增删链接（incident 场景） | 自动化（integration） | 同文件 | 单文件 + backlinks 正确 |
| A6 | `index rebuild --backlinks` 触及 stale 名笔记 | 自动化（integration） | 同文件 | 单文件（逐条） |
| A7 | `show` 可读 + `delete --force` 删真实文件 | 自动化（integration） | 同文件 | `success=true`；文件消失且无残留。**前置：被删笔记必须无入链**（否则触发引用保护 `1 note(s) reference this note`，E3c 实测） |
| A8 | MOC 成员回填/ghost 检查 | 自动化（integration） | 同文件或 `tests/unit/test_moc_member_cli.py` 增补 | 单文件；成员被接受 |
| A9 | 护栏：改标题改名 / 改 type 跨目录 | 自动化（integration） | `uv run pytest tests/unit/test_edit.py` | 全绿 |
| U1 | 真实库受控演练（v2 重设计） | 用户实测（须用户点头后由 agent 用仓库版代码执行） | ① `jfox add` 在真实库建牺牲笔记 S；② `mv` 其文件制造发散名；③ `jfox add` 一条链接 S 的笔记触发回填；④ 断言 `glob(S.id + "*")` 单文件且 backlinks 落位；⑤ `jfox delete` 清理 S 与链接者；⑥ `jfox index verify --json` 的 `duplicate_ids` 为空 | 六步全部符合，现场无残留 |

U1 说明（v2）：v1 的「incident 复刻」无效——incident 笔记已被清理成规范名，普通回填测不到 stale 路径；真实库当前 0 条 stale 笔记，要验证只能受控制造。上列六步全程可逆（牺牲笔记 + 完整清理），执行前需用户确认；若倾向零触碰，可降级为只读核验（仅⑥）。未执行前不允许宣称全部验收完成。

## 6. 风险与缓解

| 风险 | 缓解 |
|------|------|
| 钉路径让 `update_note` 改名失效（E2b 已实证） | 本 spec 的 A3/A9 覆盖：update_note 改 `expected_filepath` 后必须同时过 stale 自愈与新改名两测 |
| MOC 标题编辑后文件随 update_note 改名（行为变化） | 现库 0 条 stale MOC，且属规范化收敛；A8 覆盖成员侧，MOC 自身由 A9 同族语义覆盖 |
| `from_markdown` 公共面被误用 | 调用方仅 `note.py` 内部 2 处 + 测试（已 grep 核实） |
| 其他隐藏站点 | 钉路径是「根因级」修复，未来新站点天然免疫；新增测试锁定三个症状 |
| load 之后文件被外部改名（微竞态） | save 会按陈旧 pin 在旧路径复活文件。与现状同窗口（现状更糟：直接写规则名），非本次范围；`update_note` 重钉 pin 已收窄此窗口 |

## 7. 实现文件清单（预期）

- `jfox/models.py`：`from_markdown` 钉路径；新增 `expected_filepath` property；`filepath` docstring。
- `jfox/note.py`：`update_note` 写盘/改名判据改用 `expected_filepath`（+docstring）；`save_note` docstring 明确就地写。
- **防回归注释（交付物，#548 教训）**：`filepath` property、`from_markdown`、`update_note` 三处必须留注释，说明「就地写 / 规范化写」两分法、update_note 为何不能用 `note_obj.filepath`（E2b：钉路径后改名判据恒假，`test_edit.py:72-82` 必挂）、以及写盘成功后重钉 pin 的原因——防止未来被「简化」回 `note_obj.filepath`。
- `tests/unit/test_note_path_rules.py`（新）。
- `tests/integration/test_stale_name_single_file.py`（新，含 A4–A8）。
- `CHANGELOG.md`：`## [Unreleased]` 加 Fixes 条目。
- 视情况：`tests/unit/test_edit.py` 增补 stale 自愈用例。
