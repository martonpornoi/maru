# ADR 0038: Stage governance after the edition workspace spine

- Status: Accepted
- Date: 2026-08-01
- Clarifies: ADR 0037

## Context

ADR 0037 defined the first production-consolidation milestone as an edition
workspace spine ending with organization representation and effective-access
explanation. Implementation showed that the first four records form a safe,
independently executable dependency slice, while representation introduces a
separate authority lifecycle, invitation model, department/resource scope,
and field-level disclosure decisions.

Mounting those governance controls as part of the record slice would either
make the slice unnecessarily large or encourage a second, incomplete role
system. The current platform administrator also must remain outside every
organization and convention relationship.

## Decision

The ADR 0037 edition-workspace milestone is delivered in two ordered slices:

1. **M1 — edition workspace spine:** organization, series, and edition records;
   audited and idempotent edition creation; explicit working context; bounded
   record activity; and a truthful platform-oversight access summary.
2. **M2 — governance and scoped access:** organization representation and
   activation, invitation/acceptance, repository-owned fictional Department
   hierarchy, department/resource authorization constraints, computed
   effective-access explanation, and audited access management.

M1 may be accepted and committed without M2, but its access header must remain
explicitly provisional and platform-only. It must not imply that an Executive
Board, department, Django Group, or named person can use a page before the
canonical M2 relationships and policy sources exist.

M2 must extend the existing capability policy and audited relationship
commands. It must not introduce editable page ACLs, use Django Groups as a
parallel authority source, grant authority through selected-edition session
state, or enroll the platform administrator into an organization.

Department-owned mutation pages remain blocked until M2 can enforce their
organization, edition, department, resource, relationship, lifecycle, and
field restrictions together.

## Consequences

- Pages 1 through 7 form a complete and reviewable platform-admin record
  journey before governance editing is mounted.
- M2 becomes the next mandatory security milestone rather than an optional UI
  enhancement.
- The full ADR 0037 milestone outcome is unchanged; only its delivery order is
  made explicit.
- Programme, timetable, logistics, document, and communications mutations may
  model their domains in parallel, but may not mount department-owned writes
  ahead of the M2 authorization boundary.
- The hands-on M1 tutorial honestly exercises platform oversight only.

## Alternatives considered

### Add a temporary Executive Board flag to organization records

Rejected. A flag cannot represent multiple people, invitation and acceptance,
time bounds, delegation, disclosure policy, or revocation, and would become a
second authorization system.

### Treat Django staff or Groups as convention governance

Rejected. Platform framework administration is not an organization
relationship and cannot safely express tenant, edition, department, resource,
or field scope.

### Delay the entire record journey until governance is complete

Rejected. It would withhold a safe executable dependency slice and make the
larger governance milestone harder to understand and verify.

## Requirements affected

- IDN-012
- HR-006 through HR-010
- UX-020
- UX-021
- UX-022
- UX-023
- NFR-001 through NFR-004
- NFR-008
