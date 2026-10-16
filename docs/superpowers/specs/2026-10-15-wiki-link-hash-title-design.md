# Issue #458 Spec：修复标题含 `#` 的 wiki-link 截断与静默错链

> 日期：2026-10-14 · 类型：bug · issue：#458 · 调研存档：`~/.claude/github-issue-driven/zhuxixi/jfox/issue-458/research/`
> Drafted: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-14T09:10:00+08:00
> Revised: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-14T09:40:00+08:00 —— v2，按 spec review 第 1 轮 R1-G1/G2/G3/D1/D2/D3 修订
> Revised: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-14T10:20:00+08:00 —— v3，按 spec review 第 2 轮 R2-G1/G2/G3/G4/G5/D1/D2/D3/D4/D5 修订
> Revised: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-14T11:05:00+08:00 —— v4，按 spec review 第 3 轮 R3-G1/G2/G3/D1/D2/D3/D4 修订
> Revised: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-14T21:05:00+08:00 —— v6，按 spec review 第 5 轮 R5-G1/G2/D1/D2/D3/D4 修订：清除 v1–v4 旧口径残留
> Revised: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-14T21:35:00+08:00 —— v7，按 spec review 第 6 轮 R6-G1/D1/D2/D3 修订
> Revised: deepseek/deepseek-flash (selected) · deepseek/deepseek-flash (physical) @ 2026-10-14T22:00:00+08:00 —— v8（定稿），按 spec review 第 7 轮 R7-D1/D2 修订（真缺口 0，已收敛）（见文末修订记录）

## 一句话设计

把 `#` 歧义的裁决从**提取阶段的无条件截断**推迟到**解析阶段的候选顺序试**：先拿完整原文做精确匹配，不中再拿 `#` 前缀试；子串兜底**只对完整原文生效、不再对前缀生效**。改动的接缝在提取层（返回候选列表），四个解析消费者全部迁移。

## 根因（systematic-debugging Phase 1-3 已完成）

`jfox/note_index.py:46-51` 的归一化函数无条件把 `#` 当锚点分隔符：

```python
def _normalize_wiki_link_title(link_text: str) -> str:
    target = link_text.split("|", 1)[0]
    return target.split("#", 1)[0].strip()   # ← 全仓唯一截断点
```

截断通过 `extract_wiki_links_from_text`（`note_index.py:34-43`，对每个链接调上述归一化）传播给**全部**消费者。截断后的前缀落进 `jfox/cli.py:315-359 find_note_id_by_title_or_id` 的三级匹配，第二级（精确标题）必然失败，于是走第三级「标题包含」子串匹配并**返回第一个包含者**（顺序相关）。后果有两级：

1. **静默指向错笔记**（比悬空更危险，悬空扫描扫不出来）；
2. 若子串也不中，才表现为悬空。

### 已复现的两级后果（本机 default 库，2026-10-14）

**口径与数字全部由 `research/measure-458.py` 产出，可复跑**（四个数字段 A/B-C/D 与 U1 标准同源）：

| 指标 | 数值 | 脚本段 |
|---|---|---|
| wiki-link 引用处总数 | 6101 | A |
| 其中含 `#` | 183 | A |
| 非 `#` 链接的不同目标数（零回归口径） | 1156 | A |
| **非 `#` 链接在现状与方案间的行为差异数** | **0** | A |
| 含 `#` 且靠子串兜底解析的缩写写法处数 | 15（2 个目标） | A |
| 非 `#` 且仅靠子串兜底解析的处数 | 348（46 个目标） | A |
| 截断受害者 引用处 / 不同目标 | **164 / 54** | B/C |
| 含受害链接的笔记数 | 123 | B/C |
| 现状：正确 / **静默错链** / 悬空 | 97 / **67（12 个目标）** / 0 | B/C |
| 方案：正确 / 静默错链 / 悬空 | 160 / 4 / 0 | B/C |
| **存量对账：缺失真值 / 残留错链（处数）** | **47 / 93** | D |
| **定向手术：remove / add / keep（处数）** | **12 / 612 / 177** | E |
| **真值连新解析也推不出的 id 数（#470 范畴）** | **6** | E |
| 需手术笔记数 | 376 | E |
| **手写 links 候选（落库 − 旧解析，全库去重 id 数）** | **41（124 条笔记）** | D |

方案为**净改善**：67 处静默错链降到 4 处，悬空仍为 0，且**零回归**——1156 个非 `#` 链接目标的现状/方案行为差异为 **0 个**（脚本 A 段产出）。

方案下残留的 4 处错链是 `pi-agent-board issue #42 键位决策最终形态…` 这类同名/近名歧义（`← 双语` vs `← 双语义`），属 #470 问题 2 的范畴，**不在本 spec 范围**（见「非目标」）。

### 关键反证

`NoteIndex.find_by_title("Issue #81 执行计划 — 防崩溃 + 断点续跑（任务拆分与优先级）")` **能命中**。说明标题库侧没有问题，错的只是「从正文提取链接」这条路径的裁决顺序。

### 为什么子串兜底是「放大器」而非纯缺陷

`cli.py:353-357` 的子串匹配也在做对的事：本库存在用户写的**缩写标题**链接，靠子串兜底解析正确——含 `#` 的这类写法实测 **15 处**（2 个目标）、非 `#` 的 **348 处**（46 个目标），两者均由脚本 A 段产出。所以设计不能简单删掉子串兜底，而应把它从「对截断前缀匹配」改为「对完整原文匹配」，既消掉脆弱性、又保住这些缩写用法。

### 反向证据（说明脆弱性真实存在）

本 spec 起草当天，default 库新增了一条标题含 `issue` 的 permanent 笔记，导致 6 处 `[[Issue #81 执行计划]]` 的解析结果**立刻从正确变为指向该新笔记**。子串兜底「返回第一个包含者」的时序脆弱性由此实证。

## 设计

### 核心契约变更（接缝在提取层）

截断发生在提取层，所以契约变更必须落在提取层——只改 `cli.py` 的解析会把其余三个消费者留在旧行为上。

```python
# jfox/note_index.py

def split_wiki_target(link_text: str) -> List[str]:
    """把一个 wiki-link 的目标拆成按优先级排列的候选。

    含 `#` 时返回 [完整原文, 前缀]；无 `#` 时返回 [原文]。
    alias（`|` 左侧）在此剥离。空前缀不产生空候选。
    """
    raw = link_text.split("|", 1)[0].strip()
    if "#" in raw:
        prefix = raw.split("#", 1)[0].strip()
        return [raw, prefix] if prefix and prefix != raw else [raw]
    return [raw]


def extract_wiki_link_targets(text: str) -> List[List[str]]:
    """提取每个 wiki-link 的候选目标列表（顺序即优先级）。

    不做剔除（fenced / 行内代码 / HTML 注释），调用方自行预处理——与既有
    extract_wiki_links_from_text 的职责边界保持一致。
    """
    return [split_wiki_target(m.group(1).strip()) for m in _WIKI_LINK_RE.finditer(text)]
```

### 四个消费者全部迁移

| 消费者 | 现状用途 | 迁移后语义（R2-D1 / R2-D4 修订） |
|---|---|---|
| `cli.py:383` `resolve_wiki_links` | add / edit / rebuild 落 frontmatter links | 消费 `extract_wiki_link_targets`，对每个候选列表按「精确 ID → 精确标题（**casefold 比较**）」逐个试；全不中时**只对 `candidates[0]`（完整原文）**做子串兜底 |
| `note_index.py:269` `find_notes_referencing_title` | backlink 回填反查（`cli.py:635` 消费） | **成员判断**：候选列表中任一候选 **casefold 后**等于目标标题即算引用（现实现为 `link.lower() == title_lower`，大小写不敏感契约由 `test_note_index.py:340` 钉住，不得丢） |
| `note.py:601`（`promote_note` 内） | **精确 ID 匹配**（无子串兜底）+ `grounded_by` 合并 | **候选迭代精确匹配**：对每个候选做 `find_by_title` 精确匹配（**不加子串兜底**）；`grounded_by` 是 ID 列表，不参与候选拆分。语义与上一行不同，不得套用成员判断 |
| `graph.py:97`（解析在 `graph.py:107-125` `_resolve_link`） | 知识图谱建边 | 同 `resolve_wiki_links`：候选迭代精确 + 子串只对完整原文 |

`extract_wiki_links_from_text`（`note_index.py:34`）与 `cli.extract_wiki_links`（`cli.py:309-312` 包装）构成**旧提取函数族**：迁移完成后产品代码调用方清零（`cli.py:312` 的唯一调用方 `cli.py:383` 同步迁移），二者一并删除或转调取 `candidates[0]`（即不再截断）——**不保留任何继续吃截断文本的通道**（见开放项 1）。

**锚点语义不变**：`[[笔记B#章节]]` 的候选是 `["笔记B#章节", "笔记B"]`，第二个候选精确命中「笔记B」——`tests/unit/test_note_index.py:394-418` 钉住的别名+锚点混合用例应保持通过（A6 显式钉住）。

### 为什么有效

- **精确阶段**：`#` 类链接先试完整原文。标题含 `#` 的真实笔记在此命中，不再经过截断——67 处静默错链由此降到 4 处。
- **锚点语义保留**：完整原文不中时仍试 `#` 前缀的**精确**匹配。
- **子串阶段**：只对完整原文。非 `#` 链接的原文就是前缀，行为与现状逐字节一致（1156 个目标零差异，脚本 A 段实测）；`#` 类链接的缩写写法仍能靠完整原文子串命中，但不再因前缀过短而误中无关笔记。

### 为什么不选备选方案

| 备选 | 不选的理由 |
|---|---|
| 删掉 `#` 锚点语法（把 `#` 一律当标题字符） | 破坏性变更，`[[标题#锚点]]` 用户全部受影响；且本库有真实锚点用法与测试钉住 |
| 保留现状，只把 `moc` 渲染改成 ID 形式 | **已完成**（`moc/draft.py::_member_link`，见「已排除项」）；存量正文旧链接仍错 |
| 直接删除子串兜底 | 会打断用户写的缩写标题链接——含 `#` 的实测 15 处、非 `#` 的 348 处（脚本 A 段），造成回归 |
| 只改提取层返回完整文本、不做候选 | 会把 `[[标题#锚点]]` 变成无法解析的整体，破坏锚点语义（`test_note_index.py:394-418` 会挂） |
| 只改 cli 解析、不动提取层 | 另外三个消费者（graph / note / referencing）继续吃截断文本，影响面声明落空 |

### 已排除项（issue 正文的第 1 条建议已完成）

issue 正文写「`moc create` / `draft.py` 渲染成员列表时使用 `[[标题]]` 形式」。当前 main 已是 canonical 形式：

```python
# jfox/moc/draft.py:99-108
def _member_link(note_id: str, title: str) -> str:
    """…退化为 [[ID]] 形式，规避 #458/#470。"""
    if "\n" in title or "\r" in title or "]" in title:
        return f"[[{note_id}]]"
    return f"[[{note_id}|{title}]]"
```

使用于 `render_moc_content`（create / update）与 `upsert_member_line`（add-member），引入 commit `e02e2c4` (#505)。**本 spec 不含此项。**

## 影响面

**截断点在单点，但传播路径经提取层到四个消费者**。四个消费者全部纳入本 spec 的改动与验收：

| 消费者 | 用途 | 验收 ID |
|---|---|---|
| `cli.py:383` → `resolve_wiki_links` | add / edit / rebuild 落 frontmatter links | A3 / A5 |
| `note_index.py:269` → `find_notes_referencing_title`（`cli.py:635` backfill 消费） | backlink 回填反查 | A8 |
| `note.py:601`（`promote_note` 内） | note 层链接解析 | A6（含 `test_note_promote.py`） |
| `graph.py:97`（+`graph.py:107-125`） | 知识图谱建边 | A7 |
| `redirect.py:136` | redirect 引用迁移 | A4 |

`redirect.py` 当前 import `_normalize_wiki_link_title`；迁移后消费候选契约，但 redirect 的「只做精确匹配、不改写子串命中的链接」语义必须保持不变——**redirect 不参与子串兜底**，这是既有契约（`test_no_substring_match` 钉住）。

`graph.py:97` 对 raw content 提取链接、不做剔除（口径与 `note_index` 相反）。该口径差异属既存事实，**不在本 spec 范围**（#548 spec 已登记）。

## 非目标

- **不处理 #470 问题 2（同名标题解析歧义）**——同一条三级匹配链的另一面，属性独立。本 spec 方案下残留的 4 处错链即属此类，需另开 issue 或拆出处理。
- **不处理 #470 问题 1（edit 覆盖 frontmatter links）**——`_edit_impl` 的 `n.links = resolved_links` 覆盖语义。U1 的手术方案**绕开**该语义（只改 frontmatter links 数组、不经 `resolved_links`），两者不冲突；本 spec 也不去改动它。反向约束：若实现期为 #470 问题 1 改动 `apply_backlinks` 写路径，需保证 U1 手术仍能按预期写入 links（U1 步骤④ 的「不得用 `jfox edit`」不变）。
- **不统一 `redirect.py` / `graph.py` 的剥离口径分歧**（#548 spec 已登记为独立话题）。
- **不引入完整 Markdown 解析器**——`_strip_wiki_link_exclusions` 的轻量口径不变。
- **不新增产品 CLI 命令做批量修正**——存量修复沿 #548 的 U 项先例走一次性脚本 + 用户核对。
- **不改 `moc/draft.py`**（已符合 canonical 方向）。

## 保证边界

- 本 spec **不保证**子串兜底完全无语义歧义：完整原文对多条标题同时成立子串时，仍返回「第一个包含者」（顺序相关）。本 spec 消除的是「截断前缀过短导致的误中」，不是子串匹配本身的顺序敏感性。
- 本 spec **不保证**同名标题（标题逐字节相同）能被消歧——该场景下 `NoteIndex._by_title` 的覆盖行为决定结果，属 #470 问题 2。
- **零回归**的保证范围仅限脚本 A 段实测的 1156 个非 `#` 链接目标（差异 0）+ 仓内既有测试；未覆盖全库所有可能写法。
- U1 的手术方案**不依赖** `_edit_impl` 的覆盖语义（`cli.py:2019`）——它绕开 `resolved_links` 直接改 frontmatter links 数组，因此手写 links 天然不受影响。反向约束：若实现期为 #470 问题 1 把 `apply_backlinks` 的窄写改成其它语义，需重新核对手术脚本能否仍按计划写入。
- 方案把静默错链从 67 处降到 4 处，**不是 0**——残留 4 处属 #470 同名歧义，不要在 U1 里期望归零。

## 可测性拆分设计

改动落在两个**纯函数**上，加两个**依赖注入的解析函数**：

- `split_wiki_target(link_text) -> List[str]` —— 纯函数，字符串进、列表出，无 IO。
- `extract_wiki_link_targets(text) -> List[List[str]]` —— 纯函数，无 IO（不做剔除，与既有职责一致）。
- `resolve_link_target(candidates) -> Optional[str]` —— 依赖 `NoteIndex` 查询，测试用 mock index 注入（既有 `tests/unit/test_wiki_link_resolution.py:23` 的 `_make_index` 是现成先例）。

测试边界：

- **unit（A1–A4、A6、A8）**：直接对纯函数与 mock index 断言。无 embedding、无 ChromaDB、无文件系统，亚秒级。
- **integration（A5、A7）**：经 `ZKCLI` 走真实落库读回，证明用户可观察症状消失。
- **用户实测（U1，存量修复）**：存量正文里的链接文本本身是完整的（截断只发生在解析侧），修复后重新解析就能拿到正确目标；手术只改 frontmatter `links` 数组、不动正文。不新增产品 CLI 命令的依据：这是对历史 bug 的一次性修复，沿 #548 的 U 项先例走一次性脚本 + 用户核对即可，不值得为它常驻 CLI 表面。

### 存量修复：用定向手术，不用重存（v5 改，R4-G1）

**v1–v4 的 U1 用 `jfox edit` 重存来清存量错链，这条路是死的。** `edit` 的 `n.links = resolved_links`（`cli.py:2019`）是**覆盖语义**，必然丢弃正文推不出的存量条目（= #470 问题 1）；而 U1 既想靠它清错链、又想靠同一操作保住手写 links，两个目标在同一机制上不可兼得。复核者实测：重存集 50 条里 40 条会触发回滚，且我规定的回滚命令 `jfox edit --content-file <同内容>` 会重跑同一解析、是空操作。

换成**定向手术**（只改 frontmatter `links` 数组，不经 `resolved_links`）：

```
target_links = new_parse ∪ (stored − old_parse)
remove       = stored − target_links
add          = target_links − stored
```

其中 `old_parse` / `new_parse` 分别是旧、新解析器对**该笔记正文**的解析结果全集；`stored − old_parse` = 正文压根推不出的存量条目（手写或早期遗留）——靠这一项把它排除在 remove 之外，从而天然保住手写 links（非循环：存量错链是旧解析的产物，必在 `old_parse` 里，不会落进该集合）。

**关键发现（E 段实测，推翻 v1–v4 的框架）：** 真正的「截断诱因错链」只有 **12 处**。v3/v4 把它叫「残留错链 93 处」是错的口径——那 93 里 **81 处是旧解析也推不出的存量条目**（手写/早期遗留），本来就不应删。按 v4 的门禁去清「93 → 0」会误删 81 条合法链接。

自动地，手术拆成两个已有能力的组合：

| 分量 | 处方 | 规模 |
|---|---|---|
| **add** | 直接跑已有的 `jfox index rebuild --backlinks`（`cli.py:454` 并集语义，只增不删） | 612 处 |
| **remove** | 定向删除 12 处截断错链 id（`remove = stored ∩ (old_parse − new_parse)`） | 12 处 |
| **keep** | 不动（手写/早期遗留） | 177 处 |

**为什么手术能解决 R4-G1**：不经过 `resolved_links`，手写 links 天然不受影响；回滚从「空操作」变成真实的「写回旧 links 数组」；remove 集合只含可证明的截断诱因错链（`old_parse` 产出、`new_parse` 不产出）。

### 三种口径必须分开（R2-G1 / R3-G2 / R5-G1）

- **解析口径（脚本 B/C 段）**：只读正文 + 索引做模拟，**不读落库的 frontmatter links**。手术只改 frontmatter links、**不改正文与标题**，所以 B/C 段输出在手术前后**逐字节相同**——**不得用作门禁**（用它会得到「执行前后都通过」的空转结论，这是 R2-G1 拦下的问题）。
- **落库对账口径（脚本 D 段）**：读每条笔记真实的 frontmatter `links`，与正文真值对账。**自 v5 起仅作对账旁证**——v4 曾把它当门禁（「缺失真值 47 / 残留错链 93 → 0/0」），该门禁已废弃：93 里 81 处是旧解析也推不出的存量条目（手写/早期遗留），按它执行会误删 81 条合法链接（R5-G1）。
- **手术口径（脚本 E 段）**：U1 的**唯一门禁**——见上一节公式，同时给出 keep（手写保全）与 remove（确定删）。基线实测：需手术 **376 条笔记**，remove **12** / add **612** / keep **177**。

E 段是**只读 dry-run**：只输出每条的 `remove` / `add` / `keep` 明细，不做任何写入——所以 U1 执行前就能先把整个手术计划过一眼。

> v3 曾用「手写候选 = 落库 − 旧解析」当 ④ 的判据，结论仍不可行（R4-G1）；v5 把它降为手术公式里的 `keep` 项，不再用作回滚门禁。

### 存量修复的触发路径（已验证）

- `jfox index rebuild --backlinks`：`merged = sorted(set(n.links + parsed_links[n.id]))`（`cli.py:454`）——**并集语义，只增不删**，正是手术公式里 add 分量的现成处方。注：该路径带自链过滤（`resolve_wiki_links(content, self_id=n.id)`），实测有 **2 处**自链子串命中（`Wiktionary`、`Zima One`）会被跳过，故实际补 **610/612**。
- `jfox edit <id> --content-file <同内容>`：`n.links = resolved_links`（`cli.py:2019`）——**覆盖语义**，产出正文解析真值但**同时丢弃正文推不出的存量条目**（= #470 问题 1）。**因此 U1 不用它**：既清错链又保手写，两个目标在同一机制上不可兼得（R4-G1 的病因）。

因此 U1 走**定向手术**（只改 frontmatter `links` 数组，不经 `resolved_links`），而非重存；执行步骤见下文 U1。

## 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|----|--------|----------|----------|----------|
| A1 | `split_wiki_target` 对含 `#` 原文返回 `[完整, 前缀]`，无 `#` 返回 `[原文]`；先剥 alias 再切锚点；空前缀不产生空候选 | 自动化验证（unit） | `uv run pytest tests/unit/test_wiki_link_target.py -k split` | 清单①–④全通过 |
| A2 | `resolve_link_target` 按候选顺序命中：完整原文精确 → 前缀精确 → 完整原文子串；且子串阶段**不再对前缀生效** | 自动化验证（unit） | `uv run pytest tests/unit/test_wiki_link_target.py -k resolve` | 清单⑤–⑨全通过，特别是⑧「前缀能子串命中、完整原文不能」须返回 None |
| A3 | #458 本体：完整标题含 `#` 且该标题真实存在时解析到正确笔记 | 自动化验证（unit） | 同上，用例⑩（真实形态：`zima-blue-cli #213：…` + 干扰笔记「…zima-blue-cli 仓库根 CLAUDE.md…」） | 返回真实目标 id，而非干扰笔记 |
| A4 | redirect 的精确匹配语义不回归（不参与子串兜底），且含 `#` 锚点形式能精确命中 | 自动化验证（unit） | `uv run pytest tests/unit/test_redirect.py` + 新增一条含 `#` 锚点用例（如 `[[旧标题#锚点]]` 的迁移改写目标正确） | 既有用例（含 `test_no_substring_match` / `test_id_form_matches`）全部通过；新增含 `#` 用例通过 |
| A5 | 端到端：`add` 正文含 `[[完整标题（含#）]]` 的笔记后，`show --json` 的 `links` 指向真实目标 | 自动化验证（integration） | `uv run pytest tests/integration/test_wiki_link_hash_title.py`（新增文件） | `links` 含真实目标 id；不含任何指向干扰笔记的条目 |
| A6 | 既有解析行为不回归，**覆盖全部四个消费者的既有测试入口**，且 promote 路径的含 `#` 锚点有正向验证 | 自动化验证（unit） | `uv run pytest tests/unit/test_wiki_link_resolution.py tests/unit/test_note_index.py tests/unit/test_rebuild_backlinks_impl.py tests/unit/test_note_promote.py tests/unit/test_add_backfill_links.py` + 新增一条 promote 用例：正文含 `[[标题#章节]]` 的 candidate 经 `promote_note` 后 links 含正确目标 | 全部通过；`test_note_index.py:394-418` 的别名+锚点用例必须通过；`test_note_promote.py:117-134`（`note.py:601` 所在 `promote_note` 路径）必须通过；`test_add_backfill_links.py` 覆盖 `cli.py:635` 消费路径；新增含 `#` promote 用例通过 |
| A7 | 图谱建边路径迁移：`[[完整标题（含#）]]` 在 graph 中生成指向真实目标的边 | 自动化验证（integration） | 新增用例，fixture 用 `tests/conftest.py` 的 `temp_kb` + `cli`（参照 `tests/test_advanced_features.py:55` 的 `KnowledgeGraph` 构建模式——`tests/integration/` 目录下**没有**可复用的 graph fixture，须新建）；命令 `uv run pytest tests/integration/test_wiki_link_hash_title.py -k graph` | 目标节点的入度含来源笔记；不产生悬空边 |
| A8 | backlink 回填路径迁移：`find_notes_referencing_title` 能识别含 `#` 的完整标题引用，且保持大小写不敏感 | 自动化验证（unit） | `uv run pytest tests/unit/test_note_index.py -k referencing`（今日即命中既有 7 个 `test_find_notes_referencing_title*` 用例）+ 新增含 `#` 用例 | 含 `#` 的完整标题引用被识别；锚点形式 `[[标题#锚点]]` 同样被识别；`test_note_index.py:340` 的大小写不敏感用例保持通过 |
| U1 | 存量错链清理：用定向手术清 12 处截断诱因错链，手写 links 零丢失 | 用户实测 | 见下方「U1 执行步骤」 | 见下方「U1 通过标准」（E 段口径） |

A5/A7/A8 为必做（影响面声明与验收矩阵必须一致）。

### U1 通过标准（三口径，与测量脚本输出一致）

- **解析口径（脚本 B/C 段，执行前后不变，仅作旁证）**：静默错链目标数 ≤ 4（残留属 #470 同名歧义）；164 处受害引用中 ≥ 160 处命中真实目标。
- **手术口径（脚本 E 段，这是门禁·机械判定式）**：手术后 `stored ∩ (old_parse − new_parse) = 0`（即复测时 E 段 `remove` 计数 = 0）；手写 links 丢失 = 0（keep 集合不参与手术）；另 `add` 残留 = 2（自链子串命中，`rebuild` 路径自带链过滤跳过）属预期。
  > 术语提醒：本门禁指「remove 类清零」，**不是**真值口径的错链归零——真值口径下术后仍有 4 处（属 #470，见上一条口径）。把两者混读会得到假阳性失败（R5-D2）。
- **不可达项（脚本 E 段，逐条记录，不要求归零）**：真值连新解析也推不出的 id = **6**（属 #470 同名歧义，R4-G2）。

> v4 的「缺失真值 = 0 / 残留错链 = 0」两个门禁已废弃：前者把 #470 同名歧义算成了本 issue 的失败（R4-G2），后者口径错（93 里 81 处不是错链，按它执行会误删合法链接）。

### U1 执行步骤（调用全部钉定项目环境，R2-G3）

所有 jfox 调用统一用 `uv run --project /home/elling/git-repo/github/jfox jfox …`（或先确认已升级的安装版），
避免 PATH 上的安装版 1.16.3 跑旧截断逻辑。设 `ISSUE_DIR=~/.claude/github-issue-driven/zhuxixi/jfox/issue-458`。

```
⓪ 前置：修复已合入 main 且本机 jfox 已升级（或全程走 uv run --project）。
   sanity check：建一条临时笔记，正文写 [[<某条标题含 # 的真实笔记>]]，
   uv run --project <repo> jfox show <新笔记> --json 看 links 是否指向真实目标。
   确认通过再继续——旧逻辑下前缀精确永不命中真目标，只会悬空或错链，故本检查能区分新旧逻辑。
① 备份：uv run --project <repo> jfox backup run
② 基线 + 手术计划（均只读）：
   uv run --project <repo> python $ISSUE_DIR/research/measure-458.py > $ISSUE_DIR/baseline.txt
   先过目 E 段的手术计划（376 条笔记 / remove 12 / add 612 / keep 177），确认无误再继续。
   ⚠️ 不要在此时执行 D 段的「残留错链 93 → 0」——那 93 里 81 处不是错链（见上文）。
③ 补 add：uv run --project <repo> jfox index rebuild --backlinks
   （并集语义，只增不删；覆盖 E 段那个 612 处 add。实补 610——其中 2 处是自链
   子串命中（Wiktionary / Zima One），rebuild 路径自带链过滤会跳过；术后 E 段
   残留 add=2 属预期，不是未收敛。）
④ 删 remove：跑手术脚本（**待创建**，$ISSUE_DIR/research/surgery-458.py）：
   uv run --project <repo> python $ISSUE_DIR/research/surgery-458.py --dry-run  # 先列计划
   uv run --project <repo> python $ISSUE_DIR/research/surgery-458.py            # 执行
   脚本只改 frontmatter links 数组（不经 resolved_links）；ledger 落
   $ISSUE_DIR/research/surgery-ledger.json，每条记录 {note_id, note_file, old_links, new_links}。
   ⚠️ 本步不得用 jfox edit——那会触发覆盖语义、吃掉手写 links（R4-G1 的病因）。
⑤ 核对：读 ledger，逐条核对 remove 项仅限计划内 id、keep 集合 177 处全部保留；
   任一笔记出现计划外丢失 → 用旧 links 数组写回该条（真实可执行的回滚）。
⑥ 终门禁：uv run --project <repo> python $ISSUE_DIR/research/measure-458.py
   与 baseline.txt 比对，通过标准见上（E 段：remove = 0 / 手写丢失 = 0 /
   add 残留 = 2 / 不可达 ≤ 6）。
⑦ 收尾：再跑一次 uv run --project <repo> jfox index rebuild --backlinks。
   因为 ③ 先于 ④ 执行，backlinks 是基于「含错链的 links」算的；④ 删掉 12 处
   错链后，目标笔记的 backlinks 会残留来源 id。收尾重算一次即收敛
   （并集只增不删，且错链 id 已不在来源 links，故安全）。
```

> **为什么不用 `jfox edit` 回滚**：v1–v4 的 ④ 写的回滚命令 `jfox edit --content-file <同内容>` 会重跑同一解析，与重存结果完全相同——是空操作（R4-G1）。手术方案下回滚就是「写回旧 links 数组」，不再有这个问题。

## 回归用例清单（A1/A2/A3 落到 `tests/unit/test_wiki_link_target.py`）

| # | 用例 | 期望 | 防什么 |
|---|------|------|--------|
| ① | `split_wiki_target("A#B")` | `["A#B", "A"]` | 候选顺序 |
| ② | `split_wiki_target("A")` | `["A"]` | 无 `#` 单候选 |
| ③ | `split_wiki_target("A#B\|C")` | `["A#B", "A"]` | 先剥 alias 再切锚点 |
| ④ | `split_wiki_target("#B")`（前缀为空） | `["#B"]` | 空前缀不得产生空候选 |
| ⑤ | 完整原文精确命中 | 完整原文的目标 | A3 本体 |
| ⑥ | 完整原文不中、前缀精确命中 | 前缀目标 | 锚点语义保留 |
| ⑦ | 两者都不中、完整原文子串命中 | 子串目标 | 缩写标题链接（`[[Issue #81 执行计划]]`）不回归 |
| ⑧ | **前缀能子串命中、完整原文不能** | `None`（不返回前缀子串目标） | **本 spec 的核心行为变更**：前缀不再参与子串 |
| ⑨ | 全不中 | `None` | 悬空路径 |
| ⑩ | `[[zima-blue-cli #213：…（usage 采集）]]` + 干扰笔记「…zima-blue-cli 仓库根 CLAUDE.md…」 | 真实目标 | #458 评论区的实测复现形态 |
| ⑪ | 候选匹配大小写：`[[某标题小写形式#章节]]` 命中大写标题 | 命中 | 候选比较须 casefold（`test_note_index.py:340` 契约） |

用例⑧是「零回归」承诺的边界：它断言的是**行为改变**，必须被显式钉住，否则后续维护者会误判为 bug 改回去。

## 改动文件

- `jfox/note_index.py`：新增 `split_wiki_target`、`extract_wiki_link_targets`（均纯函数）；`find_notes_referencing_title`（`note_index.py:269` 内部提取点）改消费候选列表并保持 casefold 比较。
- `jfox/cli.py`：新增/改写 `resolve_link_target`（候选顺序 + 子串只对完整原文）；`resolve_wiki_links`（`cli.py:383`）改为消费候选；`cli.extract_wiki_links` 包装（`cli.py:309-312`）随迁移处理。
- `jfox/note.py`：`note.py:601`（`promote_note` 内）改消费候选列表（候选迭代精确匹配，无子串）。
- `jfox/graph.py`：`graph.py:97` 提取与 `graph.py:107-125` `_resolve_link` 改消费候选列表。
- `jfox/redirect.py:136`：消费候选契约，保持精确匹配语义。
- `tests/unit/test_wiki_link_target.py`（新增）：清单①–⑪。
- `tests/unit/test_note_index.py`：新增 A8 含 `#` 用例。
- `tests/integration/test_wiki_link_hash_title.py`（新增）：A5 + A7。
- 一次性脚本 `surgery-458.py`（**待创建**，U1 用；放 issue 调研目录 `$ISSUE_DIR/research/`，**不进产品仓库**；只改 frontmatter `links` 数组、不经 `resolved_links`；ledger 落 `$ISSUE_DIR/research/surgery-ledger.json`）。
- `~/.claude/github-issue-driven/zhuxixi/jfox/issue-458/research/measure-458.py`：测量脚本（已落盘，U1 复用）。

## 开放项（实现阶段决定，不影响本 spec 的验收契约）

1. **旧提取函数族**（`note_index.extract_wiki_links_from_text` + `cli.extract_wiki_links` 包装）是删除还是转调取 `candidates[0]`——取决于迁移后剩余调用方数量（实现时 grep 确认）。**无论哪种走法，四个消费者都必须在本次迁移完毕**。
2. `split_wiki_target` 的归属：留在 `note_index.py`（与现归一化同处），不新增模块。
3. `_normalize_wiki_link_title` 是否保留为薄 shim——同 1，实现时按 grep 结果定。

## 修订记录

- v8（2026-10-14，spec review 第 7 轮后 · **收敛定稿**）：
  - **R7-D1（接受并改）**：脚本「U1 手术后的预期门禁值」块枚举缺「add 残留 = 2」（其余四处均有），且复用 D 段术语「缺失真值」指代 E 段的不可达项（同一份输出中该词以 47 与 6 两个含义出现）。→ 补齐枚举、术语改为「真值不可达项」。
  - **R7-D2（接受并改）**：文字微瑕——删重复括注、`automatically地` → 「自动地」、脚本注释标点。
- v7（2026-10-14，spec review 第 6 轮后）：
  - **R6-G1（接受并改）**：R5-G1 对脚本打印块的修复不完整——`measure-458.py` 的 D 段打印头仍标着「U1 的门禁数据源」（v4 废弃口径），与同一份输出后文的警示块及 spec 三口径自相矛盾；baseline.txt 因此内部不一致。→ 打印头改为「对账旁证（门禁见 E 段）」。
  - **R6-D1（接受并改）**：脚本 docstring 仍是 v4 叙事（「四段」「C 段不能当门禁、只有 D 段能」「这两个数字才是 U1 的差异来源」「重存（jfox edit）」），实际已输出 A–E 五段、门禁在 E 段、机制已换手术。→ docstring 重写为五段口径；清理残留注释。
  - **R6-D2（接受并改）**：门禁打印文本错字「手写丢 loss」→「手写丢失」。
  - **R6-D3（接受并改）**：门禁枚举在三口径节/脚本打印与步骤⑥ 之间差一项 → 两处补「`add` 残留 = 2 属预期」。
- v6（2026-10-14，spec review 第 5 轮后）：
  - **R5-G1（接受并改）**：废弃的「D 段 0/0」门禁残留在两处——文档「三种口径」节，以及被声明为唯一权威、U1 实跑的 `measure-458.py` 打印块。→ 文档该节改写为「三口径分开」并把 D 段降为对账旁证；脚本打印块改为 v5 三口径（remove 清零 / keep 保全 / 不可达 ≤6），并加「D 段 0/0 已废弃、93 里 81 处不是错链」的显式警示。
  - **R5-G2（接受并改）**：「重存」叙事在 5 处残留（可测性拆分设计的「重存即自愈」、触发路径节的「唯一途径」「U1 走重存」、非目标与保证边界两节的「依赖 edit 覆盖语义」），与「④ 不得用 jfox edit」直接矛盾。→ 全部改写为手术框架：`edit` 只能作为「为何不用」的反证；U1 明写「不依赖覆盖语义」。
  - **R5-D1（接受并改）**：612 处 add 中有 2 处自链子串命中（`Wiktionary` / `Zima One`），`rebuild` 自带链过滤会跳过 → 实际补 610；已在触发路径节与 U1 步骤③⑥ 注明「术后 add=2 残留属预期」。
  - **R5-D2（接受并改）**：门禁术语与真值口径字面冲突 → 改为机械判定式 `stored ∩ (old_parse − new_parse) = 0`（复测时 E 段 remove = 0），并加术语提醒。
  - **R5-D3（接受并改）**：「手写候选 41 处」误标单位——41 是全库**去重 id 数**，keep 177 是手术子集内的**逐笔记处数**，两者不同聚合、不同子集。→ 数字表拆成两行并标清单位；脚本打印同步修正。
  - **R5-D4（接受并改）**：③ 先于 ④ 导致错链目标笔记的 backlinks 残留来源 id。→ U1 新增步骤⑦（收尾重跑 `rebuild --backlinks`）。
- v5（2026-10-14，spec review 第 4 轮后 · 用户选 A：继续第 5 轮）：
  - **R4-G1（接受并改，改机制）**：U1 的「重存」机制与 `edit` 的覆盖语义根本冲突（覆盖语义必丢正文推不出的 links = #470 问题 1），且 ④ 的回滚命令是空操作。→ **U1 改为定向手术**：`target = new_parse ∪ (stored − old_parse)`，拆成「`rebuild --backlinks` 补 add」+「定向删除 12 处错链 id」；手写 links 因不参与公式的删集而天然保住；回滚变成真实的写回动作。（脚本 E 段把手术计划做成只读 dry-run，执行前可全量过目。）
  - **R4-G2（接受并改）**：同名歧义使部分真值永不可达 → 门禁不再要求「缺失真值 = 0」，改为「不可达项 ≤ 6 且逐条记录为 #470 范畴」。
  - **起草者自查修正（推翻 v1–v4 的框架）**：E 段实测发现 v3/v4 的「残留错链 93 处」口径错——其中仅 **12 处**是截断诱因错链，另 81 处是旧解析也推不出的存量条目（手写/早期遗留），按旧门禁「93 → 0」会误删 81 条合法链接。released numbers 全部改为 E 段产出。
- v4（2026-10-14，spec review 第 3 轮后）：
  - **R3-G1（接受并改）**：④ 引用的「残留错链项清单」在脚本里不存在（只打印文件名+条数，不打印 id 级条目），类型也不匹配 ④ 要比较的 id 集合；ledger 落盘路径未定义。→ 脚本 D 段补打 id 级清单；spec 写明 ledger 落盘路径 `$ISSUE_DIR/research/resave-ledger.json` 及记录字段。
  - **R3-G2（接受并改）**：v3 的 ④ 规则 `旧−新 ⊆ 已知错链集合` 按构造恒真、零判别力（`旧−新 = 落库 − 新解析 = 错链集合`），承诺的手写保护分支不可达。→ 改用**非循环手写口径**：脚本 D 段新产出「手写 links 候选 = 落库 − 旧解析」（基线 41 处 / 124 条笔记）；④ 规则改为「该集合必须仍在新 links 里，丢任何一个即回滚」。这是 v2「必回滚」→ v3「必不回滚」之后的正确形态。
  - **R3-G3（接受并改）**：⑤ 门禁排在 ⑥ 补缺之前，实测基线里 3 条「仅缺不错」笔记只能靠 `rebuild --backlinks` 补回，按 v3 顺序 ⑤ 首跑必假失败（缺失真值 = 3）。→ 把补缺提到终门禁之前，⑤ 改为补缺、⑥ 改为终门禁。
  - **R3-D1（接受并改）**：348 处数字无脚本出处（复核者复算恰好正确）。→ 脚本 A 段新增「非 `#` 且仅靠子串兜底解析的处数」，输出 348（46 个目标）。
  - **R3-D2（接受并改）**：`resave-458.py` 未标注「待创建」。→ 改动文件处补标注。
  - **R3-D3（接受并改）**：⓪ 的 `uid run` 笔误 → `uv run`。
  - **R3-D4（接受并改）**：A4/A6 只跑既有测试，而既有测试无含 `#` 用例——走「转调 shim」分支且漏迁移 promote/redirect 时，非 `#` 行为不变、A4/A6 照样全绿，含 `#` 语义退化无验收钉住。→ A4 新增 redirect 含 `#` 锚点用例；A6 新增 promote 正文 `[[标题#章节]]` 用例。
- v3（2026-10-14，spec review 第 2 轮后）：
  - **R2-G1（接受并改）**：U1 门禁原来不可观测——脚本只读正文做模拟，而重存只改 frontmatter links，B/C 段输出在重存前后逐字节相同。给 `measure-458.py` 增加 **D 段存量对账**（读真实 frontmatter links 与正文真值比对），把 U1 门禁改挂到「缺失真值 / 残留错链」两个数字（基线 47 / 93）；脚本内打印的通过标准由「=0 / 全部正确」改为与矩阵一致的双口径，并显式警示「不要用 C 段做门禁」。
  - **R2-G2（接受并改）**：④ 回滚规则原为「旧−新 必须为空」，与「移除错链」的目标自相矛盾（会让 50 条修复全部回滚）。改为 `旧−新 ⊆ 已知错链集合`，错链集合来自 D 段输出。
  - **R2-G3（接受并改）**：U1 步骤 ①③④ 的裸 `jfox` 调用全部改为 `uv run --project <repo>` 形式；重存脚本内嵌 REPO 路径（与 measure-458.py 同款）。
  - **R2-G4（接受并改）**：撤回无出处的数字——「19 处缩写依赖」实际为 **15 处**（脚本 A 段产出）；「1156 个非 `#` 目标」与「差异 0」也改为脚本 A 段产出；删除「口径与数字全部由脚本产出」中不成立的覆盖声明（现 A/B-C/D 四段确实全部由脚本产出）。
  - **R2-G5（接受并改）**：A6 命令追加 `tests/unit/test_note_promote.py`（`note.py:601` 所在 `promote_note` 路径的唯一既有测试入口）与 `tests/unit/test_add_backfill_links.py`（`cli.py:635` 消费路径）。
  - **R2-D1（接受并改）**：设计表 `find_notes_referencing_title` 行明确「候选比较须 casefold」，不再写成大小写敏感的 `title in candidates`；新增回归用例⑪。
  - **R2-D2（接受并改）**：A7 的 fixture 改为可追溯方案（`tests/conftest.py` 的 `temp_kb` + `cli`，参照 `tests/test_advanced_features.py:55`），并注明 `tests/integration/` 下无可复用 graph fixture。
  - **R2-D3（接受并改）**：U1 全文路径改为绝对路径；区分「issue-458 调研目录 research/」（脚本实际所在）与仓库路径；⑤ 的基线引用由 ⓪ 更正为 ②；新增 baseline.txt 落点定义。
  - **R2-D4（接受并改）**：设计表 `note.py:601` 行不再写「同上」——该处是「候选迭代精确匹配（无子串兜底）+ grounded_by 合并」，与 `find_notes_referencing_title` 的成员判断语义不同。
  - **R2-D5（接受并改）**：开放项 1 扩为「旧提取函数族」（含 `cli.extract_wiki_links` 包装）。
  - 起草者补充：U1 步骤新增 ⑥（对未被 ③ 覆盖的受害笔记跑 `index rebuild --backlinks` 补缺失真值）；「保证边界」补一条「方案降到 4 处不是 0，不要在 U1 期望归零」。
- v2（2026-10-14，spec review 第 1 轮后）：R1-G1/G2/G3/D1/D2/D3。
- v1（2026-10-14）：初稿。
