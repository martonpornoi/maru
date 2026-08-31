# Checkpoint: Programme item and readiness foundation

- Date: 2026-08-31
- Issue: [#61](https://github.com/martonpornoi/maru/issues/61)
- Parent umbrella: [#48](https://github.com/martonpornoi/maru/issues/48)
- Phase: Progressive adoption and pre-production release evaluation
- Related requirements: PRG-005, PRG-006, PRG-008, PLN-004, EVT-006,
  EVT-007, AUD-001, AUD-003, AUD-005, PRI-001, NFR-002, NFR-003, NFR-008
  through NFR-010, and NFR-013
- Related decisions: ADRs 0001, 0003, 0005, 0041, 0051, and 0081; no new ADR

## Outcome

Maru now has an installed but dormant `maru.programme` bounded context. It
owns canonical edition-scoped Programme items, structural provenance, separate
working/delivery/Department-discussion histories, explainable readiness
requirements and evidence, immutable reviewed public-copy renditions, and
reasoned idempotent command receipts.

Seven protected commands and bounded layer-specific queries implement the
private domain contract. Neither current adoption profile includes Programme,
the runtime role remains read-only for its relations, and no caller, route,
destination, handler, worker, setup path, or public timetable is activated.

## Decisions

- The canonical item contains identity and closed codes only. Private working,
  delivery, discussion, readiness, and reviewed public-copy information remain
  structurally separate, retain rationale histories, and have independent
  disclosure ceilings.
- Organizer-created core items cover ceremonies, breaks, announcements, and a
  bounded organizer-defined kind. A typed accepted-Applications source binding
  is reserved without implementing ingestion or copying proposal/review data.
- Aggregate transitions use optimistic versions, normalized request digests,
  immutable retry receipts, minimized audit, and one registered event/outbox
  fact in the same success transaction.
- Public-copy approval uses its own rendition sequence and event aggregate. It
  neither changes the private item/readiness cursors nor claims publication.
- Readiness is an evidence/source-version projection, never a score or inferred
  completion. New concerns begin at the latest applicable working or delivery
  dependency version; evidence becomes stale only when its dependency changes.
- Identity, Events, and Authorization expose minimized identifier-only public
  seams. Programme carries opaque IDs and an Events-owned lifecycle admission
  boolean, never another domain's private model instance.
- A non-default authorizer is an automated-test seam only when both the test
  setting is enabled and the connected database name begins with `test_`.
- The additive capability vocabulary advances Authorization policy attribution
  to `2026-08-31.1`. Existing profile manifests remain literal and unchanged:
  `full_convention@1` is
  `e0081b116f8af045fd5a9195c1f4f3295b20d3c57163e8ef0a3547f86861df81`;
  `workforce_only@1` is
  `66ad0e96a641d99e163d735d612dd2138c96ef0af619cfac57839695d09c2ad0`.

## Changed areas

- Programme models, catalogs, inputs, authorization, commands, queries,
  readiness projection, event contract, adoption/dormancy checks, migrations,
  and closed writer boundary.
- Public Identity/Events reference queries and Authorization's identifier-only
  exact-edition policy adapter.
- Authorization capability migration/catalog attribution, Effects registry and
  explicit dormant-event handling, readiness health, database-role safety, and
  current-profile adoption checks.
- Product, domain, module, security, operations, setup, roadmap, backlog,
  changelog, and current-state documentation.

## Verification

- Pre-delivery local evidence includes 76 DB-free Programme unit tests, 75
  foundation/shared unit tests, 19 documentation-policy tests, and 30 isolated
  PostgreSQL Programme schema/readiness drift tests.
- The first combined ten-file PostgreSQL scope exposed one stale assumption
  that every registered event has an internal handler. After the closed
  registry was corrected to distinguish handled events from the deliberately
  dormant, unhandled Programme event, a fresh isolated PostgreSQL 17.11 rerun
  passed all 460 tests in 317.59 seconds.
- The repository-wide pre-delivery gate passes package construction and
  dependency audits, Ruff formatting/lint, MyPy across 401 source files,
  semantic and strict docstring validation, warning-fatal Sphinx/AutoAPI,
  migration drift, local and production Django checks, OpenAPI regeneration,
  and Staff Console generation, type checking, 33 tests, and production build.
  Full clean-tree exact-commit certification remains separate delivery
  evidence for the commit that is ultimately pushed.
- The installed Authorization function fingerprint is
  `4b858dd2d560cfb53d9589dbe56f97828d29c9007e9666e50adef53d3bb87a14`.
  Exact capability-migration and unchanged-manifest assertions are part of the
  focused PostgreSQL scope.
- Protected pull-request acceptance is authoritative only for the exact pushed
  head and is not claimed by this checked-in checkpoint.

## Data, migration, and deployment notes

- Programme `0001` creates 11 empty relations; `0002` installs exact scope,
  lifecycle, closed-code, append-only, contiguous-version, source-chain,
  receipt, truncate, and transition-evidence guards; `0003` adds the early
  populated downgrade fence. Authorization `0020` adds exact-edition scope
  support for the nine dormant capability codes, plus a populated downgrade
  fence and exact reversal.
- The health dependency fingerprints the exact Programme relation set, columns
  and collations, complete constraint/index definitions, durability and row-
  security metadata, functions, triggers, owners, and ACLs. Its 207-object
  immutable catalog is data-free readiness evidence, not profile activation.
- Empty reversal is exact. With durable Programme data, `0003` refuses early;
  `0002` and `0001` repeat same-transaction `ACCESS EXCLUSIVE` preflights
  immediately before guard and table removal. Refusal preserves the schema and
  migration evidence.
- The runtime role receives `SELECT` only on all Programme relations and no
  Programme function execution. Deployment seeds no Programme or cross-module
  row and does not change any edition's profile pair.
- Recovery fixes forward or restores Programme, Audit, Effects event/outbox,
  and migration history from one mutually consistent whole-database point.

## Known risks and incomplete work

- This foundation has no usable Programme workspace. Calls, hosts, accepted-
  item ingestion, Scheduling, Venue placement, staffing, release, public or
  personal timetables, on-site continuity, setup, and browser acceptance remain
  absent.
- Active-use retention approval, production recovery rehearsal, deployment,
  owner acceptance, and production-data authorization remain separate gates.
- The exact schema fingerprint is intentionally PostgreSQL 17-specific and any
  reviewed schema change must update migrations, drift tests, and immutable
  catalog evidence together.

## Recommended next actions

1. Add Programme calls, purpose-scoped host/co-host collaboration, and preview-
   first import while keeping `programme_operations@1` inactive.
2. Follow with staged Applications review/decisions and the typed accepted-item
   adapter, then Scheduling core and its accessible editor.
3. Complete staffing, release/outputs, on-site continuity, profile activation,
   and integrated browser/recovery acceptance in umbrella dependency order.
