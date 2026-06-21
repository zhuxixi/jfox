# JFox 碎片采集（Phase 1）设计方案

- **关联 Issue**: [#261](https://github.com/zhuxixi/jfox/issues/261) `feat: Claude Code Hook 碎片采集（Loop Engineering Phase 1）`
- **父 Issue**: [#249](https://github.com/zhuxixi/jfox/issues/249) Session 知识自动化闭环（五层 MVP）
- **日期**: 2026-06-21
- **状态**: 设计已确认，待实现

## 0. 关键设计依据（实测驱动）

CC hook 每个**事件 spawn 一次进程**。若 hook 命令是 `jfox fragment capture`（Python 子进程），实测冷启动 **210–300ms**，**超过 issue 要求的 100ms 硬约束 2~3 倍**。`curl` POST localhost 仅 **<5ms**。

| 方案 | 耗时 | 100ms 预算 |
|------|------|-----------|
| `jfox` 子进程（模拟 `fragment capture`）| 210–300ms | ❌ 超标 |
| `curl` POST localhost | <5ms | ✅ 达标 |

➜ **hook 必须是哑 curl 管道，检测逻辑下沉到 daemon 服务端**（Python 早就热）。这反而更优：daemon 是唯一 SQLite 写者，热连接、无并发锁竞争。

## 1. 架构

```
CC hook: packages/cc-plugin/hooks/fragment-capture.sh   (bash+curl, <10ms, 不 spawn Python)
   │   读 stdin JSON → 原样 POST http://127.0.0.1:18700/api/fragment
   ▼
JFox Daemon (jfox/daemon/server.py, 常驻, Python 已热)
   ├─ POST /api/fragment  → detector.py 分类 → store.py 写 SQLite (单一写者/WAL/热连接)
   │                        Stop 时额外计算并返回本轮摘要
   └─ GET  /api/fragments → 按 session/type 查询
jfox fragments list/show   (用户手动跑, 走 store.py 直读同一 SQLite, WAL 并发安全)
```

放 embedding daemon 里（而非新进程）：daemon 100% 常驻；`fragment` 模块本身是纯逻辑（`detector.py`/`store.py` 不依赖 daemon），daemon 只是 host，耦合仅在 `server.py` 接线层，可单测、可后续拆分。

## 2. 模块拆分（新增/改动文件）

| 文件 | 角色 | 新增/改动 |
|------|------|----------|
| `jfox/fragment/__init__.py` | 包入口 | 新增 |
| `jfox/fragment/store.py` | SQLite 读写（WAL, 建表, insert/query/summary） | 新增 |
| `jfox/fragment/detector.py` | 纠正/决策关键词检测，纯逻辑可单测 | 新增 |
| `jfox/daemon/server.py` | 加 `POST /api/fragment` + `GET /api/fragments`；lifespan 初始化 store | 改动 |
| `jfox/cli.py` | 加 `jfox fragments list/show` 子命令 | 改动 |
| `jfox/global_config.py` | 加 `fragment_capture` 配置段（关键词 + enabled，仿 auto_summary 先例） | 改动 |
| `packages/cc-plugin/hooks/fragment-capture.sh` | 哑 curl 脚本 | 新增 |
| `packages/cc-plugin/hooks/hooks.json` | hook 注册（plugin wrapper 格式） | 新增 |
| `packages/cc-plugin/.claude-plugin/plugin.json` | 加 `"hooks": "./hooks/hooks.json"` | 改动 |
| `tests/unit/test_fragment_detector.py` | detector 纯逻辑单测（秒级） | 新增 |
| `tests/unit/test_fragment_store.py` | store SQLite 单测 | 新增 |

## 3. 数据模型（SQLite）

落盘：`~/.zettelkasten/fragments.db`（全局，CC-session 维度，不归属某个 KB）。WAL 模式，daemon 启动时建表。

```sql
CREATE TABLE IF NOT EXISTS session_fragments (
    fragment_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id      TEXT NOT NULL,
    fragment_type   TEXT NOT NULL,   -- user_input|correction|decision|tool_call|session_summary
    source_event    TEXT NOT NULL,   -- UserPromptSubmit|PostToolUse|Stop
    timestamp       TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    content         TEXT,            -- 摘要(prompt / tool_response 前 500 字)
    metadata_json   TEXT             -- 完整原始事件 JSON（碎片永不删除，可回溯）
);
CREATE INDEX IF NOT EXISTS idx_frag_session ON session_fragments(session_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_frag_type    ON session_fragments(fragment_type, timestamp);
```

索引服务于两个查询：Stop 摘要（按 session）+ `list --type`（按 type）。

> 注：JFox 此前**无应用层 SQLite**（`auto_summary` 用 JSON Ledger）。这是首次引入 SQLite —— 合理，因碎片高频写入 + 永不删除，JSON 线性增长会变慢。`auto_summary` 保持 JSON（写入频率低），不强求统一。

## 4. CC Hook 配置

**`packages/cc-plugin/hooks/hooks.json`**：
```json
{
  "description": "JFox 碎片采集 - 实时捕获 session 纠正/决策信号",
  "hooks": {
    "UserPromptSubmit": [{ "hooks": [{ "type": "command",
      "command": "bash \"${CLAUDE_PLUGIN_ROOT}/hooks/fragment-capture.sh\"", "timeout": 5 }] }],
    "PostToolUse":      [{ "hooks": [{ "type": "command",
      "command": "bash \"${CLAUDE_PLUGIN_ROOT}/hooks/fragment-capture.sh\"", "timeout": 5 }] }],
    "Stop":             [{ "hooks": [{ "type": "command",
      "command": "bash \"${CLAUDE_PLUGIN_ROOT}/hooks/fragment-capture.sh\"", "timeout": 5 }] }]
  }
}
```

**`fragment-capture.sh`**（哑管道，~15 行，永不阻塞 CC）：
```bash
#!/usr/bin/env bash
set -u
PAYLOAD="$(cat)"
# POST 原样给 daemon；-m1 限时1s，失败静默，exit 0 永不阻塞 CC
RESP="$(printf '%s' "$PAYLOAD" | curl -s -m 1 -X POST \
    http://127.0.0.1:18700/api/fragment -H 'Content-Type: application/json' \
    --data-binary @- 2>/dev/null || true)"
# Stop 事件打印 daemon 返回的一行摘要
case "$PAYLOAD" in *'"hook_event_name":"Stop"'*)
  MSG="$(printf '%s' "$RESP" | python3 -c 'import sys,json;print(json.load(sys.stdin).get("message",""))' 2>/dev/null)"
  [ -n "$MSG" ] && echo "JFox 碎片采集: $MSG" ;; esac
exit 0
```

## 5. Daemon API

**`POST /api/fragment`** — body = CC 原始事件 JSON
- 解析 `hook_event_name` → 调 `detector.classify()` 得 `fragment_type` + `content`
- `store.insert(...)`（metadata_json 存完整原文）
- 若 `Stop`：`store.session_summary(session_id)` 计算本轮各类型计数，写一条 `session_summary` 行，响应带 `message`
- 返回 `{fragment_id, message}`

**`GET /api/fragments?session=&type=&limit=`** → `store.query(...)`

## 6. 检测规则（detector.py，关键词可配置）

| source_event | → fragment_type | 检测方式 |
|---|---|---|
| UserPromptSubmit | `correction` | prompt 含 `不对/错了/应该/不要/等等/停/不是/别/换一种/反过来` |
| UserPromptSubmit | `decision` | 含 `用方案/选/因为/理由是/我决定/就这样/先不做` |
| UserPromptSubmit | `user_input` | 否则 |
| PostToolUse | `tool_call` | 无需检测，content=tool_response 前500字 |
| Stop | `session_summary` | 触发本轮汇总 |

关键词放 `~/.zk_config.json` 的 `fragment_capture` 段，仿 `auto_summary` 先例，可改、可关（`enabled:false`）。

## 7. Stop 摘要输出
daemon 在 Stop 响应里返回 `message`（如「本轮采集 12 碎片：纠正 3 / 决策 2 / 工具 7」）；hook 脚本打印一行到 stdout，满足验收「Stop 触发时输出本轮采集摘要」。完整明细在 `jfox fragments list --session <id>`。

## 8. 验收标准映射（issue 6 项）

| 验收项 | 满足方式 |
|--------|---------|
| `fragment capture` 子命令 | ⚠️ **改为 hook→daemon API**（Python 子进程实测超 100ms） |
| 纠正信号检测准确 | detector.py 关键词，可单测 |
| 碎片写 SQLite | store.py + `~/.zettelkasten/fragments.db` |
| `jfox fragments list` | CLI 子命令 |
| Stop 输出采集摘要 | daemon 响应 message + hook 打印 |
| < 100ms 不影响 CC | 实测 curl <10ms，有 `timeout` 兜底 |

## 9. 与原 issue 描述的偏离（实现说明里会注明）
1. **检测在 daemon 服务端**（非 hook 端）—— 实测 Python 冷启动超 100ms。
2. **hook 用 curl 非 `jfox fragment capture` 子进程** —— 同上。
3. **首次引入应用层 SQLite** —— JFox 此前无 SQLite（`auto_summary` 用 JSON）。

## 10. 不做（Phase 2~5）
Hermes 采集 / 碎片分析合成 / 候选笔记生成 / 宝石晋升 —— 后续 issue。
