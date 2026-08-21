# PR #410 pi-cr Round-1 修复报告

日期：2026-08-21
分支：`issue-390-moc-density-diagnose`
基线：`d1b9aa67bf2ee99f84e9b1b7c9ed816497edf322`

## 结论

PR #410 Round-1 的 4 条 open issue 均已修复。实现保持 MOC 诊断只读、permanent-only、live/archived 过滤、BM25 N/A、文件系统 fail-safe、orphan flags、确定性排序及 JSON/table 契约不变，未增加第三方依赖。

## Issue 1：根 CLI eager import 重依赖

### 修复

- 将 `moc_app` 的导入与 `app.add_typer(...)` 从 `jfox/cli.py` 顶部移到现有重型 sub-app 注册区。
- `jfox/moc/cli.py` 不再顶层导入 `cluster.py`，实际执行 diagnose 时才加载聚类服务。
- `jfox/moc/__init__.py` 使用按需属性加载保留既有公开接口，并把轻量的 `MocDiagnoseError` 放在子包入口。
- 新增隔离 subprocess 测试，同时验证 `moc` 已注册且 `chromadb`、`networkx` 未进入 `sys.modules`；补 `--version` 回归测试。

### RED

```text
uv run pytest tests/unit/test_moc_cli.py::test_import_root_cli_keeps_moc_registered_without_heavy_dependencies tests/unit/test_moc_cli.py::test_root_version_still_works_with_moc_registered -q
1 failed, 1 passed
失败断言：payload["chromadb_loaded"] is False（实际为 True）
```

### GREEN

```text
同一命令：2 passed
uv run jfox --help：显示 moc
uv run jfox --version：jfox 1.7.2
uv run jfox moc --help：显示 diagnose
```

### 性能

使用同一 `.venv/bin/python`、每次独立进程、5 次测量 `import jfox.cli`：

- 修复前 `d1b9aa6`：1058.9 / 861.9 / 785.9 / 815.3 / 808.3 ms；中位数 **815.3 ms**；加载 chromadb/networkx。
- 修复后工作树：166.7 / 198.4 / 182.5 / 152.1 / 152.3 ms；中位数 **166.7 ms**；不加载 chromadb/networkx/numpy。
- 中位数减少 **648.6 ms（79.6%）**，同时 `moc` 仍注册在 root Typer app。

## Issue 2：活跃 ChromaDB 目录可能复制出撕裂快照

### 修复

- 复制前后递归读取源目录 manifest：`(相对路径, size, mtime_ns)`，覆盖 SQLite、WAL、SHM 及 Chroma segment 文件。
- manifest 变化时丢弃整个临时目录并重试；`copytree`/文件访问异常同样有限重试。
- 最多尝试 3 次，不引入长 sleep；每次都创建全新临时目录，兼容 Windows 文件锁导致的短暂复制失败。
- 最终失败清理临时状态并抛 `VectorStoreReadError`，明确说明可能有 daemon/indexer 写入并提示稍后重试。
- 始终只让 Chroma 打开快照，不打开或修改 live Chroma 目录。

### RED

```text
uv run pytest tests/unit/test_vector_store_embeddings.py -q
3 failed, 4 passed
```

失败分别证明旧实现：

1. manifest 变化后没有重试；
2. 一次 copytree 文件锁失败即退出；
3. 最终错误不含 daemon/稍后重试提示，临时状态未按新契约清理。

### GREEN

```text
uv run pytest tests/unit/test_vector_store_embeddings.py -q
7 passed
```

测试不只校验调用次数，还验证：第二份快照包含更新后的 WAL 和递归 segment 内容；失败重试不会残留 partial 文件；最终失败后 client/collection/tempdir/snapshot 均为空；原始 live DB 内容未变。

## Issue 3：新增模块 docstring/comment 应使用中文

### 修复

- `jfox/moc/cluster.py`、`jfox/moc/cli.py`、`jfox/moc/__init__.py` 的模块、类、函数 docstring 和说明注释均改为中文。
- 新增测试模块说明改为中文；CLI 英文输出、错误契约和 JSON key 保持不变。

### 检查证据

基线 AST 检查发现纯英文 docstring：

- `cluster.py`：17
- `cli.py`：4
- `__init__.py`：1

修复后 AST 检查三文件均为 `[]`；对注释/docstring 的 grep 未发现纯英文说明残留。代码标识符、JSON key、CLI 契约字符串及类型检查指令不计入说明文字。

## Issue 4：dense N×N 内存无界增长

### 修复

- 新增 `MAX_DENSE_CLUSTER_NOTES = 5000`，并用中文注释说明 N×N 稠密矩阵约束。
- 只对已通过 permanent/live/archived/重复向量过滤后的真实参与聚类条目计数。
- 5000 条以内正常执行；超过上限直接抛 `MocDiagnoseError`，明确说明不会产生不完整建议，未来需使用稀疏图或分块算法。
- 设计文档记录 5000 条限制和未来演进方案。

### RED

```text
uv run pytest tests/unit/test_moc_cluster.py::test_diagnose_dense_limit_includes_exact_boundary tests/unit/test_moc_cluster.py::test_diagnose_dense_limit_rejects_above_boundary_without_truncation -q
1 failed, 1 passed
失败：超过边界 DID NOT RAISE MocDiagnoseError
```

### GREEN

```text
同一命令：2 passed
```

边界内完整执行；超过边界错误同时包含配置上限、`稀疏`、`分块`，未静默截断。

## 最终自动验证

### 聚焦测试

```text
uv run pytest tests/unit/test_moc_cluster.py tests/unit/test_moc_cli.py tests/unit/test_vector_store_embeddings.py tests/unit/test_bm25_concurrency.py -q
84 passed in 1.65s
```

覆盖任务要求的四个文件及全部新增回归测试。

### CLI 既有格式回归

```text
uv run pytest tests/test_cli_format.py -q
48 passed in 156.64s
```

另在最终代码状态复跑代表用例：

```text
uv run pytest tests/test_cli_format.py::TestCLIFormat::test_status_format_json tests/test_cli_format.py::TestCLIFormat::test_status_format_table tests/test_cli_format.py::TestCLIFormat::test_status_format_yaml tests/test_cli_format.py::TestCLIFormat::test_add_content_file tests/test_cli_format.py::TestCLIFormat::test_add_format_json -q
5 passed in 7.33s
```

### 静态检查与导入

```text
uv run ruff check
All checks passed!

uv run black --check jfox tests
193 files would be left unchanged.

uv run python -m compileall -q jfox
通过

uv run python -c 'import jfox.cli; import jfox.moc.cli; import jfox.moc.cluster; import jfox.vector_store; print("compile/import ok")'
compile/import ok
```

隔离 import 断言：`chromadb`、`networkx` 均未加载，root app 中存在 `moc`。

## 真实 default KB 只读验收

验收时系统存在运行中的 `jfox.daemon.server`，因此同时覆盖常见 daemon 并发场景。

执行：

```text
uv run jfox moc diagnose --kb default --json
uv run jfox moc diagnose --kb default
```

结果：

- JSON `success: true`
- filesystem permanent：529
- vector permanent：603
- vector orphan：74
- BM25 permanent：529，覆盖率 1.0
- threshold sweep：4 档
- suggested clusters：8
- union orphans：89
- table 四区段正常输出

### `.zk` 原始文件一致性

诊断前后递归采集 default KB `.zk` 的完整 manifest，每项包含：

- 相对路径
- size
- mtime_ns
- SHA-256

两次 manifest 均为 112 个文件，`cmp` 返回 0，**前后完全一致**。这证明 JSON 与 table 两次真实诊断均未修改 live `.zk` 原始文件。

## 变更文件

- `docs/superpowers/specs/2026-08-21-moc-density-diagnose-design.md`
- `jfox/cli.py`
- `jfox/moc/__init__.py`
- `jfox/moc/cli.py`
- `jfox/moc/cluster.py`
- `jfox/vector_store.py`
- `tests/unit/test_moc_cli.py`
- `tests/unit/test_moc_cluster.py`
- `tests/unit/test_vector_store_embeddings.py`
- `.superpowers/pr410-fix-report.md`

未修改 README，也未运行约 50 分钟的 full/embedding suite。

## 残余风险

- manifest 前后稳定是无新依赖条件下的有限一致性保护，不等价于数据库级事务快照；若写入持续发生，命令会在 3 次后明确失败并要求稍后重试，而不会使用未经确认的快照。
- 5000 条上限避免无界增长，但接近上限时 dense 矩阵及中间布尔矩阵仍有明显内存成本；后续应按错误提示演进为稀疏图或分块算法。

## Commit

- 实现提交：`7526ae6`（`fix(moc): address density diagnose review`）
- 本报告提交：包含本文件的后续 `docs` commit（SHA 无法在自身内容中自引用）。
