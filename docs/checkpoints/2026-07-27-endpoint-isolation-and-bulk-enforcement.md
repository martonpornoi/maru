# Endpoint isolation and frozen bulk enforcement

- Date: 2026-07-27
- Phase: Platform foundation V02
- Related requirements: IDN-002, IDN-004, QRY-001, QRY-003, INT-001,
  NFR-001, NFR-002, NFR-003
- Related ADRs: 0002, 0003, 0005

## Outcome

Maru now has reusable enforcement and test contracts for the endpoint shapes
that commonly leak tenant data: list, detail, search, count, autocomplete,
write, bulk target resolution, and error responses.

The event-edition reference API adds:

```text
GET  /api/v1/organizations/{organization_id}/editions/autocomplete
POST /api/v1/organizations/{organization_id}/editions/bulk-transition
```

Autocomplete is an organization-authorized, literal, minimized, count-free
projection. Bulk transition resolves at most 25 unique identifiers from a
tenant-filtered base query, locks the complete exact set, authorizes every
edition, and only then performs any transition.

## Decisions

- Projection contracts fail closed when the policy field ceiling cannot supply
  every declared serializer field.
- `freeze_bulk_targets` is framework-neutral and requires the caller to provide
  an already tenant/edition-scoped trusted queryset inside an atomic
  transaction.
- Target rows are locked in deterministic primary-key order to reduce deadlock
  risk; results retain client input order.
- Missing, cross-tenant, and denied bulk identifiers share one external
  `bulk_target_unavailable` shape. Protected audit records retain whether the
  internal outcome was deny or error without recording target identifiers.
- A bulk lifecycle request is all-or-nothing. Per-target transition audits,
  domain events, and outbox messages commit only when every target succeeds.
- Autocomplete requires organization-level list authority. An edition-only
  grant cannot broaden into suggestions or counts.

No new ADR was needed. The implementation makes ADR 0002's tenant boundary,
ADR 0003's query/field/bulk rules, and ADR 0005's atomic effects requirement
executable.

## Changed areas

- Added reusable complete-projection and transactional target-freezing
  enforcement primitives under `maru.authorization`.
- Added minimized edition autocomplete query/response serializers and API.
- Added bounded bulk transition request/response contracts and atomic service.
- Added request-level bulk audit using only policy version and target count.
- Added a reusable endpoint isolation test harness and deliberately unsafe
  fixtures proving it detects protected values and denied count metadata.
- Applied the matrix to list, detail, search/count, autocomplete, and bulk
  writes with anonymous, same-tenant, other-tenant/edition, expired/revoked,
  field, state, and failure cases.
- Regenerated and validated the OpenAPI 3.1 artifact.

## Verification

- 193 PostgreSQL tests pass.
- Branch-aware coverage is 92.29% against the 90% gate.
- Ruff formatting and lint pass.
- Strict mypy passes 81 source files.
- Django local and production deployment checks pass.
- Migration drift check reports no changes and the applied migration plan is
  empty.
- OpenAPI 3.1 generation and validation pass without warnings.
- Documentation validation passes 56 Markdown files and 164 unique
  requirement identifiers.

## Data, migration, and deployment notes

No database migration is required. The change adds two authenticated API
operations and updates `openapi.yaml`. Existing edition and effect records are
unchanged.

Clients should treat `bulk_target_unavailable` as a safe set-level failure and
must not infer which identifier failed. Retrying an already-applied lifecycle
transition remains an invalid state change; general write idempotency is still
future MARU-API-001 work.

## Known risks and incomplete work

- The enforcement primitives are proven through the edition reference resource;
  each future module must supply its own tenant-scoped query and domain policy.
- Bulk optimistic concurrency/version preconditions and general idempotency
  keys are not yet implemented.
- Direct grant, revoke, role-version, and role-assignment commands remain.
- The effects worker is not yet a supervised operational process.

## Recommended next actions

1. Implement audited direct authority-management commands using the same
   freeze/deny/audit discipline.
2. Add the supervised effect worker, fair scheduling, hard timeouts, metrics,
   alerts, and authorized replay.
3. Complete V02 user/staff activity projections and recovery evidence.
