# Spec：issue #511 — wiki-link 字面量误链 + edit 自链

> 状态：Accepted（已按 review 修订并执行完毕）
> 路由：bug → systematic-debugging（Phase 1 根因调查完成，见 research/01）
> 关联：#470（同路径覆盖+不去重+同名歧义）、#458（# 截断），均 OPEN 不并入本 PR

## 1. 根因报告（浓缩）

| # | 根因 | 证据 |
|---|------|------|
| R1 | `_edit_impl` / `_add_note_impl` 解析循环缺自链过滤 + 去重；`_rebuild_backlinks_impl` 有 → 同系统两套规则 | cli.py:1845/520 vs cli.py:377 |
| R1b | edit 保存后 backlinks 回填循环为「新增链接」给自己回填 backlink → 自链 + 自 backlink 两面脏数据 | cli.py:1866 |
| R2 | `find_note_id_by_title_or_id` 三级匹配含「标题包含」substring fallback，短词必命中且不排除自身；命中即静默成功 | cli.py:284 |
| R3 | `_strip_wiki_link_exclusions` 只剥 fenced code block + HTML 注释；add/edit 完全不调用（直接 extract）；inline code（反引号 span）不剥 | note_index.py:42、cli.py:520/1845 |

机制链（表现 2）：正文字面量 `[[ID]]` → extract 命中 → substring fallback 命中自身标题 → 无自链过滤 → links 落盘自链 ×2（不去重）→ backlinks 回填 → 自 backlink 落盘。

## 2. 修复设计

### 2.1 核心决策

| 决策 | 选择 | 理由 |
|------|------|------|
| D1 规则统一方式 | 新增纯函数 `resolve_wiki_links(content, self_id)`，edit/add/rebuild 三处共用以替代各自内联循环 | 一条规则（自链过滤 + 去重）杜绝再漂移；可测性拆分见 §3 |
| D2 rebuild 是否改用 | 是（仅替换第一阶段解析循环，合并语义不变；填充 parsed_links 时保留 `target_id in note_by_id` 存在性过滤——note_by_id 来自文件系统扫描，与 NoteIndex 是两数据源，此行为 rebuild 的对账兜底，一行保留） | 规则真正统一；现有 backlinks 测试守护回归；不丢 rebuild 特有的存在性双保险 |
| D3 剥离接入 | 剥离**放进 `resolve_wiki_links` 内部第一步**（`_strip_wiki_link_exclusions(content)` 先行再解析），edit/add/rebuild 三路径天然一致；只影响解析输入、不改落盘正文 | 放调用点会让 rebuild 与 edit/add 解析输入再次不一致（本 issue 要根治的病复发） |
| D4 inline code | `_strip_wiki_link_exclusions` 增剥反引号 span（`` `...` ``） | 治本：字面量示例不再误链，promote 路径自动获益 |
| D5 substring fallback | **不动** | 被 show/moc/search 共用，行为变更影响面大 → 独立 issue |
| D6 去重是否做 | 做（对齐 rebuild） | 防 `[[同一目标]] ×2` 落盘重复；「覆盖 vs 合并」语义留给 #470 |

### 2.2 改动点（文件级）

1. `jfox/cli.py` — 新增纯函数 `resolve_wiki_links(content, self_id=None) -> (list, list)`：
   - 内部第一步：`_strip_wiki_link_exclusions(content)` 剥离（解析输入）
   - 随后：`extract_wiki_links` → `find_note_id_by_title_or_id` → 跳 `target_id == self_id` → 去重 → unresolved 收集（find 返回 None）
   - `_edit_impl` / `_add_note_impl`：解析段替换为 `resolve_wiki_links(content, self_id=n.id)`
   - `_rebuild_backlinks_impl`：第一阶段内联循环替换为 `resolve_wiki_links(n.content, self_id=n.id)`；填充 `parsed_links[n.id]` 时保留 `if target_id in note_by_id` 存在性过滤（rebuild 特有的对账兜底）；后续合并逻辑**零改动**
2. `jfox/note_index.py` — `_strip_wiki_link_exclusions` 增剥 inline code：`` re.sub(r"`[^`]+`", "", text) ``（轻量级，与现有 docstring「不保证解析所有 Markdown 边界情况」一致）
3. 测试新增：
   - `tests/unit/test_wiki_link_resolution.py`（纯函数，无 IO）
   - `tests/integration/test_links_edit_add.py`（CLI 级，temp_kb + ZKCLI）

### 2.3 非目标（明确不做）

- substring fallback 改精确匹配 → 独立 issue
- 同名标题解析优先级（#470 问题 2）→ #470 范围
- edit 的 links「覆盖 vs 合并」语义（#470 问题 1）→ #470 范围
- 新增「扫描自链存量」的正式 CLI 命令 → 一次性脚本（U1）

## 3. 可测性拆分设计

| 拆分出的单元 | 位置 | 纯度 | 测试边界 |
|-------------|------|------|----------|
| `resolve_wiki_links(content, self_id=None)` | cli.py | 纯（入参文本+ID，出参两列表；内部第一步剥离，依赖 note_index 只读） | 不触磁盘/frontmatter；unit 用 mock NoteIndex 直接测（沿用 test_rebuild_backlinks_impl.py 先例） |
| `_strip_wiki_link_exclusions(text)` 增强 | note_index.py | 纯（文本→文本） | unit 直接测正则行为 |
| edit/add/rebuild 装配层 | cli.py | 有副作用（落盘） | integration 用隔离 temp_kb 全链路测 |

约束：实现不得把已拆分的过滤/去重/剥离逻辑重新内联回 CLI 装配层。

## 4. 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|----|--------|----------|----------|----------|
| A1 | `resolve_wiki_links` 自链过滤 | 自动化（unit，mock NoteIndex，沿用 `tests/unit/test_rebuild_backlinks_impl.py` 的 `_FakeNote`+MagicMock 模式） | `uv run pytest tests/unit/test_wiki_link_resolution.py -v` 中 test_self_link_filtered | resolved 不含 self_id（构造标题含目标词的自身命中场景） |
| A2 | `resolve_wiki_links` 去重 | 自动化（unit） | 同上 test_dedup | 正文两个相同 `[[标题]]` → resolved 仅 1 条 |
| A3 | `resolve_wiki_links` unresolved 语义 | 自动化（unit） | 同上 test_unresolved | 不存在的目标进 unresolved，不影响 resolved |
| A4 | `_strip_wiki_link_exclusions` 剥 inline code | 自动化（unit） | `uv run pytest tests/unit/test_wiki_link_resolution.py -v` 中 test_strip_inline_code | `` `[[ID]]` `` 输入 → 输出无 `[[` |
| A5 | edit 全链路：字面量不自链 | 自动化（integration） | `uv run pytest tests/integration/test_links_edit_add.py -v` 中 test_edit_no_self_link | temp_kb 建「标题含 ID canonical」笔记 + 追加含 `[[ID|标题]]` 正文 → 读盘断言 links/backlinks 均不含自身 ID（直读磁盘等价且强于 show --json） |
| A6 | add 全链路：字面量不自链 | 自动化（integration） | 同上 test_add_no_false_self_link | 同上断言（add 场景） |
| A7 | 解析剥离生效 + 正文完整性 | 自动化（integration） | 同上 test_literal_in_fence_and_inline_not_linked | ① 正文 fenced 块与反引号内的 `[[...]]` 不进 links；② 剥离只影响解析输入——edit 后 `n.content` 与原始输入逐字节一致（剥离区域也原样落盘） |
| A8 | rebuild 不回归（规则一致性） | 自动化（unit + integration） | `uv run pytest tests/unit/test_rebuild_backlinks_impl.py tests/integration/test_index_rebuild_backlinks.py -v`；再造双链接场景跑 `jfox index rebuild --backlinks` | 现有测试全过；rebuild 结果与 edit 结果一致（同正文同 links） |
| A9 | 既有测试全量回归 | 自动化（unit/integration） | `uv run pytest tests/ -m "not slow and not embedding"` | 全绿（Fast 档，与 CI 相同范围） |
| U1 | 存量自链扫描（可选） | 用户实测 | 一次性脚本遍历 default 库：`n.id in n.links or n.id in n.backlinks` 的笔记清单 | 输出清单，逐条人工确认处置 |

> U1 处置有轻量手段：含历史自链的笔记，下次 `jfox edit` 时 `old_links` 含自己、`new_links` 不含 → backlinks 回填循环会反向删掉自己的 backlink——**edit 一次即自清**，无需专门清理器。扫出清单后逐条 edit（或无操作内容改动）即可。

> A5/A6 的复现场景严格对齐 issue 复现步骤（标题含「ID canonical」、正文含 `[[ID|标题]]` 字面量、edit 追加内容）。

## 5. 风险与回归面

- `_strip_wiki_link_exclusions` 增强影响 promote_note（note.py:501）——inline code 不再误链，属修复方向；A9 覆盖既有 promote 测试。
- rebuild 改用 `resolve_wiki_links` 必须保持「合并现有 links + 重新计算 backlinks」语义不变，A8 守护。
- 剥离正则取轻量级（不处理转义反引号），与现有函数 docstring 一致，不扩大承诺。

## 6. 里程碑

1. 用户确认本 spec
2. worktree `issue-511-wiki-link-self-link`（模型 B：同 session 绝对路径作业）+ 本 spec 作为首个 commit
3. writing-plans 产出 plan（task ↔ 验收 ID 双向追溯）
4. TDD 实现（先写 A1-A4 失败测试 → 改代码 → A5-A9）
5. 本地 CR → PR + Zima CR → merge
