## 设计决策更新

### 默认格式：人工优先，Agent 显式指定

经过讨论，确定以下设计原则：

| 场景 | 默认格式 | 原因 |
|------|---------|------|
| **人工操作** | `table` | 美观、直观、一眼看懂 |
| **Agent/脚本** | `json` | 结构化、易解析、可管道 |

### 实现方案

1. **所有命令统一支持 `--format` 参数**
   - `--format table` (默认) - 人类可读
   - `--format json` - 机器解析
   - `--format csv/yaml/paths/tree` - 按需使用

2. **向后兼容**
   - 保留 `--json` 作为 `--format json` 的快捷方式
   - 废弃 `--no-json`，改用 `--format table`

3. **待实现子任务**
   - [ ] #27 Update status command with --format support
   - [ ] #28 Update kb command with --format support (当前 default 为 json，需改为 table)
   - [ ] 添加环境变量 `ZK_DEFAULT_FORMAT` 支持

### 验收标准
- `zk kb list` 默认显示 table 格式（不再是 json）
- `zk status` 默认显示 table 格式（不再是 json）
- Agent 使用时显式指定 `--format json`
