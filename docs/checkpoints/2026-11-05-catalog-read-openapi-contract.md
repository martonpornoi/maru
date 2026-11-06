# Catalog order-history and activity OpenAPI contract

## Scope

This bounded INT-001 increment under
[#36](https://github.com/martonpornoi/maru/issues/36) describes the existing
own-order history and staff-activity GET adapters. REG-026, AUD-001 and ADRs
0003, 0050 and 0056 retain the owning Catalog, authorization and private-reference
boundaries.

Order history documents `200`, query rejection `400` and denial `403`.
An authorized scope without a catalog returns an empty order list. Staff
activity documents `200`, unsupported-query `400`, denial `403` and an
authorized unavailable catalog `404`. Each documented response includes
private cache directives and correlation headers. Problems declare
`application/problem+json`. The examples use fictional activity and an empty
order history.

## Audit ordering and isolation

The staff query authorizes the exact edition, reads allowlisted activity and
appends its audit record before the adapter rejects unsupported query fields.
Its `400` response therefore retains the allowed-read audit entry with the
actor, exact scope, request ID, source and target count. Denial and catalog
absence append no activity-read audit. The verified own-history requests
append no audit rows.

The response matrix checks eleven scenarios over real commands and migrated
PostgreSQL. Two people receive their own orders, another person receives an
empty list, an anonymous request is denied, and an authorized activity reader
cannot read a foreign edition. Each actual body is validated against the
generated status and media-type schema. Catalog, receipt, event, outbox,
admission and audit table counts reconcile the expected effects.

## Verification boundary

The 41 focused Catalog PostgreSQL tests and 121 focused unit tests passed.
OpenAPI generation reported 23 existing enum warnings and zero errors. The
semantic schema comparison changed only these two GET operations, and the
generated Staff Console types passed TypeScript checking. Ruff, mypy and
focused docstring checks passed. The owned database was removed and all ten
preserved fixture states matched.

The change adds reference annotations and tests over the existing method
bodies. It needs no migration or retained-data repair. Self-read audit purpose,
cardinality limits, dependency failures and response-wide concurrency
guarantees remain separate decisions under #36. Demo coverage is unaffected.

The first full local run found that placing the matrix in a new integration
file left it outside the checked-in timing inventory. The failed candidate and
its outputs were retained. The repaired candidate places the same matrix in
the existing Catalog integration module and requires fresh exact-head
certification.
