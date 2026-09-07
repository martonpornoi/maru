# Scheduling candidates, conflict evidence and physical reservations

Date: 2026-09-07
Issue: [#81](https://github.com/martonpornoi/maru/issues/81), child of
[#48](https://github.com/martonpornoi/maru/issues/48).
Status: implementation candidate; complete certification and protected delivery pending.

## Outcome and contract

[ADR 0088](../architecture/decisions/0088-versioned-scheduling-candidates-and-venue-binding.md)
establishes Scheduling-owned service days, stable grouped occurrences and
immutable versioned candidate manifests. Explicit placement, movement, resizing,
unplacement, copying, restoration and archival preserve occurrence identity and
other alternatives. UTC instants, IANA-zone/DST interpretation, overnight days,
grid precision and preparation/effective/teardown envelopes are explicit.

Current Programme and Venue sources retain independent authorization and field
ceilings. Host consent and deliberately shared availability remain Programme
facts; required occurrence presence is an explicit planner selection, not
automatically the entire room work envelope. Private host periods are evaluated
in memory, not copied into retained candidate or conflict history. Another
edition's physical contention exposes only bounded busy consequences and an
edition-specific opaque key, never its booking identity or private content.

Conflict reports retain exact descriptors, dependency versions/digests and
completeness. Missing, stale or overflowing sources cannot pass. Warning
acknowledgement binds exact current evidence and cannot override hard blockers
or unavailable checks. Staffing, rest, accessibility fit and release readiness
remain explicitly unevaluated; room reservation is not Programme readiness.

Explicit reservation/replacement/cancellation uses reciprocal Scheduling intent
and Venue binding, exact current physical versions, independently authorized
owners and one transaction. Draft alternatives do not reserve rooms. Independent
Venue approval excludes the original placement author as well as the booking
creator/editor. Generic Venue rescheduling/publication cannot bypass a linked
Programme occurrence. Historical cancellation remains possible after candidate
archival or day retirement; history is never erased.

## Safety and installation

Fifteen Scheduling relations and one Venue binding relation have additive owner
migrations, immutable scope/version/evidence guards, exact catalog/schema
readiness and SELECT-only runtime provisioning. New capabilities/descriptors
grant no authority by themselves. The neutral Core catalog helper fingerprints
relation structure without reading tenant data or importing domain owners.

Canonical edition/person/owner/physical-member locks serialize shared writers.
Candidate state, immutable manifests, reservations, receipts, audit, registered
events and outbox commit atomically. Raw-DML tests cover late child append,
stale dependency acknowledgement, incomplete two-owner evidence, physical
rewrites, approval independence and silent occupancy cancellation.

Unused installation reverses and reapplies normally. Joint populated fences
protect both Scheduling and Venue history before either owner's guards can be
removed. Older fences may refuse after unused successors legitimately reverse;
tests verify retained owner evidence and ordinary full-graph forward recovery.
See the [recovery runbook](../operations/scheduling-migration-and-recovery.md).

## Verification at this checkpoint

- Combined new Scheduling/owner-seam group: 377 passed in 326.99 seconds,
  93.64 percent branch-aware targeted coverage against the unchanged 90 percent
  gate. This includes all twelve new integration files, real races, late
  rollback, schema drift, committed reversal, populated fences and recovery.
- Complete database-free suite after final compatibility/dormancy tests:
  3,163 passed in 11.83 seconds. The dormancy tests independently reject missing
  declarations and every current-profile/effect activation path.
- Runtime ACL/provisioning group: 98 passed in 45.44 seconds, including table,
  column, inherited and PUBLIC privilege drift and the real provisioning SQL.
- Eight affected conversion/host historical cases passed in 495.13 seconds.
  Registration audience and Identity retention committed round trips passed
  in 379.30 seconds after repairing historical target/state reconstruction.
  All original assertions remain, plus explicit absent-owner regression checks.
- Historical conversion assertions now distinguish legitimate reversal of
  unused successors from loss of protected owner history. No migration is
  faked, no guard is disabled, and ordinary full-graph recovery is retained.
- Strict mypy passed 465 source files; Ruff, NumPy and semantic docstring
  validation passed. A fresh warning-fatal Sphinx build passed. Django detected
  no model/migration drift. Synthetic invitation delivery remains unconfigured
  and fail-closed, with its expected system-check warning.
- The twelve new integration weights use measured complete-file timings from
  the successful focused run. Existing file weights, case selection, coverage
  and timeouts are unchanged. This is not a whole-suite performance claim.

These groups overlap and must not be summed as full-suite acceptance. Database
tests use isolated synthetic PostgreSQL 17 data. No real-browser journey applies
to this route-free kernel. Clean exact-head full local certification and hosted
PR gate/CodeQL remain pending; the focused evidence alone does not authorize merge.

## Continuation and non-goals

Both existing literal adoption profiles remain unchanged. No Programme route,
UI, API, worker, release, Registration, Participation, payment or attendance
state is activated. The new foundation is not a usable departmental timetable
or production approval. The [owner contract](../modules/scheduling.md) records
the exact commands, source ceilings, limits and remaining consumers.

Finish protected delivery, reconcile #81/#48 and synchronize main. Continue
single-agent through the accessible editor, Workforce staffing, atomic release
and projections, on-site continuity, guided surfaces/activation and integrated
synthetic acceptance. Keep #48 open until its complete journey is verified.
