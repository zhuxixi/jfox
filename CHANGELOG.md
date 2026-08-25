# Changelog

All notable changes to jfox-cli will be documented in this file.

## [1.10.0] - 2026-08-25

### Features

- **skill**: jfox-moc skill + organize 密度交接 (#417) (#419)
- 引入 markdownlint 统一 Markdown 风格（#411） (#418)
- **moc**: create/update 补 --json 简写 (#425) (#429)

### Fixes

- **docs**: spec update command uses --format json, align with CLI contract (#417) (#424)
- #392 CR 低危遗留项——re-read-and-merge 修复双文件与并发丢更新 (#422)
- markdownlint 尊重 .gitignore，修复 lint job 扫描 .venv 失败（#418 后续） (#420)

### Changes

- **bm25**: 清理存量类型债——documents 注解 List[List[str]] + batch 快照 possibly-unbound 模式（#405） (#421)
- **claude.md**: 记 moc/ 模块、vector_store 只读快照读路径与 index verify 对账语义（#407/#410） (#415)

[1.10.0]: https://github.com/zhuxixi/jfox/compare/v1.9.0...v1.10.0

## [1.9.0] - 2026-08-22

### Features

- MOC create/update 命令——从诊断簇生成与维护 structure 笔记 (#413) (#414)

[1.9.0]: https://github.com/zhuxixi/jfox/compare/v1.8.0...v1.9.0

## [1.8.0] - 2026-08-22

### Features

- add MOC density diagnose command (#410)

### Fixes

- **index**: verify 以 frontmatter 真实 ID 对账向量库，修复 legacy 文件名误报 orphan (#407) (#408)

### Changes

- 项目级 .pi-lens.json 关闭自动格式化，与 CI black 对齐 (#409)
- **claude.md**: 记 BM25 并发写乐观并发控制与引擎 stale 检查语义（#391/#396） (#400)

[1.8.0]: https://github.com/zhuxixi/jfox/compare/v1.7.2...v1.8.0

## [1.7.2] - 2026-08-21

### Fixes

- **bm25**: 孤儿 tmp 无效时覆盖分支版本撞号，clear 数据复活（#403） (#404)
- **bm25**: PR #396 cc round-4 遗留修复——clear 快照化/单边态自愈/tmp 消费闭环（#401） (#402)
- **bm25**: 索引并发写乐观并发控制，根治 daemon 旧快照覆盖回滚（#391） (#396)
- **update**: 升级期间显示进度提示，stdin 指向 DEVNULL 防挂住 (#394) (#395)

### Changes

- style(bm25): collapse multi-line condition to single line (pi-lens format)
- **claude.md**: 记 delete_note backlinks 增量清理语义 (#388) (#397)
- **claude.md**: 记 CI paths 触发限制（#382） (#384)

[1.7.2]: https://github.com/zhuxixi/jfox/compare/v1.7.1...v1.7.2

## [1.7.1] - 2026-08-16

### Fixes

- **note**: delete_note 清理目标笔记 backlinks，消除悬空 id (#386) (#388)
- **note_index**: 抬高 frontmatter 行数上限并消除静默丢弃 (#380) (#382)

### Changes

- ignore pi local session config (#381)
- **skill**: session-to-permanent 模板改三层结构（#375） (#377)

[1.7.1]: https://github.com/zhuxixi/jfox/compare/v1.7.0...v1.7.1

## [1.7.0] - 2026-08-07

### Features

- **skills**: add session-to-permanent skill for CC + Kimi (#317) (#368)
- **skill**: session-to-permanent 审阅确认改用 question 选择题 (#317) (#367)
- **pi**: add jfox-session-to-permanent skill (#366)
- **skills**: align pi skills with Claude Code version (#364)
- **nightly-test**: #263 本机定时全量测试 cronjob + 失败自动提 issue (#361)

### Changes

- **claude.md**: 记 rich Console JSON soft_wrap Windows gotcha（#336） (#345)
- **claude.md**: add daemon-scheduled loop convention (backup #339) (#343)
- **claude.md**: cc-plugin Current 版本指针 0.6.0 → 0.7.0 同步 (#351)
- **claude.md**: 补 Local nightly full-test（#263/#361）CI 文档段 (#362)

[1.7.0]: https://github.com/zhuxixi/jfox/compare/v1.6.1...v1.7.0

## [1.6.1] - 2026-07-29

### Fixes

- **bookshelf**: #349 add 对齐 scan2book 扁平 bundle 契约 (#350)

[1.6.1]: https://github.com/zhuxixi/jfox/compare/v1.6.0...v1.6.1

## [1.6.0] - 2026-07-28

### Features

- **release**: #334 /release-all 统一发版编排 + #333 CHANGELOG verify (#344)
- **bookshelf**: 好书资产管理子命令 (PDF + scan2book bundle + 元数据) (#325) (#336)
- **backup**: #338 KB 滚动备份 + 恢复（daemon 调度，#263 前置） (#339)
- **gem-synth**: dedup 命中 candidate 时增量合并补入（#309） (#335)

### Changes

- **promote**: 按 clear-reports 重写 promote/jfox-promote SKILL.md 散文层（#341） (#342)
- **claude.md**: cc-plugin 版本 0.5.1 → 0.6.0 (#337)

[1.6.0]: https://github.com/zhuxixi/jfox/compare/v1.5.0...v1.6.0

## [1.5.0] - 2026-07-25

### Features

- **promote-skill**: #319 三模式过审重写（cc+kimi） (#324)
- **release-cc-plugin**: 新增 cc-plugin 发版 skill (#316)
- **cli**: jfox show 支持 --json 输出 (#278) (#315)

### Fixes

- **gem-synth**: candidate 双 H1 标题，strip content 开头冗余 H1 (#320)

### Changes

- **gem-synth**: dedup 生命周期解耦——消除核心层反向依赖 (#310) (#322)
- **claude.md**: 补 auto_summary 模块、gem_synth dedup，修正 cc-plugin 版本 (#323)
- **claude.md**: 补 note 生命周期事件 + numpy lazy-import gotcha (#322) (#326)

[1.5.0]: https://github.com/zhuxixi/jfox/compare/v1.4.0...v1.5.0

## [1.4.0] - 2026-07-12

### Features

- **session-summary**: 去掉两步确认，生成后直接写入 session 类型 (#312)
- **gem-synth**: 合成去重 dedup（存盘前正文余弦查重） (#308)
- **kimi-plugin**: 补齐 skill 覆盖缺口——模板、自动总结、归档、check、config、gem-synth/fragments (#306)
- **kimi-plugin**: 添加 jfox-promote skill 支持 candidate 过审晋升 (#305)

### Changes

- **show**: 设计 spec for show --json (#278)

[1.4.0]: https://github.com/zhuxixi/jfox/compare/v1.3.1...v1.4.0

## [1.3.1] - 2026-07-12

### Features

- **auto-summary**: add schedule time window (closes #298) (#301)

### Fixes

- **gem-synth**: 隔离 claude -p cwd，避免 auto-summary 总结 gem-synth 内部 session (#303)

[1.3.1]: https://github.com/zhuxixi/jfox/compare/v1.3.0...v1.3.1

## [1.3.0] - 2026-07-10

### Features

- **gem-synth**: L5 候选晋升层（candidate → permanent） (#296)
- **kimi-plugin**: 为 health check 与 orphan 链接推荐引入 AgentSwarm 并行执行 (#300)

### Fixes

- **fragment**: skip internal auto-summary/gem-synth sessions to break feedback loop (#297) (#299)
- **search**: BM25 索引支持 note_type，修复 hybrid/keyword 模式 --type 过滤失效 (#285) (#292)

[1.3.0]: https://github.com/zhuxixi/jfox/compare/v1.2.3...v1.3.0

## [1.2.3] - 2026-07-07

### Fixes

- **gem-synth**: find_anchors 在 SQL 层排除已处理，修循环空转（#290） (#291)

[1.2.3]: https://github.com/zhuxixi/jfox/compare/v1.2.2...v1.2.3

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
