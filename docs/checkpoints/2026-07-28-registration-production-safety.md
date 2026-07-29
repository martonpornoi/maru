# Registration production-safety checkpoint

Date: 2026-07-28  
Outcome: Repository-controlled production blockers implemented and verified;
external deployment, load, policy, and product gates explicitly retained

## Scope

This milestone extended the edition-owned registration vertical from phased
offers and moderated profiles through the safety-critical boundaries needed for
a realistic pilot:

- verified public identity, recovery, sessions, step-up, abuse controls, scoped
  restrictions, consequences, and appeals;
- complete JSON headless submission with exact-origin browser policy,
  configuration/policy versioning, conditional validation, and idempotency;
- hosted payment intent and authenticated webhook reconciliation;
- append-only operational finance, receipt, refund/cancellation dual control,
  dispute/fee/settlement evidence, and exception queues;
- canonical inbox and optional email projection with retry/failure evidence;
- minor/guardian admission policy;
- image safety scanning/rendition evidence, moderation, reuse, and disposal;
- subject rights, exports, post-edition correction, retention minimization, and
  disposal receipts;
- credentials, signed bounded offline manifests, check-in reconciliation, and
  conflict queue;
- readiness gates, comprehensive unresolved-queue counts, immutable closure
  manifest, and archive recheck; and
- production settings validation, scoped registration metrics, OpenAPI, module
  docs, and end-to-end operator/tester documentation.

## Defects corrected during verification

- The entitlement database trigger originally made a legitimate cancellation
  unable to revoke active admission. Migration `registration.0024` now permits
  only `active -> revoked` while freezing organization, edition,
  registration, grant code/time, and all other evidence. Other updates and
  deletes remain rejected.
- Closure formatted a dictionary of blocker counts as a Django validation
  message, which fails because message mappings must contain strings/lists.
  Closure now returns a stable human-readable list of named counts.
- Closure now includes pending/permanently failed notification delivery,
  pending profile/fursuit media, proposed historical corrections, unapplied
  due restriction consequences, and open appeals in addition to the original
  registration/finance/offline/outbox queues.
- Registration metrics now verifies the edition belongs to the requested
  organization before reading any counts.
- OpenAPI enum naming was made explicit, eliminating schema warnings and
  keeping generated frontend types stable.
- Financial operation APIs previously admitted enum values whose fulfilment was
  absent. Transfer, product change, and price adjustment now fail explicitly
  instead of entering a misleading approved state.
- Retention policies are read-only in bootstrap admin until independently
  approved provisioning exists.

## Durable decisions

Accepted:

- ADR 0013: identity assurance and scoped restrictions;
- ADR 0014: hosted payments and operational finance;
- ADR 0015: canonical service notifications;
- ADR 0016: minors, media, and privacy operations; and
- ADR 0017: credentials, offline check-in, and closure.

Stable requirements added: IDN-007/008, MSG-007, REG-017 through REG-020, and
PRI-009.

## Verification evidence

- Backend: 369 tests pass against PostgreSQL 17.
- Coverage: 90.03% branch-aware, above the 90% gate; migration declarations are
  omitted.
- Python quality: Ruff format/lint pass; strict mypy passes 152 source files.
- Django: system check and production `check --deploy` pass; migration drift is
  empty.
- API: OpenAPI 3.1 generation/validation passes without warnings and TypeScript
  API types regenerate.
- Staff Console: typecheck, 12 tests, and production Vite build pass.
- Dependencies: Python and production frontend audits report no known
  vulnerabilities; local Maru is skipped as a non-PyPI project.
- Recovery: PostgreSQL backup restores into a fresh drill database and verifies
  75 migrations, 82 accounts, 2 organizations, 6 editions, 33 audit events, and
  13 outbox messages before cleanup.
- Documentation validation is rerun after this checkpoint; the final count is
  recorded in `docs/project/CURRENT.md`.

## Recovery and migration implications

Migrations add identity, communication, finance, media safety, privacy,
accreditation, and closure records plus database guards. These records contain
accepted security, attendee, financial, or operational history. Schema rollback
must not delete them. Roll forward with a repaired release after data
acceptance; restore rehearsal and count reconciliation remain the recovery
baseline.

## Explicit residual gates

Maru is not automatically production-approved:

- the actual payment provider, SMTP, scanner/storage, scheduler/workers,
  telemetry, relay client/devices, printers, and secret lifecycle must be
  selected, provisioned, and rehearsed;
- production-shaped throughput/load proof is still required;
- retention/minor/refund/restriction policy must be approved for the
  jurisdiction and provisioned through controlled authority;
- transfer, product change/repricing, badge layout/printing, staff-on-behalf,
  broad catalog, and platform-global privacy/identity are not implemented; and
- privacy, finance, security, safeguarding, jurisdiction, operations, and event
  leadership must record an edition go/no-go.

The exact exit evidence and sequencing live in
`docs/project/REGISTRATION_TODO.md`.
