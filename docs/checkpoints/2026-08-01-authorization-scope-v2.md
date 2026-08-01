# Authorization scope v2 implementation checkpoint

Date: 2026-08-01  
Branch: `codex/full-platform-consolidation`  
Decision: ADR 0041  
Milestone: Production consolidation M2.2

## Outcome

Maru now enforces exact organization, edition, department, and typed-resource
authorization scope below the browser layer. Department authority does not
implicitly inherit through the department tree. Policy callers cannot construct
trusted scope from route identifiers: they use sealed targets resolved from
persisted ownership and lifecycle facts, and privileged commands lock and
resolve those facts again inside their transaction.

The first typed resource is `workforce.position`. Activation backfills a stable
immutable binding for every existing Position. New specialist-record and
preserved-bootstrap Position workflows call one explicit authorization service,
which locks and re-reads the Position and creates that same deterministic
binding. Maru intentionally uses neither a generic foreign key, model signal,
nor hidden cross-module write trigger for this integration.

## Database and command boundary

The stopped-writer sequence is:

1. authorization `0004_scope_v2_schema` adds bindings and optional exact scope;
2. workforce `0004_scope_v2_integrity` installs ownership, hierarchy,
   reporting, binding, and role-evidence guards; and
3. authorization `0005_scope_v2_activation` validates historical data,
   backfills deterministic Position bindings, activates the exact catalog and
   scope/delegation guards, and installs the durable first-scoped-write fence.

Issuance fields are append-only. Replacement creates a new record. Revocation
is one-way and must carry a timestamp, revoker, and reason together. Persistent
role bundles, grants, and delegation reject unknown or relationship-only
capabilities. Delegation cannot move across tenants, sideways or upward in
scope, change capability, escape the parent term, or retain authority after an
ancestor is revoked.

`check_scope_v2_readiness` returns stable count-only JSON. Its migration-data
status can be ready while `production_status` remains blocked. It deliberately
records exact actor/approver authority-source provenance for root authority as
unresolved; ADR 0041 does not claim to solve that separate IDN-005 invariant.

## Recovery boundary

Before migration, stop old writers and require zero readiness blockers. The
migrations preserve historical organization- and edition-wide meaning rather
than silently narrowing it. Before the first scoped write, the activation layer
can reverse its deterministic backfill when no incompatible evidence exists.
After the durable write fence is set, retain compatible code and fix forward or
restore the whole database to a mutually consistent pre-write recovery point.
Never reverse one module independently. The operator procedure is
`docs/operations/authorization-scope-v2-migration-and-recovery.md`.

## Verification at checkpoint creation

- 157 focused tests pass on an isolated PostgreSQL database, covering schema,
  forward/reverse activation, raw and bulk bypass, concurrent hierarchy and
  reporting cycles, exact policy and command behavior, resource bindings,
  readiness privacy, representation, platform separation, and workforce
  onboarding.
- Ruff formatting and lint pass after formatting two pre-existing drifted
  files; strict mypy passes across 199 source files.
- Django system check and migration drift check pass.
- A 57-test ordered historical-migration matrix passes and confirms
  authorization `0005`, workforce `0004`, and organizations `0012` are restored
  before current-model assertions.
- Forty-four additional runtime tests cover binding failure paths, scope/model
  validation, resolver tampering, malformed delegation ancestry, stale target
  locks, in-transaction rechecks, and readiness catalog categories.
- The definitive repository-wide invocation passes all 876 tests in 458.05
  seconds, reaches 90.43 percent branch coverage, and emits no warnings.
- The local and deploy-shaped Django checks, deterministic OpenAPI/client
  generation, Staff Console typecheck/19 tests/production build, and
  documentation validation for 167 Markdown files and 195 requirement
  identifiers pass without generated-artifact drift.
- The populated synthetic demo applied authorization `0004`, workforce `0004`,
  and authorization `0005`; scope and representation readiness each report
  zero blockers, and every expected migration leaf is applied.
- Live browser smoke verifies the platform shell, scoped Board organization and
  representation access, foreign-organization 403 denial, and no horizontal
  overflow at the 1280-pixel desktop viewport. No new console error appeared
  during this migrated-database smoke; historical pre-fix sidebar errors remain
  visible in the browser's retained diagnostic history only.

## Open gates

- Store and enforce the exact authority source used by every ordinary actor and
  approver when issuing root grants or roles.
- Mount a contextual assignment editor and computed effective-access
  explanation before enabling department-owned browser mutations.
- Add the synthetic Awoostria-shaped department/position template and hierarchy
  workflow; never copy a public volunteer roster into fixtures.
- Rehearse the complete sequence against a representative restored deployment
  with old-writer, fix-forward, backup, and PITR evidence.
- Complete accessibility, denied/error/stale visual states, and owner-led
  tutorial rehearsal.

## Resume point

Address authority-source provenance before mounting the hierarchy/editor slice.
Preserve the non-participating platform-administrator invariant and deny access
whenever scope or provenance cannot be proven from current database records.
