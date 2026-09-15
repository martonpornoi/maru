# Guided operator notices: protected delivery

Date: 2026-09-15. [PR #136](https://github.com/martonpornoi/maru/pull/136),
partial delivery of #108 within #48.

## Exact identity and acceptance

- Base: `47019037f1b64cf7007bbee1c2061ad6f964f9cd`.
- Certified/submitted head: `342833311ae1f003abd045d19f14c139243b8316`.
- Protected squash: `984b4ed1a0f83923f98f5a4e1e37e66d435fa653`, merged
  2026-09-15 11:00:12 UTC using ordinary match-head squash.
- Equal certified/squash tree: `765484e1439eb8e2bea452bcfc28355843084b80`.
- Fresh exact-head PR gate/CodeQL, CLEAN mergeability and complete empty review
  threads were verified. Clean local main and origin/main were synchronized;
  unrelated worktrees and stashes were preserved. No rerun or acceptance exception.

All eight retained local gates passed in **1,134.443 seconds (18m54s)**,
including 7,774 units in 46.99s and 93 frontend cases. The schema-4 receipt
completed at 10:29:01.889529 UTC with `postgresql_deferred`, zero database
instances and null combined coverage/headroom. Receipt SHA-256:
`20acaa979a91c7a8465dd2eec788cd5224053f7b994b79741000424d0888c81d`.
Receipt, plan, JUnit and both packages were archived outside `.local-ci/`;
all five source/copy hashes matched. JUnit recorded 7,774 cases, zero
failures/errors/skips and 46.858 seconds. Existing development warnings remain
documented in the PR and do not establish native acceptance.

Hosted [workflow 34958308303](https://github.com/martonpornoi/maru/actions/runs/34958308303)
passed on the exact head:

- Units: **91.04s**, whole job 1m48s, 10:30:54–10:32:42 UTC.
- Frontend: **93 passed**, seven files, verified in the completed quality log.
- Quality: **27m56s**, 10:30:54–10:58:50 UTC.
- Documentation: **25m42s**, 10:32:05–10:57:47 UTC.
- Workflow latency: **28m27s**, 10:30:32–10:58:59 UTC.
- PR gate: three seconds. CodeQL workflow 34958303356 and aggregate passed.

No CI policy, timeout or quality standard changed. The observed **2m04s** quality
margin is not guaranteed future headroom; #113 remains open.

## Delivered and remaining

The [implementation checkpoint](2026-09-15-programme-operator-notice-selection.md)
records independent current owner labels, known-person lookup, original-person
signed selection, actual-sender positive/empty audit and final disclosure checks.
Bounded synthetic browser observations are not native-owner or human acceptance.

#108 marks only operator selection complete and separately retains notice/output/
continuity connections. Native debt is #102 comment 5678394305; human tasks are
#92 comment 5678394584. #48 comment 5679124179 and #113 comment 5679124494 record
delivery and actual timing. Both #108 and #48 were verified OPEN after bookkeeping.
No schema, runtime role, profile or production activation occurred.

Continue on `codex/programme-output-continuations` from this squash: same-person/
same-operator continuations, independently admitted fields and final rendered
source checks. References/files, accountable setup and #109/#102/#97/#92 remain
mandatory before final promotion. PostgreSQL stays uncollected/unexecuted under
ADR 0100; no schema-only exception is standing authority.
