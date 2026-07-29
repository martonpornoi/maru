# Checkpoint: V01 organization and edition kernel

Date: 2026-07-26  
Milestone: Tenant-isolated self context and durable edition history  
Version: `0.1.0a0`

## Delivered

- Organization tenant with lifecycle, locale/time-zone defaults, and
  case-insensitive stable slug.
- Convention series scoped to exactly one organization.
- Organizer membership as a separate account relationship.
- Event edition with direct organization/series scope, dates, time zone,
  languages, currencies, and explicit lifecycle.
- Reasoned, locked lifecycle transition command and history.
- Participation with multiple capacity records and opt-in public-history flags.
- Archive-time edition/series label finalization.
- PostgreSQL triggers guarding organization/series, organization/edition, and
  archive immutability even when model validation is bypassed.
- Self-only context and archived-participation REST endpoints.
- Deterministic two-organization, multi-edition reference fixture.
- Module documentation and repository-owned documentation validator.

## API

```text
GET /api/v1/me/context
GET /api/v1/me/participation-history
```

Both derive identity only from the authenticated principal. There is no
client-supplied account, organization, or edition selector.

## Verification

```text
uv lock: current and offline-verifiable
Ruff format/lint: pass (57 files)
strict mypy: pass (43 source files)
PostgreSQL migrations: apply from clean test database
migration drift: none
Django system check: pass
OpenAPI 3.1 validation: pass
pytest: 79 pass
covered source: 95.88%
documentation: 45 files, 164 unique requirements, all relative links valid
```

Tests include cross-organization non-disclosure, raw ORM scope bypass, archive
bulk-update bypass, terminal lifecycle, snapshot timing, anonymous denial,
scoped uniqueness, protected deletion, and duplicate identity/participation.

## Decisions and security

- No generic organization or edition API exists before V02 capabilities.
- Membership does not grant a broad organizer view by itself.
- Archive immutability is defense in depth at model, command, and database
  layers.
- Edition/series names are finalized while Closing and do not follow future
  renames.
- Cross-module archive finalization is one explicit command inside the same
  transaction; the later outbox is for post-commit effects, not this invariant.

## Incomplete

- Production authentication and account recovery.
- Capability grants, role bundles, field projections, audit, and outbox.
- Organization/series/participation mutation commands.
- Edition template cloning, departments, archive manifest/amendment API, and
  retention execution.
- A reusable full endpoint matrix will expand as V02 introduces staff/list/
  search/write endpoints; the present self endpoint has no target-selector
  attack surface.

## Resume point

Implement MARU-AUT-001 through MARU-AUT-004, starting with a declarative
capability catalog and scope intersection. Do not expose staff endpoints until
their query and field projections share the policy decision.
