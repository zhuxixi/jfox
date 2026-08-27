# Issue #436 Organize Archive Design

> 设计文档（spec）：jfox-organize 提炼流程硬删改 archive 软删除

日期：2026-08-27
Issue: #436

## 根因

`jfox-organize` skill 的「Step 2 提炼」流程第 6 步用 `jfox delete <原始-id> --force` 清理已提炼的源 fleeting 笔记。`--force` 硬删不可逆，agent 误判（删错 id / 不该删的素材）时源笔记永久丢失。

jfox 已有 `archive`（软删除，文件保留）+ `unarchive`（恢复）命令，且 `jfox-promote` 已有「reject = archive」约定。本修复把 organize 对齐到该约定。

## 修改决策表

| # | 文件 | 位置 | 改动 |
|---|------|------|------|
| 1 | `skills-recommend/pi/jfox-organize/SKILL.md` | 提炼流程第 6 步 | `jfox delete <原始-id> --force` → `jfox archive <原始-id>`，步骤名「删除源 fleeting」→「归档源 fleeting」，补一句可恢复说明 |
| 2 | `skills-recommend/pi/jfox-organize/SKILL.md` | 错误处理 | 「`jfox delete` 目标 ID 不存在」→「`jfox archive` 目标 ID 不存在」 |
| 3 | `skills-recommend/kimi-cli/jfox-organize/SKILL.md` | 提炼流程第 6 步 | `jfox delete <original-id> --force` → `jfox archive <original-id>`，步骤名「Delete source fleeting」→「Archive source fleeting」，补可恢复说明（英文） |
| 4 | `skills-recommend/kimi-cli/jfox-organize/SKILL.md` | Command Reference | `jfox delete <id> --force` → `jfox archive <id>` |
| 5 | `skills-recommend/kimi-cli/jfox-organize/SKILL.md` | 错误处理 | 「`jfox delete` ID not found」→「`jfox archive` ID not found」 |
| 6 | `skills-recommend/pi/jfox-common/SKILL.md` | §4.4 删除笔记 | delete 语法示例保留（delete 是合法命令），补 archive / unarchive 示例 + 一行提示「清理已提炼的源笔记优先用 archive」 |
| 7 | `skills-recommend/pi/jfox-common/SKILL.md` | 快速参考表 | delete 行后补 archive / unarchive 两行 |
| 8 | `skills-recommend/kimi-cli/jfox-common/SKILL.md` | Delete Note | 同 #6（英文） |
| 9 | `skills-recommend/kimi-cli/jfox-common/SKILL.md` | 快速参考表 | 同 #7（英文注释） |

## 非目标

- 不抽象 issue 背景里提到的「安全协议」统一 skill（issue 明确聚焦最小修复点）
- 不改 jfox CLI 本身（`delete` / `archive` 命令行为不变）
- 不改其他 skill 中已有 archive 约定的部分

## 验证

1. `rg -n "delete.*--force" skills-recommend/` 结果中不再有 organize 的硬删调用；common 中仅剩 delete 语法示例（合法保留）
2. 两个 organize skill 的提炼流程第 6 步均为 `jfox archive`
3. markdownlint 通过（`npx --yes markdownlint-cli2`）
4. PR 描述引用 `Closes #436`
