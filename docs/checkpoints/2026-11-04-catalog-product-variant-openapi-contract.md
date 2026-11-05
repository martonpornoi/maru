# Catalog product and variant creation OpenAPI contract

## Scope

This INT-001 increment under [#36](https://github.com/martonpornoi/maru/issues/36)
documents the two existing product and variant creation commands. It keeps the
Catalog management authority, tenant and edition boundaries, draft and version
requirements, and the shared command services. The checked-in OpenAPI reference
and generated TypeScript distinguish a new receipt (`201`) from replay
(`200`), invalid input or command conflict (`400`), denial (`403`), and
unavailable records in an authorized scope (`404`).

The fictional examples show a convention merchandise product and a finite-stock
variant. Requests use the existing command and data model. The change needs
no migration or data repair.

## Focused verification

- All 43 Catalog integration tests passed against disposable PostgreSQL. Native
  HTTP checks compare the actual status, media type, private caching, request
  correlation and JSON body with the schema. They check replay after a later
  creation, stale versions, conflicting keys, closed input, denial before
  parsing, and matching errors for foreign and unknown parent products. Replay
  retains the original target, version and reason. The test database was
  removed and the ten preserved fixtures remained stopped.
- The 18 Catalog and Venues API unit cases passed. The semantic OpenAPI diff
  covers exactly the two creation operations. Schema validation reported
  23 existing enum naming warnings and zero errors. The generated Staff Console
  types passed TypeScript checking.

## Remaining work

The [Catalog API contract](../modules/catalog-api.md#product-and-variant-creation-responses)
records the verified creation semantics. Issue #36 remains open for wider API
conformance, including read completeness, read-audit policy and dependency
failure handling under the
[conformance plan](../development/catalog-edition-api-conformance-plan.md).
