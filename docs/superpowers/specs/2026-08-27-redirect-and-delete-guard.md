# Spec: Redirect and Delete Guard

**Issue:** [#435](https://github.com/zhuxixi/jfox/issues/435)  
**Status:** Approved (autonomous implementation)  
**Date:** 2026-08-27

## Problem

用户删除或重命名笔记后，其他笔记中的引用变成悬空链接：
- 751 处实测悬空（46 frontmatter + 705 body）
- `index rebuild --backlinks` 只报告、不修复（保留现有 `links`，不删除悬空项）
- 用户被迫手动逐篇 `jfox edit` 修复，或容忍数据腐化

## Solution

### Phase 1: Redirect + Delete Guard（本次实现）

#### A. `jfox redirect OLD_ID KEEP_ID`

批量重写所有引用 OLD_ID 的笔记：
- Frontmatter `links: [OLD_ID]` → `links: [KEEP_ID]`
- 正文 `[[OLD_TITLE]]` / `[[OLD_ID]]` → `[[KEEP_ID]]`
- 正文 `[[OLD_TITLE|alias]]` → `[[KEEP_ID|alias]]`（保留 alias）
- 正文 `[[OLD_TITLE#anchor]]` → `[[KEEP_ID#anchor]]`（保留 anchor）
- **不改写 `grounded_by`**（保持历史溯源快照）

**Preflight 检查：**
- OLD_ID 不存在 → 报错
- KEEP_ID 不存在 → 报错
- 存在重复标题 OLD_TITLE → 报错（无法确定哪个 `[[OLD_TITLE]]` 原本指向哪个 ID）
- 存在 substring-only 匹配 → 报告"不可迁移"，继续处理其他

**输出结构：**
```json
{
  "success": true,
  "old_id": "...",
  "keep_id": "...",
  "files_changed": 15,
  "frontmatter_links_updated": 12,
  "body_links_updated": 23,
  "backlinks_updated": 15,
  "conflicts": [],  // 文件改动冲突（mtime/hash 不匹配）
  "unmigratable": ["substring匹配的链接"],
  "unreadable_files": []
}
```

#### B. `jfox delete NOTE_ID` 增强

删除前扫描入链：
- 扫描 `NoteIndex.get_all_meta()`（包含归档）查 `links` 包含 NOTE_ID 的笔记
- 扫描 `find_notes_referencing_title(NOTE_TITLE)`（正文引用）
- 有入链 → 报错并列出引用方，提示先 `jfox redirect` 或 `--allow-dangling`
- `--allow-dangling` → 跳过检查，保持现有行为

### Phase 2+（后续）

- `jfox redirect OLD KEEP --delete-source`（事务化 redirect + 删除）
- Tombstone 重定向记录（`redirect_to: KEEP_ID` 留在 OLD frontmatter）
- Merge 支持（KEEP 吸收 OLD 正文）

## Technical Details

### Canonical Link Form

**决策：** `[[KEEP_ID]]`（纯 ID 形式）

**理由：**
- 简单、确定、当前解析器已支持 ID 精确匹配
- 避免未来再次遇到同名笔记时歧义
- Corpus 实测 4613 处 wiki link 中仅 3 处 ID 形式，但这是唯一无歧义的形式

**Tradeoff：** 源码中 `[[202608...]]` 不如标题友好，但可通过渲染层补显示名（未来优化）

### Ambiguity Handling

**Duplicate titles:** 多个笔记共享 OLD_TITLE → preflight fail，要求用户先手动消歧

**Substring matches:** 522 处链接只能 substring 匹配 → 报告为 `unmigratable`，不改写

### Archived Notes

**必须显式扫描：**
- `NoteIndex.get_all_meta()`（含归档）
- `list_notes(include_archived=True)`
- 归档来源的 frontmatter/body 也要更新
- 归档目标仍是有效 KEEP_ID

### Frontmatter Preservation

**不能用 `Note.to_markdown()`：** 会丢未知字段

**方案：** YAML patch
- 用 `yaml.safe_load()` 解析 frontmatter
- 只更新 `links` / `backlinks` 字段
- 用 `yaml.dump()` 写回，保留其他字段

### Concurrency

**Phase 1 不做跨进程锁：**
- 每个来源文件 read → check mtime/hash → write
- 冲突时报告 `conflicts`，用户重试

**Future：** KB-level write lock 或 journal

### Verification

**Post-redirect 验证：**
- 重新扫描入链，确认无残留 OLD_ID 引用
- 输出 `verification_passed: true/false`

## Implementation Plan

1. `jfox/redirect.py` - 新模块
   - `scan_references(old_id, old_title) -> ReferenceReport`
   - `redirect_references(old_id, keep_id, dry_run=False) -> RedirectResult`
2. `jfox/cli.py` - 新命令
   - `@app.command() def redirect(...)`
   - `_delete_impl()` 增加 preflight 扫描
3. 测试
   - `tests/unit/test_redirect.py` - redirect 逻辑
   - `tests/unit/test_delete_guard.py` - delete preflight
   - `tests/integration/test_redirect_e2e.py` - 端到端

## Acceptance Criteria

- [ ] `jfox redirect OLD KEEP` 成功重写所有引用
- [ ] Frontmatter `links` 和正文 wiki link 都被更新
- [ ] Alias/anchor 被保留
- [ ] `grounded_by` 不被改动
- [ ] 归档来源/目标被正确处理
- [ ] 重复标题 preflight fail
- [ ] `jfox delete` 有入链时报错
- [ ] `--allow-dangling` 跳过检查
- [ ] 未知 frontmatter 字段被保留
- [ ] 测试覆盖率 > 85%
