# Spec: #519 轻量化安装——`[embed]` extra 拆分 + 软依赖降级 + 文档（rev2）

- **Issue**: zhuxixi/jfox#519
- **日期**: 2026-09-10（rev2 依据当日评审修订）
- **状态**: draft rev2，待用户确认（github-issue-driven 步 4 暂停点）
- **调研留档**: `~/.claude/github-issue-driven/zhuxixi/jfox/issue-519/research/dependency-chain-and-code-structure.md`

**rev2 修订记录**（评审项 → 修订位置）：

1. P0 降级边界：降级点从 `create_note` 改为 `note.save_note()`（§3.4），VectorStore 抛出的专用异常不得被通用 `except Exception` 吞掉（§3.2）。
2. P0 hybrid 告警挂点：`_semantic_search` 与 `_hybrid_search_with_k` 双路径处理，CLI 从引擎单例读 warning（§3.3、§3.5）。
3. P0 daemon 场景：本地组件探测与「服务可用性」分离（`is_local_embed_available` / `is_embedding_service_available`），核心 CLI + 外部 daemon 合法可用（§3.1、§3.5）。
4. P0 rebuild 保护：无 embed 时 `index rebuild` 不清空既有向量库，只重建 BM25（§3.5、§4、A6）。
5. P1：移除 watcher 增量承诺（非目标）；`suggest-links` 改为关键词降级（exit 0）；补 `query` 命令；定义 JSON 错误/警告协议；CI Core/Full 补 `--extra embed` 并注册 `no_embed` marker；修正 git 源 extras 语法笔误；版本决策闭合为 2.0.0（§6）。
6. P2：依赖数量措辞、save 层契约覆盖所有调用方、status 改为增量字段（§3.5、A10）。

## 1. 背景与目标

`jfox-cli` 核心依赖 `sentence-transformers>=3.0` → torch；PyPI 的 Linux torch wheel 默认 CUDA 构建，metadata 无条件声明 10 个 `nvidia-*` 依赖（数 GB 下载）。CPU wheel 只在 pytorch 专用 index，包 metadata 无法按机器区分，需 jfox 侧规避。

**目标**：纯 CPU 机器默认 `uv tool install jfox-cli` 全程零 `nvidia-*` 包；语义检索组件化为可选安装；无该组件时核心功能（CRUD / BM25 检索 / 图谱）可用且有友好引导；不破坏「核心 CLI + 外部 embedding daemon」组合。

**调研支撑**：全仓 torch / sentence_transformers import 仅 5 处且全部是函数内延迟 import；核心 CLI 路径零依赖 torch 系；daemon 模式 CLI 进程走 HTTP 不碰模型库。

## 2. 方案总览（三层）

1. **打包**：`sentence-transformers` 移出核心 dependencies → 新增 `[embed]` extra；dev extra 不含 embed（CI Fast job 天然成为无 embed 测试环境）；`uv.lock` 重算。
2. **软依赖降级**：毫秒级本地探测 + 服务可用性判定（本地组件或 daemon）+ 专用异常 + 统一安装提示；各入口按降级矩阵处理（隐式经过语义 → 降级 + 提示；显式要语义且服务不可用 → 拒绝 + 提示）。
3. **文档**：README 安装章节三段式（默认轻量 / `[embed]` 组件 CPU+GPU 两条命令 / 升级说明）。
4. **版本**：发布按 major（2.0.0）处理（决策见 §6，本 PR 不改版本号）。

## 3. 组件契约

### 3.1 `embedding_backend.py` 新增公共接口

```python
def is_local_embed_available() -> bool:
    """本地 sentence-transformers 是否已安装。importlib.util.find_spec 探测，
    模块级缓存（首次探测后固定），不执行 import，毫秒级。"""

def is_embedding_service_available() -> bool:
    """是否存在可用的 embedding 服务：本地组件可用，或外部 daemon 在跑。
    daemon 判定复用 daemon.process.is_daemon_running + DaemonClient.available；
    进程运行在 daemon 内部（JFOX_DAEMON_PROCESS）时只看本地组件。
    本地探测走缓存；daemon 状态每次实时检查（可起可停）。"""

def reset_embed_availability_cache() -> None:
    """清空本地探测缓存（测试后门）。"""

class EmbedDependencyMissingError(RuntimeError):
    """本地语义组件缺失且无可用 daemon。message 含安装提示。"""

def format_embed_hint(context: str = "") -> str:
    """纯函数：拼装统一安装提示文案。context 为场景前缀（如 '语义检索'）。"""
```

**文案定稿**（`format_embed_hint` 输出，中文，四要素齐全）：

```
[提示] <context>需要语义检索组件（jfox 核心为精简安装，未包含）。
  GPU 机器:  uv tool install "jfox-cli[embed]"
  CPU 机器:  UV_TORCH_BACKEND=cpu uv tool install "jfox-cli[embed]"
  pip 用户:  pip install "jfox-cli[embed]"
             （CPU 机器先执行: pip install torch --index-url https://download.pytorch.org/whl/cpu）
补装后运行 `jfox index rebuild` 可补建语义索引。
```

`EmbeddingBackend.load()` 中 `from sentence_transformers import ...` 的 ImportError 转为 `EmbedDependencyMissingError` 再抛；daemon 优先的既有顺序不变（daemon 可用时根本不走本地加载）。`encode(daemon_only=True)` 的既有 RuntimeError 语义不变（dedup 等调用方自行降级）。

### 3.2 `VectorStore` 层（事实报告者，不做业务降级，不做本地前置拦截）

- `add_note` / `search`（query 编码路径）：捕获到 `EmbedDependencyMissingError` 时，先记录 `self.last_embed_warning = str(e)`，然后**原样 re-raise**（不得被通用 `except Exception` 吞成 `False` / `[]`）；其余异常保持现有处理（dim warning / log / return False / []）。
- 不在 `VectorStore` 入口做 `find_spec` 前置拦截——本地组件缺失但 daemon 可用是合法组合，能否编码由 `EmbeddingBackend` 实际尝试后决定。
- `add_or_update_note`（VectorStore 替换原语）与 `note.update_note()`（编辑路径的 delete→add 序列）：遵守不变量「**编码成功前不得删除既有行**」——先把删除动作放到可编码确认之后；无可用编码能力时既跳过写入也跳过删除，既有向量行保持原样，避免把可用索引删坏。
- `delete_note` / `get_all_embeddings` 等不 encode 的方法不检查（ChromaDB 本身是核心依赖，保留）。

### 3.3 `SearchEngine` 层（hybrid / semantic 双路径降级）

- `__init__` 增加 `self.last_embed_warning: Optional[str] = None`；每次 `search()` 开头清空。
- `_semantic_search` 与 `_hybrid_search_with_k` **两条路径都**捕获 `EmbedDependencyMissingError` → 设置 `last_embed_warning = format_embed_hint("语义检索")` → 返回 `[]`（hybrid 由 RRF 自然退化为 BM25-only）。
- CLI 与实际搜索共用 `get_search_engine()` 单例，读取其 `last_embed_warning`（不依赖 `VectorStore.last_dimension_warning` 传达 embed 缺失信号；dim 警告通道保持原样）。
- `note.search_notes()` 签名不变，内部走同一引擎单例。

### 3.4 save 层契约（`note.save_note()` 与 `note.update_note()`）——add/edit 降级的真正落点

`create_note()` 只构造对象、不索引；索引写入发生在两个函数：`save_note()`（新建；add 及 backlinks 回填 / `auto_summary` / `prompts` / `moc` 等共用）和 `update_note()`（编辑；现为「delete_note → add_note」序列且吞异常）。两函数契约一致：

```python
if add_to_index:
    vector_store = get_vector_store()
    try:
        vector_store.add_note(note)        # 或 update_note / add_or_update_note 的替换序列
    except EmbedDependencyMissingError:
        pass  # 文件已写、BM25 继续；warning 已由 VectorStore 记录
    # BM25 写入照常执行
```

- 捕获范围**只限** `EmbedDependencyMissingError`；其他向量写入错误行为不变（现有策略）。
- **不变量：编码成功前不得删除既有向量行**（`update_note` / `add_or_update_note` 的替换写入先确认可编码，再执行删除 + 写入）。
- 文件写入成功 + BM25 成功 + 向量跳过时返回 `True`。
- 本契约在 save 层生效，**所有调用方**（CLI add/edit、backlinks 回填、`auto_summary.runner`、`prompts.actions`、`moc.generate` 等）自动获得同样降级；`add_to_index=False` 调用不涉及。

### 3.5 CLI 层（`cli.py`）

**输出协议**（统一定义，替代含糊的「stderr 提示」）：

- 人类模式（table）：降级提示走 stdout 黄色文本；拒绝提示走 stderr；退出码 1。
- JSON 模式：降级警告进结构化 `warnings` 数组（stdout 不混文本）；拒绝输出结构化错误（stdout）：

  ```json
  {"success": false, "code": "embed_dependency_missing", "error": "<安装提示>"}
  ```

- csv/yaml/paths 等结构化非 JSON 模式：提示走 stderr（沿用 dim warning 既有先例）。
- 统一 warnings 结构：`{"code": "embedding_unavailable", "message": "<安装提示>", "fallback": "keyword" | "bm25_only"}`。

| 命令 | 改动 |
|------|------|
| `add` / `edit` | 经 §3.4 契约（add→`save_note`，edit→`update_note`）；CLI 成功后读取 `get_vector_store().last_embed_warning` 并展示（对齐既有 dim warning 读取方式）。JSON 输出新增 `semantic_index_warning` 字符串字段 |
| `search --mode semantic` | 前置 `is_embedding_service_available()`：不可用 → 拒绝（人类模式 stderr / JSON 模式结构化错误），不静默换 BM25；运行期中途失败（如 daemon 中途退出）仍走引擎降级（空结果 + warning），不重复拦截 |
| `search` 默认 hybrid | 引擎降级后读 `engine.last_embed_warning`：table 模式 stdout 黄字；JSON 模式 `warnings` 数组 |
| `search --mode keyword` | 不动 |
| `query` | hybrid 降级同样处理（读引擎 warning，输出 `warnings`）；结果新增 `effective_mode` 字段（`hybrid` / `keyword`，避免降级后旧字段名误导；既有字段保留兼容） |
| `index rebuild` | 无服务可用时：不调用 `Indexer.index_all()`（**不清空向量库**）、不 reset collection；只重建 BM25；`--backlinks` 照常执行（不依赖 embedding）；输出 warning + JSON `"semantic_skipped": true`（含 warnings） |
| `daemon start` / `restart` | 前置 `is_local_embed_available()`（daemon 进程必须本地加载模型）：缺失 → 拒绝（同协议）；`daemon stop` / `status` 不动 |
| `status` | 增量新增 `embedding` 块：`{"local_package": bool, "daemon_running": bool, "service_available": bool}`；既有 backend 字段保持兼容 |
| `suggest-links` | 无服务可用：跳过语义建议、**保留既有关键词匹配降级**（`note.suggest_links` 已有该能力），输出「当前仅关键词匹配」warning，退出码 0（不拒绝执行） |
| `dedup_check`（gem-synth / add 防重内部路径） | 现有降级语义保持（daemon 不可用 → None 放行）；异常噪声并入静默降级 |
| `ingest-log` / `bulk-import`（经 `bulk_import_notes` → `ModelCache.get_model` 直接加载本地模型） | 前置 `is_local_embed_available()`，缺失 → 拒绝；`perf report/clear-cache` 不触模型，不动 |
| 文件 watcher 增量 | 本 issue 不做改动、不做承诺（见 §7 非目标） |

### 3.6 打包与 CI（`pyproject.toml` / `.github/workflows/` / `pytest.ini`）

```toml
dependencies = [
    # 移除 sentence-transformers>=3.0；其余基础依赖不动
]
[project.optional-dependencies]
embed = ["sentence-transformers>=3.0"]
dev = [ ...现有 6 项工具链，不新增 embed... ]
```

- **pytest.ini**：注册 `no_embed` marker（项目开启 `--strict-markers`，未注册会直接失败）：`no_embed: marks tests for no-embed runtime（需在无 sentence-transformers 环境执行）`。
- CI **Fast** job（`uv sync --extra dev`，无 embed）：跑 `not embedding and not slow` + 新增 `no_embed` 子集（它们天然被该选择式包含）。
- CI **Core / Full / Coverage** job：`uv sync --extra dev --extra embed`（真实 embedding 测试不变）。
- **本地开发**：`uv sync --extra dev --extra embed`（README dev 章节 + AGENTS.md 同步）。
- `uv.lock` 重算；核心解析树无 torch / nvidia-*。

## 4. 降级矩阵（决策表·定稿）

| 入口 | 无服务可用时行为 | 提示渠道 | 退出码 |
|------|------------------|----------|--------|
| `add` / `edit`（及所有 `save_note` / `update_note(add_to_index=True)` 调用方） | 笔记 + BM25 照常，语义向量跳过；替换写入不删既有向量行 | 人类模式 stdout；JSON `semantic_index_warning` | 0 |
| `delete` | 不受影响（`delete_note` 不 encode） | — | 0 |
| `search`（hybrid 默认） | BM25-only 结果 | stdout / JSON `warnings` | 0 |
| `search --mode semantic` | 拒绝执行 | stderr / JSON 结构化错误 | 1 |
| `search --mode keyword` | 不受影响 | — | 0 |
| `query` | BM25-only + `effective_mode: keyword` | stdout / JSON `warnings` | 0 |
| `index rebuild` | 不清空向量库；只重建 BM25；`--backlinks` 照常 | stdout / JSON `semantic_skipped` + `warnings` | 0 |
| `daemon start/restart` | 拒绝启动 | stderr / JSON 结构化错误 | 1 |
| `daemon stop/status` | 不受影响 | — | 0 |
| `status` | 正常输出 + `embedding` 可用性块 | 正常输出 | 0 |
| `suggest-links` | 关键词匹配降级（跳过语义） | stdout / JSON `warnings` | 0 |
| gem-synth `dedup_check` | 返回 None 放行（现有语义） | 日志降噪 | — |
| `ingest-log` / `bulk-import` | 拒绝执行（本地模型路径） | stderr / JSON 结构化错误 | 1 |
| `moc diagnose` | 不受影响（只读已存向量，CPU NumPy） | — | 0 |
| 文件 watcher 增量 | 本 issue 不做承诺（§7） | — | — |

**原则**：隐式经过语义（add/edit、hybrid、query、rebuild、suggest-links）→ 降级 + 提示 + 退出码 0；显式要语义且服务不可用（--mode semantic、daemon start/restart、`ingest-log`/`bulk-import`）→ 拒绝 + 提示 + 退出码 1；能判定「本地组件或 daemon 任一可用」的入口使用 `is_embedding_service_available()`。

## 5. README 改动（安装章节三段式）

```markdown
## 安装
### 默认安装（轻量，纯 CPU 友好）
uv tool install "jfox-cli"        # git 源: uv tool install "git+https://github.com/zhuxixi/jfox.git"
# 含笔记 CRUD / BM25 关键词检索 / 知识图谱，不含语义向量检索

### 语义检索组件（可选）
GPU 机器:  uv tool install "jfox-cli[embed]"
CPU 机器:  UV_TORCH_BACKEND=cpu uv tool install "jfox-cli[embed]"
pip:       pip install "jfox-cli[embed]"（CPU 机器先装 torch cpu 版，见上文）

### 从 1.x 升级到 2.0
默认安装不再包含语义检索组件；已有环境升级后语义检索需补装 [embed]
（首次使用时 jfox 会给出同样提示）。
```

- git 源 + extra 的写法**实现时验证**，README 只写实测可用者；默认候选（PEP 508）：`uv tool install "jfox-cli[embed] @ git+https://github.com/zhuxixi/jfox.git"`。**不写未经验证的语法。**
- 同步范围：README（安装 / dev 章节）、AGENTS.md（开发环境安装命令）。

## 6. 版本与升级路径

- **决策（评审闭合）**：发布版本为 **2.0.0**（strict SemVer——默认安装组成变化，语义检索移出默认安装；项目文档无 1.x 兼容承诺，取最诚实信号）。本 issue 的 PR 不改版本号，版本与 CHANGELOG 由 release 流程处理；发布时 CHANGELOG 置顶「行为变更」条目：核心包不再默认携带语义组件 + 补装命令 + CPU 免 CUDA 变量说明。
- 现有用户原地升级（pip 不卸载已装包）：预期零感知。环境重建 / uv prune 场景：首次用语义功能时得到提示，一条命令恢复，已有向量索引不丢（ChromaDB 数据与包安装无关）。
- 若 review 阶段推翻为 1.15.0：需同时在 README/CHANGELOG 明确「有意兼容策略例外」。

## 7. 非目标

- fastembed / model2vec / ONNX 后端替换（Phase 3，独立 issue/roadmap）
- chromadb 依赖瘦身（onnxruntime 体积可接受，属核心向量存储）
- #250 rebuild GPU 负载 / CPU fallback（正交，独立推进）
- pip 侧 CPU torch 自动检测安装（文档指引即可）
- PyPI metadata 层面声明 torch index（生态限制，不可行）
- **文件 watcher 增量 BM25 同步**（现状缺口：`Indexer._index_file` 只写向量库、不更新 BM25；本 issue 不引入也不承诺，如需修复另开 issue）

## 8. 验收矩阵

| ID | 功能点 | 验收方式 | 具体验证 | 通过标准 |
|----|--------|----------|----------|----------|
| A1 | 本地探测 + 服务可用性判定 | 自动化（unit） | `uv run pytest tests/unit/test_embed_availability.py -v`（monkeypatch `find_spec`；mock `is_daemon_running`/`DaemonClient.available`） | 缺失/存在返回正确；缓存不重查（计数 find_spec 调用次数）；reset 后重查；daemon 在跑时服务可用=True；`JFOX_DAEMON_PROCESS` 下只看本地 |
| A2 | `EmbedDependencyMissingError` + 提示文案 | 自动化（unit） | 同上文件：断言 `format_embed_hint()` 输出 | 含 `UV_TORCH_BACKEND`、`jfox-cli[embed]`、pytorch cpu index、`index rebuild` 四要素 |
| A3 | pyproject 结构 | 自动化（static） | `uv run python -c "import tomllib; ..."` 断言脚本 | 核心依赖无 sentence-transformers；embed extra 含之；dev extra 不含 |
| A4 | save 层降级（add/edit 及共用调用方） | 自动化（integration） | no-embed 环境 `uv run pytest tests/integration/test_no_embed_degradation.py -m no_embed -v` | 笔记文件落盘、BM25 可检索到、语义写入未发生、退出码 0、可读到提示；**编辑已索引笔记（edit→`update_note`，预置 dummy 向量行）时既有向量行不被删除** |
| A5 | search 三模式 + query 降级 | 自动化（integration） | 同上文件 | hybrid：BM25 结果 + table 提示 + JSON `warnings[0].code == "embedding_unavailable"`；semantic：退出码 1 + JSON 结构化错误（`code == "embed_dependency_missing"`）；keyword 不受影响；query：BM25 结果 + `effective_mode == "keyword"` + warnings |
| A6 | index rebuild 降级 | 自动化（integration） | 同上文件（预置 dummy 向量行模拟既有索引） | BM25 全量重建、**既有向量行保留（ids/count 不变）**、`semantic_skipped: true`、warnings、退出码 0；`--backlinks` 仍执行 |
| A7 | suggest-links 降级 + 拒绝类入口 | 自动化（integration） | 同上文件 | suggest-links：关键词建议 + warning + 退出码 0；daemon start/restart：退出码 1 + 安装提示；`ingest-log` / `bulk-import`：退出码 1 + 提示 |
| A8 | 安装体积（wheel 级）+ 无模型 smoke | 自动化（automated E2E） | `scripts/verify_lightweight_install.sh`：`uv build` → 独立 venv 装本地 wheel → `uv pip list` 断言 → 隔离 HOME 跑 `jfox init` / `jfox add` / `jfox search --mode keyword` | 零 `nvidia-*` 包、无 torch；`jfox --version` 可执行；smoke 三命令成功（add 降级不报错） |
| A9 | CI 无 embed 维度 | 自动化（build/CI） | push 后 Fast job（跑核心子集 + `no_embed` 测试）；Core/Full 带 `--extra embed` | Fast 绿（无 embed 环境）；Core/Full 绿（真实 embedding 测试）；`no_embed` marker 已在 pytest.ini 注册 |
| A10 | status embedding 块 | 自动化（integration） | no-embed 文件：`jfox status --format json` | `embedding.local_package == false`、`embedding.service_available == false`、`embedding.daemon_running == false`；退出码 0；既有字段兼容 |
| U1 | 发布后 CPU 机器一键安装 | 用户实测（2.0.0 发布后可执行） | 干净容器/VM：`UV_TORCH_BACKEND=cpu uv tool install "jfox-cli[embed]"`，然后 `jfox add` + `jfox search --mode semantic` | 全程零 `nvidia-*` 下载；语义检索返回结果 |
| U2 | 升级路径抽查（可选） | 用户实测（2.0.0 发布后可执行） | 已装 1.x 的环境 `uv tool update jfox-cli` 后跑语义检索 | 语义照常（uv 不 prune）或得到友好提示（若 prune）；核心功能始终可用 |

## 9. 可测性拆分设计（实现硬约束）

| 拆分单元 | 性质 | 怎么测 | 测试边界 |
|----------|------|--------|----------|
| `is_local_embed_available()` / 缓存 / `reset_...` | 纯探测 + 模块级缓存（副作用=缓存写入，已隔离） | unit：monkeypatch `importlib.util.find_spec` | 不装真库；断言缓存不重查（计数 find_spec 调用次数） |
| `is_embedding_service_available()` | 组合判定（本地缓存 + daemon 实时检查） | unit：mock `is_daemon_running` / `DaemonClient.available` / `JFOX_DAEMON_PROCESS` | 不启动真 daemon；daemon 分支可注入 |
| `format_embed_hint(context)` / `EmbedDependencyMissingError` | 纯函数 + 异常类型 | unit：断言四要素片段与 context 拼接；异常 message 携带 hint | 无 I/O |
| VectorStore 守卫（add_note / search / add_or_update_note） | 事实报告者：typed raise + 记录 `last_embed_warning` + 替换写入不删既有行 | unit：mock backend 抛 typed error，断言 re-raise 与 warning 记录；**不测降级决策** | store 层只报事实，降级归调用层——此边界禁止回耦；「不删既有行」在 A4 用真实 ChromaDB 行验证 |
| `note.save_note()` / `note.update_note()` 语义路捕获 | 降级决策点（两函数一致） | integration（no-embed venv）：真 CLI add/edit | 文件落到盘、BM25 可搜到、向量跳过、返回 True 分开断言；替换写入不删既有行 |
| `SearchEngine.last_embed_warning`（semantic + hybrid 双路径） | 实例属性告警通道 | unit：mock vector_store 抛 typed error，分别走 `_semantic_search` / `_hybrid_search_with_k`，断言返回 []/BM25 且 warning 非空、`search()` 会清空旧值 | 引擎不做 I/O 提示，打印归 CLI 层 |
| CLI 前置检查（semantic / daemon start或restart / ingest-log / bulk-import）与警告展示 | 早退守卫 + 输出协议 | integration（no-embed venv）：退出码 + stdout/stderr 分流 + JSON 结构 | JSON 模式 stdout 不混文本（snapshot 断言） |
| `scripts/verify_lightweight_install.sh` | E2E 脚本（build + 干净 venv + 装包 + 断言 + 隔离 HOME smoke） | 本地/CI 可执行 | 不依赖 PyPI（装本地 wheel），发布验证归 U1 |
| `no_embed` pytest 标记 | 测试环境维度标记 | Fast job（天然无 embed）执行；装有 embed 的环境通过 `pytest.mark.skipif(is_local_embed_available(), ...)` 跳过 | 与 `embedding` 标记语义互斥；marker 注册于 pytest.ini（`--strict-markers`） |

## 10. 风险与开放问题

1. **uv tool update 是否 prune 孤儿依赖**：pip 明确不卸载；uv 未文档化承诺。U2 实测观察，两种结果均在可接受设计内（零感知或友好提示）。
2. **pip 用户补装 `[embed]` 在 CPU 机器拉 CUDA torch**：pip resolver 从 PyPI 取 torch 默认 CUDA 版——文案已含「先装 cpu torch」指引，属文档缓解，不做自动检测（非目标）。
3. **git 源 + extras 语法**：PEP 508 `"jfox-cli[embed] @ git+https://..."` 为默认候选，实现时验证 uv 实际支持情况；README 只写实测可用者。
4. **Fast 环境（无模型库）下既有测试的隐性依赖**：已知 `tests/performance/*` 为 slow 标记（Fast 不收集）、`conftest.embedding_model` 有 try/except、`tests/unit/test_embedding_local_load.py` 自带 stub；仍有未知隐性依赖可能在 A9 实跑时暴露，发现后按 `no_embed`/`embedding` 标记归类修正。
5. **`uv.lock` 变更规模**：torch 族移入 optional 组，lock diff 大但机械；dev 环境锁文件同步更新。

## 11. 数据流总结

```
uv tool install jfox-cli           → 核心依赖（无 torch）→ 轻量环境
uv tool install "jfox-cli[embed]"  → + sentence-transformers + torch（UV_TORCH_BACKEND=cpu 时 +cpu 版）

CLI 命令
  ├─ 显式语义入口（--mode semantic / ingest-log / bulk-import；daemon start|restart 只查本地）
  │     is_embedding_service_available() / is_local_embed_available()
  │       ├─ 可用   → 继续（编码时 daemon 优先，本地兜底）
  │       └─ 不可用 → 拒绝：人类模式 stderr；JSON {"success": false, "code": "embed_dependency_missing", ...}；exit 1
  ├─ 隐式语义路径（add/edit → save_note / update_note；hybrid search/query；suggest-links；index rebuild）
  │     EmbeddingBackend.encode → daemon 优先 → 本地 load()
  │       ├─ 可用   → 正常
  │       └─ EmbedDependencyMissingError →
  │             save_note / update_note：文件 + BM25 完成，warning 记录，exit 0
  │             search/query：BM25 fallback + warnings，exit 0
  │             suggest-links：关键词降级 + warning，exit 0
  │             rebuild     ：跳过语义（不清空、不删行），BM25 重建 + warnings，exit 0
  └─ 不触达语义（CRUD / BM25 / 图谱 / 模板 / bookshelf / fragment / moc / watcher）→ 完全不变
```
