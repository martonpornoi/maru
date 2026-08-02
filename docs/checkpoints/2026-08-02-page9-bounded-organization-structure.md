# Checkpoint: Page 9a.0 bounded Organization structure

- Date: 2026-08-02
- Phase: Production consolidation M2.4 / Page 9a.0
- Related requirements: IDN-002, IDN-004, IDN-009, IDN-011, IDN-012,
  EVT-002, HR-010, HR-011, UX-019, UX-020, UX-025, AUD-001, INT-001,
  NFR-001 through NFR-004, NFR-008, NFR-009
- Related ADRs: 0036, 0039, 0040, 0041, 0042, 0044, 0045, 0046

## Outcome

Page 9a.0 is one canonical read-only **Organization structure** workflow at:

```text
/admin/platform/organizations/<organization-slug>/series/<series-slug>/editions/<edition-slug>/structure/
```

The shared sidebar exposes it once beneath an authorized selected edition. The
old React Convention work `structure` destination and `?view=structure` link
are removed. The strict existing API GET now returns the same bounded
projection contract for supported clients.

The page composes **Executive Board** as a minimized organizations-owned
governance anchor above the workforce tree. It is never persisted, inferred,
or mirrored as a Department. Helper Board and every operational/nested node
remain real edition-owned Departments. A same-named legacy Executive Board
Department stays a separate operational record rather than being repaired or
treated as representation.

## Decisions

- Read requires `workforce.view_structure` effective at the exact edition.
  Manage-only, Department/resource-only authority, Django staff, Board visual
  placement, and selected-edition session state do not imply read.
- Active platform-administrator oversight remains explicit and
  non-participating.
- Department template-application/create/update/reparent/order/retire/delete controls are
  not mounted. They remain Page 9a.1 under ADR 0045.
- The immutable code-owned `awoostria-reference@1` catalog is implemented and
  pinned: exactly 22 Departments, Helper Board as sole root, no Executive Board
  Department, exact identifier without aliases, bounded graph validation,
  canonical UTF-8 JSON, and SHA-256 content evidence. It does not apply itself.
- Code owns ceilings of 256 Departments, 1,024 Positions, 4,096 effective
  holder relationships, depth 32 for Department and Position parent graphs,
  and 16,384 expanded other-role edges. A limit breach returns
  `structure_limit_exceeded` and zero Department rows.
- Holder labels are resolved only after the workforce relationship is current,
  its linked RoleAssignment has a supported exact scope shape and current
  pinned lineage, and identity confirms an active person account.
- Both adapters repeat fresh final authorization and append minimized
  `workforce.structure.read` sensitive-read audit before releasing labels.
  Audit failure is a safe name-free `503`.

## Changed areas

- canonical administration route, Page 9 template, recursive semantic tree,
  shared sidebar and selected-edition discovery;
- minimized organizations governance-anchor query;
- bounded workforce query and exact authorization/active-person label
  boundaries;
- recursive API serializer, typed RFC 9457 problems, OpenAPI, and generated
  TypeScript schema;
- removal of the duplicate React destination/client fetch/CSS; and
- product, module, API, security, testing, project, and tutorial documentation.

## Verification

- focused Page 9/API/capability-catalog/template suite: 52 passed in 15.66
  seconds;
- standalone populated structure query-count regression: passed;
- adjacent navigation/shell/admin/representation suite: 65 passed in 58.18
  seconds;
- OpenAPI generation with validation and generated TypeScript client:
  passed;
- TypeScript type checking, 19 Vitest tests, and Vite production build: passed;
- repository-wide Ruff, strict mypy, Django checks, migration drift,
  production-setting checks, OpenAPI/frontend gates, and whitespace: passed;
  and
- live authenticated desktop route: rendered the canonical Page 9 with one
  current canonical link, complete bounded tree and separate governance
  anchor, and no legacy query link, email, or rendered UUID.

The definitive full repository gate passes 1,239 tests in 1,172.87 seconds
with 90.35 percent branch coverage and no warnings. The in-app viewport
override did not reliably establish a 390-pixel Page 9 run, so no
narrow-viewport claim is made.

## Data, migration, and deployment notes

Page 9a.0 adds no database migration and writes no Department, Position,
assignment, membership, representation, participation, role, or capability.
The only request-side write is the minimized sensitive-read audit after fresh
authorization and before disclosure. A failure withholds the projection.

The API declares `200` plus RFC 9457 `400` for unsupported query input, `403`
for denied/unavailable scope, and `503` for database, integrity, policy, or
audit dependency failure. It does not use a distinct not-found response that
would reveal a foreign route.

## Known risks and incomplete work

- The bounded projector reads Departments, Positions, assignments, governance,
  and identity labels in several database statements. A concurrent structure
  write can produce a coherent but cross-version composition. Fresh final
  authorization closes authority expiry/revocation, not this data-snapshot
  risk.
- Page 9a.1 must add the edition structure aggregate/version fence and
  retry/conflict semantics before Department mutations are mounted.
- Built-in Awoostria application/receipt, Department commands, migration/
  downgrade/recovery rehearsal, mutation audit/events/outbox, and Page 9b
  Position management are not implemented; only the immutable catalog exists.
- Full pytest/coverage, reliable 390-pixel, keyboard/automated accessibility,
  complete state matrix, and owner tutorial evidence remain.
- Production authority reconciliation, load, cutover, representative restore,
  and PITR remain independent release gates.

## Recommended next actions

1. Implement Page 9a.1's additive structure control/version and immutable
   template-receipt schema, including populated-data preflight and recovery.
2. Add shared HTML/API Department commands with strict input, idempotency,
   optimistic concurrency, audit/event/outbox atomicity, retirement, and
   protected deletion.
3. Prove concurrent read/write version behavior, full repository coverage,
   reliable 390-pixel/accessibility states, and the owner walkthrough.
4. Keep Page 9b Position/authority-bearing management separate until its
   dual-control, typed-resource, opportunity, lifecycle, and recovery contract
   is complete.
