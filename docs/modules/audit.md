# Audit module

Status: Implemented V02 kernel with edition-spine mutation evidence
Last updated: 2026-09-02

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

Organization structure HTML and API reads append
`workforce.structure.read` after fresh final exact authorization and before
releasing organization, edition, Department, Position, or holder labels. The
allow record contains exact actor/organization/edition target, source channel,
the `audit_sensitive_read` obligation, and only policy version, route name,
and HTTP method as safe metadata. It contains no names, email, login handle,
authority identifier, reason, count, projection state, or tree payload. If the
audit append fails, the adapter returns a
generic name-free `503` and releases no partial projection.

Direct grants, role-bundle versions, and role assignments record separate
actor and independent-approver allow events. Immediate grant and assignment
revocation records the revoker. Failed canonical transactions retain one safe
error event after rolling back partial success evidence.

Audit `0005` hardens the pre-existing append-only event guard, adds a permanent
no-truncate fence and a partial unique activation index, and makes the single
ADR 0044 exact-lineage marker audit part of the same database transaction,
timestamp, and transaction ID. Audit `0006` adds the reciprocal boundary: a
`BEFORE INSERT` guard leaves every ordinary audit operation unchanged but
accepts the reserved activation operation only when its frozen payload matches
the platform-administrator marker and active latch created or transitioned in
that same transaction. Its upgrade preflight accepts either one pristine
dormant state or one exact durable marker/audit pair and rejects legacy orphan,
extra, or malformed reserved events. Its reverse fence is removable only from
the pristine dormant state.

The audit functions pin the trusted schema order and are included in
authorization readiness fingerprints. Reserved trigger functions are not
generally executable: `PUBLIC` execution is revoked. Test-only truncation
requires both a `test_` database name and the dedicated test GUC; production
settings reject either escape shape.

Convention series record and Event edition record do not present `AuditEvent` rows as a human activity feed.
Record activity uses allowlisted domain facts and safe identity labels; audit
remains security/control evidence with separate authorization, purpose, and
retention. A later cross-domain Activity workspace must preserve that boundary.

Dormant Applications Programme-call and proposal commands use the same safe
audit envelope but never place an answer, profile value, consent, invitation
address, collaborator roster, sealed snapshot, or review fact in metadata.
Successful mutations commit one minimized allow event with the aggregate,
dedicated receipt, version proof, domain event, and outbox row. Denials and
validation errors retain only caller-safe scope and a stable closed reason;
foreign or malformed targets collapse to the same non-disclosing shape. An
acknowledgement audit attributes the responding contributor and exact sealed
revision without copying what that revision contains.

Dormant Programme-import mutations use one minimized outer command outcome and
retain the protected nested call/proposal outcomes without copying source keys,
emails, answers, contributor profile or consent values, identity-match state,
payloads, request/content digests, source bindings, command reasons, or database
messages. Organizer preview records only closed operational facts. Lead-self
preview re-resolves the exact staged email and appends the required sensitive-
read audit before returning that actor's bounded claim projection; audit
failure releases no private projection and persists no reusable identity match.
Disposal remains attributable at exact Edition scope without granting staged-
content read authority.

Programme Department ownership transitions use the same minimized envelopes.
Call reassignment, active-call retirement, clean-batch reassignment, disposal,
and exact-ID orphan recovery retain action, exact tenant/edition, actor,
aggregate/version, correlation, and receipt references without copying either
Department name, dependency kind/count, source key, email, proposal/import
content, payload, or digest. A refused Workforce retirement records no
Applications target identifier and no successful structure evidence. The
public dependency seam itself is not an audit-backed listing oracle: it returns
only `clear`, `blocked`, or `unavailable`, with a known block taking precedence.

## Tests

Tests cover safe payload rejection, direct and bulk mutation/deletion,
one-time sealing, multiple linked batches, empty reruns, sequence gaps, digest
and count mismatch, batch immutability, batch-size bounds, command output, and
command failure. Activation-evidence tests cover ordinary-operation
pass-through, same-transaction marker/latch binding, fresh-correlation forgery,
active upgrade, dormant reverse, and fail-closed catalog tampering. Organization structure read projection
tests cover HTML/API source channels, exact minimized metadata, and audit-
append failure before disclosure.
Ownership-continuity tests cover exact source/destination attribution on
successful receipts, generic denial/error metadata, atomic rollback on audit
failure, replay without duplicate evidence, and the absence of call, batch,
Department, source, and private-content facts from refusal surfaces.

## Limitations

Signing or independently storing integrity checkpoints, partitioning,
retention execution, subject security history, cursor pagination, signed
exports, alert integration, and subject-specific security history remain. Hash
chaining provides tamper evidence; it does not replace access control, backups,
or independent checkpoints.
