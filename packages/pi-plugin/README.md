# jfox pi-plugin

pi-coding-agent 侧 user prompt 采集扩展（issue #462）：把 pi 会话中真人输入的
prompt 记录进 jfox 记录层（#399），与 Claude Code 侧对齐。

## 工作原理

监听 pi 的 `input` 事件，过滤程序注入（`source === "extension"`）与 JFox 内部
session，把用户输入合成为 CC 兼容事件后：先原子写本地 spool，再尽力 POST
jfox daemon 的 `/api/prompt`。daemon 确认落盘（stored/duplicate/skipped）后删除
spool；daemon 不可用时 spool 保留，`jfox prompts drain` 恢复。全程不阻塞 pi。

## 前置条件

- jfox ≥ 1.14.0（记录层 `/api/prompt` 端点）；source 透传需包含 #462 改动的发布版本——旧 daemon 收到 pi 事件时按 claude-code 记录，功能不破坏，建议升级
- jfox daemon 运行中（`jfox daemon start`）；停机也能采（spool 兜底）

## 安装

拷贝或符号链接单文件到 pi 扩展目录，重启 pi 或执行 `/reload`：

```bash
cp packages/pi-plugin/extensions/jfox-prompt-capture.ts ~/.pi/agent/extensions/
```

符号链接方式（仓库更新后 `git pull` 即生效）：

```bash
ln -s "$(pwd)/packages/pi-plugin/extensions/jfox-prompt-capture.ts" ~/.pi/agent/extensions/
```

## 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `JFOX_DAEMON_URL` | `http://127.0.0.1:18700` | jfox daemon 地址 |
| `JFOX_PROMPT_SPOOL_DIR` | `~/.zettelkasten/prompt-spool` | 本地 spool 目录 |
| `JFOX_INTERNAL_SESSION` | （未设置） | 命中 `auto-summary`/`gem-synth`/`prompt-judge` 时跳过采集（防反馈循环，由 jfox 内部 runner 设置） |

## 验证

在 pi 里发一条消息，然后：

```bash
jfox prompts list --json | head -40
```

最新记录应含 `"source": "pi-coding-agent"`，`prompt` 为输入原句。

## 开发测试

无 npm 依赖，node ≥ 22.6 直跑：

```bash
node --experimental-strip-types packages/pi-plugin/test/run-tests.ts
```
