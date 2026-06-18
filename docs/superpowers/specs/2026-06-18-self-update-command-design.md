# Design: jfox self-update 命令

> Issue: #238
> Branch: `feat/issue-238-self-update`

## 背景

用户希望直接通过 `jfox update` 完成 jfox 自身升级，而不需要手动调用 `uv tool upgrade`、`pipx upgrade` 或 `pip install --upgrade`。

## 目标

- 新增 `jfox update` 命令，自动检测当前安装方式并调用对应升级命令。
- 显示升级前后版本对比。
- 开发模式下明确提示使用 `git pull + uv sync --extra dev`。
- 网络失败时给出清晰的错误提示和手动升级指引。

## 非目标

- 不支持自动检测 `conda`、`poetry` 等其他安装方式。
- 不实现自动回滚。
- 不修改现有 CLI 命令的行为。

## 决策记录

| 决策 | 选择 | 理由 |
|------|------|------|
| 命令名 | `jfox update` | 与 issue 需求一致，语义直观 |
| 安装方式检测顺序 | dev → uv → pipx → pip | dev 需要优先识别，避免误升级；uv/pipx 路径特征明显 |
| 升级包名 | `jfox-cli` | 与 `pyproject.toml` 中的 `project.name` 一致，PyPI 实际分发名 |
| 版本对比 | 升级前读取 `jfox.__version__`，升级后调用 `jfox --version` 子进程 | 运行中进程的 `__version__` 不会自动更新，需用新进程获取 |
| 开发模式判定 | 同时检查 `.git` 目录、`pyproject.toml` 和 editable marker | 覆盖 `uv sync --extra dev` 和 `pip install -e ".[dev]"` |

## Section 1: 文件与命名

- 修改文件：`jfox/cli.py`（新增 `update` 命令及内部实现 `_update_impl`）。
- 新增测试：`tests/unit/test_update.py`。
- 可选更新：`README.md` 命令速查表、`docs/installation.md` 升级说明。

## Section 2: 安装方式检测逻辑

### 2.1 检测顺序

```
if is_dev_installation(package_path):
    return "dev"
if is_uv_tool_installation(package_path):
    return "uv"
if is_pipx_installation(package_path):
    return "pipx"
return "pip"
```

### 2.2 dev 模式判定

满足以下任一条件即视为开发模式：

1. `jfox.__file__` 位于某个包含 `pyproject.toml` 且 `project.name == "jfox-cli"` 的目录下，且该目录同时包含 `.git/`。
2. `jfox.__file__` 路径中出现 `.egg-link` 或 `site-packages/*.egg-link` 指向源码目录。
3. `jfox` 可执行文件为源码目录下的 `.venv/bin/jfox`（`uv sync` 产生的虚拟环境入口）。

### 2.3 uv tool 判定

- 优先调用 `uv tool dir` 获取工具根目录。
- 若 `jfox.__file__` 位于 `<uv-tool-dir>/jfox-cli/` 下，则为 uv tool 安装。
- 降级策略：若 `uv` 命令不可用，则按路径特征匹配 `uv/tools/jfox-cli/`。

### 2.4 pipx 判定

- 优先调用 `pipx environment --value PIPX_HOME` 获取 pipx 主目录。
- 若 `jfox.__file__` 位于 `<pipx-home>/venvs/jfox-cli/` 下，则为 pipx 安装。
- 降级策略：匹配常见路径 `pipx/venvs/jfox-cli/`。

### 2.5 pip 判定

不满足以上任何条件时，默认为 pip 安装（系统 Python 或 user site-packages）。

## Section 3: 升级命令映射

| 安装方式 | 命令 |
|---------|------|
| dev | 不执行命令，提示 `git pull && uv sync --extra dev` |
| uv | `uv tool upgrade jfox-cli` |
| pipx | `pipx upgrade jfox-cli` |
| pip | `pip install --upgrade jfox-cli` |

## Section 4: CLI 行为

### 4.1 命令签名

```python
@app.command()
def update(
    output_format: str = typer.Option("table", "--format", "-f", help="输出格式: json, table"),
    json_output: bool = typer.Option(False, "--json", help="JSON 输出快捷方式"),
):
    """升级 jfox 到最新版本"""
```

### 4.2 输出示例

**table 模式：**

```
当前版本: 1.0.0
安装方式: uv tool
执行: uv tool upgrade jfox-cli
...
升级完成: 1.0.0 → 1.1.0
```

**json 模式：**

```json
{
  "success": true,
  "method": "uv",
  "previous_version": "1.0.0",
  "current_version": "1.1.0",
  "command": "uv tool upgrade jfox-cli"
}
```

### 4.3 错误处理

- 无法识别安装方式：按 `pip` 处理，并附带警告。
- 升级命令返回非零：输出 stderr，提示手动执行对应命令。
- 升级后无法获取新版本：输出 `"unknown"` 并提示重新运行 `jfox --version`。

## Section 5: 边界与异常

- 升级过程中自身代码被替换，运行中进程不受影响，升级完成后通过子进程获取新版本。
- Windows 下 `uv tool dir` 等命令同样适用；路径使用 `Path.is_relative_to` 处理。
- 代理/内网环境：捕获 `subprocess.CalledProcessError`，返回包含完整手动命令的 JSON/table 错误信息。

## Section 6: 验收标准

- [ ] `jfox update` 命令可用，默认输出 table 格式。
- [ ] `jfox update --json` 输出合法 JSON。
- [ ] 开发模式提示 `git pull + uv sync --extra dev`，不调用任何升级命令。
- [ ] uv / pipx / pip 三种安装方式分别调用正确命令。
- [ ] 升级前后版本号均显示（或升级后显示 `"unknown"`）。
- [ ] 网络/命令失败时退出码为 1，并给出手动升级指引。
- [ ] 单元测试覆盖 detection + command selection + JSON output + error handling。

## Section 7: 验证方式

1. 单元测试：mock `shutil.which`、`subprocess.run`、模块路径和版本号，验证各安装方式的命令选择。
2. 本地 smoke test：在开发模式下运行 `jfox update`，确认提示信息正确。
3. 静态检查：`ruff check jfox/cli.py tests/unit/test_update.py` 通过。
