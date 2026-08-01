# Maru

Maru is the working name for an API-first convention operations platform. It is
intended to give attendees, volunteers, hosts, dealers, staff, and organizers
one account and one coherent experience across many independently operated
conventions.

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
- Preserved React/TypeScript convention workflows and separately deployable
  future clients; ADR 0030 deliberately leaves them unmounted during the
  page-by-page experience rebuild
- Background workers for delivery, exports, imports, and other slow operations

Reflex is not part of the platform core. The current browser experience
contains Sign in and Page 1, a read-only platform organization inventory,
while the product is rebuilt one reviewed page at a time.

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

Open <http://127.0.0.1:8000/>. The current experience deliberately exposes only
Sign in and the platform-administrator-only `/admin/` organization inventory.
For a new empty database, create one
bootstrap administrator with:

```powershell
uv run python src/manage.py createsuperuser
```

The local baseline prepared during ADR 0030 uses:

```text
Username: admin
Email: admin@maru.local
Password: M4rucon-Rehearsal-2031!
```

These are local-only credentials. The preserved demo and Marucon fixtures may
still populate backend reference data, but their former browser pages are not
mounted in the current baseline. The synthetic fixture command remains:

```powershell
uv run python src/manage.py seed_demo_data
```

The demo administrator is `demo.admin@maru.invalid`. Every synthetic account
uses the documented local-only password `Z7!maru-demo-fixture-2026`. The
fixture is local-only, idempotent, uses reserved `.invalid` addresses, and
must never be used as production data or credentials.
See [development setup](docs/development/setup.md) for configuration, checks,
troubleshooting, fixture details, the empty-experience runbook, and preserved
rehearsals.

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
- [Controlled reset ledger](docs/project/RESET_REBUILD.md)
- [Registration implementation backlog](docs/project/REGISTRATION_TODO.md)
- [Research landscape](docs/research/landscape-2026-07.md)
- [Testing strategy](docs/quality/testing-strategy.md)
- [Documentation standards](docs/quality/documentation-standards.md)
- [Development setup](docs/development/setup.md)
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
