---
name: jfox-ci
description: |
  Trigger GitHub Actions CI workflows for the jfox project.
  Supports fast, full, and core test types.
  Triggers on: "跑测试", "trigger ci", "full test", "跑一下ci", "运行测试",
  "run tests", "ci check", "github actions".
---

# CI Skill

通过 `gh` CLI 触发 GitHub Actions workflow，支持快速测试、全量测试和核心测试。

## 用法

```
/skill:jfox-ci              # 默认触发 fast 测试
/skill:jfox-ci fast         # 快速测试（跳过 embedding）
/skill:jfox-ci full         # 全量测试（所有 OS + Python 版本）
/skill:jfox-ci core         # 核心测试（含 embedding，main 分支专用）
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

轮询检查 CI 状态并汇报结果。

轮询间隔根据测试类型确定：

| 测试类型 | 预计耗时 | 轮询间隔 | 最大轮次 |
|---------|---------|---------|---------|
| full    | ~60 min | 10 min  | 8 次    |
| fast    | ~30 min | 10 min  | 5 次    |
| core    | ~30 min | 10 min  | 5 次    |

每轮执行（轮询检查 CI 状态并汇报结果；pi 无 CronCreate，由 agent 定期重跑或用 subagent scheduled run 驱动）：

### Step A: 检查 run 状态

```bash
gh run view <run_id> --json status,conclusion,jobs --jq '{status,conclusion}'
```

- status: "completed" → 检查 conclusion
- status: "in_progress" / "queued" / "waiting" → 仍在跑，继续轮询

### Step B: 逐 job 状态报告

```bash
gh run view <run_id> --json jobs --jq '.jobs[] | {name, status, conclusion}'
```

逐个 job 报告状态：

- conclusion: "success" → ✅
- conclusion: "failure" → ❌
- status: "in_progress" / "queued" → ⏳

### Step C: 决策

**全部 job 完成时**：

- 全绿 → 报告 "CI 全绿 ✅"，告知用户，结束轮询
- 有失败 → 报告 "CI 失败 ❌" 列出失败 job，建议查看日志：`gh run view <run_id> --log-failed`，结束轮询

**仍在跑时**：

- 轮次计数 +1
- 若超过该测试类型的最大轮次 → 报告超时，建议手动检查，结束轮询
- 否则报告当前进度，继续轮询

向用户展示：

```
已触发 <type> 测试: <run_url>
预计耗时 ~<duration> 分钟，每 10 分钟检查一次进度。
```

## 错误处理

- workflow 不存在 → 提示检查 `.github/workflows/integration-test.yml`
- `gh` 未认证 → 提示运行 `gh auth login`
- 触发失败 → 展示错误信息
