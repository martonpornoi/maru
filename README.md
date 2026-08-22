# Maru

Maru is the working name for an API-first convention operations platform. It is
intended to give attendees, volunteers, hosts, dealers, staff, and organizers
one account and one coherent experience across many independently operated
conventions.

Maru is public, pre-production software open to collaboration. It is not
yet a supported hosted service or PyPI package and must not receive production
personal data. The primary future release artifact is an immutable Django
application image in GitHub Container Registry with source provenance, SBOM,
documentation, OpenAPI, dependency locks, and checksums.

Browse the [public contributor documentation](https://martonpornoi.github.io/maru/)
for maintained product, architecture, development, operations, and security
guides plus the statically analysed Python API reference.

See [CONTRIBUTING.md](CONTRIBUTING.md) to work on Maru,
[SUPPORT.md](SUPPORT.md) for help channels,
[SECURITY.md](SECURITY.md) for private vulnerability reporting,
[GOVERNANCE.md](GOVERNANCE.md) for maintainer authority and continuity, and
[the release process](docs/operations/release-process.md) for CalVer and GitHub
artifact semantics. Contributions are licensed under
[Apache-2.0](LICENSE) and follow the [Code of Conduct](CODE_OF_CONDUCT.md).
Bundled third-party components retain the licenses recorded in
[THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

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
task-oriented `/admin/` shell with Administration home, embedded Convention
work, permission-filtered specialist records, and collision-safe platform
routes. Platform administration remains separate from convention
participation. Exact implemented behavior, current repository evidence, and
remaining accessibility, recovery, deployment, and owner gates are maintained
in [CURRENT.md](docs/project/CURRENT.md) and the
[production-consolidation ledger](docs/project/PRODUCTION_CONSOLIDATION.md).
Dated test, coverage, migration, and vulnerability evidence stays in those
maintained handoff documents instead of being duplicated here.

Maru establishes convention authority through verified recipient-owned
accounts, an explicit multi-person Executive Board ceremony, exact scoped
assignments, and audited containment. Organization, edition, Department, and
typed-resource authorization remain deny-by-default without implicit hierarchy
inheritance. Repository fixtures and tutorials are synthetic-only. See the
[authorization model](docs/security/authorization-model.md),
[management shell contract](docs/product/page-contracts/00-management-experience-shell.md),
and maintained ledgers for the exact mounted behavior and residual production
gates.

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
shared `/admin/` shell. Each route rechecks its own platform, organization,
edition, Department, or typed-resource policy; a selected context or nearby
navigation entry never grants access. Specialist records also retain their
independent Django staff/model permissions.
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
platform administrator. The Django **User accounts** specialist record is
inspection-only: it cannot create people, set or reset passwords, change
platform privileges or lifecycle, or attach convention relationships. After
bootstrap, invite ordinary person accounts from **Platform administration >
User accounts > Invite** so each recipient chooses their own password.

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

- [Public generated contributor documentation](https://martonpornoi.github.io/maru/)
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
- [Project governance and maintainer continuity](GOVERNANCE.md)
- [Repository workflow and protection](docs/development/repository-governance.md)
- [Support policy](SUPPORT.md)
- [Security policy](SECURITY.md)
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
