# Edition Catalog OpenAPI contract

## Scope

This INT-001 increment covers the edition Catalog read and draft creation
operations under [#36](https://github.com/martonpornoi/maru/issues/36).
The adapter annotations describe the responses that the existing Catalog query
and command produce. A read can return `200`, query validation `400`, access
denial `403` or authorized absence `404`. Draft creation returns `201` for a
new receipt and `200` for a matching retry. Invalid or conflicting creation
intent returns `400`, and denied creation returns `403`.

The generated reference declares the problem media type, cache directives,
correlation header and fictional examples. A retry uses the same actor, edition,
key and normalized currency. It returns the original target and creation version
and preserves the original reason. The schema and generated TypeScript
declarations are part of the same change.

## Focused verification

- All 40 Catalog integration tests passed against a disposable, migrated
  PostgreSQL database. The edition API cases compare actual response statuses,
  headers, media types and JSON bodies with the generated contract. The owned
  database was removed and the ten preserved fixtures remained stopped.
- 119 focused unit tests passed. Generated TypeScript passed the Staff Console
  type check. A semantic comparison with the base schema found changes to the
  two selected operations and the new Catalog problem component.
- OpenAPI generation and validation reported zero errors and the 23 existing
  enum naming warnings. Ruff, mypy and focused docstring checks passed.

## Remaining work

The [Catalog API contract](../modules/catalog-api.md#edition-catalog-responses)
describes the verified responses. Read completeness, read-audit policy,
dependency failures and broader API compatibility remain separate decisions
in the [conformance plan](../development/catalog-edition-api-conformance-plan.md).
Issue #36 remains open.
