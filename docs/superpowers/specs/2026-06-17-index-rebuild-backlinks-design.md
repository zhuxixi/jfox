# Issue #252: `jfox index rebuild` 重新计算 backlinks 设计文档

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## 背景

`jfox index rebuild` 当前只重建：

1. ChromaDB 向量索引（`Indexer.index_all()` → `vector_store.reset_collection()` + 全量 add）
2. BM25 关键词索引（`bm25_index.rebuild_from_notes()`）

但它**没有**重新解析笔记正文中的 `[[笔记标题]]` 维基链接，也没有根据解析结果更新笔记 frontmatter 中的 `links` 和 `backlinks` 字段。

这会导致以下问题：

- 手动修改笔记文件后，即使执行 `jfox index rebuild`，backlinks 关系也不会恢复
- 知识库迁移/整理后，链接网络丢失
- 必须通过 `jfox add` 重新创建笔记才能建立链接

## 目标

让 `jfox index rebuild` 支持可选的 `--backlinks` 参数，在重建索引的同时：

1. 全量加载所有笔记
2. 解析每篇笔记正文中的 `[[...]]` 维基链接
3. 按标题/ID 解析链接目标
4. 更新每篇笔记的 `links` 字段（按当前内容重新生成）
5. 根据所有笔记的 `links` 重新计算每篇笔记的 `backlinks`
6. 只写入确实有变化的笔记文件，避免无意义的 I/O

## 非目标

- 不修改 `jfox add` / `jfox edit` 的现有 backlinks 维护逻辑
- 不改变 `jfox index rebuild` 的默认行为（默认不重建 backlinks，避免意外覆盖用户手动写入的 frontmatter）
- 不引入新的持久化存储格式

## 方案

### 1. 新增 `jfox index rebuild --backlinks`

在 `jfox/cli.py` 的 `index()` 命令中：

- 为 `rebuild` action 增加 `--backlinks` / `-b` 选项
- 当用户传入 `--backlinks` 时，在 `indexer.index_all()` 和 BM25 重建完成后调用 backlinks 重建逻辑

### 2. 独立函数 `_rebuild_backlinks_impl()`

在 `jfox/cli.py` 中新增内部实现函数，职责单一：

- 通过 `note.list_notes()` 加载所有笔记
- 构建 `标题/ID → note_id` 的解析映射
- 遍历每篇笔记，调用现有 `extract_wiki_links()` 提取链接
- 对每个链接调用 `find_note_id_by_title_or_id()` 解析
- 汇总得到新的 `links` 和 `backlinks`
- 与现有值比较，仅当变化时才调用 `note.save_note(note, add_to_index=False)` 写回文件

### 3. 输出与结果

JSON 输出增加字段：

- `backlinks_rebuilt`: bool
- `backlinks_updated`: int（实际写入文件的笔记数量）
- `backlinks_total`: int（扫描的笔记总数）
- `unresolved_links`: List[str]（无法解析的链接文本，去重）

Table 输出增加对应行：

- `✓ Backlinks rebuilt: X notes updated / Y scanned`
- 如有未解析链接，显示警告

### 4. 错误处理

- 加载失败的笔记跳过，记录 warning
- 保存失败不中断整个流程，记录 warning，但 `backlinks_rebuilt` 仍为 True（部分成功）
- 无任何笔记时返回成功

## 关键代码位置

- `jfox/cli.py:1935-1959`：`rebuild` action 的现有实现
- `jfox/cli.py:237-243`：现有 `extract_wiki_links()`
- `jfox/cli.py:246-290`：现有 `find_note_id_by_title_or_id()`
- `jfox/note.py:97-125`：`save_note()` 支持 `add_to_index=False`

## 测试策略

1. **集成测试**：在临时知识库中创建笔记 A、B，B 引用 A，手动清空 A 的 `backlinks` 字段，执行 `jfox index rebuild --backlinks`，验证 A 的 backlinks 恢复
2. **单元测试**：测试 `_rebuild_backlinks_impl()` 的链接解析与 backlinks 计算逻辑（使用 mock 笔记）
3. **边界测试**：
   - 空知识库
   - 链接到不存在的笔记
   - 多个笔记链接到同一目标
   - 没有 `--backlinks` 时不应修改任何笔记

## 兼容性

- 默认行为不变，不影响现有用户
- 新增的 `--backlinks` 选项是可选的
- 输出 JSON 新增字段，不会破坏现有解析（新增字段是兼容的）

## 验收标准

- [ ] `jfox index rebuild --backlinks` 成功重新计算并写入所有 backlinks
- [ ] 默认 `jfox index rebuild` 行为与修改前一致
- [ ] 新增集成测试通过
- [ ] ruff / black 检查通过
- [ ] PR 描述关联 issue #252
