---
name: release
description: Release a new version of jfox. Bumps version, generates CHANGELOG, creates PR and GitHub Release. Triggers on "发版", "release", "bump version", "发布版本".
---

# Release Skill

将 jfox 发版流程从多步手动操作简化为一条命令。覆盖版本号 bump → CHANGELOG → commit → PR → GitHub Release 全流程。

## 用法

```
/release 0.5.0          # 指定具体版本号
/release patch          # bump patch: 0.4.1 → 0.4.2
/release minor          # bump minor: 0.4.1 → 0.5.0
/release major          # bump major: 0.4.1 → 1.0.0
```

## 执行流程

严格按照以下步骤执行。每一步必须完成后再进入下一步。

### Step 1: 前置校验

运行以下检查，任何一项失败则立即停止并告知用户原因：

```bash
# 1. 当前分支必须是 main
git branch --show-current
# 期望输出: main

# 2. 工作区必须干净
git status --porcelain
# 期望输出: 空

# 3. 不存在未合并的 bump 分支
git branch --list 'chore/bump-*'
# 期望输出: 空

# 4. 没有未合并的 bump PR
gh pr list --state open --head "chore/bump-*"
# 期望输出: 空
```

### Step 2: 运行辅助脚本（预览模式）

用 `--dry-run` 先预览计算结果：

```bash
uv run python .claude/skills/release/release_helper.py <version> --dry-run
```

解析 JSON 输出，提取 `current_version`、`new_version`、`changelog_preview`、`changelog_summary`。

### Step 3: 展示变更摘要并等待确认

向用户展示：

```
📦 Release 预览:
  当前版本: {current_version}
  新版本号: {new_version}
  变更摘要: {changelog_summary}

CHANGELOG 预览:
{changelog_preview}

将修改的文件:
  - pyproject.toml
  - jfox/__init__.py
  - uv.lock
  - CHANGELOG.md
```

**必须等待用户明确确认后才继续。** 如果用户拒绝或要求修改，停止流程。

### Step 4: 运行辅助脚本（正式模式）

```bash
uv run python .claude/skills/release/release_helper.py <version>
```

确认脚本退出码为 0。如果非 0，读取错误信息并告知用户，停止流程。

### Step 5: Git 操作

```bash
# 创建分支
git checkout -b chore/bump-version-{new_version}

# 暂存文件
git add pyproject.toml jfox/__init__.py uv.lock CHANGELOG.md

# 提交
git commit -m "chore: bump version to {new_version}"

# 推送
git push -u origin chore/bump-version-{new_version}
```

### Step 6: 创建 PR

使用 CHANGELOG 内容作为 PR body：

```bash
gh pr create \
  --title "chore: bump version to {new_version}" \
  --body "$(cat <<'EOF'
## Summary
Bump version from {current_version} to {new_version}

{changelog_preview}

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)"
```

记录返回的 PR URL。

### Step 7: 等待合并

告知用户：

```
PR 已创建: {PR_URL}
请合并此 PR 后告知我，我将继续创建 GitHub Release。
```

等待用户确认 PR 已合并。

### Step 8: 切回 main 并拉取最新代码

```bash
git checkout main
git pull origin main
```

### Step 9: 创建 GitHub Release

```bash
gh release create v{new_version} \
  --title "v{new_version}" \
  --notes "$(cat <<'EOF'
{changelog_preview}
EOF
)"
```

告知用户：

```
Release v{new_version} 已创建！
GitHub Actions 将自动发布到 PyPI。
可在 https://github.com/zhuxixi/jfox/actions 监控发布状态。
```

## 错误处理

- 脚本返回非零退出码 → 读取错误 JSON，展示给用户，停止流程
- git 操作失败 → 展示错误信息，建议用户手动修复
- PR 创建失败 → 检查是否已有同名 PR，或提示权限问题
- Release 创建失败 → 检查 tag 是否已存在，或提示权限问题

## 注意事项

- **不使用 `--no-verify`**，保持 pre-commit hook 正常运行
- **始终在新分支操作**，不直接修改 main
- **每个确认点都必须等待**，不自动跳过
