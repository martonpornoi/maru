# Checkpoint: Exact adoption manifests

- Date: 2026-08-31
- Issue: [#59](https://github.com/martonpornoi/maru/issues/59)
- Parent umbrella: [#48](https://github.com/martonpornoi/maru/issues/48)
- Phase: Progressive adoption and pre-production release evaluation
- Related requirements: EVT-006, NFR-002, NFR-003, NFR-013
- Related decisions: ADR 0080 and ADR 0081; no new ADR

## Outcome

The executable `full_convention@1` and `workforce_only@1` adoption profiles are
now immutable exact-version manifests rather than module-level hints. Each
manifest pins literal capability, destination, shell-kind, effect-route,
catalog-entry, adapter, conflict-source, reserved-root, and primary-module
values. Runtime consumers use the edition's persisted profile code and version
and fail closed when that exact pair or requested value is absent.

This is the enforcement prerequisite contracted by the Programme Operations
architecture. It deliberately does not declare or activate
`programme_operations@1`.

## Decisions

- Exact-version manifest lookup precedes edition capability policy, including
  self, platform, direct-grant, and role paths.
- An ordinary role bundle is usable only when every one of its capabilities is
  pinned by the exact manifest; reserved roots are pinned explicitly.
- Organization- and platform-scoped Effects routes use a separate explicit
  non-edition catalog, while edition routes require the exact manifest pair.
- Applications, Workforce, Registration, navigation, page context, access
  management, and Effects use typed catalog/adapter checks rather than
  module-name inference.
- Each adapter and future conflict source belongs to one immutable owner
  registry and declares both trustworthy-result and fail-closed semantics.
- `events.E001` resolves every manifest member against independent registries,
  enforces owner/adopted-module boundaries, and requires the retained,
  selectable, and database-supported exact pairs to agree. `effects.E001`
  remains authoritative for registered event/handler resolution.
- The global module and member catalogs are declarations only. Both v1 module
  and member sets are independent literals and do not expand when a future
  registered module, capability, destination, catalog entry, adapter, conflict
  source, or root role appears.
- Current v1 creation digests remain stable. A future profile version must
  include its version in new evidence rather than rewriting historical v1
  receipts.
- Historical edition-creation replay resolves its retained exact pair before
  today's selectable version and expansion policy; only a new idempotency key
  uses current selection.
- An edition profile remains immutable. Recovery never changes a persisted
  pair or silently widens an existing manifest.

## Changed areas

- Events owns the immutable manifest registry, exact lookup/filter helpers,
  creation validation, independent current-pair database catalog/constraint,
  and value-safe deployment compatibility check.
- Authorization gates capabilities, targets, role bundles, and access
  workspaces against the exact edition manifest, including incompatible dormant
  provenance.
- Core navigation and context disclose only exact-profile destinations and
  shell kinds; repository tests cross-check Python/TypeScript Staff Console
  tokens and every emitted navigation kind. My Context additionally projects
  Workforce's exact assignment-evidence semantic so both Staff Console copy
  sites never infer Participation evidence from module membership. A selected
  edition also filters governed Specialist records and direct edition-owned
  admin routes by the exact pinned module; foundation and unregistered global
  incident/recovery administration retain their independent permission rules.
- Applications gates starters, self-purpose routes, source adapters, and target
  adapters at discovery and command time. Missing accepted-target support
  discloses and writes nothing.
- Effects gates publish, secondary enqueue, worker dispatch, and replay, adds a
  route-compatibility system check, exposes tenant-safe quarantine status, and
  retains each bounded replay decision in an append-only receipt.
- Communications self-inbox and direct read mutations require the originating
  event's exact notification route before rendered content is loaded. Workforce
  keeps the internal Identity restriction fact but pins no edition notification
  route and therefore writes no Communications state; the explicit non-edition
  organization route remains independent.
- Registration discovery and direct self routes, Catalog checkout/payment, and
  Logistics retained-offer routes deny before private-row loading when the
  exact profile is incompatible. Registration guardian-token continuation,
  lifecycle/tier-replacement workloads, metrics, payment-intent APIs, and
  identified-intent webhook reconciliation repeat that boundary before owned
  row projection or mutation; truly unknown provider references remain a safe
  organization-scoped exception. Scheduled restriction consequences use
  explicit exact-profile adapters for their Registration and Accreditation
  consumers. Workforce templates and Position-assignment Participation
  evidence consume exact profile adapters/catalog entries, and the assignment
  database guard now resolves the exact code/version pair.
- Product/module/operations documentation and the current roadmap now state
  the same boundary and ordered Programme continuation.

## Verification

- All 2,358 unit tests pass. The complete 283-test PostgreSQL database-role
  safety suite and focused exact-profile consumer suites pass for Events,
  Authorization, Applications, Effects, navigation, Registration, Venues,
  Workforce, and cross-profile isolation. The five edition-creation and
  historical-replay cases pass again after the database-catalog refactor.
- Staff Console TypeScript checking and 33 frontend tests pass. Ruff lint and
  formatting, MyPy across 388 source files, Django compatibility checks,
  migration-drift checks, PyDocLint, semantic docstrings, documentation policy,
  the warning-fatal Sphinx/AutoAPI build, and `git diff --check` pass.
- The final combined matrix, exact clean-tree certification, and protected
  pull-request gate remain authoritative for the delivered commit.

## Data, migration, and deployment notes

Two additive hardening migrations accompany the unchanged EventEdition pair
constraint. `effects.0003_effect_replay_receipts` adds tenant-bound append-only
replay rationale and makes every retry-budget increase depend on its exact next
receipt; actors must be active accounts, the runtime role has SELECT/INSERT
only, initial and replay budgets share a database-enforced ceiling of 100, and
downgrade is refused after the first receipt exists. Activation refuses legacy
outbox rows already above that ceiling instead of silently rewriting them.
`workforce.0015_exact_assignment_adoption_profile` replaces the reviewed
assignment guard with exact code/version branching and refuses downgrade after
governed assignment evidence exists. Neither migration rewrites existing rows.

The EventEdition constraint still accepts only the current
`full_convention@1` and `workforce_only@1` pairs and builds from an independent
immutable database-support catalog that compatibility checks must match to the
manifest registry. Existing creation paths write those exact versions. This
change does not activate a new profile, grant authority, add navigation, or
change production settings.

The checked-in runtime-role provisioning example is the evolving deployment
baseline and now narrows the replay-receipt relation after migrations. The
synthetic OCI rehearsal remains independently bound to the immutable
`be0b21d` release source and its reviewed SQL digest; neither that release pin
nor its image identity changed in this issue.

Forbidden Effects publication produces no new delivery. Queued work that no
longer matches its exact scope/profile route is quarantined before invoking a
handler, with bounded tenant-safe reason groups available to operators. Replay
rationale is normalized to 240 characters, one replay adds at most 20 attempts,
the cumulative limit is 100, and bounded tenant-scoped history is inspectable
without event payload disclosure. Replay revalidates the persisted exact route
before appending rationale or mutating the quarantined row.

## Known risks and incomplete work

- `programme_operations@1` remains a target contract only. There is no runtime
  Programme or Scheduling module, operator role, setup route, adapter,
  publication, or migration yet.
- External catalog growth still requires an explicit new exact profile version,
  database-guard migration, compatible web/worker release, and activation plan;
  it must not mutate a v1 manifest.
- Production recovery, deployment, retention, offline operation, and partner
  acceptance remain separate gates.

## Recommended next actions

1. Implement the private Programme item/readiness aggregate and
   organizer-created core-item workflow.
2. Continue through Applications intake/review adapters, Scheduling,
   accessible editing, staffing, release projections, and continuity/export.
3. Activate Programme Operations setup, authority, exact manifest, database
   guards, and integrated recovery acceptance only after those continuations
   exist.
