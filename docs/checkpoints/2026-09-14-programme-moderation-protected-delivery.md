# Programme moderation protected delivery

Date: 2026-09-14. Parent #48, bounded #108 moderation increment.

## Exact protected result

- PR [#125](https://github.com/martonpornoi/maru/pull/125), ready and CLEAN with
  no unresolved review threads before the normal match-head squash.
- Certified head: `91af3ccfc673de6d9280671ceb224b32baaf5807`.
- Base: `95ed7b847bf942be4ffcc07438d864fdb1b53961`.
- Protected squash: `cb36b8eee6d7f4919fa3254f7fb543711c3a14ed`, merged
  2026-09-14 19:05:32 UTC.
- Certified and merged trees both `ddc6152be771224c1eb608178736507bcf73f02b`.
  Clean local main and origin/main equal the squash. Unrelated detached repair
  worktree and both stashes remain unchanged. No deleted or renamed paths.

## Verification actually performed

Clean exact-commit `scripts/certify.ps1` passed all eight retained development
gates in 1166.496 seconds (19m26s), completed 2026-09-14 18:33:40 UTC. Units:
7,050 passed in 63.60s, three existing URLField transition warnings; JUnit:
7,050 tests, zero failures/errors/skips. Frontend: 85 passing. No failed canonical
attempt or repair. Schema-4 receipt reports `postgresql_deferred`, development
checks passed, zero databases and null combined coverage/headroom; SHA-256
`0b9a351ca5a2ba88ec0cf051a239fb79e94614c6c685c237bf2d3e9e655437a4`.

Receipt, exact plan, unit report, wheel and sdist are hash-verified in the ignored
`.tools/certification-evidence/issue108-91af3cc-deferred/` archive. This is local
contributor evidence, not a signed hosted attestation.

Hosted run `34881657574` passed at the exact head without repair/rerun:

- Unit job `104102257709`: 18:35:10–18:36:42 UTC (1m32s); its completed pytest
  log records 7,050 passing in 75.26s.
- Quality `104102257653`: 18:35:11–19:04:18 (29m07s), including warning-fatal
  documentation 18:36:13–19:03:14 (27m01s) and 85 passing frontend tests.
- Aggregate PR gate `104112153096`: 19:04:21–19:04:24, success. Workflow elapsed
  18:34:48–19:04:24 (29m36s through completed gate).
- CodeQL run `34881656239`: all three language/action analyses and CodeQL
  succeeded. PostgreSQL jobs were deliberately skipped, never reported passed.

The observed 53-second quality margin is not guaranteed future headroom. Existing
[#113](https://github.com/martonpornoi/maru/issues/113#issuecomment-5669235227)
records it; no timeout or acceptance policy was loosened.

## Scope, issue management and next work

The [implementation checkpoint](2026-09-14-programme-moderation-workspace.md)
records independent discovery, field-scoped snapshot evidence, canonical stage
facts, explicit moderation/advance/reopen, safe original receipts, synthetic
browser evidence and the maintained but unexecuted native scenario. No writer,
schema, runtime privilege, profile or production route changed.

#108's moderation checkbox is now delivered, not the entire guided journey.
[#48 delivery evidence](https://github.com/martonpornoi/maru/issues/48#issuecomment-5669234886)
retains that distinction. Genuine human acceptance remains
[#92](https://github.com/martonpornoi/maru/issues/92#issuecomment-5668578752);
native execution remains
[#102](https://github.com/martonpornoi/maru/issues/102#issuecomment-5668579034).
Keep #48/#108 open through #102/#97/#109/#92 and final gated promotion.
Next bounded increment: independent final/wait-list decision and exact
recipient-message composition, followed by the remaining documented #108 work.
