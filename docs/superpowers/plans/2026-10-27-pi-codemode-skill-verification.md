# pi codemode templates — manual verification (U1–U4)

These checks cannot run in CI: they exercise the pi `codemode` runtime against a live jfox CLI.
Run them **after the PR merges**, from a session that loads the merged skill.

## Preconditions

- [ ] `jfox similarity check --help` succeeds (capability check — do not gate on `jfox --version`, which still reads 1.16.3 on main).
- [ ] `jfox daemon status` reports running. `similarity check` uses the `daemon_only` path; without the daemon every verdict is `unavailable`.
- [ ] The `codemode` tool is present in this session's tool list. If it is absent, record `blocked` — do not substitute the bash flow.
- [ ] The session loads the **merged** skill: pi resolves skills from `~/.pi/agent/settings.json` → `packages` → `../../work/git-repo/jfox` → `package.json` `pi.skills` (main checkout). A worktree session loads the old copy. After merging, `git pull` and start a new session (or `/reload`).
- [ ] Isolated library for write tests:
      `export ZK_CONFIG_PATH=/tmp/u-585/config.json ZK_KB_ROOT=/tmp/u-585/kbroot`
      Do **not** run `jfox init` — a missing config path auto-creates the `default` entry, and `init` then reports `already exists`.
- [ ] Record the real library's permanent-note count before testing; it must be unchanged afterwards.

## U1 — batch dedup query (template one)

1. Prepare ≥5 candidates (`{title, summary}`) on a topic where the library has notes.
2. Run template one unchanged.
3. Observe:

- [ ] One round trip, no per-candidate model calls.
- [ ] Returned payload has no `document` field; total size is a small fraction of the raw JSON.
- [ ] Every row has `verdict` and `top1`.
- [ ] `moc_signals` is non-empty for at least one candidate in a library that has structure notes.
- [ ] `all_keyword` is `false` when the daemon is healthy.

## U2 — `new → added` (template two)

1. Seed the isolated library with **≥30 permanent notes spanning several topics** (a loop of `jfox add` is fine). Fewer than 30 makes `baseline needs at least 30 permanent notes` the verdict, and same-topic seeding skews the percentile.
2. Run template two with one genuinely new draft.
3. Observe:

- [ ] `verdict=new` and `outcome=added`, `note_id` returned.
- [ ] `counts.added === 1`.
- [ ] No `--force` was used anywhere.
- [ ] Real library note count unchanged.

## U3 — `covered → needs_manual`

1. In the same isolated library, run template two with a draft whose title and body are near-identical to a seeded note.
2. Observe:

- [ ] `verdict=covered` (if the draft lands below p90, the seeding lacks topic diversity — adjust seeds, do not lower the bar).
- [ ] `outcome=needs_manual`, nothing written.

## U4 — `unavailable` and `duplicate`

1. Point `ZK_CONFIG_PATH`/`ZK_KB_ROOT` at a fresh directory (<30 notes) and run template two once.
   - [ ] `verdict=unavailable`, `outcome=signal_missing`, nothing written.
2. In the seeded library, run only the `jfox add` step with an existing title.
   - [ ] Returns `skipped: duplicate` with `duplicate.matched_id`.
   - [ ] The script classifies it as `duplicate`, not `error`.

## Cleanup

- [ ] `rm -rf /tmp/u-585`
- [ ] Report results in issue #585; leave U-items `pending` until actually executed.
