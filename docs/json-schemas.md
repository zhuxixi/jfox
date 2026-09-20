# jfox --json 输出 schema

本文档是全部 `--json` 输出的权威 schema 参考（issue #502，随下一 minor 版本发布）。调用方（脚本 / AI agent）只需读本文即可正确解析任意命令的 JSON 输出，无需逐命令猜测字段路径。

## 分流规则

所有 `--json` 输出顶层必有布尔 `success` 字段：

- `success: true` —— 命令执行成功，业务字段位置见下表
- `success: false` —— 执行失败，必有非空 `error` 字符串，进程退出码 1

调用方只需 `data["success"]` 即可分流，无需先读退出码；退出码与 `success` 保持一致（`check` 等报告型命令例外，见「特殊语义说明」）。

```bash
jfox add "内容" --title "标题" --json | python3 -c "
import json, sys
d = json.load(sys.stdin)
if d['success']:
    print(d['id'])        # add 顶层冗余快捷字段
else:
    print(d['error'])
"
```

## 顶层字段约定

| 字段 | 类型 | 出现条件 |
|------|------|----------|
| `success` | bool | 恒有 |
| `error` | string | 仅失败时（非空）；个别命令成功时也存在但为空串，见特殊语义 |
| `id` / `title` | string | 仅 `add` 成功时（冗余快捷字段，与 `note.id` / `note.title` 同值） |
| 其余 | 按命令 | 见下表 |

## 主 CLI 命令 schema

命令均支持 `--json` 或 `--format json`；`--kb <name>` 选择目标知识库。

其中 #519 新增的降级警告 `warnings[]` 元素统一形状：`{"code": "embedding_unavailable", "message": "<安装提示>", "fallback": "keyword" | "bm25_only"}`；缺语义组件的拒绝错误统一携带 `code: "embed_dependency_missing"`（`error` 含 GPU/CPU/pip 三路安装指引）。

| 命令 | 成功顶层字段 | 实体位置 | 失败形状 |
|------|--------------|----------|----------|
| `init` | `success, message, name` | 平铺 | `{success, error}` |
| `add` | `success, id, title, note{id,title,type,filepath,links}` + 可选 `warnings, backfill_failures, rollback_failures, backfill_note_save_failed, vector_dimension_warning, semantic_index_warning`（#519 无语义组件时降级提示） | 嵌套 `note`；顶层冗余 `id`/`title` | 重复：`{success, skipped:"duplicate", duplicate{matched_id,matched_title,matched_by,score}}`；其余 `{success, error}` |
| `search` | `success, query, mode, include_archived, total, results[]` + 可选 `warnings[]`（#519 降级时） | 列表 `results` | `{success, error}`；`--mode semantic` 且无语义服务时拒绝：`{success, code:"embed_dependency_missing", error}`（#519） |
| `status` | `success, knowledge_base{path,exists}, stats, backend{type,model,dimension}, embedding{local_package,daemon_running,service_available}`（#519 可用性块） | 嵌套三段 | `{success, error}` |
| `list` | `success, total, notes[]`（项含 `outgoing,incoming`） | 列表 `notes` | `{success, error}` |
| `show` | `success` + `id,title,type,created,updated,tags,links,backlinks,topic,filepath,content,content_body` + 可选 `source,archived`、candidate 字段（`gem_level` 等）、溯源字段（`source_fragments` 等） | 顶层平铺 | `{success, error}` |
| `refs` | 默认：`success, notes[]`；`--search`：`success, query, matches[]`；`--note`：`success, note{id,title,type}, forward_links[], backward_links[]`（悬空项带 `dangling:true`） | 分支各异 | `{success, error}` |
| `delete` | `success, deleted, title` | 平铺 | 入链守卫：`{success, error, references{frontmatter[],body[],total}}`；其余 `{success, error}` |
| `archive` / `unarchive` | `success, archived`/`unarchived`, `title` | 平铺 | `{success, error}` |
| `edit` | `success, note{id,title,type,filepath}` + 可选 `title_changed{old,new}, warnings, semantic_index_warning`（#519 无语义组件时） | 嵌套 `note` | `{success, error}` |
| `query` | `success, query, semantic_results, effective_mode, results[]` + 可选 `warnings[]`（#519 降级时 `effective_mode:"keyword"`） | 列表 `results` | `{success, error}` |
| `graph` | `--stats`：`success, total_nodes, total_edges, avg_degree, isolated_nodes, clusters, top_hubs[]`；`--orphans`：`success, orphans[]`；`--note`：`success, note_id, title, related[]` | 分支各异 | `{success, error}` |
| `daily` | `success, date, total, notes[]` | 列表 `notes` | `{success, error}` |
| `inbox` | `success, total, notes[]` | 列表 `notes` | `{success, error}` |
| `suggest-links` | `success, content, total_suggestions, threshold, suggestions[]` + 可选 `warnings[]`（#519 降级为关键词匹配时） | 列表 `suggestions` | `{success, error}` |
| `index <action>` | `rebuild`：`success, indexed, semantic_skipped, bm25_rebuilt, bm25_indexed[, backlinks_*]` + 可选 `warnings[]`（#519 无语义服务时 `semantic_skipped:true`、仅重建 BM25）；`rebuild-bm25`：`success, indexed`；`status`：`success, total_indexed, last_indexed, pending_changes, vector_store`；`bm25-status`：`success, bm25_index{...}`；`verify`：`success`（语义见特殊语义说明）+ 透传字段 | 平铺 | `{success, error}`（错误分支需显式 `--json` 开启，见特殊语义说明） |
| `kb <action>` | `list`：`success, current, knowledge_bases[]`；`create/switch/use/remove/delete/rename`：`success, message`；`current/info`：`success, name, path, total_notes, by_type, created, last_used, description, is_current` | 平铺实体 | `{success, error}`（错误分支需显式 `--json` 开启，见特殊语义说明） |
| `ingest-log` | `success, repo_path, commits_extracted, imported, failed, total`（空仓库带 `message`） | 平铺计数 | `{success, error}`；缺语义组件拒绝：`{success, code:"embed_dependency_missing", error}`（#519） |
| `bulk-import` | `success, imported, failed, total`（`--json` 默认开启） | 平铺计数 | `{success, error}`；缺语义组件拒绝：`{success, code:"embed_dependency_missing", error}`（#519） |
| `check` | `success, total, issues[{file,issue,size}]`（发现 issue 时退出码 1，见特殊语义说明） | 列表 `issues` | `{success, error}` |
| `update` | `success, method, previous_version, current_version, already_latest, command, output, stderr, error`（成功时 `error` 为空串）+ dev 分支 `message` | 平铺 | 同形状 `success:false` |
| `redirect` | `success, old_id, keep_id, files_changed, frontmatter_links_updated, body_links_updated, backlinks_updated, conflicts[], unreadable_files[], errors[], verification_passed[, dry_run]` | 平铺计数 + 列表 | `{success, error, errors[], conflicts[], unreadable_files[], verification_passed}`（`error` 为首条错误 / 冲突或不可读文件计数摘要 / 验证未通过提示） |
| `config` | 无 JSON 输出（console） | — | — |
| `perf` | 无 JSON 输出（console） | — | — |
| `daemon` | 无 JSON 输出（console） | — | — |
| `model download` | `model, success, cache_dir, instructions` | 平铺 | `{success:false, error}`（意外异常也保证 JSON） |

## 子应用命令 schema

### template

| 命令 | 成功顶层字段 | 实体位置 | 失败形状 |
|------|--------------|----------|----------|
| `template list --format json` | `success, builtin[], custom[]`（项含 `name,description,note_type`） | 列表 | `{success, error}` |
| `template show <name>` | `success, name, description, note_type, title_format, content, tags, is_builtin` | 顶层平铺 | `{success, error}` |
| `template create ...` | `success, template{name,description,note_type}` | 嵌套 `template` | `{success, error}` |
| `template remove <name>` | `success, deleted` | 平铺 | `{success, error}` |
| `template edit` | 无 JSON 输出（console） | — | — |

### fragments

| 命令 | 成功顶层字段 | 实体位置 | 失败形状 |
|------|--------------|----------|----------|
| `fragments list --format json` | `success, fragments[], total`（行含 `fragment_id,session_id,fragment_type,source_event,timestamp,content,metadata_json`） | 列表 `fragments` | `{success, error}` |
| `fragments show <id>` | `success` + 上述 7 键平铺 | 顶层平铺 | `{success, error}` |

### prompts

| 命令 | 成功顶层字段 | 实体位置 | 失败形状 |
|------|--------------|----------|----------|
| `prompts list` | `success, items[]` | 列表 `items` | `{success, error}` |
| `prompts show <id>` | `success` + 行平铺 + `judgment` | 顶层平铺 | `{success, error}` |
| `prompts status` | `success, total_prompts, unjudged, processing, failed, succeeded, pending_disposition, active_unresolved` | 平铺统计 | — |
| `prompts drain` | `success, imported, duplicates, remaining, ...` | 平铺 | spool 溢出：`{success:false, error, ...}` + 退出码 1 |
| `prompts backfill` | `success, found, imported, skipped` | 平铺计数 | 失败为未捕获异常：非零退出码 + traceback，无 JSON 输出（已知例外，后续收敛） |
| `prompts judge` | `success, total, succeeded, failed, batches, items[]` | 平铺 + 列表 | 失败为未捕获异常：非零退出码 + traceback，无 JSON 输出（已知例外，后续收敛） |
| `prompts config` | `success, capture{...}, judge{...}`（`--set` 成功输出为 console，见特殊语义说明） | 嵌套两段 | `{success, error}` |
| `prompts promote/unresolved/resolve-unresolved/ignore/retry <id>` | 成功无 JSON 输出（console 确认文本） | — | `{success, error}` |

### candidates

| 命令 | 成功顶层字段 | 实体位置 | 失败形状 |
|------|--------------|----------|----------|
| `candidates list --format json` | `success, candidates[], total` | 列表 `candidates` | `{success, error}` |
| `candidates show <id>` | `success` + `Note.to_dict()` 平铺（`content` 为全文） | 顶层平铺 | `{success, error}` |
| `candidates promote/reject <id>` | `{promoted`/`rejected`, `success}`（`success` 为操作结果布尔，见特殊语义说明） | 平铺 | 正常失败无 `error` 键（已知例外）；异常失败 `{success:false, error}` |

### bookshelf

| 命令 | 成功顶层字段 | 实体位置 | 失败形状 |
|------|--------------|----------|----------|
| `bookshelf add ...` | `success, slug, title, page_count, path` | 平铺 | `{success, error}` |
| `bookshelf list` | `success, books[], total` | 列表 `books` | `{success, error}` |
| `bookshelf show <slug>` | `success` + `BookMeta.to_dict()` 平铺 + `path, pages[]` | 顶层平铺 | `{success, error}` |
| `bookshelf show <slug> --page N` | `success, slug, page, content` | 平铺 | `{success, error}` |
| `bookshelf remove <slug>` | `success, slug, removed`（用户取消时 `removed:false`，仍 `success:true`） | 平铺 | `{success, error}` |

### auto-summary

| 命令 | 成功顶层字段 | 实体位置 | 失败形状 |
|------|--------------|----------|----------|
| `auto-summary status` | `success, config, ledger_file, ledger_stats, progress{total_scannable, succeeded, skipped, pending, failed, retryable, percentage, in_schedule_window}` | 嵌套多段 | — |
| `auto-summary enable/disable` | `success, message` | 平铺 | `{success, error}` |
| `auto-summary scan` | `success, pending[{session_id,project,size_bytes,mtime,age_minutes}]` | 列表 `pending` | — |
| `auto-summary run` | `success, succeeded, scanned, processed, skipped, failed, items[]`（`succeeded` 为 int 计数，见特殊语义说明） | 平铺 + 列表 | — |
| `auto-summary forget <id>` | `success, removed` | 平铺 | 多命中：`{success:false, error, matches[]}` |
| `auto-summary prune` | `success, pruned, older_than_days` | 平铺 | `{success, error}` |

### backup

| 命令 | 成功顶层字段 | 实体位置 | 失败形状 |
|------|--------------|----------|----------|
| `backup status` | `success, enabled, schedule_time, retain, backup_root, last_run, last_ok` | 平铺 | — |
| `backup list` | `success, items[]`（项含 `archive,size,ok`） | 列表 `items` | — |
| `backup verify <snapshot>` | `success, snapshot, ok`（`success` 与 `ok` 同值，`ok` 为兼容保留） | 平铺 | `{success:false, snapshot, ok:false, error}` + 退出码 1 |
| `backup enable/disable/run/restore` | 无 JSON 输出（console） | — | — |

### moc

`moc` 全部命令（`diagnose / create / update / add-member / remove-member`）本就带 `success`，本轮未改动：成功均为 `success` + 各自业务字段（`diagnose` 含 `coverage{...}, threshold_sweep[], orphans{...}`；`create` 含 `cluster{...}, draft{...}, created`；`update` 含 `updates[], applied`；`add-member/remove-member` 平铺操作结果），失败为 `{success, error}`。

## 特殊语义说明

以下行为是**有意设计**，调用方按此理解：

1. **`check` 报告语义**：`check --json` 发现问题时输出 `success:true`（命令本身执行成功、报告有效）+ 非空 `issues[]`，同时退出码 1。分流以 `success` 为准；`issues` 非空表示「检查发现了待处理问题」。
2. **`auto-summary run` 计数语义**：顶层 `success:true` 表示本轮调度执行完成并产出报告；单条会话的处理结果看 `succeeded`（int 计数）、`failed`、`items[]`。`success:true` 不代表所有条目都成功。
3. **`index verify` 的 `success`**：表示「校验过程本身无执行错误」（如目录不可读）；索引数据是否健康看透传的 `healthy` 字段。`success:true, healthy:false` = 命令成功执行且发现数据不一致。
4. **`backup verify` 的 `success` 与 `ok`**：同值。`ok` 是本轮统一前的原始字段，为兼容保留；新代码请读 `success`。
5. **`kb` 错误分支的触发条件**：`kb` 的错误 JSON 由 `--json` 标志（`json_output`）触发；仅 `--format json` 不带 `--json` 时错误走 console 文本。这是全库 `json_output` 快捷方式约定的一部分。
6. **`prompts config --set` 成功输出**：仅 console 确认文本，无 JSON 成功形状（失败时有 `{success, error}`）。
7. **`prompts` 动作命令成功无 JSON**：`promote` 等五个动作命令成功时只输出 console 确认文本（历史行为，未纳入本轮统一范围）。
8. **`candidates promote/reject` 正常失败无 `error` 键**：service 层拒绝（如校验不通过）返回 `{promoted:false, success:false}` 而无 `error`；仅异常失败带 `error`。已知例外，后续版本收敛。
9. **`update` 成功时的 `error` 键**：恒存在但成功时为空字符串 `""`——判断成败请以 `success` 布尔为准，勿以 `error` 是否为 `null` 判断。

## 统一引入的破坏性变更

本轮统一引入的破坏性变更（均为低频管理命令，已在 CHANGELOG `Unreleased` 标注，随下一 minor 发布）：

| 命令 | 变更前 | 变更后 |
|------|--------|--------|
| `backup list` | 裸 JSON 数组 `[...]` | `{success, items:[...]}`（原 `[0]` 索引改为 `.items[0]`） |
| `prompts list` | 裸 JSON 数组 `[...]` | `{success, items:[...]}` |
| `auto-summary run` | 顶层 `success` 为 int 计数 | `success` 变布尔（命令完成即 `true`）；计数改名 `succeeded` |
| `auto-summary status` | `progress.success` 为 int 计数 | 改名 `progress.succeeded` |

其余全部变更为纯增量（新增 `success` 字段或错误分支补 JSON 输出），不影响既有解析。
