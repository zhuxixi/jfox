# PR 自动 Code Review 系统设计

## 概述

本系统实现当 GitHub 上任何仓库创建或更新 PR 时，自动触发 Claude Code 的 code review，并将结果提交到 PR 评论中。

**核心目标：**
- 全自动：PR 创建/更新后自动触发，无需人工干预
- 多仓库：支持监控账号下所有可访问的仓库
- 轻量级：单 Python 脚本，资源占用低
- 易部署：Windows 环境一键启动

---

## 架构

```
┌─────────────────┐     ┌─────────────┐     ┌──────────────────────────┐
│  GitHub Webhook │────▶│  smee.io    │────▶│  Flask Webhook Receiver  │
│  (PR opened/    │     │  (proxy)    │     │  (Windows 本地运行)       │
│   synchronize)  │     └─────────────┘     └──────────┬───────────────┘
└─────────────────┘                                    │
                                                       ▼
                                              ┌──────────────────────┐
                                              │ 调用 Claude Code     │
                                              │ claude code          │
                                              │   --print            │
                                              │   /code-review:code-review <PR_URL>
                                              └──────────┬───────────┘
                                                         │
                                                         ▼
                                              ┌──────────────────────┐
                                              │ 提交 Review 评论     │
                                              │ (gh pr review ...)   │
                                              └──────────────────────┘
```

---

## 组件说明

### 1. smee.io（Webhook 代理）

GitHub Webhook 需要公网地址，smee.io 是 GitHub 官方提供的免费代理服务，将 webhook 事件转发到本地。

- 访问 https://smee.io 获取一个唯一 URL
- 本地客户端连接到 smee.io，接收事件
- 无需暴露本地端口到公网

### 2. Flask Webhook 接收器

核心服务，负责：

1. **接收事件**：监听来自 smee.io 的 POST 请求
2. **过滤事件**：只处理 `pull_request.opened` 和 `pull_request.synchronize`
3. **提取信息**：从 payload 获取 PR URL、仓库、分支等信息
4. **触发 Review**：调用 Claude Code 执行 code review
5. **提交结果**：使用 `gh` CLI 将 review 结果提交到 PR

**技术栈：**
- Python 3.10+
- Flask（轻量级 web 框架）
- requests（HTTP 客户端）

### 3. Claude Code 调用

通过 subprocess 调用本地安装的 Claude Code：

```bash
claude code --print /code-review:code-review <PR_URL>
```

Claude Code 会分析 PR 并返回 review 结果（JSON 或文本格式）。

### 4. GitHub CLI (gh)

用于提交 review 评论，复用已有的认证：

```bash
gh pr review <PR_URL> --comment -b "<review_result>"
```

---

## 数据流

### PR 创建场景

```
1. 用户在 GitHub 创建 PR
2. GitHub 发送 webhook 到配置的 smee.io URL
3. smee.io 转发到本地 Flask 服务
4. Flask 验证事件签名（可选）
5. Flask 提取 PR URL: https://github.com/owner/repo/pull/123
6. Flask 调用: claude code --print /code-review:code-review <URL>
7. Claude Code 返回 review 结果
8. Flask 调用: gh pr review <URL> --comment -b "<result>"
9. 评论出现在 PR 中
```

### PR 更新场景（push 新代码）

```
1. 用户 push 新 commit 到 PR 分支
2. GitHub 发送 `pull_request.synchronize` 事件
3. 同上流程，重新执行 code review
4. 新评论追加到 PR
```

---

## 配置

配置文件：`config.json`

```json
{
  "smee_url": "https://smee.io/YOUR_UNIQUE_CHANNEL",
  "port": 3000,
  "log_level": "INFO",
  "review_on_open": true,
  "review_on_sync": true,
  "skip_drafts": true,
  "max_pr_age_hours": 24
}
```

**配置项说明：**

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `smee_url` | smee.io 提供的唯一 URL | 必填 |
| `port` | 本地 Flask 服务端口 | 3000 |
| `log_level` | 日志级别 | INFO |
| `review_on_open` | PR 创建时自动 review | true |
| `review_on_sync` | PR 更新时自动 review | true |
| `skip_drafts` | 跳过 Draft PR | true |
| `max_pr_age_hours` | 只 review 24 小时内创建的 PR（防止误触发历史 PR） | 24 |

---

## 安装与运行

### 前置依赖

1. Python 3.10+
2. Claude Code 已安装并登录
3. GitHub CLI (gh) 已安装并登录

### 安装

```bash
# 克隆或下载项目
git clone <repo>
cd pr-auto-reviewer

# 创建虚拟环境
python -m venv venv
venv\Scripts\activate

# 安装依赖
pip install -r requirements.txt
```

### 配置

1. 访问 https://smee.io 获取一个新的 channel URL
2. 复制 `config.example.json` 为 `config.json`
3. 将 smee_url 填入配置

### 启动

```bash
# 方式1：直接运行（前台）
python webhook_server.py

# 方式2：后台运行（Windows）
start /B python webhook_server.py
```

### 配置 GitHub Webhook

对于要监控的仓库，在 Settings > Webhooks 中添加：

- **Payload URL**: 你的 smee.io URL (如 `https://smee.io/abc123`)
- **Content type**: `application/json`
- **Events**: 选择 "Pull requests"
- **Active**: 勾选

**注意**：每个仓库都需要单独配置 webhook。如果想要监控所有仓库，可以考虑使用 GitHub App（需要额外配置）。

---

## 错误处理

| 错误场景 | 处理方式 |
|----------|----------|
| smee.io 连接断开 | 自动重连，指数退避 |
| Claude Code 调用失败 | 记录日志，重试 3 次 |
| gh CLI 认证过期 | 记录错误，通知用户 |
| PR 不存在或无权访问 | 跳过，记录警告 |
| 网络超时 | 重试 3 次，每次间隔 5 秒 |
| Review 结果为空 | 跳过提交评论 |

---

## 日志

日志输出到控制台和文件 `logs/webhook.log`：

```
2026-04-13 10:30:15 [INFO] 收到 webhook: pull_request.opened, repo=owner/repo, pr=#123
2026-04-13 10:30:15 [INFO] 开始 review: https://github.com/owner/repo/pull/123
2026-04-13 10:31:02 [INFO] Review 完成，提交评论
2026-04-13 10:31:03 [INFO] 评论提交成功
```

---

## 安全考虑

1. **Webhook 签名验证**（可选）：
   - 配置 GitHub webhook secret
   - 本地验证 HMAC 签名，防止伪造请求

2. **Token 安全**：
   - 复用 gh CLI 的认证，不存储 PAT
   - gh CLI 使用系统密钥管理器存储 token

3. **访问控制**：
   - Flask 服务只绑定 localhost（`127.0.0.1`）
   - 不暴露到公网

4. **日志脱敏**：
   - 不记录敏感信息
   - PR URL 等基础信息正常记录

---

## 扩展性

### 未来可扩展的功能

1. **更细粒度的控制**：
   - 按仓库配置不同的 review 规则
   - 支持 `.github/code-review-config.yml`

2. **更多触发条件**：
   - 只在特定标签的 PR 上触发
   - 只在特定分支的 PR 上触发

3. **结果通知**：
   - 发送到 Slack/飞书
   - 发送邮件通知

4. **Review 缓存**：
   - 对相同 commit 的 PR 返回缓存结果
   - 减少 API 调用和计算成本

---

## 文件结构

```
pr-auto-reviewer/
├── webhook_server.py      # 主服务
├── config.py              # 配置加载
├── github_client.py       # GitHub API 封装
├── reviewer.py            # Claude Code 调用封装
├── requirements.txt       # 依赖
├── config.example.json    # 配置示例
├── config.json            # 实际配置（gitignore）
├── logs/                  # 日志目录
│   └── webhook.log
└── README.md              # 使用说明
```

---

## 成功标准

- [ ] PR 创建后 1 分钟内自动触发 review
- [ ] Review 结果成功提交到 PR 评论
- [ ] PR 更新后自动重新 review
- [ ] 服务稳定运行 7 天无崩溃
- [ ] 支持同时监控多个仓库
