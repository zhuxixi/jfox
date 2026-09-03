# Spec: MOC 单成员管理命令 + 沉淀时归属流程（issue #484）

> Status: DRAFT — 等用户审阅确认
> Issue: `zhuxixi/jfox#484`
> 调研目录：`~/.claude/github-issue-driven/zhuxixi/jfox/issue-484/research/`
> 正式文档目标：`docs/superpowers/specs/2026-09-03-moc-member-management-design.md`

## 1. 背景与目标

`session-to-permanent` 当前在新 permanent 笔记落库后直接结束，没有把新笔记归入 MOC。
新笔记因此会游离在主题地图之外；仅依赖事后 `moc update` 又无法覆盖语义偏远主题和用户
忘记运行维护命令的场景。

本 issue 建立三层闭环：

1. `jfox moc add-member` / `remove-member` 提供可靠的单成员操作入口；
2. `session-to-permanent` 在最终落库前确认新笔记的 MOC 归属，落库后调用 `add-member`；
3. `moc update` 继续作为批量维护和遗漏发现的兜底入口，文档明确它不是沉淀时归属的主路径。

本 spec 同时把**新生成的 MOC 正文成员链接**统一为 ID canonical 形式
`[[NOTE_ID|标题]]`。存量 MOC 不做全库迁移，但单成员 add/remove 会按安全规则处理存量格式。

## 2. 设计决策

| ID | 决策点 | 结论 | 理由 |
|----|--------|------|------|
| D1 | 正文 canonical 格式 | 新生成或新写入的成员行以 ID 为目标、以标题为别名；标题不安全时只写 ID 目标；create 继续保留已有的 `— N links` 后缀，add 新行不添加后缀 | ID 位于目标部分，标题只作显示别名，规避 #458 的 `#` 截断和 #470 的同名歧义；add 没有聚类 link degree 数据 |
| D2 | `render_moc_content` | 同步改为渲染 ID canonical 链接；不做全库迁移 | 新建 MOC 不再产生已知标题死链；存量文件由 add/remove 按需处理 |
| D3 | 正文分组 | 未指定 `--group` 时按正文中普通组的出现顺序匹配成员 tags；无命中使用「其他」组；没有时创建；`--group` 可覆盖 | 组名本质上来自共享 tag；默认自动归类，仍保留人工控制能力 |
| D4 | 系统区段 | `近期活动`、`待归类` 不参与 tag 匹配，也不允许作为 `--group` 目标；「其他」是普通 fallback 组 | 防止新成员进入动态/待处理区段；保留系统区段语义边界 |
| D5 | 幂等语义 | add 检查并修复 links、正文行、成员 backlink 三类状态，而不是只检查 `moc.links` | 三套成员事实可能漂移；重复调用应修复缺失状态，不应把不一致误判为 no-op |
| D6 | legacy 标题行 | `[[标题]]` 只有在全库大小写不敏感地唯一时才可认领、改写或删除；标题歧义时不猜 | #470 的标题索引覆盖规则不具备安全确定性 |
| D7 | 成员类型 | 活跃 permanent 正常执行；活跃非 permanent 允许执行并 warning；已归档成员拒绝 add；structure 作为成员允许但 warning | 保护 MOC 稳定骨架约定，同时兼容已有手工非 permanent 链接 |
| D8 | MOC 状态与自链 | 已归档 MOC 拒绝 add、允许 remove；`moc_id == note_id` 始终拒绝 add | 归档 MOC 不应继续增长；自链没有导航价值 |
| D9 | 参数形式 | `MOC_ID` / `NOTE_ID` 只接受满足 `^[A-Za-z0-9][A-Za-z0-9_-]*$` 的非空 ID，不做标题或 substring 解析；按索引精确加载后再次核对对象 ID | ID 是确定性接口，避免标题歧义及基于 glob 的文件误命中 |
| D10 | 多 MOC | 一条新笔记可以挂 0 个、1 个或多个 MOC；每条新笔记独立确认，允许不同笔记选择不同 MOC | MOC 成员关系天然多对多，不能把整个 batch 绑定到一个 MOC |
| D11 | 索引与 embedding | add/remove 不运行聚类和语义诊断，但 `update_note` 默认更新索引，可能调用 embedding backend；测试使用 mock backend | “无需聚类”不等于“完全不触发 embedding”；保持现有 `update_note` 语义 |
| D12 | 部分失败 | MOC 主文件成功而 backlink 辅助写入失败时，命令返回 `success=true`、`partial=true` 和具体失败 ID；若没有任何持久化变化，`applied=false`；MOC 主文件写入失败则失败且不调用 backlink helper | 主状态与辅助状态分开报告，便于重试而不误报 |

## 3. 组件与数据流

### 3.1 精确加载与标题唯一性

add/remove 运行在 `use_kb` 上下文中，所有索引和文件操作必须使用当前 active config，不得读取默认
知识库的缓存。

每个命令开始时先创建 `idx = get_note_index(active_config)` 并执行一次 `idx.rebuild()`，把该索引作为
本次命令的 active-config 快照。CLI 使用一个精确加载边界：通过 `idx.find_by_id(note_id)` 获取精确的
`NoteMeta`，再从其 `filepath` 加载 Note，并核对 `note.id == note_id`。不能仅依赖当前
`load_note_by_id()` 的 `id*.md` glob 命中结果。这样既保留现有索引入口，又避免短前缀误命中。

legacy 标题的唯一性通过 `get_note_index(active_config).get_all_meta()` 统计：按大小写不敏感的完整
标题计数，统计包含已归档但 frontmatter 有效的笔记。标题计数不调用 `find_by_title()`，因为该方法
只保留同名标题的最后一条元数据。

### 3.2 CLI：`jfox moc add-member <MOC_ID> <NOTE_ID> [--group <组名>] [--kb <kb>] [--format table|json] [--json]`

CLI 支持现有的 `--kb`、`--format table|json` 和 `--json` 快捷方式，并遵循当前 MOC CLI 的
`_xxx_impl` + `use_kb` 结构。

处理顺序：

1. 校验两个 ID 均满足 `^[A-Za-z0-9][A-Za-z0-9_-]*$`；在当前 active config 中从本命令开始时建立的
   `idx` 精确加载 MOC，并核对对象 ID 完全相等。
2. MOC 不存在、类型不是 `structure` 或已归档时失败；`MOC_ID == NOTE_ID` 时失败。
3. 精确加载成员笔记，并确认文件真实存在、对象 ID 完全相等且成员未归档；不存在、ghost 或已归档时失败。
4. 活跃非 permanent 成员生成 warning；structure 成员额外生成 `nested structure member`
   warning，但继续执行。
5. 使用前述已刷新过的 `idx` 统计成员标题唯一性；标题唯一性和正文加载必须来自同一次 active-config
   索引快照。同时记录执行前两种状态：
   - `links_has_member = NOTE_ID in moc.links`；
   - `backlink_has_member = MOC_ID in member.backlinks`；
   正文是否已有成员行由随后调用 `upsert_member_line` 返回的 `had_existing_row` 表示。
6. 调用 `upsert_member_line` 处理正文：
   - 已有目标 ID 的 canonical 行：不重复插入、不搬组、不改已有别名；
   - 没有 canonical 行但存在唯一的 legacy `- [[标题]]` 成员行：将所有可安全认领的行原地改写为
     canonical 目标（正常标题为 `[[NOTE_ID|标题]]`，包含换行或 `]]` 的不安全标题使用 `[[NOTE_ID]]`），
     保留行的其他文本后缀，不额外插入；
   - legacy 标题不唯一：不认领旧行，追加一条 canonical ID 行并返回 warning；
   - 既有 canonical 行与 legacy 行同时存在时，canonical 行优先，legacy 行不自动删除；唯一 legacy 行
     仍可由 remove 安全删除；
   - links 已有 ID 但正文缺行：补正文行；
   - 三处都没有：按 D3/D4 选择组并插入正文行。
7. 将 MOC frontmatter links 规范化为 `sorted(set(moc.links + [NOTE_ID]))`，保留其他已有链接。
8. 只要正文或 links 发生变化，就调用 `update_note(moc)`。写盘返回 false 时立即失败，不调用
   backlink helper；`update_note` 对向量/BM25 索引失败的处理沿用现有实现。
9. 即使 MOC 正文和 links 已经一致，只要成员 backlink 缺失，也调用 `backfill_moc_backlinks(moc, [NOTE_ID])`
   修复 backlink。
10. 汇总 legacy 歧义、类型和 backlink 失败 warning，生成 JSON 或 table 输出。

**add 幂等字段定义**：

- `already_member=true`：执行前，`links_has_member`、`backlink_has_member` 或纯函数返回的
  `had_existing_row` 至少有一项为 true；即使本次随后修复缺失状态，也保持 true。歧义 legacy 行不算
  `had_existing_row`，因为无法安全确认它属于目标 ID。
- `applied=true`：正文、frontmatter links 或成员 backlink 至少有一项被持久化修改；只有内存对象变化、
  但写盘失败时不算 applied。
- 三处已经一致且 links 无重复时，返回 `already_member=true, applied=false, partial=false`，不产生无意义
  的更新时间或索引更新。
- links 已有但正文缺失、正文已有但 links 缺失、backlink 缺失或 links 有重复，都不是纯 no-op；命令应修复
  缺失/重复状态。

### 3.3 CLI：`jfox moc remove-member <MOC_ID> <NOTE_ID> [--kb <kb>] [--format table|json] [--json]`

CLI 同样支持现有的 `--kb`、`--format table|json` 和 `--json` 快捷方式。

处理顺序：

1. 校验两个 ID 均满足 `^[A-Za-z0-9][A-Za-z0-9_-]*$`；使用本命令开始时建立的 active-config `idx` 精确加载
   MOC，并核对对象 ID完全相等；要求 MOC 类型为 `structure`。MOC 已归档不影响 remove。
2. 成员笔记可以不存在或已归档；若仍存在，加载其 title 和 backlinks，用于 legacy 判断和 backlink 摘除。
   目标不存在时仍可按 ID 清理 MOC links 与 canonical ID 行；目标不存在不产生 backlink 写入失败。
3. 调用 `remove_member_lines`：
   - 删除正文中所有精确匹配 NOTE_ID 的 canonical 成员行，跨所有顶层区段查找；
   - 如果目标笔记仍存在且其标题在全库唯一，同时删除精确匹配的 legacy `- [[标题]]` 成员行；
   - 如果目标笔记不存在或无法取得标题，只清理 ID canonical 行和 frontmatter links，不把任意标题行当作该成员；
   - 如果标题有歧义，保留 legacy 行并返回 warning；不使用 substring 或索引覆盖结果猜测目标；
   - 普通组删行后只剩空白时，删除该普通组标题及其空白行；如果组内还有说明文字、子标题、代码或其他
     Markdown 内容，则保留组标题；
   - `近期活动`、`待归类` 的标题永不删除，但这些区段中的精确 ID 成员行可以按 NOTE_ID 清除。
4. 从 MOC links 删除 NOTE_ID 的所有重复项。
5. 只要正文或 links 发生变化，调用 `update_note(moc)`；写盘失败时不摘除成员 backlink，并返回失败。
6. 目标笔记仍存在时调用 `remove_moc_backlinks(moc.id, [NOTE_ID])`；目标已不存在不调用 helper。
7. 输出 remove 专属 JSON/table 契约。

**remove 状态定义**：

- `removed=true`：至少删除了一条正文行、一个 links 条目或一个成员 backlink，并且对应变化成功持久化。
- `not_member=true`：执行前没有 links、backlink、canonical 行或可安全认领的 legacy 行；歧义 legacy 行不算已确认的成员状态。
- 只有歧义 legacy 行而没有其他可确认状态时，返回 `removed=false, not_member=true, applied=false, partial=false`
  并带 warning；不修改 MOC 文件，也不调用 `remove_moc_backlinks`。
- 如果同时清理了 links、canonical 行或 backlink，但歧义 legacy 行仍保留，返回 `partial=true`，因为可确认的
  状态已清理但正文仍有无法安全判断的旧行。
- remove 会删除所有区段中的目标 ID 行，不因同一成员跨多个 tag 组而只删除第一处。

### 3.4 JSON 契约

add-member 成功响应固定包含：

```json
{
  "success": true,
  "moc_id": "MOC_ID",
  "note_id": "NOTE_ID",
  "title": "成员标题",
  "group": "实际组名或 null",
  "already_member": false,
  "applied": true,
  "partial": false,
  "rows_added": 1,
  "rows_canonicalized": 0,
  "warnings": []
}
```

- `group` 在已有多处成员行时取正文中第一处所属组；没有正文行或本次没有插入/认领时为 null。
- `rows_added` 是本次新增的正文成员行数；`rows_canonicalized` 是本次从唯一 legacy 标题行改写的行数。
- 主文件只补 links/backlink 而没有正文操作时，`group` 为 null。
- `partial=true` 时，`warnings` 必须列出 backlink 失败成员 ID、MOC ID 和可重试命令上下文；legacy 歧义 warning
  必须包含目标标题。
- 失败响应沿用现有 `_fail` 契约：`{"success": false, "error": "..."}`，进程返回码为 1。

remove-member 成功响应固定包含：

```json
{
  "success": true,
  "moc_id": "MOC_ID",
  "note_id": "NOTE_ID",
  "title": "成员标题或 null",
  "removed": true,
  "not_member": false,
  "applied": true,
  "partial": false,
  "removed_rows": 2,
  "removed_groups": ["zima", "cr"],
  "warnings": []
}
```

- `removed_rows` 是本次删除的正文行数；`removed_groups` 去重但保持正文首次出现顺序。
- `warnings` 始终是数组；非 permanent、nested structure、legacy 歧义和 backlink 辅助写入失败都放入该数组。
- backlink 失败 warning 至少包含成员 ID 和 MOC ID；必要时给出可重试的命令。
- 如果只清理了 frontmatter links 或 backlink，没有正文行被删除，`removed_rows=0`，不伪造正文变更。

### 3.5 `draft.py` 纯函数边界

正文处理不读索引、不访问文件、不加载 embedding。使用结果 dataclass，使 CLI 不重复实现 Markdown 扫描逻辑：

```python
@dataclass(frozen=True)
class MemberUpsertResult:
    content: str
    resolved_group: Optional[str]
    changed: bool
    rows_added: int
    rows_canonicalized: int
    had_existing_row: bool
    matched_groups: tuple[str, ...]
    ambiguous_legacy: bool

@dataclass(frozen=True)
class MemberRemovalResult:
    content: str
    changed: bool
    removed_rows: int
    removed_groups: tuple[str, ...]
    ambiguous_legacy: bool


def upsert_member_line(
    content: str,
    note_id: str,
    title: str,
    tags: Sequence[str],
    group: Optional[str],
    *,
    legacy_title_unique: bool,
) -> MemberUpsertResult:
    """插入、认领或修复一个 MOC 成员正文行；纯函数。"""


def remove_member_lines(
    content: str,
    note_id: str,
    title: Optional[str],
    *,
    legacy_title_unique: bool,
) -> MemberRemovalResult:
    """删除一个成员在所有区段中的正文行；纯函数。"""
```

实现约束：

- 使用保留换行符的逐行扫描，并忽略 fenced code block 内的伪标题和伪成员行；只把顶层 H2 标题到下一个
  顶层 H2 标题之间的 Markdown 当作区段。H3 不开启新组。
- 成员行必须是 Markdown 无序列表项，支持可选缩进的短横线列表标记，并且链接目标 token 精确匹配 NOTE_ID；
  支持 ID-only 和 ID+alias 两种形式。不得使用 ID 前缀匹配，NOTE_ID 必须按结构化字符串解析或安全转义。
- legacy 行只认列表项中的 `[[标题]]` 目标，不使用 `#` 截断后的标题，也不使用 substring fallback。
- `upsert` 发现 canonical 行时不搬组、不改别名、不重复插入；如果同时存在 legacy 行，legacy 行保留，避免在
  不必要时破坏用户的跨组整理。`had_existing_row=true`。标题别名包含换行或 `]]` 时，新插入/改写的 canonical
  目标使用 `[[ID]]`，否则使用 `[[ID|标题]]`。
- 没有 canonical 行且有唯一 legacy 行时，canonicalize 所有精确匹配行，保留原组和行后缀，不额外插入；
  `rows_canonicalized` 等于改写行数。
- 没有 canonical 行且 legacy 标题有歧义时，不改写旧行，按组选择规则追加一条 canonical 行，并将
  `ambiguous_legacy=true`。
- `upsert` 的自动选组按正文出现顺序检查普通组名，大小写敏感地与 tags 精确匹配；排除 `其他`、`近期活动`、
  `待归类`。多个 tag 命中取第一个组；没有命中使用现有「其他」，否则创建「其他」。
- 显式 `--group` 必须是单行非空组名，精确匹配已有普通组；不得是 `近期活动` 或 `待归类`。不存在时在第一个
  系统区段之前创建；`--group 其他` 合法。
- 新组或 fallback 组插入在第一个系统区段之前；正文存在普通组但没有系统区段时，追加在最后一个普通组之后；
  没有任何顶层组时，在正文末尾创建组和成员行。
- 组内追加发生在该组结束、下一个顶层 H2 标题之前；保留已有正文、顺序和空行，不重排已有成员。
- 删除普通组前，确认目标行移除后组体只剩空白；有说明文字、子标题、代码或其他 Markdown 时保留组标题。
- 系统区段标题永不删除；删除同一成员的多处行时，`removed_groups` 去重但保持正文出现顺序。
- `render_moc_content` 使用同一 canonical 规则渲染 create 产物：普通成员和 orphan 成员都输出 ID canonical
  链接，普通成员保留 `— N links` 后缀。该改动只影响新生成正文，不迁移存量文件。
- 如果标题含换行或 `]]`，canonical 行使用 `[[ID]]`，并由 CLI 返回 warning；ID 仍是唯一目标。标题含 `|`
  不影响目标解析，仍可使用 `[[ID|标题]]`。正常标题仍使用 `[[ID|标题]]`。

### 3.6 backlinks 辅助函数

扩展 `jfox/moc/generate.py` 的现有 helper，并保持已有调用方可以忽略返回值：

```python
@dataclass(frozen=True)
class BacklinkUpdateResult:
    changed_ids: tuple[str, ...]
    failed_ids: tuple[str, ...]
```

- `backfill_moc_backlinks` 返回 `BacklinkUpdateResult`；`write_moc` 和 update 调用方可以忽略返回值。
- `remove_moc_backlinks` 返回 `BacklinkUpdateResult`；目标不存在或目标 backlink 中没有 MOC ID 时不算失败，也不进入
  `changed_ids`；真实读写/索引异常进入 `failed_ids`。
- 单成员失败继续处理其他成员并记录日志；CLI 将 `failed_ids` 转成 warning 和 `partial=true`。
- MOC 主文件先由 `update_note` 持久化，再写成员 backlinks。辅助写入失败时，重试 add/remove 不会丢失已经保存的
  MOC 主状态。
- CLI 用 helper 的 `changed_ids` 和 `failed_ids` 计算 backlink 是否产生持久化变化，不能仅凭调用 helper 就把
  `applied` 报为 true。

## 4. skill 层设计

### 4.1 session-to-permanent 三平台同步

同步修改以下三个文件，保持流程语义一致，但使用各平台已有的交互工具名称：

- `skills-recommend/pi/jfox-session-to-permanent/SKILL.md`
- `packages/cc-plugin/skills/session-to-permanent/SKILL.md`
- `packages/kimi-plugin/skills/jfox-session-to-permanent/SKILL.md`

#### Step 2：采集 MOC 候选信号

每条候选知识点执行现有的 `jfox suggest-links ... --json` 后，读取 `suggestions` 的 `type` 字段。
`type == "structure"` 且未归档的笔记成为该候选的 MOC 信号；按 MOC ID 去重，保留标题和 score。
现有 suggest-links 默认排除归档结果；skill 仍不得把无法确认状态的 structure 自动当作挂载目标。

该步骤只产生候选信号，不自动修改 MOC，也不改变现有去重判定。若用户之后修改新笔记草稿，必须对最终
草稿重新运行 suggest-links，不能复用修改前的 MOC 信号。

#### Step 4：最终草稿审阅后确认归属

仍先按现有流程审阅新笔记和补充已有笔记的草稿。对于每一条“新笔记”草稿：

1. 如果最终草稿没有活跃 structure 信号，不增加 MOC 问题，不强制用户指定 MOC；
2. 如果有一个或多个信号，增加“挂到哪个 MOC？”确认；选项包含每个 MOC 的标题、ID 和 score，以及“不挂”；
3. 一条笔记可以选择多个 MOC。pi 的 `question` 工具采用顺序交互：选择一个 MOC 或“不挂”后，若已选择
   MOC，再问“是否继续挂到其他 MOC”，直到用户结束；
4. cc-plugin / kimi-plugin 使用平台已有的 AskUserQuestion 或等价顺序交互。不得把一次 batch 的一个选择解释成
   所有新笔记共用的 MOC；每条新笔记都独立建立“笔记 → MOC 集合”映射；
5. 保留“手动指定”自由输入路径。用户输入后，用 `jfox show <MOC_ID> --json` 校验 ID、`type=structure`
   且未归档；无效输入重新询问或选择不挂；手动指定也遵守每笔记可多选规则；
6. 补充已有 permanent 的候选不增加该问询，继续由 `moc update` 或手动 add-member 管理存量归属。

#### Step 5：落库后挂载

每条用户确认写入的新笔记依次执行：

```bash
jfox add ... --type permanent --json
jfox moc add-member <MOC_ID> <NEW_NOTE_ID> --json
```

目标知识库不是默认库时，两条命令都传相同的 `--kb <kb-name>`；默认库沿用各平台 skill 的既有约定。
对同一新笔记选择的多个 MOC，逐个调用 add-member。

- `jfox add` 失败时不调用 add-member；
- add-member 失败时不回滚已经确认并成功落库的 permanent，报告失败的 note ID、MOC ID 和可重试命令；
- 某个 MOC 挂载失败不阻止同一笔记继续尝试其他已确认 MOC，也不阻止 batch 中其他笔记落库；
- 无 MOC 信号的批次继续正常落库；汇总可提示用户使用 `jfox moc add-member` 手动补挂。

### 4.2 jfox-moc skill（仅 pi）

修改 `skills-recommend/pi/jfox-moc/SKILL.md`：

- 命令参考加入 `jfox moc add-member <moc_id> <note_id> [--group <组名>] --json`；
- 命令参考加入 `jfox moc remove-member <moc_id> <note_id> --json`；
- 说明成员正文使用 `[[ID|标题]]`，不要新写只有标题的链接；
- 说明存量旧标题行由 add/remove 按唯一性安全处理，不做全库自动迁移；
- 明确“session-to-permanent 沉淀时归属”是主路径，“moc update”是批量兜底；
- 保留现有 `moc update` 的 dry-run/`--yes`、只摘死链和语义漂移交人工判断的说明。

## 5. 错误处理与一致性边界

### 5.1 可拒绝的输入

以下情况返回 `success=false`、退出码 1，且不修改任何文件：

- MOC 不存在、ID 不精确、不是 structure，或 add 目标 MOC 已归档；
- add 成员不存在、ID 不精确、文件不在磁盘或成员已归档；
- add 发生自链；
- ID 为空、包含路径分隔符或 glob 元字符；
- `--group` 为空、含换行，或指定 `近期活动` / `待归类`；
- `--format` 不是 table/json。

### 5.2 可继续但需 warning 的状态

以下情况允许主操作继续：

- 成员是活跃的非 permanent 类型；
- structure 作为成员（nested structure）；
- add 发现 legacy 标题有歧义：追加 ID canonical 行，保留旧行并 warning；
- remove 发现 legacy 标题有歧义：保留旧行并 warning；如果同时清理了其他确认状态则 `partial=true`；
- backlink 回填或摘除的单个目标读写失败：主 MOC 已成功持久化时返回 `success=true, partial=true`。

### 5.3 与既有机制的边界

- `moc update` 仍按现有语义运行：语义漂移成员不自动摘除，死链才进入 remove diff；本 issue 不把 update 改成
  全量正文重渲染，也不新增 move-member 功能。
- add/remove 不运行聚类，但 `update_note` 的索引更新仍可能调用 embedding backend；向量/BM25 的失败处理遵循
  `update_note` 现有日志语义，不另造一套索引错误契约。
- `[[ID|标题]]` 会被现有 `note_index.extract_wiki_links_from_text` 解析为 ID 目标；本 issue 不修 `jfox edit`
  的 links 覆盖问题（#470），只通过 MOC canonical 行降低其影响。
- 不做全库 legacy 标题链接迁移；不修改非 MOC 笔记的 wiki-link 语义；不新增 cc/kimi 的 jfox-moc skill；
  不把 session 笔记固定写入 MOC 稳定骨架。

## 6. 验收矩阵

自动化验证覆盖纯函数、CLI 编排、真实临时文件和文档静态契约；用户实测只承担真实 skill 交互和真实 CLI
环境验证，不能用自动化测试替代。

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|----|--------|----------|----------|----------|
| A1 | MOC create 新正文使用 ID canonical 链接，并保留分组/孤儿/近期活动结构 | 自动化验证（unit） | `uv run pytest tests/unit/test_moc_draft.py -v` | render 相关断言通过；create 不再产生只有标题的成员链接 |
| A2 | `upsert_member_line` 的组匹配、fallback、显式组、新组位置、系统区段跳过、canonical 幂等、正文缺行时插入、唯一 legacy 改写、歧义追加 | 自动化验证（unit） | `uv run pytest tests/unit/test_moc_draft.py -v` | 表驱动 case 全通过；纯函数不访问 I/O |
| A3 | `remove_member_lines` 删除所有 ID 行、唯一 legacy 行、普通空组，保留有内容组和系统标题 | 自动化验证（unit） | `uv run pytest tests/unit/test_moc_draft.py -v` | 多组、重复行、ID-only/ID+alias、歧义、代码块和空组 case 全通过 |
| A4 | add-member 的 ID/MOC/成员校验、归档/self-link 拒绝、非 permanent warning、三态修复、JSON/table/help | 自动化验证（unit） | `uv run pytest tests/unit/test_moc_member_cli.py -v` | 返回码、JSON 字段、warning、helper 调用顺序和失败无副作用符合契约 |
| A5 | add/remove 的真实文件一致性：frontmatter links、正文行、成员 backlinks 三处同步；remove 对称清理 | 自动化验证（integration） | `uv run pytest tests/integration/test_moc_member_commands.py -v`（临时 KB + `mock_embedding_backend`） | add 后三处均含关系；remove 后三处均清除；重复 add 不重复正文/links |
| A6 | backlink 辅助写入部分失败时保留主 MOC 结果并报告 partial/warnings | 自动化验证（unit） | `uv run pytest tests/unit/test_moc_generate.py tests/unit/test_moc_member_cli.py -v` | changed/failed ID 正确返回；其他成员继续；JSON 明确 partial |
| A7 | 现有 MOC CLI 不回归，新增子命令进入 help | 自动化验证（unit/static） | `uv run pytest tests/unit/test_moc_cli.py tests/unit/test_moc_create_cli.py tests/unit/test_moc_update_cli.py -v` | create/update/diagnose 原有契约通过；add-member/remove-member help 存在 |
| A8 | 三平台 session-to-permanent 与 pi jfox-moc 同步、示例正确、Markdown 合规 | 自动化验证（static） | 运行 markdownlint；逐一对四个具体文件执行固定字符串检查：`jfox moc add-member`；对 pi jfox-moc 执行固定字符串检查：`jfox moc remove-member` | markdownlint 通过；四个相关文件都包含 add-member，pi jfox-moc 包含 remove-member |
| A9 | 快速回归集合 | 自动化验证（unit/static） | `uv run pytest tests/ -m "not embedding and not slow" -q` | 快速测试全部通过 |
| U1 | session-to-permanent 信号驱动真实交互和多 MOC 挂载 | 用户实测 | 在有至少两个活跃 MOC 的测试 KB 中准备一条同时相关的新 permanent 草稿和一条与现有 MOC 不相关的草稿；运行 Step 2→4，前者确认出现 structure 信号并询问，后者确认没有强制 MOC 问询；为前者选择两个 MOC；Step 5 后执行 `jfox show <moc_id> --json` 和 `jfox refs --note <new_note_id> --json` | 每个选定 MOC 都新增 ID canonical 成员行；每个 MOC links 含新 ID；新笔记 backlinks 含全部选定 MOC ID；无信号草稿不出现强制 MOC 问询 |
| U2 | 真实 CLI 的 add/remove、幂等和旧格式安全处理 | 用户实测 | 选可恢复的测试 MOC 与临时 permanent：执行 `jfox moc add-member <moc_id> <note_id> --json` 两次；执行 `jfox moc remove-member <moc_id> <note_id> --json`；再准备唯一标题旧 `[[标题]]` 行和同名标题旧行分别验证；每次操作前后执行 `jfox show <id> --json` 与 `jfox refs --note <id> --json` | 第二次 add 不重复正文或 links；remove 后三处清除；唯一旧标题可 canonicalize/remove；同名旧标题保留并 warning；失败输入不改文件 |

**用户实测时机**：A1–A9 自动化验证通过后执行 U1/U2；真实库操作必须使用可恢复的测试 MOC 和临时笔记，
不得直接对生产 MOC 做不可逆测试。若 U1 因平台交互能力或缺少两个活跃 MOC 而无法执行，标记为 `pending`，
不得以 A1–A9 通过替代。

## 7. 可测性拆分设计（硬约束）

### 7.1 纯函数边界

`jfox/moc/draft.py` 负责顶层 H2 扫描、系统区段识别、组选择、成员行识别、legacy 安全判断、canonical 化、
插入、删除和空组判断。这些函数只接收字符串与显式参数，unit 测试覆盖：

- 正常 create 格式、旧标题格式、ID-only、ID+alias 和可选后缀；
- 多 tag 命中顺序、大小写敏感、fallback、新组、无系统区段和系统区段；
- links 已有但正文缺行、正文已有但 links 缺失等纯文本状态；
- 唯一 legacy 改写、同名 legacy 保留、跨组重复行、普通空组与有内容组；
- fenced code block 中的伪标题/伪成员行不被处理；
- 标题含 `#` 时按 raw legacy 标题精确匹配，不走会截断的标准化解析。

纯函数测试不验证文件存在、NoteType、归档状态、links/backlinks 或 embedding。

### 7.2 CLI 编排边界

`jfox/moc/cli.py` 的 `_add_member_impl` / `_remove_member_impl` 只负责编排：

1. ID 安全校验和 active config 下的精确加载；
2. MOC/成员类型及归档状态校验；
3. NoteIndex 标题唯一性查询；
4. 调用纯函数；
5. links 规范化或摘除重复项；
6. `update_note` 主文件持久化；
7. backlink helper 调用和 changed/failed、warning/partial 汇总；
8. table/JSON 输出。

CLI unit 测试通过 mock 验证拒绝路径、三态幂等、helper 调用顺序和失败处理；文件集成测试使用临时 KB
fixture 与 mock embedding backend，保留真实文件、NoteIndex 和索引更新路径，但不加载真实模型、不运行聚类。
测试应显式使用 `get_note_index(active_config)` 或当前 `use_kb` 上下文，不能依赖默认 KB 全局缓存。

### 7.3 skill 文档边界

skill 变更是静态文档契约：三个 session-to-permanent 文件必须描述相同的信号驱动规则、最终草稿重新检索、
每笔记独立的多 MOC 映射、落库后调用和失败重试；pi jfox-moc 必须包含两个新命令及主路径/兜底定位。
通过 markdownlint 和四个具体文件的内容检查验证，不把平台真实交互伪装成自动化 unit 测试。

实现阶段不得把正文扫描逻辑内联回 CLI，也不得让纯函数访问文件系统、NoteIndex、embedding 或全局 config。

## 8. 数据流图

```text
session-to-permanent
  Step 2: suggest-links --json
      └─ type=structure + active ──▶ 每条新笔记的 MOC 候选集合
  Step 3/4: 用户修改后对最终草稿重新检索并审阅
      └─ 每条新笔记独立选择 0..N 个 MOC
  Step 5: jfox add --type permanent
      └─ 获得 NEW_NOTE_ID
          └─ 对每个已确认 MOC 调用 moc add-member

jfox moc add-member MOC_ID NOTE_ID
  validate exact IDs + active structure MOC + active member
    └─ title uniqueness check
      └─ upsert_member_line（纯函数）────正文 canonical 行/legacy 修复
          └─ moc.links 合并去重──────────frontmatter
              └─ update_note（主文件/index）
                  └─ backfill_moc_backlinks ──成员 backlinks

jfox moc remove-member MOC_ID NOTE_ID
  validate exact MOC ID + load optional member
    └─ remove_member_lines（纯函数）────删除正文行/空组
        └─ moc.links 删除目标────────────frontmatter
            └─ update_note（主文件/index）
                └─ remove_moc_backlinks ──成员 backlinks
```
