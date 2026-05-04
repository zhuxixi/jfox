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

### Step 4: 监听结果

使用 CronCreate 创建定时轮询任务，自动检查 CI 状态并汇报结果。

轮询间隔根据测试类型确定：

| 测试类型 | 预计耗时 | 轮询间隔 | 最大轮次 |
|---------|---------|---------|---------|
| full    | ~60 min | 10 min  | 8 次    |
| fast    | ~30 min | 10 min  | 5 次    |
| core    | ~30 min | 10 min  | 5 次    |

创建 CronCreate 定时任务（非 durable）：

```
cron: "*/10 * * * *"
recurring: true
prompt: |
  CI Monitor tick for run <run_id> (<type> test):

  ## Step A: Check run status

  Run: `gh run view <run_id> --json status,conclusion,jobs --jq '{status,conclusion}'`

  - status: "completed" → check conclusion
  - status: "in_progress" / "queued" / "waiting" → still running, continue

  ## Step B: Report per-job status

  Run: `gh run view <run_id> --json jobs --jq '.jobs[] | {name, status, conclusion}'`

  Report each job's status:
  - conclusion: "success" → ✅
  - conclusion: "failure" → ❌
  - status: "in_progress" / "queued" → ⏳

  ## Step C: Decision

  **If all jobs completed:**
  - All success → Report "CI 全绿 ✅"，取消 cron，告知用户
  - Any failure → Report "CI 失败 ❌" 列出失败 job，取消 cron，建议查看日志：
    `gh run view <run_id> --log-failed`

  **If still running:**
  - Increment tick counter
  - If exceeded max rounds for this test type → 报告超时，取消 cron，建议手动检查
  - Otherwise report current status and continue

  ## Step D: Cancel on completion

  When all jobs are done (success or failure), use CronDelete to cancel this monitoring job.
```

向用户展示：

```
已触发 <type> 测试: <run_url>
预计耗时 ~<duration> 分钟，每 10 分钟检查一次进度。
```

## 错误处理

- workflow 不存在 → 提示检查 `.github/workflows/integration-test.yml`
- `gh` 未认证 → 提示运行 `gh auth login`
- 触发失败 → 展示错误信息
