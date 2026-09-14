# Protected exact Programme case-intake delivery

PR [#122](https://github.com/martonpornoi/maru/pull/122) was protected squash-merged
at 2026-09-14 14:52:14 UTC to `91e02f4633b497b7bd00f93aeb609cb344ccfb0e`.
Its tree equals certified head `b80e9e5751f35dfb5eebf7ced40f83d706944853`.
Clean local main and origin/main were verified and fast-forward synchronized.
Unrelated stashes and the detached worktree remain untouched.

## Verification

All eight retained local gates passed in 996.584 seconds (16m37s), completed
2026-09-14 14:25:50 UTC. Exact-head units: 6,788 passed in 40.69s; frontend:
85 passed. The unit XML records zero errors, failures or skips. Three existing
URLField warnings remain. The schema-4 receipt reports `postgresql_deferred`,
development passed, zero databases and null combined coverage/headroom.

Receipt SHA-256: `b2c3d213156ddede2598470e0aed727b206b737547721abc0d51865db136b436`.
Policy SHA-256: `36354f14eabc58fa31ae7b2d7ec0e9a5e7afb8ab2c4b48bfa02a1edeff5f528d`.
Receipt, plan, unit XML and both distributions were archived outside the next
certification directory before proceeding.

Hosted [run 34855662124](https://github.com/martonpornoi/maru/actions/runs/34855662124)
passed units in 87.20s (1m50s job), quality in 22m44s, documentation in 21m07s
and the overall workflow in 23m12s. Exact-head PR gate and CodeQL passed without
hosted repair or rerun. All review conversations were resolved. The observed
7m16s quality margin is not guaranteed future headroom; #113 remains open.

The first local certification was intentionally stopped during Sphinx to remove
an invented provisional native-test timing, prohibited by ADR 0100. The complete
new native scenario now extends the existing review-services test file, with
both timing maps unchanged. No native scenario was removed or executed. Only
the corrected clean-head certification above is acceptance evidence. See the
[implementation checkpoint](2026-09-14-programme-review-case-intake.md) for
focused repairs, browser scope and recovery details.

## Continuation

#108 records exact-seal case opening as delivered, not its full review journey.
Named reviewer management, independently admitted review/moderation/decision,
accepted-item conversion and remaining guided connections/setup stay open.
One new maintained native scenario is unexecuted #102 debt; genuine human
acceptance remains #92. #109 integrated acceptance, #102 restoration/exhaustive
checks, #97 recovery and #92 evidence precede final profile promotion.
No schema, production route/profile or PostgreSQL policy was changed.
