# Workforce-only rehearsal technical delivery

## Protected result

[PR #237](https://github.com/martonpornoi/maru/pull/237) squash-merged on
3 November 2026 at 07:35:16 UTC as
`8c6ccd52fa46b1cc2b4f225512b5b0dadcd095a5`. Its sole parent is
`92f59d227e2bdd247c404f7131cd0e58651504a9` and its tree
`9a8f71dcfe3f96902b4411cd30ff56b598bf98b1` matches certified head
`88b76203496a419e1945b71199f03efbcae67af6`. The designated clean
main was fetched and fast-forwarded. Local, origin, remote and GitHub API
refs agreed.

The [rehearsal guide](../operations/workforce-only-rehearsal.md) covers
twenty steps across four separate role sessions. The protected change also
delivers a restricted synthetic launcher, a minimized baseline and final
inspector, and the [historical migration test isolation repair](2026-11-02-workforce-rehearsal-migration-isolation.md).
Production source is identical to the protected parent.

## Verification

Local and hosted all-history acceptance agreed on 392 groups, 111 PostgreSQL
shards, 5,394 native cases, 16,182 passing test phases and 128 frontend cases.
Windows passed 14,972 units with one expected POSIX skip. Hosted Linux passed
all 14,973 units. Each unit run reported eleven warnings. Hosted native shards
44 and 93 reported three warnings in total.

The local combined SQLite original reconstructed 91.353558% branch-aware
coverage. The 112 original hosted coverage parts independently reconstructed
91.348679% and matched every original XML file, line and branch condition.
The unchanged threshold is 90%. Hosted jobs and native execution reached a
peak of eight. Runner Docker command and response timestamps bound allocation
and running peaks at eight, and all 111 container and network removals were
confirmed. The longest hosted job took 3,069 seconds with cleanup. Its
conservative projection was 5,204.5 seconds against the 5,400-second ceiling.

All 114 [hosted artifacts](https://github.com/martonpornoi/maru/actions/runs/41554743666)
and the original workflow log were preserved. The synthetic merge tested by
GitHub had the exact certified tree and expected parents. The live PR gate,
all three independently verified [CodeQL analyses](https://github.com/martonpornoi/maru/actions/runs/41554738928),
and current branch protection, review and thread checks passed before merge.
The audit reported one moderate Node advisory without an identifier. Python
reported no known vulnerabilities in audited dependencies and skipped the
local Maru package because it was unavailable on PyPI.

## Remaining acceptance

[#42](https://github.com/martonpornoi/maru/issues/42) remains open for the full
four-role browser journey and final lifecycle absence proof. Browser input
stopped at the current-URL safety control. The existing trial and manual
fixtures were preserved. Real browser zoom, representative assistive
technology, independent human decisions, recovery and operational acceptance
remain separate from this technical delivery.
