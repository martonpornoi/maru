# Protected delivery of dormant Programme file custody

Date: 2026-09-16. PR [#147](https://github.com/martonpornoi/maru/pull/147),
one prerequisite beneath #108 / #48; neither parent is complete.

## Exact evidence

- Certified head: `410ff2a3e960cee71aad38122b59d638b56ab386`.
- Base: `4faef0f75979e61427f829ee4342cd24ad1593c3`.
- Protected squash: `9324dade5ca25b69f084fa55c242716642164b26`,
  merged at 2026-09-16 07:32:08 UTC.
- Both trees: `ab3be91a3b575da67440f8fda10bf36f41e3ecec`.
- All eight retained local certification gates passed in **357.431 seconds**;
  8,681 unit tests passed in **53.86 seconds**.
- Schema-4 receipt result: `postgresql_deferred`; zero database instances,
  null combined coverage and timing headroom. Receipt SHA-256:
  `49e88a111ba442c44394bb001fdcf6e94fa5294a5a93f0092950ebe24b327fb9`.
- Receipt, plan, unit JUnit and both package artifacts were copied and
  hash-verified outside the disposable certification directory.
- Hosted run `35068030342`: 8,681 units in **104.26 seconds** (2m38s job);
  quality **9m53s**; exact-head `PR gate` and CodeQL passed. No pending review
  or unresolved thread existed at merge. Normal match-head squash, no bypass.
- Local main was fast-forwarded to protected origin/main and verified clean;
  unrelated worktrees and historical feature branches were preserved.

## Scope and continuation

The [schema checkpoint](2026-09-16-programme-file-custody-schema.md) records
ADR 0105, exact-purpose immutable metadata/bytes, first-answer evidence, quotas,
readiness and downgrade fencing. The explicit disposable schema-only approval
yielded real fingerprints and empty reverse/reapply in a 150.437-second initial
observation, followed by task-owned container cleanup. It did not run a native
test, scanner, upload, download, runtime workflow or logical recovery scenario.

Only the supporting schema prerequisite was marked complete in #108; #48 received
the protected evidence. #102 records 28 maintained but unexecuted native cases and
remaining quota/race/runtime/recovery proof. No native timing or full coverage is
claimed. No current profile or public route was activated.

Next implement the owning authorized upload-and-use/retry command, independent
private byte read boundary and exact-answer selection/download surfaces. Keep
anonymous omission before identifying lookup, original retry/source intent, one
canonical answer cursor and all-or-nothing custody. Complete accountable setup,
isolated fixture and #109/#102/#97/#92 acceptance remain open.
