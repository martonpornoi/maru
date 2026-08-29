![Maru convention operations platform](.github/assets/maru-header.png)

# Maru

**The calm operating system for recurring community conventions.**

[Documentation](https://martonpornoi.github.io/maru/) ·
[Product tour](https://martonpornoi.github.io/maru/start-here/product-tour.html) ·
[Roadmap](docs/project/ROADMAP.md) ·
[Releases](https://github.com/martonpornoi/maru/releases) ·
[Issues](https://github.com/martonpornoi/maru/issues) ·
[Discussions](https://github.com/martonpornoi/maru/discussions) ·
[Contributing](CONTRIBUTING.md) ·
[Support](SUPPORT.md) ·
[Security](SECURITY.md)

[![PR gate](https://github.com/martonpornoi/maru/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/martonpornoi/maru/actions/workflows/ci.yml)
[![Contributor documentation](https://github.com/martonpornoi/maru/actions/workflows/pages.yml/badge.svg?branch=main)](https://github.com/martonpornoi/maru/actions/workflows/pages.yml)

> [!IMPORTANT]
> Maru is public, actively developed, pre-production software. It is not yet a
> supported hosted service or PyPI package and must not receive production
> personal data. Use synthetic data while evaluating or contributing.

Maru gives attendees, volunteers, hosts, dealers, staff, and organizers one
account and one coherent, permission-controlled experience across independently
operated conventions. It connects operational work that otherwise lives in
forms, spreadsheets, inboxes, schedules, and disconnected specialist tools.

Implemented, tested slices include a unified management shell, convention and
edition administration, bounded Registration and onsite operations, and the
complete first Workforce journey from organization structure through governed
Shift commitments. A convention can also evaluate Workforce as its only
adopted Maru capability without silently creating Registration, payment,
attendance, or unrelated participation records.

Browse the [public contributor documentation](https://martonpornoi.github.io/maru/)
for the maintained product, architecture, development, operations, and security
guides plus the statically analysed Python API reference. Read
[the current project state](docs/project/CURRENT.md) for exact implemented
behavior, verification, limitations, and next actions.

The primary release artifact is an immutable Django application image in
GitHub Container Registry with source provenance, SBOM, documentation,
OpenAPI, dependency locks, and checksums. Evaluate the published candidate
through the isolated
[synthetic OCI runtime rehearsal](docs/operations/synthetic-oci-runtime-rehearsal.md).
Curated changes live in the
[changelog](CHANGELOG.md) and become the human-facing notes on the
[GitHub Releases tab](https://github.com/martonpornoi/maru/releases).

Contributions are licensed under [Apache-2.0](LICENSE), follow the
[Code of Conduct](CODE_OF_CONDUCT.md), and use the authority and continuity
model in [GOVERNANCE.md](GOVERNANCE.md). Bundled third-party components retain
the licenses recorded in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

Each occurrence of a convention is a first-class event edition, for example
the fictional `MaruCon 2026` or `MaruDance 2026`. Historical editions remain available so
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
accounts, explicit multi-person accountability, exact scoped assignments, and
audited containment. Full-convention organizations use the Executive Board
ceremony; Workforce-only organizations may instead use two independently
activated Maru operators without inventing a broader governance structure.
Organization, edition, Department, and typed-resource authorization remain
deny-by-default without implicit hierarchy inheritance. Repository fixtures
and tutorials are synthetic-only. See the
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

- **Start here:** [product tour](https://martonpornoi.github.io/maru/start-here/product-tour.html),
  [run locally](https://martonpornoi.github.io/maru/start-here/run-locally.html),
  [current project state](docs/project/CURRENT.md), and
  [complete generated documentation](https://martonpornoi.github.io/maru/).
- **Understand the product:** [vision](docs/product/vision.md),
  [requirements](docs/product/requirements.md),
  [capability map](docs/product/capability-map.md),
  [domain model](docs/domain/domain-model.md), and
  [implemented modules](docs/modules/README.md).
- **Understand the design:** [architecture overview](docs/architecture/overview.md),
  [accepted decisions](docs/architecture/decisions/README.md),
  [authorization](docs/security/authorization-model.md),
  [data classification and retention](docs/security/data-classification-and-retention.md),
  and [threat model](docs/security/threat-model.md).
- **Build and contribute:** [contribution guide](CONTRIBUTING.md),
  [development setup](docs/development/setup.md),
  [testing strategy](docs/quality/testing-strategy.md),
  [documentation standards](docs/quality/documentation-standards.md), and
  [protected repository workflow](docs/development/repository-governance.md).
- **Operate and release:** [operations catalog](docs/operations/index.md),
  [deployment and service objectives](docs/operations/deployment-and-service-objectives.md),
  [observability and readiness](docs/operations/observability-and-readiness.md),
  [release process](docs/operations/release-process.md),
  [changelog](CHANGELOG.md), and
  [GitHub Releases](https://github.com/martonpornoi/maru/releases).
- **Plan and reconstruct:** [roadmap](docs/project/ROADMAP.md),
  [delivery plan](docs/project/DELIVERY_PLAN.md),
  [production-consolidation ledger](docs/project/PRODUCTION_CONSOLIDATION.md),
  and [checkpoint archive](docs/checkpoints/README.md).

The product and architecture baseline plus substantial bounded Registration,
Workforce, Venue, and Logistics slices are implemented. Provider certification,
target infrastructure, representative load and recovery evidence, partner
policy review, accessibility acceptance, and edition go/no-go are still
required before production personal data. The current-state handoff owns the
exact tested and residual boundaries.
