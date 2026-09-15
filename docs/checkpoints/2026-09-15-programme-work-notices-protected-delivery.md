# Guided Programme Work notices: protected delivery

Date: 2026-09-15. PR [#135](https://github.com/martonpornoi/maru/pull/135),
partial delivery of #108 within #48.

## Exact identity and acceptance

- Base: `bdb0fe356285580663c936c3a18b666e499403d9`.
- Certified/submitted head: `ebfc53fc2fda60eb88f1d69185de8c691b469888`.
- Protected squash: `47019037f1b64cf7007bbee1c2061ad6f964f9cd`, merged
  2026-09-15 09:29:19 UTC.
- Equal certified/squash tree: `ff9cf6f90e28613a32aa58af82c260d868bd5119`.
- Fresh exact-head PR gate/CodeQL, CLEAN mergeability and complete empty review
  threads were verified. No canonical/hosted repair, rerun or acceptance exception.
- Clean local main and origin/main were synchronized to the protected squash;
  unrelated detached worktree and stashes were untouched.

Two CLI merge attempts returned GitHub gateway errors and one standard REST merge
attempt returned an incomplete response. Fresh PR/remote state checks after each
confirmed the PR still open and main unchanged. The ordinary SHA-conditional REST
squash then returned HTTP 200/merged true and was independently verified. Normal
protection remained active throughout; no bypass or direct-main push was used.

All eight retained local gates passed in **1,099.717 seconds (18m20s)**;
7,717 units in 45.85s, three existing URLField warnings. The schema-4 receipt
completed at 08:56:51.368936 UTC and honestly reports `postgresql_deferred`, zero
database instances and null combined coverage/headroom. Receipt SHA-256:
`acf5ec9baec7a5d96660576f0e5b21787f14f61c150c76faafb120bc7ee997e8`.
Receipt, plan, JUnit and both packages were archived outside `.local-ci/` with
verified source/copy hash equality. JUnit has 7,717 cases, zero errors/failures/skips
and 45.733 seconds. No earlier head's evidence was reused.

Hosted workflow [34949845128](https://github.com/martonpornoi/maru/actions/runs/34949845128)
passed at the exact head:

- Units: **85.06s**; whole job 1m48s, 08:58:07–08:59:55 UTC.
- Frontend: **93 passed**, seven files, verified in the completed quality log.
- Quality: **25m24s**, 08:58:08–09:23:32 UTC.
- Documentation: **23m22s**, 08:59:09–09:22:31 UTC.
- Workflow latency: **25m55s**, 08:57:46–09:23:41 UTC.
- PR gate: four seconds. CodeQL workflow 34949839620 and aggregate passed.

The 4m36s quality margin is an observation, not a guarantee. No CI setting changed;
the wider margin than PR #134 is not an attributable optimization. #113 remains
open without displacing unblocked #48 product work.

## Delivered and remaining

The [implementation checkpoint](2026-09-15-programme-work-notice-selection.md)
records complete bounded Work selection, separate fields, actual-sender audit,
canonical person locks, original native preview and final rendered disclosure.
Bounded synthetic browser evidence is not native-owner or full human acceptance.

#108 marks only the nested Work-selection increment complete. Operator selections,
continuity, references/files, setup and integrated gates remain incomplete. #102
comment 5677262989 records maintained but uncollected/unexecuted native debt; #92
comment 5677263260 records human tasks. #48 comment 5677935411 and #113 comment
5677935760 record delivery and timings. Both #108 and #48 were verified OPEN after
bookkeeping. No schema, runtime role, profile, CI policy or production activation.

Continue single-agent on `codex/programme-operator-notices` from this squash,
through the same exact protected flow. ADR 0100 and #102/#97/#109/#92 remain
mandatory final gates; no schema-only exception is standing authority.
