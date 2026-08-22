# Issue #392 Spec: PR #388 CR 低危遗留项修复设计

> 状态：已确认（2026-08-22 用户确认）
> 路由：chore → issue-research（一轮完成，结论已评论到 issue）
> 关联：#386（delete backlinks 清理）、#388（已合并 PR）、#391/#396（BM25 乐观并发控制，同方向参考）

## 1. 背景

`jfox delete` backlink 清理（#386，PR #388）已合并，cc bot 5 轮 CR 留下 3 项低危遗留（A1-A3），另顺带发现 2 项独立问题（B1-B2），打包为本 issue。5 项均不阻塞功能、不导致崩溃，但 A2/A3 是真实的数据一致性风险，A1/B2 是可观测性缺口。

## 2. 决策表

| 项 | 决策 | 理由 |
|----|------|------|
| A1 | 改 warning 文案为中性表述 | bot 建议，零风险，现有测试不断言旧文案 |
| A2 | 回填循环写盘前用 `find_note_file` 解析真实路径 | 不能全局改 from_markdown（破坏 update_note 重命名检测） |
| A3 | re-read-and-merge：写前从真实路径重读 fresh，在 fresh 上移除再写回 | 不丢并发方更新，且天然修复 A2 |
| B1 | conftest mock 补 `encode_single` | 一行方法，消除全库测试噪声 |
| B2 | forward/backward 一起修，条目加 `dangling` 标记 | 同构问题只修一半留不一致 |

## 3. 修复设计

### 3.1 A1：warning 文案（note.py delete_note 清理循环）

现状：`bad_types` 非空即输出「仅清理 str 引用」，但 `note_id not in t.backlinks` 时零写入零移除，日志断言了一次从未发生的清理。

改法（bot 建议原文）：

```python
f"target {tid} 的 backlinks 含非 str 元素 ({', '.join(bad_types)})，仅清理 str 引用（如存在）"
```

告警位置保持在 membership 判断之前（无论是否命中都值得提示脏数据）。

### 3.2 A2+A3：re-read-and-merge 写回真实路径（合并实现）

**delete_note 清理循环**（note.py:298-370）重构为：

```python
for tid in note.links if isinstance(note.links, list) else []:
    try:
        if not isinstance(tid, str):
            # 原守卫不变
            continue
        t = load_note_by_id(tid)
        if not t:
            continue
        if not isinstance(t.backlinks, list):
            # 原守卫不变
            continue
        bad_types = sorted({type(bid).__name__ for bid in t.backlinks if not isinstance(bid, str)})
        if bad_types:
            logger.warning(f"target {tid} 的 backlinks 含非 str 元素 ({', '.join(bad_types)})，仅清理 str 引用（如存在）")
        if note_id not in t.backlinks:
            continue
        # A2+A3：写盘前从真实磁盘路径重读 fresh，在 fresh 上移除再写回。
        # 修复：1) 文件名发散时不再另写同 id 双文件（写回 load 命中的真实路径）；
        # 2) 与常驻 daemon 并发写同一 target 时不丢对方更新（re-read-and-merge）。
        actual_path = find_note_file(config, tid)
        if not actual_path:
            logger.warning(f"Failed to clean backlinks from target {tid}: 磁盘文件未找到")
            continue
        fresh = load_note(actual_path)
        if not fresh:
            logger.warning(f"Failed to clean backlinks from target {tid}: 重新读取失败")
            continue
        if note_id not in fresh.backlinks:
            continue  # 并发方已移除本 id，无需写盘
        fresh.updated = now
        fresh.backlinks = [bid for bid in fresh.backlinks if bid != note_id]
        _atomic_write(actual_path, fresh.to_markdown())
        get_note_index().update_note_meta(fresh)
    except Exception as e:
        logger.warning(f"Failed to clean backlinks from target {tid}: {e}")
```

**promote_note 回填循环**（note.py:520-530）同构改造：写盘前 `find_note_file` + 重读 fresh + 在 fresh 上追加 backlink + 写回真实路径。fresh 重读后重新检查 `n.id not in fresh.backlinks`（并发方可能已加过）。

### 3.3 B1：conftest mock 补 encode_single

`tests/conftest.py` MockEmbeddingBackend 加：

```python
def encode_single(self, text: str):
    """单条编码（vector_store.add_note 调用）"""
    return self.encode([text])[0]
```

### 3.4 B2：refs 悬空引用可见化（cli.py _refs_impl）

forward_links 和 backward_links 同构改造：

```python
for link_id in n.links:
    link_note = note.load_note_by_id(link_id)
    if link_note:
        forward_links.append({"id": link_id, "title": link_note.title, "type": link_note.type.value})
    else:
        forward_links.append({"id": link_id, "title": "（已删除/悬空）", "type": "dangling", "dangling": True})
```

- JSON 输出：条目加 `"dangling": true` 字段（加字段不删字段，向后兼容）。
- table 输出：悬空条目用 dim/red 样式显示「已删除/悬空」。
- 悬空也算连接：悬空存在时不显示「No connections yet」（用户需要看到不一致）。

## 4. 非目标（明确不做）

- per-file 锁 / 全库文件锁架构（A3 的第三种方案，超出本 issue 范围）
- 全局改 `from_markdown` 补 set_filepath（破坏 update_note/promote 重命名语义）
- `jfox refs` search 分支（note_index meta 路径，不涉及 load 过滤）

## 5. 测试计划

1. **A1**：test_delete_backlink_cleanup.py 补断言——纯脏 list（不含本 id）时 warning 含「如存在」且不写盘（mtime 不变）。
2. **A2**：新测试——target 磁盘文件名与计算路径发散（手改标题不改文件名），delete 后断言无同 id 双文件、旧文件 backlinks 已清。
3. **A3**：新测试——模拟并发：清理循环写盘前外部修改 target 文件（加一个字段），delete 后断言外部修改保留且 backlink 已移除。
4. **B1**：断言 conftest mock 有 encode_single（或依赖现有测试不再打 AttributeError 日志）。
5. **B2**：test_cli_format.py 补断言——悬空 backlink 在 JSON 输出中带 dangling 标记；table 输出显示「已删除/悬空」。

## 6. 验证命令

```bash
uv run pytest tests/unit/test_delete_backlink_cleanup.py tests/unit/test_add_backfill_links.py tests/test_cli_format.py -v
uv run black jfox/ tests/ && uv run ruff check jfox/ tests/
```
