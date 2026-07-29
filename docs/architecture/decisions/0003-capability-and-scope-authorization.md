# ADR 0003: Capability, scope, relationship, and field authorization

- Status: Accepted
- Date: 2026-07-26
- Requirements: IDN-002, IDN-004, IDN-005, AUD-001, QRY-003, QRY-007,
  SAF-001 through SAF-004, PRI-001, INT-004

## Context

Maru combines one platform identity with multiple independent organizers,
editions, departments, temporary duty roles, personal views, restricted cases,
and external applications. Django model permissions and role names cannot
represent all of those boundaries. Checks performed only on detail views would
still leak records through lists, search, counts, files, or exports.

## Decision

Authorize each operation from:

```text
principal + capability + tenant and edition scope + relationship
+ resource state + fields + execution context
```

Roles are versioned bundles of capabilities. Grants are scoped, reviewable,
expiring, revocable, and delegable only within the grantor's authority.

Read models and serializers expose explicit permitted field projections.
Candidate queries are tenant- and capability-scoped before evaluation. High
impact actions may impose obligations such as step-up authentication, reason,
approval, watermark, or access audit.

Support access, machine identities, integration installations, and offline
devices are principals rather than hidden bypasses.

## Consequences

- Authorization policy becomes a first-class subsystem with extensive tests.
- Module APIs must publish capability and field requirements.
- Staff can receive narrow operational instructions without underlying
  sensitive detail.
- Query caching, search indexes, exports, files, and realtime delivery must be
  policy-aware.
- Organizer-configured roles cannot override platform safety invariants.
- Policy versions and reason codes improve diagnostics, but explanations must
  avoid information leakage.

## Alternatives considered

- Django groups and model permissions only: rejected because they lack tenant,
  resource, relationship, context, and field decisions.
- Hard-coded department roles: rejected because conventions organize
  differently and staff frequently hold multiple temporary capacities.
- Pure row-level access control: rejected because field restrictions and
  high-impact obligations remain necessary.
- Database superuser support access: rejected as an application workflow;
  exceptional infrastructure access remains separately controlled and audited.
