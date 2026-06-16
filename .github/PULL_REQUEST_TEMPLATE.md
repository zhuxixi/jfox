## 变更描述

<!-- 描述这次变更的内容。解决了什么问题？为什么选择这个方案？ -->



## 关联 Issue

<!-- 链接这次 PR 解决的 issue。如果没有，建议先创建一个。 -->

Fixes #

## 变更类型

<!-- 勾选适用的选项 -->

- [ ] 🐛 Bug 修复（不破坏兼容性的修复）
- [ ] ✨ 新功能（不破坏兼容性的新增）
- [ ] 🔒 安全修复
- [ ] 📝 文档更新
- [ ] ✅ 测试（新增或改进测试覆盖）
- [ ] ♻️ 重构（无行为变化）
- [ ] ⚡️ 性能优化

## 具体改动

<!-- 列出具体改动。包含代码文件路径。 -->

- 

## 测试步骤

<!-- 验证这次变更的步骤。对于 bug：复现步骤 + 修复证明。 -->

1. 
2. 
3. 

## 检查清单

<!-- 提交前完成以下检查。 -->

### 代码

- [ ] 我已阅读项目的 `AGENTS.md` 和开发规范
- [ ] 我的 commit 遵循 [Conventional Commits](https://www.conventionalcommits.org/)（`fix:`, `feat:`, `chore:`, `docs:` 等）
- [ ] 我搜索了 [现有 PR](https://github.com/zhuxixi/jfox/pulls) 确认没有重复
- [ ] 我的 PR 只包含与本次变更相关的改动（无无关提交）
- [ ] `uv run ruff check jfox/ tests/` 通过
- [ ] `uv run black jfox/ tests/` 通过
- [ ] `uv run pytest tests/ -m "not embedding and not slow"` 通过（快速测试）
- [ ] 我在本地测试通过：<!-- 例如 Ubuntu 24.04, macOS 15.2, Windows 11 -->

### 文档与维护

<!-- 勾选适用的选项。如果不适用，勾选 "N/A"。 -->

- [ ] 我已更新相关文档（README, AGENTS.md, CHANGELOG）— 或 N/A
- [ ] 我已考虑跨平台影响（Windows, macOS, Linux）— 或 N/A
- [ ] 我已更新工具描述或 schema（如果有变更）— 或 N/A

## 截图 / 日志

<!-- 如果适用，添加截图或日志输出展示修复/功能效果。 -->

