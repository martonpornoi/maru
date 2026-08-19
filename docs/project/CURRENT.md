# Current project state

Last updated: 2026-08-19
Phase: Production consolidation and management-experience recovery. The
canonical repository gate and scoped read-only Logistics browser journey remain
accepted. ADR 0055's first task-oriented management slice is repository-
verified. ADR 0057's NumPy docstring baseline and warning-fatal generated
contributor reference are repository-verified. ADR 0058's professional public
Python documentation contracts and semantic-quality gate are repository-
verified. ADR 0059's strict PyDocLint contract and bounded Ruff exemptions are
repository-verified. ADR 0060's collaboration/release foundation is locally
verified. Replacement run `32254074078` started no runner because GitHub
reports an account payment/spending-limit block. GitHub ruleset enforcement is
prepared but blocked by the repository's current private-plan capability; the
complete authenticated
reflow, keyboard, screen-reader, owner, deployment, stopped-writer/cutover,
restore/PITR, and production-governance gates remain open.
Branch: `codex/strict-python-documentation`

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

### Generated contributor documentation

- ADR 0057 documents public production Python and repository tooling with
  NumPy-style docstrings. ADR 0058 strengthens that baseline: every public
  callable documents named parameters and meaningful return/yield values,
  directly raised exceptions are explicit, and public dataclasses document
  their fields. Ruff's complete rule catalog enforces the fast style baseline,
  PyDocLint checks sections against signatures, and annotations remain the type
  authority.
- ADR 0059 enables PyDocLint's viable private-callable, star-argument, type,
  default, return/yield-type, assertion, and exact direct-raise checks. The
  constructor contract now lives beside `__init__`; the semantic gate remains
  responsible for public dataclass fields because PyDocLint's general
  class-attribute inference misclassifies Django declarative classes.
- Ruff still selects every rule. Its global ignore set is halved from sixteen
  entries to eight bounded categories: explicit dynamic `Any`, formatter
  compatibility, separately reviewed complexity/argument-count refactors, and
  local exception-message clarity. Missing annotations, magic/nested-class
  docs, redundant raises, private access, and type-only imports are no longer
  globally exempt; tests and named framework adapters carry only scoped
  exceptions.
- The pull-request CI correction preserves that boundary: test-only private
  access is scoped by the test-tree rule, 59 intentional Django, DRF, and
  schema-generator accesses in 26 production files carry exact line-level
  `SLF001` evidence, and avoidable project-owned private accesses were replaced
  with documented APIs. `src/manage.py` is executable for Linux lint parity,
  while the direct `sqlparse>=0.6,<0.7` security floor prevents resolution to
  the vulnerable 0.5.5 release.
- A repository semantic gate rejects recognizable placeholder summaries and
  descriptions, missing direct `Raises` entries, and missing dataclass
  `Attributes`. Notes, Examples, Warnings, and See Also remain judgment-based:
  they are required when they clarify authorization, failure, transaction,
  idempotency, canonicalization, or sensitive-value behavior, not as filler.
- Sphinx combines every maintained Markdown document with a statically
  analysed public AutoAPI reference. MyST, Napoleon, Mermaid, and Furo render a
  warning-clean HTML contributor portal without importing Django or connecting
  to PostgreSQL.
- Tests and generated migrations retain explicit documentation exclusions.
  GitHub validates docstrings, performs a fresh warning-fatal build, retains the
  HTML artifact, and requires the result through the stable `CI gate`.

### Change-aware GitHub acceptance and releases

- The former single 45-minute GitHub job could not represent the recorded
  4:19:18 canonical suite and failed before tests because its duplicated
  production fixture omitted the four invitation public/digest settings.
- One deterministic production-settings verifier now strips inherited Maru
  configuration, supplies synthetic verification-only invitation material,
  excludes worker private keys, and checks both exact-provenance modes in
  isolated subprocesses. Local PowerShell and GitHub call the same verifier.
- ADR 0060 makes pull-request acceptance change-aware behind one stable
  `PR gate`. Documentation-only changes start no PostgreSQL service; ordinary
  Python changes run unit plus bounded affected integration tests; migrations,
  models, settings, dependencies, security/authority boundaries, workflows,
  and test harnesses fail closed to full acceptance. Protected or mass
  deletion needs the maintainer-applied `destructive-change-reviewed` label.
- Reusable full acceptance keeps every integration file whole and serialized,
  but uses six isolated measured-duration shards rather than twelve source-size
  shards. The timing map from accepted run `31964200663` covers all current
  files and balances each shard near 3,536 weighted seconds. Unit and shard
  JUnit/coverage artifacts feed one branch-aware 90-percent verdict through
  stable `Full CI gate`; matrix fail-fast remains disabled.
- Candidate and gold releases are manual, exact-current-`main`, full-certified,
  collision-refusing CalVer workflows. GHCR receives the non-root Django/
  Gunicorn image by immutable digest with OCI SBOM and provenance. GitHub
  receives docs, OpenAPI, locks, manifest, license, and checksums. No release,
  tag, package, or visibility change was made by this milestone.
- Apache-2.0, contribution/conduct/security/support/governance policies,
  CODEOWNERS, issue/PR templates, Dependabot grouping, public-readiness steps,
  and reviewed ruleset payloads prepare the private repository for later public
  collaboration without implying production support.

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
- The ADR 0057 contributor-documentation change passes Ruff formatting and the
  complete ALL-rule lint baseline over 634 files, strict mypy over 356 source
  files, PyDocLint over public production source and scripts, Python bytecode
  compilation, and the 245-Markdown/202-requirement documentation validator.
  A fresh warning-fatal Sphinx build completes over the maintained prose and
  static AutoAPI reference. All 1,842 unit tests and the five CI workflow-
  contract tests pass. Django reports no migration drift and only the expected
  local fail-closed `identity.W001` warning; both isolated production-settings
  modes pass. The source-derived endpoint descriptions intentionally refresh
  OpenAPI and the generated TypeScript comments without changing schemas; a
  repeated OpenAPI 3.1 generation has zero errors and exactly matches the
  checked-in artifact at SHA-256
  `79ae8f720e6ce942413e19cb1a973480554159364abecf8ba64ea01b0a035b1c`.
- The ADR 0058 professional-documentation follow-up passes Ruff formatting and
  the complete ALL-rule lint baseline over 636 files, strict mypy over 356
  source files, PyDocLint with short-docstring checks enabled, and the semantic
  validator over 360 production/tooling files. The 247-Markdown/202-requirement
  documentation validator and a fresh warning-fatal Sphinx/AutoAPI build pass.
  All 1,844 unit tests, including seven documentation/workflow contract tests,
  pass; 106 focused tests for the curated parsing, normalization, and API-input
  examples also pass. Regenerated OpenAPI 3.1 reports zero errors and the
  generated Staff Console definitions typecheck; the resulting artifacts have
  SHA-256 `197bb0b34b6454298e70d9067a7cad72f6680d6a92ae3879f644c0c85a38b050`
  and `7c6efccd9d4c44a63b519d167f8220bdd760f077370149b08a9e9e5f02e67b24`,
  respectively. Schema generation retains its 18 existing enum-name warnings
  and the expected local fail-closed `identity.W001` warning.
- The ADR 0059 strict-contract follow-up passes Ruff formatting and ALL-rule
  lint over 636 files, PyDocLint's strict useful configuration and the semantic
  validator over 360 production/tooling files, and strict mypy over 356 source
  files. Documentation validation passes 249 Markdown files and 202 unique
  requirement identifiers; a fresh warning-fatal Sphinx/AutoAPI build passes.
  All 1,847 unit tests pass in 60.20 seconds, and repository-wide collection
  succeeds for 4,104 tests. Regenerated OpenAPI reports zero errors, its Staff
  Console definitions typecheck, and the artifacts have SHA-256
  `cbd3cd981fd9b9ae60e8f11745bc759acc6a491af390574b2b62d2ed54e642d0`
  and `1d82884c2d4fc5a0fd7c831dd4b37fb4932ef11df215811bf8549299aced436c`,
  respectively. The 18 existing enum-name diagnostics and expected local
  fail-closed `identity.W001` warning remain.
- The ADR 0059 pull-request CI correction reproduces and closes all three fast-
  job failures locally: Git records `src/manage.py` as mode `100755`; the lock
  resolves `sqlparse` 0.6.0 and both Python and Staff Console production audits
  report no known vulnerabilities; and the bounded-global-ignore unit contract
  passes with `SLF001` removed from the global Ruff set. Lock verification,
  Ruff formatting/ALL-rule lint over 636 files, strict mypy over 356 source
  files, strict PyDocLint plus semantic validation over 360 production/tooling
  files, the 249-Markdown/202-requirement validator, a fresh warning-fatal
  Sphinx/AutoAPI build, and all 1,847 unit tests pass locally. The replacement
  pull-request run remains the remote acceptance authority.
- The ADR 0060 collaboration/release foundation passes actionlint 1.7.7 over
  every workflow, Ruff formatting and ALL-rule lint over 642 files, strict
  mypy over 356 source files, strict PyDocLint and semantic docstring
  validation over 363 production/tooling files, and the 261-Markdown/202-
  requirement documentation validator. A fresh warning-fatal Sphinx/AutoAPI
  build succeeds; all 1,870 unit tests and all 20 Staff Console tests pass,
  TypeScript typechecking and the production frontend bundle are clean, and
  generated OpenAPI/TypeScript/static assets remain unchanged. Migration drift
  is zero, production-settings verification passes, and OpenAPI generation has
  zero errors while retaining the 18 known enum-name warnings and expected
  local fail-closed `identity.W001` warning. Live Python and complete frontend
  audits report no known vulnerabilities after the lockfile was constrained
  to patched `js-yaml`, `brace-expansion`, and `nanoid` transitive releases.
  The pinned production image builds, collects 192 static files, runs as UID
  10001 with Gunicorn 23.0.0, and includes the sidecar API-documentation
  assets. The six-shard timing inventory covers all 157 integration files with
  approximately 3,536 weighted seconds per shard. The replacement pull-request
  run remains the remote acceptance authority.
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
  remote acceptance authority. Corrective run
  [31964200663](https://github.com/martonpornoi/maru/actions/runs/31964200663)
  then passed all 19 jobs: 1,841 unit tests, 2,257 integration tests across all
  157 files and twelve PostgreSQL shards, 20 Staff Console tests, 91-percent
  branch-aware combined coverage, and the stable `CI gate`. Its only
  non-failing diagnostic was a repeated test-database teardown warning from two
  healthy thread-local Workforce mutex connections. A suite-wide audit found
  22 threaded database boundaries across 13 files that relied on
  `close_old_connections()` or a direct executor submission. They now close all
  thread-local connections unconditionally in outer `finally` blocks. Static
  inventory covers all 39 threaded database callables across 20 integration
  files; none lacks unconditional cleanup. A fresh 22-case PostgreSQL batch
  covering every changed worker path passes without a teardown warning; the
  complete four-test Workforce file and direct invitation-delivery regression
  also pass independently on freshly created test databases. The current
  commit's `CI gate` remains authoritative for the cleanup follow-up.

These results accept the repository gate and that bounded browser slice. They
are not deployment, production-readiness, recovery, accessibility, or owner
approval.

## Decisions and migration boundary

- ADRs 0049 through 0059 are Accepted. ADR 0054 accepts the bounded architecture
  and migrated integrity boundary; it does not declare the partial
  LOG-001/002/003/004/006/007 portfolio complete or approve production rollout.
- ADR 0055 changes presentation and experience evidence only. It adds no model,
  migration, authority, disclosure, recovery, or production-cutover boundary.
- ADR 0056 narrowly supersedes ADR 0030's no-browsable-documentation clause for
  the default URL configuration. It adds no model, migration, API operation,
  schema shape, generated-client, tenant, authority, runtime-role, recovery, or
  production-cutover boundary; the raw schema is now platform-admin-only.
- ADR 0057 establishes contributor documentation tooling and source contracts
  only. It adds no runtime route, model, migration, authority, API shape,
  recovery, or production-cutover boundary and does not make the generated
  Sphinx artifact a public production site.
- ADR 0058 partially supersedes ADR 0057's permissive short-docstring and
  section policy. It strengthens contributor contracts and generated
  descriptions only; it adds no runtime behavior, model, migration, authority,
  API schema shape, recovery, or production-cutover boundary.
- ADR 0059 partially supersedes ADR 0058's staged lint configuration. It
  synchronizes signature metadata, exact direct raises, and scoped lint
  exemptions without changing runtime behavior, models, migrations, authority,
  API schema shapes, recovery, or production-cutover boundaries.
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
- The generated Sphinx site is retained as a CI artifact rather than deployed.
  Its Mermaid diagrams use the contributor site's configured browser renderer;
  a future hosted or offline distribution must define an asset/CSP policy and
  verify the rendered diagrams in that target environment.
- Documentation enforcement can prove structural completeness and reject known
  placeholder patterns, but it cannot prove that every description captures
  the right domain nuance. Review must still challenge misleading omission,
  especially around authorization, side effects, idempotency, failure modes,
  transactions, and sensitive values. Examples are illustrative and are not
  automatically doctested unless a future contract explicitly opts them in.
- The task-oriented experience is currently converted only for the shared
  shell, administration home, navigation, User accounts/invitations, and Page
  8. Registration, Workforce, Venues, Logistics mutation roles, and specialist
  records still need conversion and the full 320/390/768/958/1,024/1,280/1,920,
  200-percent-zoom, keyboard, automated-accessibility, screen-reader, and owner
  evidence matrix.
- GitHub browser/accessibility, multi-Python compatibility, scheduled CodeQL,
  native dependency review, secret scanning/push protection, nightly
  concurrency repetition, and release restore rehearsal remain later testing
  layers. Release SBOM/provenance exists and public launch selects GitHub's
  recommended CodeQL default setup, but the current private plan does not
  permit ruleset enforcement or Code Security and public-only settings are
  intentionally not assumed.
- Replacement pull-request run `32254074078` started no job step because
  GitHub reports that recent account payments failed or the Actions spending
  limit must be increased. No remote PostgreSQL service ran. Local acceptance
  is complete, but the stable `PR gate` and remote full matrix remain required
  after Actions capacity is restored.
- The OCI image is a distributable deployment input, not proof of configured
  SMTP, payment, object storage/scanning, workers, telemetry, backups, load,
  accessibility, partner governance, recovery, or production readiness. The
  first release remains blocked until a dedicated release PR updates
  `pyproject.toml` from `0.1.0a0` to its derived CalVer and completes those
  chosen release-channel gates.

## Smallest sensible next actions

1. Restore GitHub Actions billing/capacity, then confirm the replacement GitHub
   `PR gate`, six measured shards, generated
   documentation, combined coverage, and container build contract. Apply the
   checked-in main/tag rulesets when GitHub enables them for the private plan or
   during the separately reviewed public transition; then raise reviews to one
   when a second maintainer exists.
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
relevant requirement IDs, ADRs 0047 through 0060, and the owning module/runbook
docs. Preserve every concurrent change in the dirty working tree. Serialize all
PostgreSQL tests that share `test_maru_test`; never infer authority from a
selected edition or route; authorize before parsing untrusted input; retain
private/no-store on authenticated projections; and keep fixed/self/public
audiences separate from assignable scoped authority. Do not treat the canonical
repository result or scoped read-only Logistics browser result as broader
visual/mutation, deployment, accessibility, recovery, owner, or production
approval.
