# Current project state

Last updated: 2026-08-16
Phase: Production consolidation and management-experience recovery. The
canonical repository gate and scoped read-only Logistics browser journey remain
accepted. ADR 0055's first task-oriented management slice is repository-
verified; its complete authenticated reflow, keyboard, screen-reader, and owner
matrix remains open alongside deployment, stopped-writer/cutover, restore/PITR,
and production-governance gates.
Branch: `codex/current-tree-consolidation`

## Current outcome

Maru remains one Django/PostgreSQL modular monolith with one administration
shell, one authorization lattice, one audit/outbox boundary, and one
registration per person and edition. The current working tree adds the
following executable journeys without restoring the legacy global-project or
cross-domain-save design.

### Navigation, My Maru, and Access

- ADR 0049 replaces selected-edition folder menus with one code-owned,
  permission-filtered, searchable navigation registry. Stable destinations may
  be pinned, but every render resolves and authorizes the pin again.
- `/my/` is the authenticated personal surface for registration/profile,
  payments and upgrades, applications, catalog orders, and published schedule.
  Attendees receive the shared identity/navigation grammar without being
  treated as administrators.
- Mounted management pages receive a computed Access explanation. The global
  component resolves organization, edition, exact Department, and typed
  resource scopes. Fixed self/public/attendee/safeguarding/security policies
  explain why mutation is unavailable instead of inventing page ACLs.
- Exact-person and immutable-role preview is signed, capped, audited, and
  read-only. It never changes session identity, authority, POST authorization,
  or audit attribution.

### Management-experience first slice

- ADR 0055 makes the management experience task-oriented without introducing a
  second shell or security boundary. The default navigation now prioritizes
  durable work, keeps contextual creation commands out of the primary list,
  and progressively discloses authorized specialist records while retaining
  them in code-owned search.
- Search uses labels, descriptions, and stable task keywords, so ordinary terms
  such as `users`, `staff`, `volunteers`, and `board` resolve the relevant
  authorized destinations. The platform destination is now **User accounts**;
  one-shot actions are not pinnable.
- The administration home starts with current work and **Continue setup** rather
  than duplicating the complete model directory. The first coherent task path
  continues from User accounts through invitation outcomes to Page 8's visible
  three-step Executive Board ceremony without changing any identity,
  invitation, representation, or authority service.
- At 1,100 CSS pixels and below the sidebar becomes a closed overlay drawer
  with backdrop, close control, Escape dismissal, focus containment/return, and
  background scroll lock. The convention-context control now shrinks with the
  available width and wide tables are contained instead of widening the page.

### Private API reference

- ADR 0056 retains `/api/v1/schema` as the one authoritative OpenAPI contract
  and adds private Swagger and ReDoc views at `/api/v1/docs/` and
  `/api/v1/redoc/` for an active platform administrator.
- The three routes recheck persisted platform authority, fail closed, are
  private/non-cacheable/non-indexable, and are excluded from credentialed
  registration-client CORS. Swagger submit methods are disabled.
- Pinned sidecar assets are served locally and ReDoc makes no external font or
  CDN request. The controlled `maru.baseline_urls` surface remains JSON-only.

### Parallel GitHub acceptance

- The former single 45-minute GitHub job could not represent the recorded
  4:19:18 canonical suite and failed before tests because its duplicated
  production fixture omitted the four invitation public/digest settings.
- One deterministic production-settings verifier now strips inherited Maru
  configuration, supplies synthetic verification-only invitation material,
  excludes worker private keys, and checks both exact-provenance modes in
  isolated subprocesses. Local PowerShell and GitHub call the same verifier.
- GitHub acceptance is split into static, Django/generated-contract, frontend,
  unit, 12 isolated PostgreSQL integration, combined-coverage, dependency-
  security, and stable `CI gate` jobs. Integration files remain whole and
  serialized within each shard; only isolated runners/databases run in parallel.
- Unit and shard JUnit/coverage artifacts feed one branch-aware 90-percent
  verdict. Matrix fail-fast is disabled, superseded pull-request runs are
  cancelled, and reviewed external actions plus PostgreSQL 17.11 are pinned by
  immutable digest.

### Registration, profile, and admission commerce

- Page 10 mounts recipient-owned platform invitations, copy-on-write
  Registration setup, the immutable `convention-registration` starter,
  governed section/question/product/minor/profile-definition commands, and
  strict HTML/API adapters.
- REG-022 profile extensions use closed reader audiences (`self`, exact
  Registration staff, one exact active Department, confirmed attendees, or
  public) with a separate writer policy. Values are append-only,
  sequence-fenced, scope-idempotent, audited, and immediately removed from
  confirmed/public projections when directory consent is withdrawn. Platform
  administrator identity alone grants no value access. Self and exact-staff
  same-shell value editing is mounted; optional typed clearing uses canonical
  JSON null and remains forbidden for required fields.
- ADR 0050 mounts same-attendee upward admission replacement with a target hold
  and authenticated exact-price-difference payment. The source admission stays
  effective until success, success leaves exactly one entitlement, and expiry
  releases only the target hold.
- Current overall/product capacities derive from append-only adjustments under
  configured hard ceilings. Wait-list staff choose a batch size; the service
  chooses the next eligible people in strict FIFO order and records actor/time
  evidence.

### Typed Applications

- ADR 0051 adds the bounded `applications` module. Ten immutable code-owned
  starters cover shirt/merchandise, DJ, dance competition, Maid Cafe, adult
  performance, volunteer, feedback, idea, damage, and helper-availability
  workflows. Registration is a separate external starter entry; a panel
  starter/programme adapter is not yet present.
- Organizers copy a starter into an edition-owned draft, configure closed typed
  sections/questions, eligibility/cardinality/windows, exact owner
  Departments, and named or immutable-role reviewers, then activate, retire,
  or create a traceable successor.
- Applicants discover only eligible edition scopes, keep typed revisions, and
  submit without creating another registration. Assigned reviewers receive
  policy-filtered answers and append reasoned decisions with exact provenance.
  Acceptance writes a closed typed transition receipt; a downstream domain
  still needs an explicit adapter before a programme item, workforce
  assignment, SecOps record, or merchandise object exists.

### Charity, Catalog, and commerce

- ADR 0052 adds reusable organizer-owned charity partners without making them
  Maru tenants. Each edition owns its exact Department, proposal, review,
  confirmation/rejection, private comments/reason, media approval, and
  independent publication evidence. Public reads release only current active,
  confirmed, explicitly published minimized snapshots.
- The bounded `catalog` module owns edition products, variants, sale/preorder/
  fulfilment policy, exact confirmed-charity beneficiaries, finite hard-ceiling
  stock, immutable order-line snapshots, attendee orders, payment intents,
  provider events, and purpose-limited staff activity. Catalog products never
  become admission entitlements.
- Same-shell attendee and staff journeys support catalog definition,
  activation, stock, order history, hosted/demo payment, and activity. All
  authenticated GET/API surfaces are private/no-store and authorize exact
  scope or ownership before parsing untrusted input.

### Venues and schedule projection

- ADR 0053 adds reusable properties, sites, buildings, spaces,
  configurations/combinations, governed media/layout references,
  accommodation room-night inventory, and explicit edition venue/space
  selections.
- Edition selections snapshot immutable physical members. Versioned hard
  availability, configured/fire capacity, and PostgreSQL exclusion constraints
  reject unsafe bookings across combined rooms while permitting an earlier
  teardown to overlap a later setup.
- Booking creation/reschedule, independent approval, independent publication,
  withdrawal, and cancellation are executable through strict HTML/API
  boundaries. Public and participant-authorized My schedule projections expose
  only approved effective information and approved public layouts, never
  setup/teardown or internal/security detail.

### Bounded Logistics

- ADR 0054 defines people as custodians rather than locations and physical
  keys as inventory rather than software authority. The mounted bounded slice
  contains person-owned equipment offers, external provider/owner identity,
  retention-bound restricted contacts, typed acyclic site/area/rack/container/
  box/vehicle/staging/venue nodes, serialized assets, stock lots, keys and
  keyholders, loan/rental return obligations, kits, manifests, digest-only
  labels, discrepancies, Stage Tech receiving, and bounded offline batches.
- Current containment, quantity, condition, location, and custody derive only
  from append-only receive/pack/unpack/move/load/unload/handover/count/
  condition/damage/return events. Personal location and continuous vehicle/GPS
  telemetry are explicitly outside the product.
- The ordered `venues 0001 -> logistics 0001 -> authorization 0016 ->
  logistics 0002` graph,
  exact bindings/guards, API/UI/navigation/Access, runtime-role provisioning,
  fail-closed readiness, and deterministic demo seed passed the final
  serialized PostgreSQL acceptance matrix. This accepts the bounded slice in
  the repository; it is not production deployment or completion of the full
  LOG portfolio.

## Verification recorded for this outcome

The 2026-08-11 canonical acceptance supersedes the earlier focused-suite counts
as the repository-wide gate:

- Ruff formatting and lint passed over 624 files; strict mypy passed over 355
  source files; collection found exactly 4,067 tests.
- The serialized canonical PostgreSQL-backed suite passed 4,067 of 4,067 tests
  in 15,558.23 seconds (4:19:18) with 90.78 percent total branch-aware
  coverage. The coverage repair added behavior and security matrices in
  Registration and Identity without exclusions, pragmas, or a threshold
  change.
- The repair exposed and fixed two genuine adapter/form defects: Registration
  setup dependency failures are caught before the broader command-error class
  and therefore retain their `503` contract, and canonical UUID form handling
  now follows the documented lower-case, hyphenated, version-agnostic shape.
- Installed module readiness, function/relation ACL, runtime-role, migration-
  graph, tenant/field/object denial, and deterministic OpenAPI/frontend checks
  passed. Migration drift is zero; Django check reports only the expected
  fail-closed `identity.W001` warning.
- A live registry-enabled dependency audit found four advisories in
  `cryptography` 46.0.7 (`PYSEC-2026-3552`, `PYSEC-2026-3553`,
  `PYSEC-2026-3554`, and `GHSA-537c-gmf6-5ccf`). `pyproject.toml` and `uv.lock`
  now select 50.0.0, the environment was synchronized, and the repeated live
  audit exits zero with no known vulnerabilities; local `maru` is skipped only
  because it is not published on PyPI. After the upgrade, the fresh invitation/
  cryptography matrix passed 639 of 639 tests in 219.69 seconds and the full
  unit suite passed 1,815 of 1,815 in 68.62 seconds.
- Two direct-database concurrency harnesses now use one-row `bulk_create` to
  bypass model `full_clean` and genuinely race the unique constraints. Their
  fresh 2-of-2 run and a combined 24-of-24 repeated stress run pass.
- Authenticated scoped read-only Logistics browser rehearsal passed at 1,920
  and 390 pixels. It does not cover broader Logistics mutation roles, every
  module's visual states, keyboard traversal, or automated accessibility.
- The ADR 0055 first slice passed seven focused source-contract/unit tests and
  all 56 focused rendered integration behaviors covering administration home,
  navigation/My Maru, unified routing, User accounts/invitations, and Page 8.
  Ruff formatting/lint, strict mypy for the navigation registry, Django checks,
  and whitespace validation pass. The Django check retains only the expected
  local fail-closed `identity.W001` warning when invitation encryption is not
  configured.
- The ADR 0056 API-reference matrix passed 33 focused unit and 7 focused
  PostgreSQL-backed integration tests. Ruff formatting/lint and strict mypy
  pass for the changed source/test paths; static dry-run includes the sidecar
  assets. Fresh OpenAPI 3.1 validation reports zero errors and exactly matches
  checked-in `openapi.yaml` at SHA-256
  `bc65826a8ceb93ca5cbe5e977e9f71dac50430c8168feb5c673fa8f0dccbb6fb`.
- The parallel-CI candidate passes the complete 1,841-test unit suite in 56.68
  seconds and its 18 focused verifier/shard/workflow-contract tests. Ruff
  formatting/lint passes over 633 files, strict mypy passes over 356 source
  files, the 78-package lock is current, and documentation validation passes
  over 242 Markdown files and 202 requirement identifiers. YAML loading,
  deterministic 157-file/12-shard inventory validation, and both real
  production-settings modes also pass. The initial remote matrix completed all
  twelve PostgreSQL shards: ten passed, while two failed one stale rendered-copy
  assertion each. The slowest successful shard completed in 1 hour 22 minutes
  51 seconds, inside the new 90-minute boundary. Audit found one adjacent
  false-positive selector assertion with the same pre-ADR-0055 wording. All
  three assertions now pin the current **Change workspace**, active-authority,
  and governance-invitation contracts and pass locally. The current commit's
  complete matrix, combined coverage, and stable `CI gate` are the corrective
  remote acceptance authority.

These results accept the repository gate and that bounded browser slice. They
are not deployment, production-readiness, recovery, accessibility, or owner
approval.

## Decisions and migration boundary

- ADRs 0049 through 0056 are Accepted. ADR 0054 accepts the bounded architecture
  and migrated integrity boundary; it does not declare the partial
  LOG-001/002/003/004/006/007 portfolio complete or approve production rollout.
- ADR 0055 changes presentation and experience evidence only. It adds no model,
  migration, authority, disclosure, recovery, or production-cutover boundary.
- ADR 0056 narrowly supersedes ADR 0030's no-browsable-documentation clause for
  the default URL configuration. It adds no model, migration, API operation,
  schema shape, generated-client, tenant, authority, runtime-role, recovery, or
  production-cutover boundary; the raw schema is now platform-admin-only.
- Registration migrations `0035` through `0040` and the Applications,
  Charities, Venues, Catalog, and Authorization migrations preserve immutable
  source/evidence bindings, append-only history, downgrade fences, and exact
  typed-resource scope. Apply migrations in dependency order; do not run an
  older writer after evidence exists or reverse one module from a cross-module
  binding chain.
- Workforce `0008` follows Workforce `0007` and the Registration `0039`,
  Applications `0001`, Charities `0001`, Venues `0001`, and Logistics `0001`
  Department-FK creators. It replaces only the closed Department-reference
  allowlist; reversing it restores the `0007` helper and therefore blocks hard
  deletion while successor references remain installed.
- Venues `0001` is the single migration owner of the shared PostgreSQL
  `btree_gist` extension. Logistics `0001` depends on it and adds the Logistics
  tables, Authorization `0016` follows with capabilities and the manifest
  resource kind/binding, and Logistics `0002` installs app-owned exact-binding
  and append-only guards. This graph removes Logistics before the extension
  owner on a clean historical reverse; reversal must still refuse evidence
  that an older schema cannot represent.
- Invitation delivery, expiry, and retention scheduler evidence uses one
  materialized PostgreSQL clock observation. Invitation transitions, scheduler
  success, retention receipts, and terminal delivery/disposition evidence stay
  append-only or one-way at both application and database boundaries; runtime
  ACLs do not add delete authority.
- The invitation-retention implementation remains disabled until its current
  corrective candidate is independently accepted and a lawful deployment
  policy/digest, supervised worker, alerting, backup-expiry, and fix-forward
  rehearsal are approved.
- Production exact-authority/runtime-role activation has not occurred.
  Representative legacy reconciliation, stopped-writer cutover, backup/PITR,
  and the non-delegable runtime-login proof remain deployment gates.

## Known limits and production gates

- Applications is a typed intake/review kernel, not full KNO-009 or a complete
  programme/workforce system. It lacks a separately configurable staff answer-
  correction window, rich rubrics/conflict handling, and real downstream typed
  adapters.
- Charity satisfies FUR-011, not full FUR-005. Campaigns, donated value, costs,
  settlement, and public financial reporting remain absent.
- Catalog and admission commerce are bounded slices of REG/FUR/FIN. Real
  provider certification, unpaid-order expiry/cancellation, refunds/exchanges,
  shipping/fulfilment/handover, supplier evidence, and accounting export remain
  open. A scarce catalog supporter item is not an Infinity admission ticket.
- Venues satisfies the reusable-space and physical-occupancy boundary, not a
  complete timetable or hotel-allocation product. Programme ownership,
  schedule releases/comparison, person/equipment/qualification conflicts,
  operational layers, guest/block/fair allocation, and calendar/signage/print
  exports remain open.
- Logistics intentionally leaves department demand/reservation planning,
  optimized drivers/routes, supplier invoice linkage, low-stock/wastage policy,
  and complete loss/disposal planning partial or absent. A governed node
  retirement command is also absent, so an active storage node can retain its
  restricted address until that lifecycle is added.
- Charity/Venue media and layouts are governed references, not a production
  upload/object-storage/malware-scanning/rendition pipeline.
- SMTP, payment credentials, object storage/scanning, workers, telemetry and
  alerts, printers/scanners, representative load, automated accessibility,
  keyboard/visual-state rehearsal, partner legal/privacy/finance/safeguarding
  approval, production secrets, restore/PITR, and operator training remain
  external release gates.
- Maru must not receive production personal data or be described as production
  approved until the remaining deployment and governance gates pass.
- API-reference deployment must include and verify collected sidecar assets.
  A future strict Content Security Policy must nonce, hash, or externalize the
  documentation templates' inline initialization before forbidding inline
  script globally. The views are not a public developer portal.
- The task-oriented experience is currently converted only for the shared
  shell, administration home, navigation, User accounts/invitations, and Page
  8. Registration, Workforce, Venues, Logistics mutation roles, and specialist
  records still need conversion and the full 320/390/768/958/1,024/1,280/1,920,
  200-percent-zoom, keyboard, automated-accessibility, screen-reader, and owner
  evidence matrix.
- GitHub browser/accessibility, multi-Python compatibility, CodeQL, dependency-
  review, secret-scanning policy, nightly concurrency repetition, and release
  restore/attestation workflows remain later testing layers. The initial
  12-shard remote run diagnosed stale ADR-0055 UI assertions and is not
  acceptance. The current commit's complete corrective matrix must pass before
  the new `CI gate` is made the protected required check.

## Smallest sensible next actions

1. Confirm the current commit's corrective GitHub matrix, combined coverage,
   and `CI gate` pass; then make `CI gate` the protected required check and add
   the bounded pull-request Playwright/keyboard/automated-accessibility matrix.
2. Complete the authenticated ADR 0055 width/zoom, keyboard, screen-reader, and
   owner rehearsal for the first slice, then migrate the highest-frequency
   Registration, Workforce, and organization journeys to the same primitives.
3. Resume Page 10 compatibility-writer retirement/stopped-writer cutover,
   representative authority reconciliation/runtime-role activation, and
   whole-database restore/PITR rehearsal.
4. Complete provider/infrastructure, load, owner, privacy/legal, finance,
   safeguarding, and operating-governance acceptance before production use.

## Resume instructions

Read `AGENTS.md`, this file, `ROADMAP.md`, `PRODUCTION_CONSOLIDATION.md`, the
relevant requirement IDs, ADRs 0047 through 0055, and the owning module/runbook
docs. Preserve every concurrent change in the dirty working tree. Serialize all
PostgreSQL tests that share `test_maru_test`; never infer authority from a
selected edition or route; authorize before parsing untrusted input; retain
private/no-store on authenticated projections; and keep fixed/self/public
audiences separate from assignable scoped authority. Do not treat the canonical
repository result or scoped read-only Logistics browser result as broader
visual/mutation, deployment, accessibility, recovery, owner, or production
approval.
