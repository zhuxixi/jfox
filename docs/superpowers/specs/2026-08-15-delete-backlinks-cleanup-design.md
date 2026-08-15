# Issue #386 Spec：jfox delete 清理目标笔记 backlinks

> 状态：v2（已过 review，修正 3 处：测试断言工具 / 幂等用例 / update_note_meta 理由），待确认后进 worktree 实现
> 类型：bug（系统性调试结论 + 修复方案）
> 日期：2026-08-15（v2 同日 review 修订）

## 一、根因

`jfox/note.py:298 delete_note()` 只做四件事：删文件、从向量索引删、从 BM25 索引删、广播 `post_delete`。**没有**遍历 `note.links`、把自身 id 从各 target 的 `backlinks` 中移除。

对比 `promote_note()`（note.py:450-463）的「增量回填」：load target → 若 `n.id not in t.backlinks` → 更新 + `_atomic_write` + `get_note_index().update_note_meta`，单 target 失败只 warning。delete 缺了反向的「增量移除」。

**顺带发现**：note.py:452 注释写 `jfox rebuild-backlinks`（不存在的命令），实际可用命令是 `jfox index rebuild --backlinks`（#252 / PR #255 实现）。

## 二、修复方案

### 2.1 核心改动：`delete_note()` 增加 backlinks 增量移除（删文件之前执行）

```python
# backlinks 增量移除：把本笔记从所有 target 的 backlinks 移除（与 promote 回填对称）。
# 放在删文件之前：若中途崩溃，重跑 delete 幂等收敛（targets 的 backlinks 已无本 id → 直接跳过）。
# target 损坏/解析失败（如手工编辑 backlinks: null）同样仅 warning 跳过，不阻塞 delete 主流程。
now = datetime.now()
# 类型守卫：note.links 可能为手编脏数据（links: null → None，或裸标量 → int/str），
# 非 list 时按空列表处理并 warning，防 `for tid in <int>` 抛 TypeError 使笔记无法删除。
if not isinstance(note.links, list):
    logger.warning(
        f"Skip backlink cleanup for note {note_id}: links 类型异常 "
        f"({type(note.links).__name__})，按空列表处理"
    )
for tid in note.links if isinstance(note.links, list) else []:
    try:
        t = load_note_by_id(tid)
        if not t:
            continue
        if not isinstance(t.backlinks, list):
            logger.warning(
                f"Skip cleaning backlinks from target {tid}: backlinks 类型异常 "
                f"({type(t.backlinks).__name__})"
            )
            continue
        if note_id in t.backlinks:
            t.updated = now
            t.backlinks = [bid for bid in t.backlinks if bid != note_id]
            _atomic_write(t.filepath, t.to_markdown())
            get_note_index().update_note_meta(t)
    except Exception as e:
        logger.warning(f"Failed to clean backlinks from target {tid}: {e}")
```

**函数内 import**：`from .note_index import get_note_index`（与 promote_note 一致，避免顶层循环导入；`_atomic_write`、`datetime` 已在模块内可用）。

### 2.2 设计决策

| 决策点 | 选择 | 理由 |
|---|---|---|
| 清理时机 | 删文件**之前** | 崩溃恢复幂等：backlinks 已清、文件未删 → 重跑 delete 继续删文件即可收敛；反之（先删文件）崩溃后只能靠 rebuild 兜底 |
| 遍历来源 | `note.links`（frontmatter 出链） | 与 promote 回填的 targets 来源对称；极端不一致场景（target backlinks 有本 id 但 links 无该 target）由 `index rebuild --backlinks` 全量重算兜底 |
| target 不存在 | load 返回 None → 跳过 | 悬空出链不是本 issue 范围 |
| 单 target 写盘失败 | warning 不中断，主删除流程继续 | 与 promote 回填容错语义一致；残留可 rebuild 兜底 |
| target 损坏/解析失败 | load/解析异常与写盘失败同等待遇：仅 warning 不中断 delete | 手改笔记常带 `backlinks: null`（`from_markdown` 得 None）或缺 frontmatter（`ValueError`）；清理循环整体在 per-target try 内，保证 delete 主流程不因无关 target 坏状态失败（promote 侧循环在主工作之后、无此风险，delete 侧必须显式防御） |
| backlinks 为空时 | 清空后写空列表，不删字段 | frontmatter 结构稳定，`to_markdown` 序列化统一 |
| `update_note_meta` | 保留调用（**必要**，非"顺手一致"） | note_index.py:336 会同步 `meta.backlinks`；refs 的搜索路径（`--search` 显示「引用此笔记: N 处」）读的正是该缓存，漏调会使引用计数过期 |

### 2.3 顺带修复

note.py:452 注释命令名：`jfox rebuild-backlinks` → `jfox index rebuild --backlinks`。

### 2.4 非目标（不做）

- **archive 不动**：软删除后笔记文件仍在（可 unarchive 恢复），backlinks 指向它不算悬空，与 issue 无关。
- **不做 delete 的全量 backlinks 重算**：已有 `index rebuild --backlinks` 兜底。
- **不改 delete 的 CLI JSON 输出结构**：`--json` 现有返回字段不变（修复是静默的一致性维护，无新失败字段；与 promote 回填的 warning 语义对齐）。
- **不改 `refs` 对悬空 backlink 的静默过滤**：`_refs_impl`（cli.py:1293-1300）`if back_note:` 会隐藏 load 不到的 id，属独立 UX 问题（用户从 refs 看不到悬空、无法察觉数据不一致），后续单独开 issue，不塞进本 PR。

## 三、测试计划

新文件 `tests/unit/test_delete_backlink_cleanup.py`（模式照抄 `test_add_backfill_links.py`：`temp_kb_registered` + `mock_embedding_backend` + `CliRunner`，mark `unit` + `fast`）：

1. **核心回归**（对应 issue 复现步骤）：add B → add A（引用 [[B]]）→ `jfox delete A --force` → 断言 `B.backlinks` 不含 A。
   **断言工具必须用 `jfox show <BID> --json` 读 frontmatter 真值，禁止用 `refs`**：`_refs_impl`（cli.py:1293-1300）构建 backward_links 时 `if back_note:` 静默过滤 load 不到的 id——删 A 后其文件已删，refs 输出无论修不修 bug 都为空，用它断言会产出"永远绿灯"的假测试。
2. **失败容错**：patch `_atomic_write` 抛异常 → delete 仍成功（exit 0、文件已删），仅 warning。
3. **无链接笔记**：add 无链接笔记 → delete 成功（回归保护：清理循环空转不崩）。
4. **幂等跳过（membership 守卫）**：构造不对称状态——A.links 含 B 但 B.backlinks 不含 A（如手工编辑 B 文件清空 backlinks）；delete A 时守卫 `note_id in t.backlinks` 判否直接跳过，断言 B 文件未被重写（mtime/内容不变）。「backlinks 已含已删 id」在单次 delete 内不可构造（笔记已删无法二次 delete），崩溃恢复收敛性由该守卫保证，不单测。

## 四、验收标准

1. 复现步骤 step6 变为 `B.backlinks == []`（以 `jfox show <BID> --json` 的 `.backlinks` 字段为准，同 issue 复现命令）。
2. 新增测试全绿，既有测试不回归（重点 `test_add_backfill_links.py`、`test_note_promote.py`、`test_note_dedup_sync.py`）。
3. `jfox index rebuild --backlinks` 兜底语义不变。
4. ruff / black 通过。

## 五、执行顺序（github-issue-driven 步 5-10，待本 spec 确认后）

1. worktree：`issue-386-delete-backlinks-cleanup`（或按 ≤64 字符规则取名 `issue-386-delete-clean-backlinks`）
2. writing-plans 产出 plan 文档
3. subagent-driven-development 实现
4. 本地快速 CR → PR + zima:needs-review → 收敛合并
