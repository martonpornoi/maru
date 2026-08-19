# Page 10 invitation integrity stable

Date: 2026-08-02

This checkpoint records the locally accepted additive database boundary for
Page 10 platform account invitations. It is not a production deployment or
writer-cutover approval.

## Outcome

- Identity `0014_invitation_delivery_integrity` now depends on audit
  `0007_identity_reconciliation_audit_uniqueness`; audit `0007` depends on
  identity `0013`, so the reconciliation-audit cardinality fence exists before
  the hardened receipt checks can rely on it.
- Invitation command receipts are unique by invitation and result version.
- Reconciliation receipts are unique by delivery and result version.
- Reconciliation audit retry evidence is conditionally unique by principal and
  retry digest for the exact capability and operation.
- Deferred integrity checks bind transitions, receipts, reconciliation state,
  and audit evidence to exact versions. Forward preflights and rollback fences
  fail closed around incompatible live evidence.
- Scheduler success evidence is append-only, recipient-free, and protected at
  both ORM and database boundaries.
- Account prefix indexes cover email, login handle, and display name with the
  required PostgreSQL operator class; the scheduler index retains its declared
  descending order.

## Exact readiness generation

`page10-invitations-additive-v6` fingerprints 33 reviewed functions, 47 exact
trigger attachments, and 12 indexes or constraints. Inspection includes
function bodies and execute ACLs, trigger timing/columns/deferral, index
expressions, operator classes, ordering/null options, constraint backing, and
partial predicates. Migration-recorder evidence is required separately from
catalog shape.

## Verification

- Fresh combined invitation vertical: 222 tests passed.
- Exact readiness and tamper matrix after the final structural regressions:
  112 tests passed.
- Independent hardening audit: 28 database-hardening tests, 27 delivery and
  reconciliation tests, and one truly fresh graph/order and duplicate-audit
  rejection test passed; verdict `STABLE`.
- Migration drift: no changes detected.
- Ruff, strict mypy for the changed identity/readiness boundary, Django system
  check, and whitespace validation passed. The development system check emits
  the expected fail-closed warning when invitation encryption keys are absent.

## Still open

- API parity and the configurable audited retention job are being implemented.
- Registration question/product/minor-policy/profile-extension editors,
  preview, activation, and direct-writer retirement remain incomplete.
- No stopped-writer generation or production cutover is active.
- Deployment keys, runtime role transition, supervised schedules, monitoring,
  representative restore/PITR and load evidence, authenticated responsive and
  accessibility evidence, owner rehearsal, and partner approvals remain
  release gates.
