# list_notes 扫描结束时汇总无效文件提示 (#188)

## 问题

`list_notes()` 遇到无效文件（空文件、frontmatter 缺失等）时 `load_note()` 返回 `None`，
被静默跳过。用户无感知知识库中存在损坏文件。

## 修复

**文件**: `jfox/note.py` — `list_notes()` 函数

在遍历循环中计数 `load_note()` 返回 `None` 的次数。函数末尾，若 `skipped > 0`，
用 `logger.warning` 输出一条汇总：

```
Warning: 3 个文件无法加载，已跳过。运行 jfox check 清理。
```

**返回值类型不变**，仍为 `List[Note]`。warning 走 logging 通道，不影响 JSON/table 输出格式。

## 设计决策

- **在 list_notes() 内部输出**：所有调用者（list、show、search、links、daily、index rebuild）
  自动受益，无需逐个修改调用方。
- **仅汇总数字**：不打具体文件名，保持输出简洁。用户可用 `jfox check`（#189）定位具体文件。
- **提示中引用 jfox check**：该命令尚未实现，文案先写入，等 #189 完成后自然生效。

## 不在本次范围

- `jfox check` 命令本身（#189）
- 具体列出损坏文件名
- 修改 `load_note()` 行为（已在上一次 PR #187 中完成）
