# Programme change-read protected delivery and checklist reconciliation

Date: 2026-09-13. #105 is closed through
[PR #106](https://github.com/martonpornoi/maru/pull/106).

## Exact protected result

- Candidate: `cd38cd384990ddfacbe8982064bad7e9492b9ef9`.
- Base: `2931d6e3d2dbf2341b1103873f4f22d153d5e1fa`.
- Protected squash: `1f4ea840d25ed2571dbc78052398f1cd9c612f70`, at
  2026-09-13 15:40:08 UTC. Candidate and squash trees match exactly.
- Before merge: clean/up-to-date exact head, green protected PR gate and CodeQL,
  no review conversations with pagination exhausted.
- Clean local main fast-forwarded to the protected result and origin/main.
  Root continuation branch: `codex/programme-change-communication`. Unrelated
  worktrees, stashes and containers were preserved.

## Verification and limits

Exact-head local non-database certification passed all eight retained gates in
883.234 seconds (14m43s). All 5,294 unit tests passed in 32.60s, with two existing
Django URL-field warnings. Packaging/locked dependencies, static/types/NumPy and
semantic documentation, fresh warning-fatal Sphinx, static Django/generated API
contracts, frontend tests/types/build and dependency audits passed.

The schema-4 receipt explicitly records `postgresql_deferred`, zero databases
and null combined coverage/timing headroom. Maintained integration additions
were **not run** under ADR 0100 and remain #102 debt. Receipt, plan output, unit
report and package artifacts are archived in
`.tools/certification-evidence/issue105-cd38cd3-deferred/`. Receipt SHA-256:
`263b80eb955c14ec7ddae97bf9712f3b31347eead6ed7d73b0ff07ad67cd5b11`.
Older #103 evidence remains separate and does not certify this head.

[Hosted acceptance](https://github.com/martonpornoi/maru/actions/runs/34764899342)
passed in 26m49s: quality 26m20s, unit job 1m09s and protected PR gate 3s.
Both PostgreSQL paths were explicitly skipped.
[CodeQL](https://github.com/martonpornoi/maru/actions/runs/34764898134) and its
aggregate passed on the exact candidate. No bypass, rerun, subagent, schedule,
production data or deployment was introduced.

## Outcome and visible #48 ownership

ADR 0101 supplies dormant exact-purpose release comparisons, retained own work
lineage and sender-authorized host/work recipient references. No communication
persistence, route, UI, profile, writer grant or schema is added. #104 and #48
remain open: comparison is not governed sending or acknowledgement.

The maintainer identified missing visible checklist links despite native
#104/#105 membership. #48 now explicitly maps #104 -> #105 -> #106, reconciles
delivered #100 and lists #102's restoration gate. Native children #107 (on-site
continuity), #108 (guided journey/gated activation) and #109 (integrated rehearsal)
name existing unchecked items, not new scope. Membership and exact edited issue
body were read back; every remaining decomposition outcome has a linked issue.

Checklist completion is the maintainer's number-one priority. Document new
prerequisites beneath their owning item and defer unrelated ideas. Smaller
deliveries never close a parent alone. #108's dormant fixture enables #109/#92
acceptance before its final gated promotion, avoiding an activation cycle.

Next: finish #104's operator recipient selection, governed preparation/review,
manual handoff and immutable exact-recipient acknowledgement, then #107/#108.
#102 database restoration, #97 recovery, #92 human and #109 integrated evidence
remain mandatory before activation or a director pilot.
