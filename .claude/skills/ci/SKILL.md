---
name: ci
description: Trigger GitHub Actions CI workflows. Supports fast, full, and core test types. Triggers on "跑测试", "trigger ci", "full test", "跑一下ci".
---

# CI Skill

通过 `gh` CLI 触发 GitHub Actions workflow，支持快速测试、全量测试和核心测试。

## 用法

```
/ci              # 默认触发 fast 测试
/ci fast         # 快速测试（跳过 embedding）
/ci full         # 全量测试（所有 OS + Python 版本）
/ci core         # 核心测试（含 embedding，main 分支专用）
```

## 执行步骤

### Step 1: 解析参数

从用户输入中提取测试类型，默认为 `fast`。合法值：`fast`、`full`、`core`。

### Step 2: 触发 workflow

```bash
gh workflow run integration-test.yml \
  -f test_type=<type>
```

### Step 3: 获取 run ID 并展示链接

```bash
# 等待几秒让 GitHub 创建 run
sleep 5

# 获取最新的 run
gh run list --workflow=integration-test.yml --limit 1 --json databaseId,status,htmlUrl
```

向用户展示：

```
已触发 <type> 测试: <run_url>
可用 gh run watch <run_id> 监控进度。
```

### Step 4: 询问是否 watch

使用 AskUserQuestion 询问用户是否要等待结果：

- 选项：
  - `watch` — 执行 `gh run watch <run_id>` 实时显示进度
  - `不用了` — 结束，用户自行查看

## 错误处理

- workflow 不存在 → 提示检查 `.github/workflows/integration-test.yml`
- `gh` 未认证 → 提示运行 `gh auth login`
- 触发失败 → 展示错误信息
