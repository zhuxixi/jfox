# Issue #460 根因报告与修复设计

## 结论

测试污染真实 `~/.zk_config.json` 的根因不是 cleanup 失败，而是全局配置路径在测试进程和 CLI 子进程中都解析到了真实用户 HOME。修复应在配置路径解析层增加 `ZK_CONFIG_PATH` 环境变量，并在 pytest 入口、任何 jfox 模块导入前，将其设置到本次测试的临时目录；保留既有 teardown 清理作为第二道防线。

## 根因链

1. `jfox/global_config.py` 在模块导入时定义 `DEFAULT_CONFIG_PATH = Path.home() / ".zk_config.json"`。
2. `tests/conftest.py` 在导入 jfox 模块前只设置 `ZK_KB_ROOT`，所以 KB 数据进入临时目录，但配置注册表仍指向真实 HOME。
3. `tests/utils/jfox_cli.py::ZKCLI._run()` 用 `subprocess.run([sys.executable, "-m", "jfox", ...])` 执行 CLI，子进程继承父进程环境，但没有独立配置路径。
4. `ZKCLI.init()` 调用默认 `set_default=True` 的 `jfox init`，使临时 KB 注册并切换真实配置中的 `default`；测试运行期间并行的用户 CLI 便会解析到测试 KB。
5. 现有 fixture `try/finally` 和 session cleanup 只能在测试退出后撤销状态，无法消除运行窗口，也无法覆盖进程被杀或并行测试。

## 设计决策

### 1. 配置路径覆盖方式

新增环境变量 `ZK_CONFIG_PATH`：

```python
_default_config_path = Path.home() / ".zk_config.json"
_config_path_env = os.environ.get("ZK_CONFIG_PATH", "").strip()
DEFAULT_CONFIG_PATH = Path(_config_path_env or str(_default_config_path)).expanduser()
```

语义：

- `ZK_CONFIG_PATH` 非空时，所有默认构造的 `GlobalConfigManager` 使用该路径。
- 未设置或为空时，保持现有行为 `Path.home() / ".zk_config.json"`。
- 显式传入 `GlobalConfigManager(config_path=...)` 的路径优先级不变，因为显式参数仍直接使用 `config_path`。
- 环境变量在模块导入时解析，符合现有 `ZK_KB_ROOT` 模式和“进程启动前配置”的使用方式。

### 2. pytest 隔离

在 `tests/conftest.py` 设置 `_TEST_ROOT` 后、导入任何会间接加载 `jfox.global_config` 的测试辅助模块前设置：

```python
os.environ["ZK_CONFIG_PATH"] = str(_TEST_ROOT / "zk_config.json")
```

这样：

- 当前 pytest 进程中的 `GlobalConfigManager()` 读取临时配置。
- `ZKCLI` 启动的 CLI 子进程继承 `ZK_CONFIG_PATH`，注册、切换、删除均只写临时配置。
- 现有 `ZK_KB_ROOT` 与 `JFOX_SYNTHESIS_DB` 的隔离模式保持一致。
- 不要求日常 pytest 为了这个问题修改用户的 HOME，也不影响真实用户的默认行为。

### 3. 回归验证

增加配置路径环境变量的子进程回归测试，避免当前测试模块已导入 `global_config` 造成假阳性：

- 子进程设置独立的 `ZK_CONFIG_PATH`、`ZK_KB_ROOT` 和临时 HOME。
- 运行 `python -m jfox init --name ... --path ... --no-default --json`。
- 断言 `ZK_CONFIG_PATH` 指定的配置文件被创建并包含测试 KB。
- 断言 HOME 下的默认 `.zk_config.json` 未被创建，证明 CLI 子进程没有回退到 HOME 配置。
- 增加未设置环境变量时仍回退到 `Path.home() / ".zk_config.json"` 的覆盖测试；现有 `test_init_with_default_path` 继续验证默认行为。

不建议在测试中直接 snapshot/比较真实用户的 `~/.zk_config.json`：这会读取用户数据，并且在用户并行执行真实 CLI 时可能产生竞态和误报。隔离路径测试能在不接触真实配置的情况下证明同一故障链已被切断。

### 4. 防御性清理

保留现有 `cli`/`cli_fast` 的 `try/finally` 和 `_cleanup_test_root`：它们继续负责临时数据回收及异常残留清理，但不再承担保护真实配置的主要职责。此次不改 cleanup 的名字匹配策略，避免把 issue 范围扩大到历史残留治理。

## 验收标准

1. `ZK_CONFIG_PATH=/tmp/test-config.json python -m jfox ...` 的默认全局配置读写只发生在该路径。
2. 未设置 `ZK_CONFIG_PATH` 时，用户现有配置路径和行为完全不变。
3. pytest 的父进程和 `ZKCLI` 子进程都使用测试临时配置；测试期间不会注册/切换真实 KB。
4. 回归测试能证明 CLI 子进程不会在 HOME 下创建默认配置文件。
5. 现有快速全局配置测试和 CLI 格式测试通过；不要求自主运行全量 embedding/慢测试。
6. 改动不涉及用户 CLI 提示、daemon 并发配置写入、真实用户配置残留的自动清理。

## 预计改动文件

- `jfox/global_config.py`：解析 `ZK_CONFIG_PATH`。
- `tests/conftest.py`：设置测试配置路径。
- `tests/unit/test_global_config.py` 或新建同目录测试：增加跨进程环境变量回归测试。

## 风险与降级

- 如果环境变量设置在 `jfox.global_config` 导入之后，当前进程不会重新计算常量；文档和测试约定应在进程启动/模块导入前设置。CLI 子进程天然满足该条件。
- 如果显式 `config_path` 与环境变量同时存在，显式参数继续优先，保证现有依赖注入测试兼容。
- nightly 脚本已经使用隔离 HOME，此改动不会改变其行为；它只是为日常 pytest 和 CR job 增加独立的配置路径保护。
