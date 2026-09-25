# #549 同 ID 双文件修复 实现计划

> **For agentic workers:** Steps use checkbox (`- [ ]`) syntax to track progress. Follow instructions exactly.

**Spec:** `docs/superpowers/specs/2026-09-24-issue-549-twin-files-design.md`（commit 47b236c）

**Work from:** `/home/elling/git-repo/github/jfox/.pi/worktrees/issue-549-stale-name-twin-files`（所有路径以此为根；禁止碰主 checkout）

**技术摘要：** 路径语义两分法——`from_markdown` 钉住真实路径（`save_note` 就地写）+ `update_note` 写盘目标改用 `expected_filepath`（规范化写 + 成功后重钉 pin）。

## 验收归属（spec 矩阵 → 任务）

| 验收 ID | 归属 |
|---------|------|
| A1/A2（路径纯函数 + 钉路径） | Task 1 |
| A3（update_note 自愈 + 重钉 pin） | Task 1 |
| A9（护栏：改名/移目录保持绿） | Task 1 |
| A4–A8（CLI 症状层） | Task 2 |
| CHANGELOG/注释交付物 | Task 3 |
| U1（真实库受控演练） | 合并后单独人工项，非代码任务 |

## 前置事实（实现者必读，违反即返工）

1. **原子性约束**：`models.py` 的钉路径与 `note.py` 的 `update_note` 调整**必须同任务同 commit 落地**。中间态（只钉路径）会让 `tests/unit/test_edit.py:72-82`（改标题→改名）与 `:373-390`（改 type→跨目录）挂掉（E2b 已实证）。
2. **契约边界**：改 title/topic/type 的意图只走 `update_note`；`save_note` 是就地写。不要给 `save_note` 加任何「找旧文件/改名」逻辑——本修复不靠它。
3. **改动面**：只允许碰 `jfox/models.py`、`jfox/note.py`、两个测试文件、`CHANGELOG.md`。不碰 `moc/`、`redirect.py`、其余 save_note 站点（钉路径后它们自动受益）。
4. **测试命名**：文件/用例名避开子串 `search|semantic|embedding|vector|query|suggest`；用例标题全局唯一（#483 闸门）。本计划的文件名已满足：`test_note_path_rules.py`、`test_stale_name_single_file.py`。
5. **夹具手法**：发散名 = 只 rename 文件（保留 id 前缀），不改 frontmatter——`cli_fast` 每条命令独立子进程，索引按盘重建，发散笔记可被正常发现/解析。
6. **#483 之后 add permanent 有 dedup 闸门**：测试标题彼此差异要大，别用近似标题。

---

## Task 1: 路径语义核心（models.py + note.py + A1/A2/A3/A9）

**Files:**

- Create: `tests/unit/test_note_path_rules.py`
- Create: `tests/integration/test_stale_name_single_file.py`（先只放 A3 两个用例）
- Modify: `jfox/models.py`
- Modify: `jfox/note.py`

- [ ] **Step 1: 写失败测试**

`tests/unit/test_note_path_rules.py`（A1/A2，纯函数层，无需 KB 写入）：

```python
class TestExpectedFilepath:
    def test_permanent_uses_title_slug(self)                    # A1：expected == config.notes_dir/"permanent"/filename
    def test_session_uses_topic(self)                           # A1
    def test_session_without_topic_falls_back_to_title(self)    # A1
    def test_fleeting_uses_dash_form(self)                      # A1：{id[:8]}-{id[8:]}.md
    def test_expected_filepath_ignores_pin(self)                # A1：set_filepath 后 expected 不变、filepath 变

class TestFromMarkdownPin:
    def test_with_filepath_pins_it(self)                        # A2：note.filepath == 传入路径
    def test_without_filepath_stays_unpinned(self)              # A2：note.filepath == expected_filepath
```

`tests/integration/test_stale_name_single_file.py`（A3，先行两个用例；发散名 helper 共用）：

```python
def _diverge(filepath: str) -> Path:
    """只 rename 文件制造发散名（保留 id 前缀），模拟外部改标题未同步改名"""
    p = Path(filepath)
    d = p.with_name(f"{p.stem}-diverged.md")
    p.rename(d)
    return d


def _files_for(dir_path: Path, nid: str) -> list:
    return sorted(dir_path.glob(f"{nid}*.md"))


class TestUpdateSelfHeal:
    def test_edit_title_on_diverged_name_canonicalizes(self, cli_fast):
        """A3：发散名笔记经 edit --title 后规范化为规则名，全程单文件"""
        # add permanent → 从 add 的 JSON 取 note.filepath → _diverge →
        # cli_fast.edit(id, title="全新标题X") →
        # 断言 _files_for 单文件、文件名含新标题 slug、旧发散名不存在

    def test_second_save_after_update_no_resurrect(self, temp_kb_registered):
        """A3：同对象 update_note 后再 save_note，不复活旧路径（重钉 pin 契约）"""
        # 复用 test_delete_backlink_cleanup.py 的 temp_kb_registered + use_kb 模式：
        # load → note.update_note（改标题）→ 对同对象 note.save_note →
        # 断言旧路径文件未被重新创建，且规则名文件唯一
```

（`temp_kb_registered` 参照 `tests/unit/test_delete_backlink_cleanup.py` 的用法；若该 fixture 名不匹配，用 conftest 中已有的等价临时 KB 上下文。）

- [ ] **Step 2: 运行确认失败**

```bash
uv run pytest tests/unit/test_note_path_rules.py tests/integration/test_stale_name_single_file.py -x -q
```

预期：`expected_filepath` 不存在（AttributeError）/ 钉路径未生效 → FAIL。只确认 RED，不修。

- [ ] **Step 3: 实现 `jfox/models.py`**

① 新增 property（放 `filepath` 旁，注释为交付物）：

```python
    @property
    def expected_filepath(self) -> Path:
        """按当前字段现算的规则路径（type 目录 + filename），不看 _filepath pin。

        #549 两分法的另一半：update_note（规范化写）以本属性为写盘目标；
        filepath 在笔记从磁盘加载时被钉住为真实路径（就地写）。
        用 note_obj.filepath 代替本属性的已知后果：钉路径后改名判据
        `old != note.filepath` 恒假，edit --title / 改 type 不再改名移动
        （tests/unit/test_edit.py:72-82、:373-390 必挂）。
        """
        from .config import config

        return config.notes_dir / self.type.value / self.filename
```

② `from_markdown`：把 `return cls(...)` 改为先存变量再钉路径（注释为交付物）：

```python
        note = cls(
            ...  # 现有参数不动
        )
        # #549：钉住加载来源的真实磁盘路径。此后 note.filepath 返回真实路径，
        # save_note（就地写）写回原文件——文件名与当前字段分家时也不会在规则名上
        # 另写同 id 双文件。需要「按当前字段重新定址」的操作（改标题/改 type）
        # 请走 note.update_note，其写盘目标用 expected_filepath。
        if filepath is not None:
            note._filepath = Path(filepath)
        return note
```

③ `filepath` property 的 docstring 补一句「加载的笔记此处返回真实磁盘路径；规则路径请用 expected_filepath」。

- [ ] **Step 4: 实现 `jfox/note.py`**

① `update_note` 写盘段（原 `_atomic_write(note_obj.filepath, ...)` 处）：

```python
        # 规范化写（#549）：目标路径按当前字段现算，不看加载 pin。
        target = note_obj.expected_filepath
        _atomic_write(target, note_obj.to_markdown())

        if old_filepath != target and old_filepath.exists():
            old_filepath.unlink()
            logger.info(f"Renamed note file: {old_filepath} -> {target}")

        # #549：写盘成功后把 pin 重钉到刚写入的路径——否则同一对象随后的
        # save_note（就地写）会按陈旧 pin 写回旧路径、复活同 id 双文件。
        note_obj.set_filepath(target)
```

② `save_note` docstring 补契约边界（交付物）：

```
    注意（#549）：写盘目标是 note.filepath——对从磁盘加载的笔记即「就地写回
    加载路径」；就地写不保证文件名随字段变化。改 title/topic/type 的意图请用
    update_note（规范化写：按当前字段现算目标并删除旧文件）。
```

- [ ] **Step 5: 运行确认通过**

```bash
uv run pytest tests/unit/test_note_path_rules.py tests/integration/test_stale_name_single_file.py -q
```

预期全绿。

- [ ] **Step 6: 护栏回归（A9）**

```bash
uv run pytest tests/unit/test_edit.py -q
```

预期全绿（改标题改名、改 type 跨目录不受影响）。

- [ ] **Step 7: 快速回归**

```bash
uv run pytest tests/unit -m "not embedding and not slow" -q
```

- [ ] **Step 8: commit**

```bash
git add jfox/models.py jfox/note.py tests/unit/test_note_path_rules.py tests/integration/test_stale_name_single_file.py
git commit -m "fix(note): 加载笔记钉住真实路径，update_note 规范化写+重钉 pin——消除同 ID 双文件（#549 A1-A3/A9）"
```

---

## Task 2: CLI 症状层集成测试（A4–A8）

**Files:**

- Modify: `tests/integration/test_stale_name_single_file.py`

- [ ] **Step 1: 补五个测试类（TDD：先写先跑，应在 Task 1 的实现上直接转绿——若红说明 Task 1 有漏）**

```python
class TestAddBackfill:
    def test_add_link_to_diverged_target_keeps_single_file(self, cli_fast):
        """A4：add 链接发散名目标 → 单文件 + backlinks 落真实文件"""
        # A = add permanent（标题「回填目标甲」）→ _diverge →
        # B = add「链向 [[回填目标甲]]」→
        # 断言 _files_for(A) 单文件（发散名那份）、A 文件 backlinks 含 B.id

class TestEditBackfill:
    def test_edit_add_link_diverged_target_keeps_single_file(self, cli_fast):
        """A5：edit 新增链接 → 单文件 + backlinks 落位"""
    def test_edit_remove_link_diverged_target_keeps_single_file(self, cli_fast):
        """A5：edit 移除链接 → backlinks 移除 + 仍单文件"""

class TestRebuildBacklinks:
    def test_rebuild_touches_diverged_note_in_place(self, cli_fast):
        """A6：rebuild --backlinks 触及发散名笔记时单文件"""
        # 造 links/backlinks 必变化：直接改发散文件 frontmatter，给 backlinks 加一个假 id
        # cli_fast.index_rebuild(backlinks=True) →
        # 断言单文件、backlinks 被重算（假 id 消失）

class TestShowDelete:
    def test_show_reads_diverged_note(self, cli_fast):
        """A7：show 发散名笔记 success=true（此前报 Errno 2）"""
    def test_delete_removes_real_file(self, cli_fast):
        """A7：delete --force 删真实文件（无入链前置）→ glob 为空"""

class TestMocMemberBackfill:
    def test_moc_backfill_diverged_member_keeps_single_file(self, temp_kb_registered):
        """A8：moc 成员回填（python 级 backfill_moc_backlinks）→ 单文件"""
        # 构造 structure Note（或 CLI add --type structure）+ 发散名成员
        # 调 jfox.moc.generate.backfill_moc_backlinks(moc_note, [member_id], cfg)
        # 断言单文件 + backlinks 含 moc.id
```

- [ ] **Step 2: 运行该文件全量**

```bash
uv run pytest tests/integration/test_stale_name_single_file.py -q
```

- [ ] **Step 3: 相关既有集成测试回归**

```bash
uv run pytest tests/integration/test_links_edit_add.py tests/integration/test_index_rebuild_backlinks.py tests/integration/test_edit_roundtrip.py tests/unit/test_delete_backlink_cleanup.py tests/unit/test_note_promote.py -q
```

预期全绿（同族回填/晋升链路未受影响）。

- [ ] **Step 4: commit**

```bash
git add tests/integration/test_stale_name_single_file.py
git commit -m "test(links): 发散名笔记 CLI 症状层集成测试——add/edit/rebuild/show+delete/moc 均单文件（#549 A4-A8）"
```

---

## Task 3: CHANGELOG + 注释交付物复核 + 全量回归

**Files:**

- Modify: `CHANGELOG.md`

- [ ] **Step 1: `## [Unreleased]` 的 `### Fixed` 下加条目**

```markdown
- links: 加载的笔记钉住真实磁盘路径——文件名与当前字段分家时，补 backlink / rebuild --backlinks / MOC 成员回填不再写出同 ID 双文件，`show`/`delete` 也能正确读写该笔记；`update_note` 改为显式规范化写并在成功后重钉路径（#549）
```

- [ ] **Step 2: 注释交付物复核（对照 spec §7）**：`filepath` property、`from_markdown`、`update_note` 三处注释齐（两分法、E2b 后果、重钉原因）；不齐则补。

- [ ] **Step 3: markdownlint**

```bash
npx --yes markdownlint-cli2@0.23.2 "CHANGELOG.md"
```

- [ ] **Step 4: 全量快速回归（本地 CR 前置）**

```bash
uv run pytest tests/ -m "not embedding and not slow" -q
```

- [ ] **Step 5: commit**

```bash
git add CHANGELOG.md
git commit -m "docs(changelog): #549 同 ID 双文件修复条目"
```

---

## 完成标准

- A1–A9 全部有对应测试且全绿；U1 留待合并后用户点头执行（spec §5）。
- 快速套件 `tests/ -m "not embedding and not slow"` 全绿。
- 分支只含 4 个 commit（spec / 核心修复 / 症状层测试 / changelog），主 checkout 零改动。

---

## 执行偏差记录（终审补记）

1. **测试文件名更名**：spec 中的 `tests/unit/test_note_path_semantics.py` 实际落地为 `test_note_path_rules.py`——#483 命名约束要求避开子串 `semantic`（spec 已同步修订）。
2. **分支为 6 个 commit 而非 4 个**：Task 1 的 lint fix wave（ruff/black）amend 进核心 commit；第 5 个 commit `a5ed229` 为终审挂账的注释债清理（`redirect.py`、`moc/cli.py`、`test_moc_member_commands.py` 纯注释/docstring——reviewer 指出「from_markdown 不回填 `_filepath`」在修复后已成假命题），第 6 个为本修订。前置事实 3 的「不碰 moc/、redirect.py」原指行为代码，注释债清理经 reviewer 建议纳入。
3. **plan 的用例骨架微调**：`temp_kb_registered` 实为 `tests/utils/temp_kb.py` 的 context manager（非 fixture），A3-2/A8 按计划备注改用 `use_kb(kb_name)` + python 级 note API 模式。
