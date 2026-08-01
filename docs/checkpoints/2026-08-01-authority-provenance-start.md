# Exact authority provenance implementation start

- Date: 2026-08-01
- Phase: Production consolidation M2.3
- Related requirements: IDN-002, IDN-004, IDN-005, IDN-009, IDN-011,
  IDN-012, UX-020, AUD-001, AUD-005, NFR-001–004, NFR-008
- Related ADR: 0044

## Outcome

ADR 0044 is accepted. It closes the design ambiguity explicitly left by ADR
0041: ordinary root authority will retain the exact source used by both the
actor and approver, and later source loss will make the dependent authority
ineffective without silently selecting another source.

This checkpoint records an implementation start, not a runtime claim. The
current schema still stores controller identities only, and
`check_scope_v2_readiness` must continue to report authority-source provenance
as an unresolved production gate until the complete staged activation passes.

## Decisions

- Use a typed append-only issuance ledger with exactly one grant, bundle, or
  assignment target; do not spread sparse source columns across every model.
- Pin ordinary source issuances deterministically by narrowest scope, direct
  grant before role, least surplus expiry, then monotonic ordinal.
- Do not accept a caller-selected source, generic platform policy, implicit
  rebinding, untyped identifiers, or inferred historical evidence.
- Keep initial Executive Board activation non-cyclic with exact platform-
  bootstrap and accepted-appointment ceremony controls. Later ordinary Board
  actions use the active Board RoleAssignment issuance as their source.
- Treat role-bundle provenance as historical definition approval; every role
  assignment still needs fresh current dual control.
- Backfill only provable Board and delegated-grant evidence. Effective ordinary
  legacy authority must be revoked/recreated or replaced under current control.

## Planned slices

1. additive issuance/control schema, model validation, administration
   inspection, and database shape/immutability tests;
2. internal source-bearing policy result, deterministic source selection,
   source-aware commands, and transactional locking;
3. Executive Board ceremony writer and provable backfill;
4. privacy-minimized readiness, explicit legacy reconciliation, activation
   guards, dynamic policy cutover, and downgrade fence; and
5. full migration, concurrency, tenant-isolation, coverage, populated-demo,
   recovery, and browser evidence.

## Recovery boundary

Until activation, the new tables are additive and current scope-v2 behavior
remains authoritative. Old writers must be stopped for the final cutover. After
the first provenance write under activated guards, compatible code must fix
forward or the whole database—including authority targets, controls,
representation, audit, and outbox—must be restored to one pre-write point.

## Resume point

Start with the additive authorization schema and its migration tests. Do not
mark production ready, mount department-owned mutation pages, or reconcile an
ordinary legacy source by inference.
