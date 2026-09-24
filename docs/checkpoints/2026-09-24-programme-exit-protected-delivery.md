# Checkpoint: Programme exit, recovery and isolation protected delivery

- Date: 2026-09-24
- Phase: Progressive adoption and pre-production release evaluation.
- Related requirements: NFR-013, EVT-007, INT-007, OPS-009, AUD-001, IDN-012,
  IDN-014, QRY-006 and UX-029.
- Related ADRs: 0081, 0098, 0106 and 0108–0114.

## Outcome and protected identity

[PR #199](https://github.com/martonpornoi/maru/pull/199) merged at
**2026-09-24T03:26:14Z** as protected squash
`be83a5764d2d6aac887615ce0d498e237e94fc27`. The exact certified feature head was
`e4b449480ab632962805bea87f3741a76f27a64d`, based on
`b056aa253a39df2648752daf35ac5a158a9950d7`. Both feature and squash trees equal
`4c470736b7502b125745ad5afa58ab1df468dd77`.

The ready PR had fresh owner destructive-change review for the isolated test
overlay rename. All 335 changed paths were checked through the paginated API
because GitHub's single-diff endpoint rejects more than 300 files. No applied
production migration was deleted. Protected rules remained active, with no
bypass actors, required exact-head PR gate, resolved conversations and unchanged
CodeQL thresholds. The authorized squash used `--match-head-commit`; clean local
main was fast-forwarded and verified equal to the squash and `origin/main`.
Other branches, stashes, checkouts and unrelated resources were preserved.

## Delivered scope

The protected merge closed #189, #190, #97, #175, #196, #197 and #198:
bounded eight-owner exit archive and custody; accountable stop-use with retained
history and shared-authority boundaries; exact active/stopped logical recovery;
independently approved Volunteer starter; genuine invitation writer cutover;
native Maru-operator lineage; and bounded current-policy observations for usable
on-site/archive output. P12 adds connected delivery-field and object-mutation
isolation without broadening production profiles, routes or permissions.

The [recovered acceptance record](2026-09-23-programme-acceptance-recovery.md)
preserves the eighteen-phase native host journey at `c063f70` (1,336.35s), separate
host checks, the failed stale schema-only expectation and all three repaired
provisioning modes (596.93s). These are additional precisely attributed evidence,
not cases silently claimed inside ordinary certification. Historical failed runs
remain preserved and are not combined into a false success receipt.

## Exact-head local and hosted verification

Full local certification at `e4b4494` passed all ten gates in **13,849.83s
(3h50m50s)**, completed 2026-09-23T22:37:07Z:

- 13,306 unit cases, 5,079 PostgreSQL cases across 71 isolated shards and
  103 frontend cases; no native failures, errors or skips.
- 91.74% combined branch-aware coverage, above the unchanged 90% requirement.
- At most eight simultaneous native databases; all 71 cleanup and measured
  timing-headroom results true. Shards took 469.719–2,982.641s; the slowest
  conservative projection was 5,073.962s, below the unchanged 5,400s threshold.
- Full receipt/artifacts preserved at
  `.tools/certification-evidence/programme-exit-e4b4494-full` and transcript at
  `.tools/programme-certification-e4b4494.log`.
- Exact plan fingerprint:
  `276c3cfad5684a439efdb8c70df822ab857b048d2182a00ac61e14389c030f3f`.

Independent [hosted acceptance](https://github.com/martonpornoi/maru/actions/runs/35929623040)
passed on the same head. It ran from 2026-09-23T22:40:23Z to the successful
PR gate at 2026-09-24T03:20:07Z: **16,784s (4h39m44s)**. All 71 PostgreSQL jobs
passed. The 72 downloaded Python reports total **18,385 cases**, zero failures,
errors or skips, and **91.74% combined coverage** (103,159 of 112,452 combined
line/branch opportunities). PostgreSQL jobs took **361–3,636s**, median **1,129s**:
6m01s–60m36s, median 18m49s, at least 59m24s below the unchanged two-hour cap.
Artifacts are preserved under `.tools/hosted-programme-pr-199`.

The initial opening workflow was superseded by the required owner-label event;
its old red gate is not a test failure in the successful authoritative run.
No hosted test rerun, timeout increase, history omission or coverage waiver was used.

## CodeQL review

[CodeQL execution](https://github.com/martonpornoi/maru/actions/runs/35929590704)
succeeded but reported two redirect alerts, which were reviewed before merge.
Alert 20 points to archive cancellation; alert 21 points to stop completion.
Both redirect destinations start with literal same-origin `/admin/programme/`
paths. Actual route definitions constrain all reported identifiers with Django
UUID converters; commands return UUID receipts/tasks. No request chooses a URL,
scheme or authority, and query overrides/unknown form inputs are refused.

Bounded diagnostics plus existing view tests passed **112 cases / 1.51s**:
exact local redirect equality, request/retry/cancel and stop destinations, eight
hostile URL payloads at all three positions for both route modules, and query/form
`next` denial before commands. An unwritable pytest cache emitted one warning;
all tests passed. `.tools/pr199-redirect-triage.xml` is diagnostic evidence, not
a replacement whole-commit certification. The tracked source remained unchanged.

The owner-account false-positive dispositions and resolved review threads retain
[archive evidence](https://github.com/martonpornoi/maru/pull/199#discussion_r4089490096)
and [stop evidence](https://github.com/martonpornoi/maru/pull/199#discussion_r4089490391).
No source suppression, security-policy change, accepted vulnerability or protected
bypass was used. GitHub reported the exact head `CLEAN` with its current PR gate
green before the match-head merge.

## Remaining acceptance and next actions

#92, #109, #108 and #48 remain open. The
[evidence map](../operations/programme-acceptance-evidence.md) separates automated
P01–P12 proof from required representative people, screen-reader/native-browser
observations and independent operational-owner acceptance. The
[participant cards](../operations/programme-human-acceptance.md) are ready, but
real participants and an approved trusted rehearsal origin have not been supplied.
The prior browser stopped before login at `ERR_CERT_AUTHORITY_INVALID`; there was
no TLS bypass or machine trust-root change. Preserve unchanged #87 evidence and
the maintainer's reduced-motion preference.

After genuine #92 acceptance and joined #109 reconciliation, implement and
separately verify #108's immutable profile/catalog, native constraints, runtime
ACL/helper, owner route/effect and setup-admission promotion together. Preserve
both existing profile fingerprints. Only then close #48's integrated outcome.
No production deployment, operational activation, personal data or production/PITR
acceptance is claimed. Real elapsed twenty-minute process expiry and deployment
capacity remain explicitly unproved; archive Python peak is not process RSS.
