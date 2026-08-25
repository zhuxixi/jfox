# Spec: moc create/update 补 --json 简写（#425）

日期：2026-08-25
状态：待用户确认 → 已获授权（用户要求全流程自动化处理，方案在 issue 描述中已审阅）

## 决策

给 `jfox moc create` / `jfox moc update` 各加 `--json` 简写，与 `diagnose` 及 jfox-common §4.1 约定对齐。

## 实现方案（纯模式复制，范本 = moc/cli.py 的 diagnose_cmd）

### 1. `jfox/moc/cli.py`

`create_cmd` 与 `update_cmd` 各加一个参数（放在 `output_format` 之后）：

```python
json_output: bool = typer.Option(
    False, "--json", help="JSON 输出（快捷方式，等同于 --format json）"
),
```

函数体开头（`_fail` 校验之前）加：

```python
if json_output:
    output_format = "json"
```

与 diagnose_cmd 现有写法逐字一致。

### 2. 测试

- `tests/unit/test_moc_create_cli.py`：新增 `test_create_json_shorthand_matches_format`——`runner.invoke(app, ["moc", "create", "--cluster", "0", "--json"])` 与 `--format json` 输出一致（patch 同一 mock report）
- `tests/unit/test_moc_update_cli.py`：新增 `test_update_json_shorthand_matches_format`——同理
- help 契约测试各加一行 `assert "--json" in " ".join(lines)`（可选，顺手补）

### 3. skill 文档同步 `skills-recommend/pi/jfox-moc/SKILL.md`

- 删顶部注释「注意：moc 命令组中 diagnose 支持 `--json` 简写，`create` / `update` 需用 `--format json`」
- Step 2/4 示例 `--format json` → `--json`（与 jfox-common 约定统一）

## 契约

- `--json` 与 `--format json` 完全等价（简写置位即覆盖 output_format）
- 错误路径行为不变（`_fail` 走 output_format 判定，简写已先行合入）
- 显式 `--format table --json` 并存时 → json 胜出（与主 cli.py 其他命令行为一致）

## 非目标

- 不改 `diagnose`（已有简写）
- 不动其他命令组
- 不重构 moc/cli.py 的参数处理为公共 mixin（单点复用不值得，保持诊断一致性即可）

## 验收标准（对齐 issue）

1. `jfox moc create --cluster 0 --json` 与 `--format json` 输出一致
2. `jfox moc update --json` 与 `--format json` 输出一致
3. SKILL.md 无例外注释，统一 `--json`
4. 新增 2 条测试 + help 契约断言通过
5. markdownlint 通过（SKILL.md 改动）
