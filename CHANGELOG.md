# Changelog

All notable changes to jfox-cli will be documented in this file.

## [1.2.2] - 2026-06-28

### Fixes
- **gem-synth**: 剥 claude markdown 代码围栏，修合成全失败 (#283) (#288)
- **add**: 创建目标笔记后回填引用方的正向 links (#276)

[1.2.2]: https://github.com/zhuxixi/jfox/compare/v1.2.1...v1.2.2

## [1.2.1] - 2026-06-26

### Features
- **gem-synth**: time-budget throttle + synthesis ledger + status (#283) (#284)

[1.2.1]: https://github.com/zhuxixi/jfox/compare/v1.2.0...v1.2.1

## [1.2.0] - 2026-06-24

### Features
- L3 宝石合成（碎裂→破损 candidate 笔记，#249 Layer 3） (#274)

### Fixes
- **cc-plugin**: remove redundant hooks field from plugin.json (#280)

### Changes
- fix stale cc-plugin versioning note (3 places, current 0.4.0) (#281)

[1.2.0]: https://github.com/zhuxixi/jfox/compare/v1.1.1...v1.2.0

## [1.1.1] - 2026-06-21

### Features
- Claude Code Hook 碎片采集（#261 Phase 1） (#269)

### Fixes
- **update**: 已是最新版本时显示正确提示 (#268)

### Changes
- gitignore .claude/settings.local.json and untrack it (#266)

[1.1.1]: https://github.com/zhuxixi/jfox/compare/v1.1.0...v1.1.1

## [1.1.0] - 2026-06-21

### Features
- **cli**: add self-update command (#258)
- 笔记归档/软删除功能（archive/unarchive） (#260)

### Fixes
- **cli**: jfox index rebuild --backlinks recalculates wiki links and backlinks

[1.1.0]: https://github.com/zhuxixi/jfox/compare/v1.0.0...v1.1.0

## [1.0.0] - 2026-06-18

### Features
- **auto-summary**: support Kimi Code session + 5-section summary notes (#248)
- **cli**: jfox list 增加 Out/In backlinks 计数列 (#253) (#254)
- **cc-plugin**: add using-jfox overview/routing skill (#243) (#251)
- add Kimi Code plugin packages/kimi-plugin (#239)

### Changes
- add GitHub PR and issue templates (#241)

[1.0.0]: https://github.com/zhuxixi/jfox/compare/v0.10.0...v1.0.0

## [Unreleased]

### Features
- auto-summary 支持 Kimi Code session（`~/.kimi-code/sessions/`），与 Claude Code 共存；新增 `session_sources`/`kimi_sessions_dir` 配置（默认 claude+kimi 都启用，auto-detect 目录）。(#242)
- 总结笔记升级为五段结构（背景/做了什么/关键决策/技术细节/未决事项），更具上下文感。(#242)

### Changes
- auto-summary ledger 去重 key 加来源前缀（`claude:`/`kimi:`），旧数据自动迁移。

## [0.10.0] - 2026-06-06

### Features
- **auto-summary**: progress visibility + remove 7-day scan limit (#235)
- **daemon**: interactive auto-summary prompt on daemon start (#233)
- add pi skills and package.json for pi-package support
- **daemon**: add restart command

### Fixes
- Issue #224 CR leftovers — atomic write + CAS + interruptible Popen + threading.Event (#236)

### Changes
- **README**: add auto-summary section with implementation details
- ignore pr-monitor state and tmp issue body files
- add superpowers plans and spec for recent work

[0.10.0]: https://github.com/zhuxixi/jfox/compare/v0.9.0...v0.10.0

## [0.9.0] - 2026-05-22

### Features
- replace hf-mirror.com with ModelScope for model download
- auto-summary daemon for Claude Code sessions

### Fixes
- Last Used 始终显示 Never，日常操作未更新 last_used (#222)
- **plugin**: remove commands field, let Claude Code auto-discover (#214)
- **plugin**: correct commands paths in plugin.json (#213)

### Changes
- ignore pr-monitor state and tmp issue body files
- add superpowers plans and spec for recent work
- document Claude Code plugin structure in CLAUDE.md (#220)
- **plugin**: rename kb skill to manage and dedup CRUD docs (#218)
- **plugin**: restructure plugin source for marketplace best practices (#217)
- add Claude Code plugin guide and design docs (#215)

[0.9.0]: https://github.com/zhuxixi/jfox/compare/v0.8.0...v0.9.0

## [0.8.0] - 2026-05-10

### Features
- add Claude Code plugin packaging for jfox skills (#209) (#210)
- 新增 session 笔记类型，专存 AI Agent 会话记录 (#202)

### Changes
- sync AGENTS.md with CLAUDE.md and current codebase (#208)

[0.8.0]: https://github.com/zhuxixi/jfox/compare/v0.7.2...v0.8.0

## [0.7.2] - 2026-05-07

### Fixes
- **note**: atomic write to prevent 0-byte note files (#201)
- strip frontmatter from --content-file input to prevent duplication (#200)

### Changes
- update CLAUDE.md to reflect current codebase state (#203)

[0.7.2]: https://github.com/zhuxixi/jfox/compare/v0.7.1...v0.7.2

## [0.7.1] - 2026-05-05

### Fixes
- dynamically detect model weight file format

[0.7.1]: https://github.com/zhuxixi/jfox/compare/v0.7.0...v0.7.1

## [0.7.0] - 2026-05-05

### Features
- **skills**: add CI monitoring with auto-polling to /ci command
- **skills**: add /ci command to trigger GitHub Actions workflows
- **cli**: add jfox check command for detecting corrupt files (#189)
- **note**: list_notes 扫描结束时汇总无效文件提示 (#188)

### Fixes
- **note**: downgrade parse failure log to warning in load_note (#187)

### Changes
- add design specs and implementation plans for recent features
- list_notes() 元数据索引，减少全量加载 (#190)
- add implementation plan for list_notes metadata index (#190)
- add spec for list_notes() metadata index (#190)
- add spec for jfox check command (#189)
- add spec for list_notes skip summary (#188)
- **spec**: add design for load_note log level fix (#186)

[0.7.0]: https://github.com/zhuxixi/jfox/compare/v0.6.0...v0.7.0

## [0.5.0] - 2026-04-29

### Features
- 支持通过标签召回笔记 (#170) (#177)
- **cli**: show tags column in list table output
- **note**: add tags parameter to list_notes() and search_notes()
- **vector_store**: add tags parameter to search() for ChromaDB filtering

### Fixes
- **test**: resolve CI test-full failures (#175)

### Changes
- add superpowers plans and specs docs, update .gitignore (#178)
- add tag filtering implementation plan for #170
- add tag filtering design spec for #170

[0.5.0]: https://github.com/zhuxixi/jfox/compare/v0.4.3...v0.5.0

## [0.4.3] - 2026-04-28

### Features
- 内网模型自动下载（3步降级重试链） (#173)

### Fixes
- **daemon**: eliminate deprecation warnings in daemon log (#171)

[0.4.3]: https://github.com/zhuxixi/jfox/compare/v0.4.2...v0.4.3

## [0.4.2] - 2026-04-22

### Features
- add Kimi CLI skill collection (#166)
- **skills**: add release skill with full workflow instructions
- **skills**: add release helper script with version bump and CHANGELOG generation

### Fixes
- **lint**: remove unused pytest import
- **skills**: improve git Chinese encoding and fix pluralization in release helper
- **skills**: address code review issues in release helper
- **cli**: list 命令 table 输出显示完整 18 位笔记 ID

### Changes
- style(lint): format test_release_helper.py with black
- Merge pull request #167 from zhuxixi/feat/kimi-cli-skills
- Merge pull request #165 from zhuxixi/fix-list-id-truncation

[0.4.2]: https://github.com/zhuxixi/jfox/compare/v0.4.1...v0.4.2

## [0.2.0] - 2026-04-13

### Features
- **edit**: add `--content-file` parameter for reading note content from a file (#106)

### Fixes
- **skill**: add `--kb` parameter support to jfox-health skill
- **cli**: add `use` as alias for `kb switch` subcommand (#105)

### Changes
- **skills**: redesign from 5 skills to 4
- **test**: fix flaky `test_update_content_preserves_id_and_created` (timing race on fast machines)

### Performance
- **startup**: lazy import optimization to eliminate startup overhead for lightweight commands (#122)
- **ci**: optimize CI coverage job to avoid rerunning tests (#119)

## [0.1.5] - 2026-04-12

### Fixes
- **index**: add `--kb` parameter to `jfox index` command (#104) (#113)
- **index**: fix `index verify` false positives (filename vs index ID format mismatch) (#111)
- **index**: fix `index rebuild` clearing ChromaDB before re-indexing (#110)
- **test**: prevent test KB residue in global config (#101)
- **ci**: resolve Windows path comparison bug and add quality gate

### Changes
- **style**: auto-fix all ruff/black lint errors (1869 fixed)

[0.2.0]: https://github.com/zhuxixi/jfox/compare/v0.1.5...v0.2.0
[0.1.5]: https://github.com/zhuxixi/jfox/compare/v0.1.4...v0.1.5
