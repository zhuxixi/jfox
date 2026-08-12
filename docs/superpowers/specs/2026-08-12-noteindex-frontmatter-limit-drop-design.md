# Spec: NoteIndex frontmatter 行数上限静默丢弃（#380）

## 背景

热门笔记 backlinks 无界增长，frontmatter 行数超过 `_MAX_FRONTMATTER_LINES = 200`（初版
`9515ef9` 引入，纯防御性初值）后，`_parse_frontmatter_only` 直接 `return None` → `rebuild()`
把文件塞进 `_invalid_files` 跳过 → NoteIndex `find_by_id`/`find_by_title` 返回 None →
指向它的 `[[wiki link]]` 全部解析失败。**反向伤害**：被链接越多（越重要）的笔记越易触发。

实测复现（sandbox）：构造 frontmatter 245 行（240 条 backlinks）的笔记，
`_parse_frontmatter_only` 返回 None，`find_by_title` 返回 None。

## 根因

`jfox/note_index.py:70-92`：

```python
_MAX_FRONTMATTER_LINES = 200
...
if len(lines) > _MAX_FRONTMATTER_LINES:
    return None   # 静默丢弃
```

上限本是「frontmatter 不闭合时避免读全文件」的 guard，但 200 远小于现实 backlinks 规模。
超限分支无任何可见日志。

## 设计决策

| 决策点 | 选择 | 理由 |
|--------|------|------|
| 上限值 | `200 → 50000` | backlinks 受 KB 笔记总数约束；个人 KB 极少过万，50000 是「远超现实上限」的纯 guard。正常文件读到闭合 `---` 即 break，零性能/内存影响。 |
| 超限行为 | `logger.warning`（点名文件 + 行数 + 原因）后 `return None` | 不再静默；将来真触发时用户可见。**不**采用「截断 links/backlinks 字段后部分解析」——会静默丢数据，比丢弃更糟。 |
| 可见性增强（index verify 接入 NoteIndex invalid files） | **非目标** | `index verify` 比对的是「文件系统 ID ↔ vector_store(ChromaDB) ID」，与 NoteIndex 职责不同。混淆二者是独立增强，留后续 issue。 |
| 兼容性 | 无数据迁移 | 抬高上限后，下次 `rebuild()`（CLI 启动即触发）自动重新纳入被丢弃的笔记。用户无需手动操作。 |

## 数据流（修复后）

```
frontmatter N 行
 ├─ N ≤ 50000 且闭合 `---` → 正常解析入索引 ✓
 ├─ N > 50000（病理）→ logger.warning(文件, N 行) → return None → _invalid_files（搜索时计数可见）
 └─ 不闭合 → for 读到 EOF 自然终止 → lines 可能为空/ yaml 失败 → None（不变）
```

## 非目标

- NoteIndex invalid files 接入 `index verify` 或新增可见命令。
- backlinks 字段截断策略。
- 全量 Note.from_markdown 解析路径无此上限，不动。

## 风险

- 极低：50000 行 yaml 解析开销在病理工况下约几 MB 内存、数十 ms，且仅对病理文件发生一次/进程。
  正常笔记 frontmatter < 数百行，读到闭合 `---` 即 break，不受影响。
