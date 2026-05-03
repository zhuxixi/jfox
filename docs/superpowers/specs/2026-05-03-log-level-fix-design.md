# 修复 load_note 空文件日志级别 (#186)

## 问题

知识库中存在空文件（如 crash 残留的 0 字节 `.md` 文件）时，`load_note()` 使用
`logger.error()` 记录解析失败日志。由于 `list_notes()` 会跳过 `None` 返回值，
命令实际正常执行，但 ERROR 日志混入输出让用户误以为操作失败。

调用链: `show` → `find_note_id_by_title_or_id` → `list_notes` → `load_note(空文件)` → ERROR log

## 修复

**文件**: `jfox/note.py:105`

将 `logger.error(...)` 改为 `logger.warning(...)`。

理由：单文件解析失败是可恢复的非致命问题，`load_note` 返回 `None` 后调用方
正常跳过，不影响命令执行结果。WARNING 级别语义正确，不会误导用户。

## 不在本次范围

以下两点记录为后续优化 issue：

- `list_notes()` 扫描结束时汇总无效文件数量并给出提示
- 新增 `jfox check` 命令检测和清理空文件/损坏文件
