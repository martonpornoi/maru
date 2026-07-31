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
- React/TypeScript convention workflows embedded in Django administration and
  separately deployable future clients
- Background workers for delivery, exports, imports, and other slow operations

Reflex is not part of the platform core. Django's administration shell combines
specialist records with purpose-built React/TypeScript Convention work.

## Local quick start

Install Python 3.12 through 3.14, `uv`, Docker with Compose, and Git. From the
repository root:

```powershell
uv sync --all-groups
docker compose up -d postgres
uv run python src/manage.py migrate
uv run python src/manage.py runserver
```

Open <http://127.0.0.1:8000/>. For an empty database, create one bootstrap
administrator with:

```powershell
uv run python src/manage.py createsuperuser
```

Alternatively, populate a comprehensive, synthetic two-convention dataset:

```powershell
uv run python src/manage.py seed_demo_data
```

The demo administrator is `demo.admin@maru.invalid`. Every synthetic account
uses the documented local-only password `Z7!maru-demo-fixture-2026`. The
fixture is local-only, idempotent, uses reserved `.invalid` addresses, and
must never be used as production data or credentials.
Open <http://127.0.0.1:8000/admin/> as
`danube.convention-chair@demo.maru.invalid` for the Danube 2026 cockpit and
registration operations, or `danube.standard-attendee@demo.maru.invalid` for a
fresh attendee registration walkthrough.
Open <http://127.0.0.1:8000/register/> without signing in to choose a convention,
create a synthetic attendee account, and complete the public registration
profile.
See [development setup](docs/development/setup.md) for configuration, checks,
troubleshooting, fixture details, and the clean-database admin-first Marucon
rehearsal.

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
- [Registration implementation backlog](docs/project/REGISTRATION_TODO.md)
- [Research landscape](docs/research/landscape-2026-07.md)
- [Testing strategy](docs/quality/testing-strategy.md)
- [Documentation standards](docs/quality/documentation-standards.md)
- [Development setup](docs/development/setup.md)
- [Current project state](docs/project/CURRENT.md)
- [Roadmap](docs/project/ROADMAP.md)
- [Delivery plan](docs/project/DELIVERY_PLAN.md)
- [Implementation backlog](docs/project/BACKLOG.md)
- [Progress matrix](docs/project/PROGRESS.md)
- [Checkpoint system](docs/checkpoints/README.md)

The product/architecture baseline and repository-controlled registration
production-safety vertical are implemented. A selected provider, target
infrastructure, representative load evidence, partner policy review, and
edition go/no-go are still required before production personal data. See the
current-state handoff and registration backlog for the exact tested and
residual boundaries.
