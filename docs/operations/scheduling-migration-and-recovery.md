# Scheduling and reciprocal Venue migration/recovery

Applies to [#81](https://github.com/martonpornoi/maru/issues/81),
[ADR 0088](../architecture/decisions/0088-versioned-scheduling-candidates-and-venue-binding.md)
and the [Scheduling owner contract](../modules/scheduling.md).
Use synthetic data. This is not production deployment or profile-activation approval.

## Install and verify

Scheduling `0001` through `0004` add fifteen owner relations and close the
service-day retirement and conflict vocabulary. Venue `0003` adds the immutable
reciprocal source binding. Authorization `0027` extends the exact-edition
Scheduling/Programme dependency vocabulary and exact-resource Venue dependency
read; it creates no grants, roles or current-profile capabilities.

Scheduling `0005` installs 45 owner row/graph/truncate guards and closed source,
manifest and evidence functions. Venue `0004` adds immutable binding, linked
Booking and reciprocal deferred graph guards; one is attached to Scheduling's
intent table. The shared graph requires exact attributed receipts, history,
Audit, DomainEvent and Outbox, and rejects missing or stale evidence at commit.
An in-process writer flag is never the only protection.

Venue `0005` and Scheduling `0006` each fence the complete fifteen-table
Scheduling graph and Venue binding before removing either owner's integrity.
Use ordinary reviewed migrations with the schema owner, then the exact
[runtime provisioning SQL](postgresql-runtime-role-provisioning.sql.example).
The sixteen new relations remain SELECT-only for runtime, without PUBLIC
mutation grants. Guard/helper functions remain owner-only, SECURITY INVOKER
and fixed-search-path. Do not grant runtime a generic write or trigger escape.

`scheduling_database_integrity_is_ready()` verifies 46 Scheduling-attached
triggers and the eleven required owner/cross-owner functions. Venue readiness
composes the original and new boundaries: 20 Venue-attached triggers and
thirteen functions. Both verify migration recorder state, exact function
definitions, ownership and execution ACLs. Pinned data-free relation digests
cover every new table's semantics, columns/defaults/collations, complete
constraints and index definitions/operational flags. Scheduling also rejects
unexpected owned tables, views or sequences. `/health/ready` exposes only
the minimized `scheduling_integrity` and `venues_integrity` outcomes.

Authorization readiness separately verifies the capability minimum-scope
function changed by `0027`. A same-named function/table or apparently valid
foreign key is insufficient if its definition differs. Do not regenerate
expected fingerprints from an unexplained live schema to make readiness green.
Compare against reviewed migration source and recover the exact contract.

## Reversal and retained-state recovery

An unused joint graph can reverse through ordinary committed Django migrations
and be fully reapplied. Once any Scheduling control, revision, intent, report,
acknowledgement or Venue binding exists, contraction locks the complete joint
graph in ACCESS EXCLUSIVE mode and refuses before removing its guards. An
archived candidate, retired day or cancelled booking is still retained evidence.
Cancellation is not authorization to discard history.

On refusal, retain compatible code and fix forward. Never fake migration
records, disable guards, delete historical rows, reset versions, or forge
reciprocal receipts to force a downgrade. The existing isolated-test-only
two-factor truncate reset is not a production recovery mechanism.

Django commits each migration separately. A broader downgrade against an
older populated Programme/Applications boundary may reverse this unused
successor graph before that older fence refuses. Keep writers stopped, inspect
the actual recorder and protected owner evidence, then reapply the complete
current leaf graph. Do not assume an exception leaves every unused successor
installed, or restart current code against a partial historical target.

Backup/restore must include mutually consistent Scheduling, Venue bookings,
occupancy, bindings, Programme host/item state, Events, Identity,
Organizations, Authorization, Audit, Effects and migration records; include
Applications for accepted-source items. Preserve the Venue exclusion constraint
and extension. Reconcile current physical occupancy with retained bindings and
source intent. Reevaluate candidates against current source versions after
recovery. Never restore withdrawn host periods as current availability or infer
consent, independent approval or future release from an old report.

## Dormant editor request recovery

The unmounted timetable editor component uses ordinary authenticated requests,
CSRF protection, no-store responses and masked sensitive POST fields. It does
not change the current-profile or runtime SELECT-only boundary. Do not mount it
or substitute an owner login to work around denied runtime writes.

An authorized validation or stale-version response retains the exact pending
form, retry key and observed versions. Review current owner records before
deliberately starting a new intent; never automatically rebase or replay a
different payload with the old key. A dependency/database failure may follow a
successful command commit. The page therefore reports uncertain completion,
not an assurance that no change occurred. Retry the exact retained request to
confirm its existing receipt, or use independently authorized history when
access is restored. Do not create a new candidate merely because a success
refresh failed.

Permission loss or unavailable complete owner reads withhold previously loaded
private labels and layers. Diagnose with existing minimized command/audit
evidence, not logged form bodies, raw owner exceptions, host calendars or private
reasons. A current draft change still leaves physical room holds unchanged;
inspect the exact authorized hold before deliberate replacement/cancellation.

## Meaningful verification

Focused tests cover DST and grid edges, explicit person presence, candidate
independence, two-clique contention, actual competing writes, exact retries,
source/field/tenant denials and late rollback. Database-bypass tests suppress
application freshness checks or reciprocal evidence and require commit failure.
Continuity tests exercise ordinary Venue approval, blocked reschedule/publication,
generic cancellation and subsequent explicit occurrence retirement.

Committed empty reversal and populated two-owner fences are distinct tests;
both require explicit full-forward recovery. Schema-drift tests use rollback
to restore altered columns, constraints, functions, ACLs and migration records.
Runtime-role tests must continue to prove the sixteen-table SELECT-only ceiling.
Historical conversion/host tests must also be checked against these successors.
Full exact-head local certification and the green protected hosted PR gate are
separate required delivery evidence. None of these activates Programme Operations.
