# Programme stop Venue boundary

Issue #190, within #108/#48. ADR 0111; EVT-007, ARC-003, ARC-005, AUD-001,
INT-007 and NFR-013. Local component preparation, not protected delivery or an
executed Stop Programme journey.

Venues 0009 adds old/new exact-parent locks and terminal guards to all nine
edition-owned relations. Organization catalog tables remain shared. Receipts with
no edition are restricted to the existing explicit catalog operations. Unknown
scope or Programme version and non-READ-COMMITTED operation fail closed.

The narrow retained corrections are actual authorized booking cancellation and
publication withdrawal, with unchanged physical envelope and other protected
fields. Occupancy may only become inactive through its exact cancellation.
Deferred constraints require reciprocal immutable history, original actor/version,
Unicode canonical intent, receipt and matching same-transaction native audit.
Current authorization remains independently required by the public commands.
No helper execution grant, linked-booking exemption or stop bypass is introduced.
Used Events stop receipts fence normal reversal. An empty test database exercised
normal reverse/reapply while correcting this unpublished migration.

Verification:

- The first migration attempt failed on a PL/pgSQL CASE expression; corrected
  parentheses allowed normal installation. No fake migration was used.
- The first executable matrix exposed that the existing physical-change helper
  intentionally excludes publication withdrawal. The new guard now binds exact
  owner receipt/audit fields directly; the old helper is unchanged.
- Initial corrected matrix: 13 passed in 4.38s, native run4.
- Expanded matrix, real Venue workflows, linked-booking guards, Scheduling
  continuity and focused units: 76 passed in 75.96s, native run5.
- Final native matrix: 31 passed in 12.86s, native run6. It covers actual
  cancellation/withdrawal and exact replay, both corrections in one transaction,
  all nine fresh-write refusals, hidden envelope/review/capacity changes,
  missing-history rollback, occupancy reactivation, missing-guard readiness and
  genuine native audit with mismatched capability/fields/retry/retention intent.

Reports are `.tools/programme-stop-venue-native-{4,5,6}.xml`. Terminal edition
states are isolated component arrangements, not a completed stop command.
Source and isolated-runtime fingerprints include the exact new guard functions
and attachments. The new CI test file has a conservative uncalibrated 300-second
weight, not a claim about hosted duration. Final bundle certification, integrated
stop races/recovery, browser/human acceptance and protected delivery remain open.
