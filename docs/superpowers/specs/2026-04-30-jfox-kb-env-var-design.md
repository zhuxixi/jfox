# feat: 支持 JFOX_KB 环境变量指定默认知识库

**Issue**: #183
**Date**: 2026-04-30

## 背景

多 agent 场景下，每个 agent 操作自己的知识库。目前每次调用 jfox 都需要传 `--kb <name>` 参数，不够便捷。通过环境变量 `JFOX_KB` 可以让 agent 进程级别设置默认 KB，无需每次传参。

## 方案

采用 **方案B：在 `use_kb()` 上下文管理器内部统一处理**。

环境变量优先级（由低到高）：
1. `~/.zk_config.json` 中的 `default` 字段（全局默认 KB）
2. `JFOX_KB` 环境变量（进程级默认 KB）
3. CLI `--kb` 参数（命令级显式指定）

即：`--kb` > `JFOX_KB` > 全局配置 default。

## 改动点

### 1. `jfox/config.py` — 修改 `use_kb()` 上下文管理器

当传入的 `kb_name` 为 `None` 时，增加对 `JFOX_KB` 环境变量的检查：

- 若 `os.environ.get("JFOX_KB")` 存在且非空，将其作为实际 KB 名称
- 若不存在，保持原有行为（使用全局配置 default）
- 优先级自然满足：用户传 `--kb` 时 `kb_name` 非 `None`，直接走原逻辑，不读取环境变量

当 `JFOX_KB` 生效时，在 `yield` 前通过 `rich.console.Console` 输出一行 dim 样式提示：

```
Using knowledge base 'work' (from JFOX_KB environment variable)
```

### 2. 错误处理

`JFOX_KB` 指向不存在的 KB 时，行为与 `--kb nonexistent` 完全一致：
`kb_manager.kb_exists()` 返回 `False`，抛出 `ValueError`，无需额外逻辑。

## 影响范围

- `jfox/config.py` — 仅修改 `use_kb()` 函数
- `cli.py` 的 20+ 个命令一行不动，全部自动生效
- 不需要修改任何 `_impl` 函数

## 使用示例

```bash
# 设置 agent 专属 KB
export JFOX_KB=agent-work

# 后续所有命令默认操作 agent-work
jfox add "完成了任务 #123"
jfox search "任务"
jfox daily

# --kb 参数仍然可以覆盖
jfox --kb personal search "私事"
```

## 测试

新增 `tests/unit/test_use_kb_env_var.py`：

- `test_jfox_kb_env_var_used_when_kb_arg_none`：设置 `JFOX_KB=work`，验证 `use_kb(None)` 切换到 work
- `test_cli_arg_overrides_jfox_kb`：`use_kb("personal")` 时忽略环境变量，使用 personal
- `test_invalid_jfox_kb_raises_valueerror`：环境变量指向不存在的 KB 时抛 `ValueError`
- `test_jfox_kb_hint_printed`：环境变量生效时输出提示（mock Console）
