---
name: release-cc-plugin
description: Release a new version of the cc-plugin (Claude Code marketplace). Bumps the three version fields in lockstep, opens a PR. Triggers on "发 cc-plugin", "plugin 发版", "release cc plugin", "bump plugin version", "发布 cc 插件".
---

# Release cc-plugin Skill

把 cc-plugin 发版流程固化：三处版本号同步 bump → PR 合 main。**不打 tag、不发 PyPI**
（`.claude-plugin/marketplace.json` 的 `source` 指向仓库内 `./packages/cc-plugin`，合 main 后用户 `/plugin update` 自动拉新）。

⚠️ 这是 **cc-plugin** 发版（marketplace，0.5.x）。CLI/PyPI 发版（1.x.x）用 `/release`。
kimi-plugin 是另一条轨道，本 skill 不管。

## 用法

```
/release-cc-plugin patch     # bump patch: 0.5.1 → 0.5.2
/release-cc-plugin minor     # bump minor: 0.5.1 → 0.6.0
/release-cc-plugin major     # bump major: 0.5.1 → 1.0.0
/release-cc-plugin 0.7.0     # 指定版本
```

默认建议 patch（无新 skill/command → semver patch）。

## 执行流程

严格按步，每步完成才进下一步。

### Step 1: 前置校验

任一不符即停并告知原因。

```bash
git branch --show-current                                # 期望 main
git status --porcelain                                   # 期望 空
git branch --list 'chore/bump-cc-plugin-*'               # 期望 空
gh pr list --state open --head "chore/bump-cc-plugin-*"  # 期望 空
```

### Step 2: dry-run 预览

```bash
uv run python .claude/skills/release-cc-plugin/release_cc_plugin_helper.py <version> --dry-run
```

解析 JSON：`current_version` / `new_version` / `files_to_change` / `changelog_summary`。

### Step 3: 展示并等确认

向用户展示：

```
📦 cc-plugin Release 预览:
  当前版本: {current_version}
  新版本号: {new_version}
  changelog:
  {changelog_summary 逐行}

将修改（三处同步，由 helper 原子 bump）:
  - packages/cc-plugin/.claude-plugin/plugin.json
  - .claude-plugin/marketplace.json（metadata.version + plugins[0].version）
```

**必须等用户明确确认。** 拒绝或要改则停。

### Step 4: 正式 bump

```bash
uv run python .claude/skills/release-cc-plugin/release_cc_plugin_helper.py <version>
```

退出码非 0 → 读 error JSON，告知用户，停。

### Step 5: 分支 / commit / push

```bash
git checkout -b chore/bump-cc-plugin-{new_version}
git add packages/cc-plugin/.claude-plugin/plugin.json .claude-plugin/marketplace.json
git commit -m "chore(cc-plugin): bump version {current_version} → {new_version}"
git push -u origin chore/bump-cc-plugin-{new_version}
```

### Step 6: 开 PR

```bash
gh pr create --title "chore(cc-plugin): bump version {current_version} → {new_version}" --body "<changelog>"
```

PR body 用 `changelog_summary` 作 release notes，并注明「合 main 后 `/plugin update` 自动拉新，无需 tag/PyPI」。

### Step 7: 告知用户合并

```
PR 已创建: {URL}
合并即生效（用户 /plugin update 拉新）。不打 tag、不发 Release。
```

等用户手动合并。**不自动创建 tag / GitHub Release。**

## 注意

- 三处版本号由 helper 原子 bump（命中数不符报错不写），堵 CLAUDE.md 点名的「漏改任一处」坑。
- 不要用 `/release`（那是 CLI/PyPI）。
- 合 main 即发布；如需追溯可手动 `gh release create cc-plugin-v<x>`，但非默认。
