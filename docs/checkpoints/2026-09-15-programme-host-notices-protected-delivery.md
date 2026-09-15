# Guided Programme host notices: protected delivery

Date: 2026-09-15. PR [#134](https://github.com/martonpornoi/maru/pull/134),
partial delivery of #108 within #48.

## Exact identity and acceptance

- Base: `13a51848c78330b636cf35d9f65e3916eb2a136a`.
- Certified/submitted head: `e8c3b627b6e6ca00e6245a82204ce64ff1dcfa52`.
- Protected squash: `bdb0fe356285580663c936c3a18b666e499403d9`, merged
  2026-09-15 08:07:16 UTC by ordinary match-head squash.
- Both heads share tree `f021ffe20fbc26189b2c2e94f879fa9f50071eb0`.
- Exact-head PR gate/CodeQL passed; fresh CLEAN mergeability and complete empty
  review-thread inventory were verified. No bypass, rerun or acceptance exception.
- Clean local main and origin/main were synchronized to the protected squash;
  unrelated detached worktree and existing stashes were preserved.

Fresh local certification passed all eight retained gates in **1,090.222 seconds
(18m10s)**; 7,661 units passed in 45.77s with three existing URLField warnings.
The schema-4 receipt completed at 07:35:01.711933 UTC and honestly reports
`postgresql_deferred`, zero database instances and null combined coverage/headroom.
Its SHA-256 is
`9fb4776ddf67b248c6d79f99b2c26ba8327c5f236be9eb377fe95b66a137b47e`.
Receipt, plan, JUnit and both packages were archived outside `.local-ci/` with
source/copy hash equality. JUnit has 7,661 cases, zero errors/failures/skips and
45.652 seconds. No earlier head's receipt was reused.

Hosted workflow [34942575928](https://github.com/martonpornoi/maru/actions/runs/34942575928)
passed at that exact head:

- Units: **84.51s**, job 1m42s; 7,661 passed, three existing warnings.
- Frontend: **93 passed**, seven files, verified from completed job output.
- Quality: **28m40s**, 07:36:58–08:05:38 UTC.
- Documentation: **26m43s**, 07:37:55–08:04:38 UTC.
- Workflow latency: **29m10s**, 07:36:37–08:05:47 UTC.
- PR gate: five seconds; CodeQL workflow 34942572476 and aggregate passed.

The observed quality margin was only 1m20s against the unchanged 30-minute limit.
This is an observation, not a guaranteed budget. #113 records the risk without
displacing currently unblocked #48 work.

## Outcome and remaining work

The [implementation checkpoint](2026-09-15-programme-host-notice-selection.md)
records current labelled occurrence/confirmed-host selection, exact existing
preview/commands, independently admitted workflow links and final rendered source
checks. Synthetic browser evidence is bounded and uses substituted owner data and
policy with SQL forbidden; no real-owner or full human acceptance is claimed.

#108 marks only this host-notice increment complete. Work/operator selections,
continuity, reference/file controls, setup and integrated final gates remain open.
Source-choice overflow still fails closed but shares generic notice-inventory
guidance; its source-specific wording is explicitly queued with the next shared
selector extension. No bound will be weakened or partial list presented as complete.

#102 comment 5676359297 records the extended but uncollected/unexecuted native host
scenario and remaining real-owner proof. #92 comment 5676359507 records human
acceptance. #48 comment 5676922174 and #113 comment 5676922490 record delivery and
timings. Parent issues #108 and #48 were verified OPEN after bookkeeping.
No schema, profile, runtime privilege, CI policy or production activation changed.

Continue with `codex/programme-work-notices` from this squash, single-agent, through
the same exact protected flow. ADR 0100 and #102/#97/#109/#92 gates remain mandatory.
