# Session History

> 开发会话历史记录 | Development Session History
>
> 由 summary-and-commit skill 自动生成和更新
> Auto-generated and updated by summary-and-commit skill

---

## Recent Sessions (最近5次)

### Session 5 - 2026-03-23

**CLI 与 Skill 同步完善**
- 为 `daily`, `inbox`, `template list`, `index` 命令添加 `--format` 参数支持
- 统一所有命令默认输出格式为 table，`--json` 快捷方式保持向后兼容
- 更新 Skill 文档（全局 + 项目），工具名称与 CLI 命令保持一致：
  - note_add → add, note_search → search, kb_graph → graph 等
- 修复测试失败：移除 graph 的日志输出避免 JSON 污染，修复 list 格式测试断言
- 全局 CLI 重新安装验证

### Session 4 - 2026-03-23

**Issue #30: 多格式输出测试套件**
- 创建 `test_formatters.py`：OutputFormatter 单元测试（31 个测试用例）
- 创建 `test_cli_format.py`：CLI --format 集成测试
- 为 ZKCLI 测试工具添加 `run()` 方法支持灵活测试
- 关闭 Issue #30

### Session 3 - 2026-03-23

**Issues #25, #26, #29: 多格式输出支持扩展**
- 为 `refs`, `graph`, `suggest-links` 命令添加 `--format` 参数支持
- 批量关闭 Issue #25, #26, #29

### Session 2 - 2026-03-23

**Issue #43: status 命令缺少 --kb 参数支持**
- 为 `zk status` 命令添加 `--kb` / `-k` 参数
- 关闭 Issue #43

### Session 1 - 2026-03-24

**Issue #40: 将 zk CLI 安装为全局可用命令**
- 验证 pyproject.toml 已正确配置 `[project.scripts]` 入口点
- 更新 README.md 添加详细的安装说明

---

*Total: 5 sessions | Last Updated: 2026-03-23*
