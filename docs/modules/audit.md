# Audit module

Status: Implemented V02 kernel with edition-spine mutation evidence
Last updated: 2026-08-01

## Purpose and requirements

`maru.audit` provides security and administrative control evidence for AUD-001
and AUD-005. It is deliberately separate from user-facing operational
timelines and optional engagement measurement.

## Owned data and invariants

- opaque principal, tenant, edition, target, request, and correlation context;
- capability, operation, allow/deny/error outcome, and safe reason code;
- obligation and changed-field names without before/after payloads;
- allowlisted, typed, bounded metadata;
- delegated, elevated, and break-glass markers;
- retention classification; and
- ordered integrity batches linked by canonical SHA-256 digests.

Events and batches are append-only in model methods and PostgreSQL triggers.
The only event update admitted by the database is a one-time assignment to an
integrity batch. There is no general Django admin registration.

The safe metadata builder rejects unknown keys, structured values, negative
counts, and oversized text. Message bodies, form values, raw queries, medical
detail, secrets, and full object snapshots have no accepted field.

## Commands

- `append_audit(AuditRecord(...))`
- `seal_pending_audit_events(limit=...)`
- `verify_audit_integrity()`
- `python src/manage.py audit_integrity [--seal] [--limit N]`
- `GET /api/v1/organizations/{organization_id}/audit-events`

Sealing is serialized with a PostgreSQL transaction advisory lock. The
management command emits a machine-readable result and exits non-zero when the
chain is invalid.

The API requires `audit.view_security` at organization scope and one bounded
purpose such as security investigation, privacy request, or integrity review.
It caps a page at 100, filters tenant before all optional filters, verifies the
field ceiling, returns only minimized metadata, and audits its own allow/deny
access. It does not return `safe_metadata`, obligations, event payloads, or
cross-tenant counts.

## Integrated behavior

Organization/series creation, organization/series profile changes, protected
empty-Draft deletion, edition creation, and edition profile changes append
allow evidence inside their canonical transaction. Changed-field names are
recorded without entered legal, contact, locale, date, or descriptive values.
Edition creation stores only a hash of the idempotency key in audit metadata.

Edition lifecycle transitions and capability delegation record correlated
allow, deny, validation error, and safe unexpected-error outcomes. A
successful audit event and domain event share correlation; the domain event
uses the audit event as its causation identifier.

Direct grants, role-bundle versions, and role assignments record separate
actor and independent-approver allow events. Immediate grant and assignment
revocation records the revoker. Failed canonical transactions retain one safe
error event after rolling back partial success evidence.

Pages 5 and 7 do not present `AuditEvent` rows as a human activity feed.
Record activity uses allowlisted domain facts and safe identity labels; audit
remains security/control evidence with separate authorization, purpose, and
retention. A later cross-domain Activity workspace must preserve that boundary.

## Tests

Tests cover safe payload rejection, direct and bulk mutation/deletion,
one-time sealing, multiple linked batches, empty reruns, sequence gaps, digest
and count mismatch, batch immutability, batch-size bounds, command output, and
command failure.

## Limitations

Signing or independently storing integrity checkpoints, database-role
separation, partitioning, retention execution, subject security history,
cursor pagination, signed exports, alert integration, and subject-specific
security history remain. Hash chaining provides tamper evidence; it does not
replace access control, backups, or independent checkpoints.
