# Programme Department ownership continuity and recovery

Status: Dormant command contract; no current profile or mounted recovery surface.
Requirements: PRG-011, HR-011, AUD-001, NFR-013.
Decision: [ADR 0084](../architecture/decisions/0084-programme-department-ownership-continuity.md).

## Resolve ownership before retirement

A Department cannot retire while it owns a Draft or Active Programme call, or
an unresolved staged import item. Expired import payload still blocks retirement.
The structure workflow returns a generic dependency conflict without revealing
Programme names, counts, private proposals, or import metadata. An unavailable
probe fails closed unless another probe has already established a blocker.

An authorized Programme owner resolves the dependency through these commands:

- `reassign_programme_call` moves a Draft call to a current Department with
  independent call-management authority for both source and destination.
- `retire_programme_call` retires an Active call while preserving proposals and
  their existing self-access relationships.
- `reassign_programme_import_batch` moves only an unexpired, wholly staged,
  payload-intact, unapplied and source-unbound batch while planning is open.
  Both Departments require import authority. Its new batch version invalidates
  earlier previews; item versions and source evidence remain unchanged.
- `discard_programme_import` clears remaining staged payload under the separate
  exact-Edition disposal capability. It remains available after expiry, planning
  closure, or historical owner retirement. Applied evidence survives.

Each mutation requires exact organization/edition scope, an expected version,
retry key, correlation identifier, and inspectable reason. After a conflict,
refresh authorized state and submit a new intent. Retry the same completed
intent with its original key to retrieve retained evidence. Never reuse a key
for changed parameters.

## Historical orphan calls

Forward migration deliberately accepts historical orphans without inventing an
actor, transition, reason, or receipt. Recovery consumes an already-known exact
call ID; it provides no listing, discovery, or content access.

`recover_orphaned_programme_call_reassignment` repairs an orphaned Draft with
the nondelegable, break-glass-required Edition capability
`applications.recover_programme_department_ownership`, plus ordinary management
authority for the current destination Department. An orphaned Active call uses
`recover_orphaned_programme_call_retirement`. A current owner must use the
ordinary commands. Orphan import batches are disposal-only.

The recovery capability is declared but absent from every current profile,
root role, route, worker, and UI. Installation does not authorize a production
operator to invoke it. Activation requires the future reviewed profile and
authority contract; do not manufacture temporary grants, use direct SQL,
disable triggers, or invoke test authorizers as an operational workaround.

Verify the retained transition receipt, reason, minimized break-glass audit,
event, and outbox evidence together. Imported calls retain their original
batch/source binding; successive reassignment receipts explain their current
owner. Applicant and collaborator history remains unchanged.

## Migration, diagnosis, and rollback

Apply Authorization `0023`, Applications `0010` through `0012`, and Workforce
`0018` through the normal migration graph under the controlled migration role.
The runtime role remains SELECT-only for dormant Programme relations. Verify
Applications and authority/Workforce readiness with their exact installed
function, trigger, constraint, index, ownership, and ACL fingerprints.

Normal Programme and Workforce writers share the edition mutex and canonical
row-lock order. A competing raw write receives SQLSTATE `40001`; roll back the
whole transaction before retrying through the governed command. Do not retry
only the failed SQL statement. Dependency unavailability requires restoring
the missing database contract, not assuming an empty dependency set.

Reversal is refused while live dependencies need retirement protection or new
transition/version evidence would become incompatible. Preserve the database
and use compatible code with a forward repair. An unused installation can be
reversed through the migration graph. Rehearse restore on an isolated synthetic
database before any deployment cutover; passing repository tests is not
production approval.

Related runbooks: [calls and proposals](applications-programme-calls-and-proposals-migration-and-recovery.md)
and [preview-first import](applications-programme-import-migration-and-recovery.md).
