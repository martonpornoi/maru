# Maru

Maru is the working name for an API-first convention operations platform. It is
intended to give attendees, volunteers, hosts, dealers, staff, and organizers
one account and one coherent experience across many independently operated
conventions.

Maru is pre-production software preparing for public collaboration. It is not
yet a supported hosted service or PyPI package and must not receive production
personal data. The primary future release artifact is an immutable Django
application image in GitHub Container Registry with source provenance, SBOM,
documentation, OpenAPI, dependency locks, and checksums.

See [CONTRIBUTING.md](CONTRIBUTING.md) to work on Maru,
[SECURITY.md](SECURITY.md) for private vulnerability reporting, and
[the release process](docs/operations/release-process.md) for CalVer and GitHub
artifact semantics. Contributions are licensed under
[Apache-2.0](LICENSE) and follow the [Code of Conduct](CODE_OF_CONDUCT.md).

Each occurrence of a convention is a first-class event edition, for example
`Awoostria 2026` or `Eurofurence 2026`. Historical editions remain available so
people can see their past participation and organizers can retain an accurate,
permission-controlled operational record.

## Technical direction

- Python and Django 5.2 LTS
- Django REST Framework
- PostgreSQL as the system of record
- A modular monolith with strongly enforced module boundaries
- Versioned REST APIs and generated OpenAPI clients
- Embedded React/TypeScript Convention work and separately deployable future
  clients; ADR 0039 integrates the preserved workflow into one coherent
  `/admin/` shell while current services and APIs remain authoritative
- Background workers for delivery, exports, imports, and other slow operations

Reflex is not part of the platform core. The active browser milestone is one
record-oriented `/admin/` shell: Administration home, embedded Convention
work, permission-filtered specialist records, and Pages 1–9 under the reserved
`/admin/platform/` route space. Platform administration remains separate from
convention participation. Backend route, authorization, frontend build,
populated and fresh migration, local restore-drill, and desktop/390-pixel
browser smoke evidence pass. Dependency audits also report no known Python or
JavaScript vulnerabilities. The current consolidated backend gate passes 1,239
tests with 90.35 percent branch coverage. Accessibility, complete visual states,
and owner rehearsal remain before
release acceptance.

ADR 0040 defines Page 8 **Representation & access** as the first M2 slice:
exact existing verified people accept their own Executive Board invitations,
at least two distinct controllers cross-approve root authority, and activation
moves the organization from Draft to Active atomically. The schema, commands,
HTML adapters, authorization matrix, synthetic fixture handoff, and backend
tests are implemented. Organizations migrations `0009` through `0011` add
database-enforced governance provenance and emergency controller containment;
organizations `0012`, participation `0004`, registration `0031`, and workforce
`0003` enforce IDN-011 for every covered convention-subject relationship.
Sensitive Page 8 reads and privileged denials are audited with a bounded
100-row directory. Accessibility/complete-state evidence, representative
deployment/PITR rehearsal, and owner tutorial remain
open; the platform administrator is the actor only and never a convention
subject.

ADR 0041 implements the exact authorization lattice—organization, edition,
department, and typed resource—without implicit department-tree inheritance.
Sealed database-resolved targets, immutable workforce-position bindings,
append-only issuance, one-way revocation, bounded delegation, PostgreSQL
integrity guards, and a privacy-minimized migration-readiness command are in
place. The contextual editor and computed access explanation remain unmounted,
and exact actor/approver authority-source provenance remains a production gate.
ADR 0042 makes all repository fixtures and
tutorials synthetic-only and retires the former public-roster rehearsal before
file, network, or database access. ADR 0043 adds the narrowly scoped global
emergency containment path for a compromised Board controller.

## Local quick start

Install Python 3.12 through 3.14, `uv`, Docker with Compose, and Git. From the
repository root:

```powershell
uv sync --all-groups
docker compose up -d postgres
$env:MARU_DATABASE_URL = "postgresql://maru:maru@127.0.0.1:5432/maru_rebuild_empty"
uv run python src/manage.py migrate
uv run python src/manage.py runserver
```

Open <http://127.0.0.1:8000/>. ADR 0039 places platform setup and the
organization-scoped management spine under `/admin/platform/` inside the
shared `/admin/` shell. Pages 1–2 are platform-administrator-only; active
scoped non-staff accounts may use permitted Pages 3–8 and Convention work,
while specialist records still require independent Django staff/model
permissions.
After signing in as the platform administrator, browse the searchable API
reference at <http://127.0.0.1:8000/api/v1/docs/> or the reading-focused ReDoc
view at <http://127.0.0.1:8000/api/v1/redoc/>. Tooling uses the canonical
machine-readable schema at <http://127.0.0.1:8000/api/v1/schema>. All three
render the same contract; see [development setup](docs/development/setup.md)
for the generation and security boundary.
For a new empty database, create one
bootstrap administrator with:

```powershell
uv run python src/manage.py createsuperuser
```

This management command is the only generic bootstrap path for the first
platform administrator. The Django **Accounts** specialist record is
inspection-only: it cannot create people, set or reset passwords, change
platform privileges or lifecycle, or attach convention relationships. After
bootstrap, invite ordinary person accounts from **Platform administration >
Accounts > Invite** so each recipient chooses their own password.

The local baseline prepared during ADR 0030 uses:

```text
Username: admin
Email: admin@maru.local
Password: M4rucon-Rehearsal-2031!
```

These are local-only credentials. The preserved demo and Marucon fixtures may
still populate backend reference data. Do not treat a reachable preserved
screen as production-ready before the remaining browser and deployment gates.
The synthetic fixture command remains:

```powershell
uv run python src/manage.py seed_demo_data
```

The demo administrator is `demo.admin@maru.invalid`. Every synthetic account
uses the documented local-only password `Z7!maru-demo-fixture-2026`. The
fixture is local-only, idempotent, uses reserved `.invalid` addresses, and
establishes each synthetic organization's two-controller Executive Board by
calling the real Page 8 services. It must never be used as production data or
credentials.
See [development setup](docs/development/setup.md) for configuration, checks,
troubleshooting, fixture details, the empty-experience runbook, and preserved
rehearsals.
Follow the [hands-on tutorial](docs/operations/maru-hands-on-tutorial.md) for the
synthetic organization → representation → series → edition journey. Local
migration, restore, and responsive smoke evidence pass; the owner-led tutorial
rehearsal remains a release gate.

## Product principles

- One account does not imply that every organizer can see all account data.
- Every operational record has a clear organization and event-edition scope.
- Archived history is immutable by default and understandable years later.
- Authorization is explicit, scoped, deny-by-default, and tested.
- Modules communicate through documented contracts rather than shared internals.
- Communication, announcements, reporting, and exports are platform features.
- Common staff tasks must be fast, searchable, accessible, and bulk-friendly.
- Privacy-aware auditability is required; indiscriminate surveillance is not.
- Important workflows must continue safely during degraded venue connectivity.

## Documentation map

- [Generated contributor documentation source](docs/index.md)
- [Product vision](docs/product/vision.md)
- [Product requirements](docs/product/requirements.md)
- [Capability map](docs/product/capability-map.md)
- [Annual lifecycle](docs/product/annual-lifecycle.md)
- [Personas and jobs](docs/product/personas-and-jobs.md)
- [Experience and information architecture](docs/product/experience-and-information-architecture.md)
- [Key workflows](docs/product/key-workflows.md)
- [Domain model](docs/domain/domain-model.md)
- [Architecture overview](docs/architecture/overview.md)
- [Architecture decisions](docs/architecture/decisions/README.md)
- [Authorization model](docs/security/authorization-model.md)
- [Data classification and retention](docs/security/data-classification-and-retention.md)
- [Threat model](docs/security/threat-model.md)
- [Resilience and offline operation](docs/architecture/resilience-and-offline.md)
- [Integrations and extensions](docs/architecture/integrations-and-extensions.md)
- [Reporting and automation](docs/architecture/reporting-and-automation.md)
- [Activity, audit, and history](docs/architecture/activity-audit-and-history.md)
- [Implemented module documentation](docs/modules/README.md)
- [Deployment and service objectives](docs/operations/deployment-and-service-objectives.md)
- [Observability and operational readiness](docs/operations/observability-and-readiness.md)
- [Registration operations and tester runbook](docs/operations/registration-runbook.md)
- [Clean convention and volunteer onboarding walkthrough](docs/operations/clean-convention-onboarding-walkthrough.md)
- [Marucon admin-first educational rehearsal](docs/operations/marucon-admin-rehearsal.md)
- [Empty-experience baseline](docs/operations/empty-experience-baseline.md)
- [Page 1 platform-administration runbook](docs/operations/page-01-platform-home.md)
- [Organization-to-edition hands-on tutorial](docs/operations/maru-hands-on-tutorial.md)
- [Edition workspace migration and recovery](docs/operations/edition-workspace-migration-and-recovery.md)
- [Executive Board migration and recovery](docs/operations/executive-board-migration-and-recovery.md)
- [IDN-011 convention-subject migration and recovery](docs/operations/idn011-convention-subject-migration-and-recovery.md)
- [Controlled reset ledger](docs/project/RESET_REBUILD.md)
- [Registration implementation backlog](docs/project/REGISTRATION_TODO.md)
- [Research landscape](docs/research/landscape-2026-07.md)
- [Testing strategy](docs/quality/testing-strategy.md)
- [Documentation standards](docs/quality/documentation-standards.md)
- [Development setup](docs/development/setup.md)
- [Repository governance](docs/development/repository-governance.md)
- [GitHub release process](docs/operations/release-process.md)
- [Public repository readiness](docs/operations/public-repository-readiness.md)
- [Current project state](docs/project/CURRENT.md)
- [Production consolidation and live capability ledger](docs/project/PRODUCTION_CONSOLIDATION.md)
- [Roadmap](docs/project/ROADMAP.md)
- [Delivery plan](docs/project/DELIVERY_PLAN.md)
- [Implementation backlog](docs/project/BACKLOG.md)
- [Progress matrix](docs/project/PROGRESS.md)
- [Awoostria reference operating-model research](docs/research/awoostria-reference-2026-08.md)
- [Checkpoint system](docs/checkpoints/README.md)

The product/architecture baseline and repository-controlled registration
production-safety vertical are implemented. A selected provider, target
infrastructure, representative load evidence, partner policy review, and
edition go/no-go are still required before production personal data. See the
current-state handoff and registration backlog for the exact tested and
residual boundaries.
