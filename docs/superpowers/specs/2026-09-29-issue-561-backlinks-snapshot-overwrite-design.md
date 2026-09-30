# Spec — Issue #561：`index rebuild --backlinks` 快照→写回无锁，并发 edit 正文被覆盖

- 状态：**设计已确认（v2，review 修订稿）**，用户已批准进实现（2026-09-29）
- 代码基线：`main @ 21ee9ea`（v1.16.2）
- 调研存档：`~/.claude/github-issue-driven/zhuxixi/jfox/issue-561/research/`
- 路由：bug → systematic-debugging（Phase 1 根因核对已完成，见调研轮 2）
- 修订记录：v1 的 D2/D3（links 并集 + backlinks 重算替换）在 review 中被否决——并发方「删除」的链接会被并集永久复活；v2 改为「**发现分歧即跳过**」（即 issue 原文选项 3）。

## 1. 根因（已核对）

`jfox/cli.py:389 _rebuild_backlinks_impl()` 三段式：`list_notes()` 一次性快照（`:409`）→ 全库解析 wiki link 并算 backlinks → 对变化笔记 `note.save_note(n, add_to_index=False)` 整条覆盖写回（`:469`）。写回内容是 `note.to_markdown()`，即 **frontmatter + 正文整体落盘**，而这段窗口内没有任何跨进程互斥（`cli.py` 全文 0 处 `FileLock`/`fcntl`），并发 `jfox edit` 的正文因此被旧快照静默覆盖。

同仓库已有同构修复先例：PR #422（`74cf92b`，#392 A3）在 `delete_note()` backlink 清理与 `promote_note()` 回填循环采用 re-read-and-merge（`find_note_file` → `load_note` → 改 fresh → `_atomic_write` → `update_note_meta`）。本 issue 即把「写回内容由磁盘最新状态派生」的思想应用到尚未覆盖的第三个调用点。

## 2. 目标 / 非目标

**目标**

- 消除 `--backlinks` 写回对并发写入者的覆盖：并发方的正文与所有 frontmatter 字段在任何时序下都不丢失、不被复活。
- 改动局限在两处：`jfox/note.py` 加窄接口，`jfox/cli.py` 换调用。
- 为并发场景补自动化回归测试（手法复用 `test_delete_backlink_cleanup.py:699` 的并发模拟）。

**非目标（明确不做）**

- ❌ per-file 锁 / 全库文件锁架构。
- ❌ 改 `jfox index rebuild` 的整体执行顺序或加全局互斥。
- ❌ 修复 `list_notes(limit=10000)` 硬上限（独立问题，建议另开 issue）。
- ❌ 让本轮 rebuild 合并并发方的新增链接（分歧笔记本轮跳过、下轮自愈即可；当场合并会引入「删除复活」的永久性错误）。

## 3. 设计（v2：发现分歧即跳过）

### 3.1 数据流

```
快照读 list_notes(10000)                          ← 不变；快照对象全程不被原地修改（D8）
  └─ 解析正文 wiki link、合并 frontmatter links、算 backlinks   ← 不变
       └─ 对每条变化笔记：apply_backlinks(snapshot, target_links, target_backlinks)
            ├─ 定位：snapshot.filepath（#549 钉住的真实路径）
            │        └─ 失效或读到别的 id → find_note_file(cfg, id) 兜底
            ├─ 定位不到 → "skipped"（日志记原因：missing）
            ├─ load_note(path) = fresh
            ├─ fresh.to_markdown() != snapshot.to_markdown()    ← 分歧检测（D2'）
            │     → "skipped"（日志记原因：diverged；本轮不碰这条笔记）
            ├─ 目标值与 fresh 现值一致 → "unchanged"（零写入守卫，D4）
            ├─ fresh.links/backlinks 赋重算值
            ├─ _atomic_write(actual_path, fresh.to_markdown())
            ├─ get_note_index().update_note_meta(fresh)          ← D6（已确认）
            └─ "updated"
```

**关键性质**：写盘只发生在「磁盘文件与快照完全一致」时——此刻 fresh ≡ 快照，写重算值等价于写快照，但窗口已压到单文件 read-modify-write；一旦检测到任何并发改动，本条笔记本轮跳过，并发方的内容原样保留。

### 3.2 组件契约（`jfox/note.py` 新增）

```python
def backlinks_write_needed(
    links: Sequence[str],
    backlinks: Sequence[str],
    target_links: Sequence[str],
    target_backlinks: Sequence[str],
) -> bool:
    """纯函数（无 I/O）：目标值与现值（各自排序去重后）是否不同。零写入守卫。"""


def apply_backlinks(
    snapshot: Note,
    target_links: Sequence[str],
    target_backlinks: Sequence[str],
    cfg: Optional[ZKConfig] = None,
) -> str:
    """重读 → 分歧检测 → 原子写。返回 "updated" | "unchanged" | "skipped" | "error"。

    - "skipped"：文件定位不到（missing）或与快照不一致（diverged），日志区分原因；
      两种都不是故障——并发删除/并发编辑是正常竞态
    - "error"  ：写盘异常（捕获后 warning，不向上抛）
    - 不修改 fresh.updated（D5）
    - 写成功后 get_note_index().update_note_meta(fresh)（D6）
    """
```

`jfox/cli.py` 第三阶段改为按返回值分派计数：`updated` → `backlinks_updated`；`skipped` → 新增 JSON 字段 `backlinks_skipped`（增量字段，向后兼容）；`error` → `backlinks_failed`；`unchanged` 不计数。**第三阶段循环不得再原地修改 `n.links` / `n.backlinks`**（现状 `cli.py:466-467` 的赋值必须删掉，否则分歧比对拿到被污染的快照）。

### 3.3 设计决策表

| # | 决策 | 取值 | 依据 |
|---|---|---|---|
| D1 | 重读路径 | `snapshot.filepath` 优先；失效或 `fresh.id != snapshot.id` 则 `find_note_file` 兜底；都失败 → `skipped(missing)` | `edit --title` 经 `update_note` 会改名移动文件（#549 起规范化写）；id 守卫防极端情况下把 backlinks 写到复用旧路径的别的笔记上 |
| D2' | 并发分歧处理 | **跳过**：`fresh.to_markdown() != snapshot.to_markdown()` 则本轮不写，记日志 | review 发现：并集会把并发方删除的链接永久复活（rebuild 的 links 策略历来只加不减，复活后不自愈）。rebuild 可随时重跑，「晚一轮」代价远小于「复活错误链接」 |
| D3' | 写入内容 | 仅在无分歧时把重算的 links/backlinks 赋到 fresh 上写盘（此刻 fresh ≡ 快照） | 无分歧时不存在需要合并的并发状态 |
| D4 | 零写入守卫 | 目标值与 fresh 现值一致 → `unchanged`，不写盘 | 保持「无变化不写盘」语义，便于 mtime 断言 |
| D5 | `updated` 时间戳 | 不修改 | 保持现状语义（元数据重算 ≠ 内容编辑） |
| D6 | NoteIndex meta | 写成功后 `update_note_meta(fresh)` | 已确认：与 #422 一致（`update_note_meta` 同步 `meta.links/backlinks`） |
| D7 | 跳过语义 | `skipped`（missing/diverged）计入新字段 `backlinks_skipped`，**不计入 failed** | #392 A1 的教训：日志/计数不能断言未发生的故障；并发删除不是失败 |
| D8 | 快照不可变 | `_rebuild_backlinks_impl` 第三阶段不再原地修改快照对象的 `links`/`backlinks` | 分歧比对依赖快照与磁盘的一致性；原地改会污染比对基准 |
| D9 | 附带清理 | 删除死代码 `changed_note_ids`（`cli.py:455/472`） | 已确认：就在被改写的代码块内 |

### 3.4 残余风险（明示）

- **helper 内 read→比对→写之间仍有微秒级 TOCTOU 窗口**：无锁前提下无法归零；此窗口内是最后写入者胜，但胜方内容派生自最新磁盘态，不会回滚对方内容。
- **分歧笔记的 links/backlinks 本轮不更新**：下次 `index rebuild --backlinks` 自愈；真实库上并发命中窗口的概率本身极低（实测每千条笔记窗口约 4.7 ms）。
- 并发方新增链接对目标笔记 backlinks 的反映同样推迟一轮（与上一条同源）。

## 4. 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|----|--------|----------|----------|----------|
| A1 | `backlinks_write_needed` 纯逻辑：目标=现值（含乱序/重复）→ False；有差异 → True | 自动化验证（unit） | `uv run pytest tests/unit/test_apply_backlinks.py -q` | 新增用例全绿 |
| A2 | 分歧跳过：fresh 与快照不一致（模拟并发 edit 改正文/标签）→ 返回 `skipped`，不写盘，并发方内容完整保留 | 自动化验证（unit） | 同上文件（patch `load_note`/`_atomic_write` 模拟时序，手法同 `test_delete_backlink_cleanup.py:699`）；mtime 断言 | 文件内容逐字节等于并发方版本；返回 `skipped` |
| A3 | 无分歧正常写：fresh ≡ 快照 → 返回 `updated`，links/backlinks 为重算值，其余字段原样；紧接第二次调用 → `unchanged` 且 mtime 不变 | 自动化验证（unit） | 同上文件 | 三项断言全过 |
| A4 | 路径容错与 id 守卫：①`prefer` 路径失效 → `find_note_file` 兜底成功；②读到 id 不匹配的占位文件 → 不落盘到该文件；③两者都失败 → `skipped(missing)`，无异常 | 自动化验证（unit） | 同上文件 | 三个子用例全过，`_atomic_write` 调用目标路径正确 |
| A5 | CLI 计数分派与 JSON 结构：`updated/unchanged/skipped/error` → `backlinks_updated / 不计 / backlinks_skipped / backlinks_failed`；既有 6 用例改造 mock 目标为 `jfox.note.apply_backlinks` | 自动化验证（unit） | `uv run pytest tests/unit/test_rebuild_backlinks_impl.py -q` | 既有用例全绿 + 新增 skipped/failed 分派用例 |
| A6 | 端到端语义不回归：链接重算、手写 links 保留、unresolved 报告 | 自动化验证（integration） | `uv run pytest tests/integration/test_index_rebuild_backlinks.py -q` | 既有 5 个集成用例全绿 |
| A7 | 静态检查与文档 lint | 自动化验证（static） | `uv run black --check jfox tests && uv run ruff check jfox tests && npx --yes markdownlint-cli2` | 无告警 |
| U1 | 真实知识库冒烟 | 用户实测 | 默认库跑 `jfox index rebuild --backlinks --format json`，再 `jfox refs <id>` 抽查 | `backlinks_rebuilt=true`、`failed=0`；抽查链接关系符合预期 |

## 5. 可测性拆分设计（实现阶段硬约束）

拆成「纯逻辑 + 副作用包装 + 编排」三层，实现不得重新耦合：

| 层 | 单元 | 依赖 | 测试方式 |
|---|---|---|---|
| 纯逻辑 | `backlinks_write_needed(...)` | 无 | 直接函数调用，无 fixture/mock/文件系统 |
| 副作用包装 | `apply_backlinks(...)` | `find_note_file` / `load_note` / `_atomic_write` / `get_note_index` | patch 这 4 个符号；并发时序用 `load_note` 的 side_effect 在两次读取间写入并发版本 |
| 编排 | `_rebuild_backlinks_impl()` | `note.list_notes` / `note.apply_backlinks` | 沿用现有 `test_rebuild_backlinks_impl.py` 风格，mock 目标由 `jfox.note.save_note` 换成 `jfox.note.apply_backlinks` |

测试边界：纯函数承担「要不要写」的全部断言；`apply_backlinks` 承担时序断言（分歧跳过、无分歧写、零写入、路径容错、id 守卫）；`_rebuild_backlinks_impl` 只断言计数分派与 unresolved 报告。

## 6. 影响面

| 文件 | 改动 |
|---|---|
| `jfox/note.py` | 新增 `backlinks_write_needed` + `apply_backlinks`（约 70 行含注释） |
| `jfox/cli.py` | `_rebuild_backlinks_impl` 第三阶段改写：换调用、删快照原地赋值、删死代码 `changed_note_ids`、JSON 增 `backlinks_skipped` |
| `tests/unit/test_apply_backlinks.py` | 新增（A1–A4） |
| `tests/unit/test_rebuild_backlinks_impl.py` | 改造 mock 目标 + 新增分派用例（A5） |
| `CHANGELOG.md` | 补一条 fix 条目 |

## 7. 已确认事项

- 合并策略：**发现分歧即跳过**（用户选定，替代 v1 并集方案）。
- D6 补 `update_note_meta`；D9 顺手删 `changed_note_ids` 死代码（用户选定「两个都做」）。
