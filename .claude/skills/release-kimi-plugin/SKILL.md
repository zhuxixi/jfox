---
name: release-kimi-plugin
description: Release a new version of the kimi-plugin (Kimi Code 集成). Bumps the single version field in kimi.plugin.json, opens a PR. Triggers on "发 kimi-plugin", "release kimi plugin", "bump kimi version", "发布 kimi 插件".
---

# Release kimi-plugin Skill

把 kimi-plugin 发版流程固化：单一版本号 bump → PR 合 main。**不打 tag、不发 Release、不发 PyPI**
（合 main 后用户拉新即生效）。

⚠️ 这是 **kimi-plugin** 发版（0.14.x）。CLI/PyPI 发版（1.x.x）用 `/release`；cc-plugin 用 `/release-cc-plugin`。
要三件套一起发，用 `/release-all`（自动跳过无改动者）。

## 用法

```
/release-kimi-plugin patch    # 0.14.0 → 0.14.1
/release-kimi-plugin minor    # 0.14.0 → 0.15.0
/release-kimi-plugin major    # 0.14.0 → 1.0.0
/release-kimi-plugin 0.15.0   # 指定版本
```

默认建议 patch（无新 skill → semver patch）。

## 执行流程

严格按步，每步完成才进下一步。

### Step 1: 前置校验

任一不符即停并告知原因。

```bash
git branch --show-current                                  # 期望 main
git status --porcelain                                     # 期望 空
git branch --list 'chore/bump-kimi-plugin-*'               # 期望 空
gh pr list --state open --head "chore/bump-kimi-plugin-*"  # 期望 空
```

### Step 2: dry-run 预览

```bash
uv run python .claude/skills/release-kimi-plugin/release_kimi_plugin_helper.py <version> --dry-run
```

解析 JSON：`current_version` / `new_version` / `files_to_change` / `changelog_summary`。

### Step 3: 展示并等确认

向用户展示：

```
📦 kimi-plugin Release 预览:
  当前版本: {current_version}
  新版本号: {new_version}
  changelog:
  {changelog_summary 逐行}

将修改（单一字段，由 helper 原子 bump）:
  - packages/kimi-plugin/kimi.plugin.json
```

**必须等用户明确确认。** 拒绝或要改则停。

### Step 4: 正式 bump

```bash
uv run python .claude/skills/release-kimi-plugin/release_kimi_plugin_helper.py <version>
```

退出码非 0 → 读 error JSON，告知用户，停。

### Step 5: 分支 / commit / push

```bash
git checkout -b chore/bump-kimi-plugin-{new_version}
git add packages/kimi-plugin/kimi.plugin.json
git commit -m "chore(kimi-plugin): bump version {current_version} → {new_version}"
git push -u origin chore/bump-kimi-plugin-{new_version}
```

### Step 6: 开 PR

```bash
gh pr create --title "chore(kimi-plugin): bump version {current_version} → {new_version}" --body "<changelog>"
```

PR body 用 `changelog_summary` 作 release notes，并注明「合 main 即生效，无需 tag/Release」。

### Step 7: 告知用户合并

```
PR 已创建: {URL}
合并即生效（用户拉新）。不打 tag、不发 Release。
```

等用户手动合并。**不自动创建 tag / GitHub Release。**

## 注意

- 单一 version 字段由 helper 原子 bump（命中数 ≠ 1 报错不写）。
- 三轨道之一；与 `/release`（CLI/PyPI）、`/release-cc-plugin`（cc marketplace）并列。
- 合 main 即发布；如需追溯可手动 `gh release create kimi-plugin-v<x>`，但非默认。
