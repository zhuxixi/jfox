# CI Coverage 优化 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 消除 coverage job 重复跑测试的浪费，将 CI 总时间从 ~35min 缩短到 ~19min，同时修复 PR coverage 评论权限问题。

**Architecture:** 让 test-fast (ubuntu) job 直接生成 coverage.xml 并作为 artifact 上传，coverage job 降级为纯解析+评论（不再跑 pytest）。仅修改 workflow YAML，不涉及任何代码变更。

**Tech Stack:** GitHub Actions (upload-artifact@v4, download-artifact@v4), pytest-cov

**Issue:** zhuxixi/jfox#112

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `.github/workflows/integration-test.yml` | Modify | 唯一需要修改的文件，所有改动集中于此 |

改动集中在两个 job：
- **test-fast** (line 64-107): 增加 coverage 生成和 artifact 上传
- **coverage** (line 243-310): 简化为下载 artifact + 解析评论

---

### Task 1: test-fast job 增加 coverage 生成和上传

**Files:**
- Modify: `.github/workflows/integration-test.yml:90-107`

这一步让 ubuntu 的 test-fast 直接生成 coverage.xml 并上传。

- [ ] **Step 1: 修改 "Run fast tests" 步骤，ubuntu 加 --cov 参数**

将 line 90-97 的 `Run fast tests (no embedding)` 步骤替换为：

```yaml
    - name: Run fast tests (no embedding)
      run: |
        # 运行非 embedding 测试（单进程避免知识库冲突）
        ARGS="-m 'not embedding and not slow' --timeout=180 -v --tb=short"
        if [ "${{ matrix.os }}" = "ubuntu-latest" ]; then
          eval uv run pytest tests/ $ARGS --cov=jfox --cov-report=xml
        else
          eval uv run pytest tests/ $ARGS
        fi
      timeout-minutes: ${{ matrix.os == 'windows-latest' && 50 || 20 }}
      env:
        PYTHONIOENCODING: utf-8
        PYTHONUTF8: 1
```

注意：使用 shell `if` 条件而非 GitHub Actions `if`，因为 step 级别 `if` 会跳过整个 step，而我们需要同一 step 内根据 matrix 条件切换参数。

- [ ] **Step 2: 在 test-fast job 中新增 coverage artifact 上传步骤**

在 "Upload test results" 步骤之后（line 107 后），新增：

```yaml
    - name: Upload coverage data
      if: matrix.os == 'ubuntu-latest'
      uses: actions/upload-artifact@v4
      with:
        name: coverage-data
        path: coverage.xml
        retention-days: 1
```

这个 step 仅在 ubuntu matrix 运行时执行（`if: matrix.os == 'ubuntu-latest'`），Windows 不会执行也不会上传。

- [ ] **Step 3: 本地验证 YAML 语法**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/integration-test.yml'))"`
Expected: 无报错（YAML 语法合法）

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/integration-test.yml
git commit -m "ci: generate coverage in test-fast ubuntu and upload artifact"
```

---

### Task 2: 简化 coverage job

**Files:**
- Modify: `.github/workflows/integration-test.yml:243-310`

删除 coverage job 中重跑测试的步骤，改为下载 artifact + 解析评论。

- [ ] **Step 1: 替换整个 coverage job**

将 line 243-310 的整个 coverage job 替换为：

```yaml
  # ============ 覆盖率报告（解析 test-fast 的 coverage artifact）============
  coverage:
    runs-on: ubuntu-latest
    needs: [test-fast]
    if: always() && needs.test-fast.result == 'success'
    permissions:
      pull-requests: write

    steps:
    - name: Checkout code
      uses: actions/checkout@v4

    - name: Download coverage data
      uses: actions/download-artifact@v4
      with:
        name: coverage-data

    - name: Post coverage comment on PR
      if: github.event_name == 'pull_request'
      env:
        GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
      run: |
        python -c "
        import xml.etree.ElementTree as ET
        import subprocess

        tree = ET.parse('coverage.xml')
        root = tree.getroot()
        rate = float(root.attrib['line-rate'])
        lines_covered = int(root.attrib['lines-covered'])
        lines_valid = int(root.attrib['lines-valid'])

        rows = []
        for cls in root.iter('class'):
            name = cls.attrib['filename']
            r = float(cls.attrib['line-rate'])
            rows.append((name, r))
        rows.sort(key=lambda x: x[1])

        comment = '## Test Coverage\n\n'
        comment += '**Overall: {:.1f}%** ({}/{} lines)\n\n'.format(rate * 100, lines_covered, lines_valid)
        comment += '| Module | Coverage | Status |\n|--------|----------|--------|\n'
        for name, r in rows:
            icon = ':green_circle:' if r >= 0.8 else ':yellow_circle:' if r >= 0.5 else ':red_circle:'
            comment += '| {} | {:.1f}% | {} |\n'.format(name, r * 100, icon)

        pr = '${{ github.event.pull_request.number }}'
        subprocess.run(['gh', 'pr', 'comment', pr, '--body', comment])
        "

    - name: Upload coverage report
      uses: actions/upload-artifact@v4
      with:
        name: coverage-report
        path: coverage.xml
```

改动要点：
1. 新增 `permissions: pull-requests: write` — 修复 PR 评论权限
2. 删除 `Set up Python`、`setup-uv`、`Install dependencies`、`Run coverage` 四个步骤 — 不再重跑测试
3. 新增 `Download coverage data` — 下载 test-fast 上传的 coverage.xml
4. 解析脚本逻辑完全不变
5. Upload 步骤只保留 coverage.xml（去掉 htmlcov/）

- [ ] **Step 2: 本地验证 YAML 语法**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/integration-test.yml'))"`
Expected: 无报错

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/integration-test.yml
git commit -m "ci: simplify coverage job to parse artifact instead of rerunning tests"
```

---

### Task 3: 创建测试 PR 并验证 CI

这一步不需要改文件，只是验证改动效果。

- [ ] **Step 1: 推送分支并创建 PR**

```bash
git push -u origin <branch-name>
gh pr create --title "perf: optimize CI coverage job to avoid rerunning tests" --body "$(cat <<'EOF'
## Summary
- 将 coverage 数据生成从独立 job 移到 test-fast (ubuntu) 中
- coverage job 降级为下载 artifact + 解析评论，不再重跑测试
- 添加 `permissions: pull-requests: write` 修复 PR coverage 评论权限

Fixes #112

## 预期效果
- CI 总时间：~35min → ~19min
- coverage job：~15min → <30s

## Test plan
- [ ] test-fast (ubuntu) 日志确认 --cov 生效且 coverage.xml 生成
- [ ] coverage job 日志确认下载 artifact 成功，无 pytest 运行
- [ ] PR 上成功发布 coverage 评论（无权限错误）
- [ ] 覆盖率百分比与改动前一致
EOF
)"
```

- [ ] **Step 2: 观察 CI 运行**

在 PR 页面确认：
1. test-fast (ubuntu) 步骤日志中有 `--cov=jfox --cov-report=xml` 参数
2. "Upload coverage data" step 成功上传 coverage-data artifact
3. coverage job 只有 3 个 step（Checkout, Download, Post comment），无 pytest 运行
4. coverage job 耗时 < 30s
5. PR 收到 coverage 评论（无 `Resource not accessible` 错误）
6. 总 CI 时间 ~19min

- [ ] **Step 3: 合入后回归验证**

合并到 main 后：
1. push 触发的 CI 正常运行
2. workflow_dispatch 手动触发时 coverage job 仍正确处理（非 PR 不评论）

---

## Self-Review Checklist

- [x] **Spec coverage:** Issue #112 三个要点（coverage 优化、权限修复、时间缩短）全部覆盖
- [x] **Placeholder scan:** 无 TBD/TODO/placeholder，所有代码和命令均完整给出
- [x] **Type consistency:** YAML 字段名和缩进一致，coverage 解析脚本完全复用原有代码
- [x] **Scope:** 仅修改 `.github/workflows/integration-test.yml`，无代码变更
