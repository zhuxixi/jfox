# Session History

> 开发会话历史记录 | Development Session History
>
> 由 summary-and-commit skill 自动生成和更新
> Auto-generated and updated by summary-and-commit skill

---

## Recent Sessions (最近5次)

### Session 3 - 2026-03-23

**Issues #25, #26, #29: 多格式输出支持扩展**
- 为 `refs` 命令添加 `--format` 参数支持（json/table）
- 为 `graph` 命令添加 `--format` 参数支持（json/table）
- 为 `suggest-links` 命令添加 `--format` 参数支持（json/table）
- 统一修改默认 `json_output` 为 `False`，默认输出表格格式更友好
- 保留 `--json` 快捷方式保持向后兼容
- 批量关闭 Issue #25, #26, #29

### Session 2 - 2026-03-23

**Issue #43: status 命令缺少 --kb 参数支持**
- 为 `zk status` 命令添加 `--kb` / `-k` 参数，支持指定目标知识库
- 重构代码结构，提取 `_status_impl` 内部实现函数
- 使用 `use_kb` 上下文管理器实现知识库临时切换
- 验证通过：`zk status --kb boboyun --format json` 和 `zk status --kb boboyun` 均正常工作
- 关闭 Issue #43

### Session 1 - 2026-03-24

**Issue #40: 将 zk CLI 安装为全局可用命令**
- 验证 pyproject.toml 已正确配置 `[project.scripts]` 入口点
- 通过 `pip install -e .` 完成可编辑安装
- 更新 README.md 添加详细的安装说明和 Windows PATH 配置指南

**Issue #27, #28: 多格式输出支持（--format 参数）**
- 修改 `zk status` 命令：默认格式从 json 改为 table，支持 `--format json/table/yaml`
- 修改 `zk kb` 命令（list/info/current）：默认格式从 json 改为 table，支持 `--format json/table/yaml/csv`
- 保留 `--json` 作为快捷方式以保持向后兼容
- 表格格式更适合人工阅读，JSON 格式适合 Agent/脚本使用

**Bug 修复**
- 添加警告过滤，消除 networkx backend 重复注册的 RuntimeWarning

---

*Total: 3 sessions | Last Updated: 2026-03-23*
