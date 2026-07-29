# Development setup

Status: Baseline  
Last updated: 2026-07-27

## Prerequisites

- Python 3.12, 3.13, or 3.14
- [uv](https://docs.astral.sh/uv/)
- Docker with Compose for the PostgreSQL development service
- Git
- Node 22.12 or newer and pnpm for Staff Console development

The system `python` on some Windows machines may be older. Verify the selected
interpreter with `uv python find` and do not run Maru on Python 3.9.

## First setup

```powershell
uv sync --all-groups
docker compose up -d postgres
uv run python src/manage.py migrate
uv run python src/manage.py runserver
```

Local defaults connect to `postgresql://maru:maru@127.0.0.1:5432/maru`.
Override settings with environment variables described in `.env.example`.
Maru does not automatically read `.env`; a shell or supervised runtime supplies
configuration.

## Bootstrap login

An empty database has no predefined account. Create a single Django bootstrap
administrator when a minimal setup is enough:

```powershell
uv run python src/manage.py createsuperuser
```

The account uses its email address to sign in at
<http://127.0.0.1:8000/admin/> or <http://127.0.0.1:8000/staff/>. Django admin
is a bootstrap data interface. The Staff Console is the first product
workspace; local password authentication is still not the production identity
system.

After creating an Organization, Convention Series, Event Edition, and a
separate Chair account in bootstrap admin, establish the first scoped
controllers and furry-convention position templates once:

```powershell
uv run python src/manage.py bootstrap_convention `
  --organization ORGANIZATION_SLUG `
  --edition EDITION_SLUG `
  --controller-email ADMIN_EMAIL `
  --chair-email CHAIR_EMAIL `
  --reason "Establish the first accountable convention leadership." `
  --confirm-organization ORGANIZATION_SLUG
```

See the
[clean convention onboarding walkthrough](../operations/clean-convention-onboarding-walkthrough.md)
for the complete no-demo-database rehearsal.

Public attendee registration starts at
<http://127.0.0.1:8000/register/>. It does not require an existing account:
choose an edition whose registration window is open, then create an account and
edition-owned profile in the same form. An existing email must sign in first.

## Synthetic demonstration data

For local exploration, create the deterministic two-convention fixture:

```powershell
uv run python src/manage.py seed_demo_data
```

The command creates:

- one bootstrap administrator, `demo.admin@maru.invalid`;
- 79 synthetic persona accounts, including three shared across organizers;
- two independent organizer tenants and convention series;
- archived 2025, preparing 2026, and draft 2027 editions for each series;
- board, convention leadership, department leads, volunteers, attendees,
  programme hosts, dealers, guests, performers, media, and edge cases;
- memberships, overlapping participation capacities, historical snapshots,
  versioned role bundles, and scoped role assignments;
- convention-specific registration sections, questions, and products,
  published templates, inherited draft provenance, registrations, complete
  synthetic attendee profiles, entitlements, and operational timelines; and
- lifecycle transitions through the authorized command, with their audit,
  domain-event, and pending outbox records.

Every synthetic account uses the static local-only password
`Z7!maru-demo-fixture-2026`. Addresses use the reserved `.invalid` top-level
domain. The command is available only under local and test settings, never
deletes rows, fails on non-demo identity collisions, and is safe to rerun. If
an older fixture used another password, reset only fixture-owned accounts:

```powershell
uv run python src/manage.py seed_demo_data --reset-passwords
```

`--password` remains available for an intentional local override. Never reuse
the documented demo password for a real account or deployment.

The current schema now includes initial workforce departments, positions,
volunteer opportunities, applications, onboarding agreements, and position
assignments. Shifts, programme, dealer-table, accommodation, and case records
remain future modules. Registration is a real vertical with a local/test-only
payment adapter. See
[`demo-data.md`](../modules/demo-data.md) for the exact boundary.

Open <http://127.0.0.1:8000/staff/> and use
`danube.convention-chair@demo.maru.invalid` with
`Z7!maru-demo-fixture-2026` for the featured Danube 2026 cockpit, registration
configuration, Reports, and Front Desk queue. Use
`danube.standard-attendee@demo.maru.invalid` for a fresh attendee registration.
Other convention-chair, staff, volunteer, and attendee accounts intentionally
receive different safe views according to their relationships and
capabilities.

## Staff Console development

The production bundle is checked into Django's app static directory. To
regenerate it and verify the separate frontend:

```powershell
cd frontends/staff-console
pnpm install --frozen-lockfile
pnpm run generate:api
pnpm run typecheck
pnpm run test
pnpm run build
cd ../..
```

Run `pnpm dev` for the Vite loop; it proxies API, account, and staff routes to
Django on port 8000. Restart a Django development process that was already
running before the Staff Console static directory was first created.

## Checks

Fast focused commands:

```powershell
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```

Complete local gate:

```powershell
./scripts/check.ps1
./scripts/verify-production-settings.ps1
```

Database tests must run on PostgreSQL. SQLite is not a supported substitute.

## Common operations

```powershell
uv run python src/manage.py makemigrations
uv run python src/manage.py migrate
uv run python src/manage.py showmigrations
uv run python src/manage.py spectacular --file openapi.yaml --validate
uv run python src/manage.py audit_integrity
uv run python src/manage.py audit_integrity --seal --limit 1000
uv run python src/manage.py effects_status --organization ORGANIZATION_UUID
uv run python src/manage.py effects_metrics --organization ORGANIZATION_UUID --pool core
uv run python src/manage.py effects_worker --pool core
uv run python src/manage.py seed_demo_data
./scripts/rehearse-db-recovery.ps1
docker compose logs postgres
docker compose stop postgres
```

Do not use `flush`, delete the volume, or roll back migrations when the target
database might contain valuable work.

See the [effect worker runbook](../operations/effects-worker-runbook.md) before
quarantine replay or queue recovery.

## Configuration

| Variable | Local default | Production |
| --- | --- | --- |
| `MARU_SETTINGS_MODULE` | `maru.settings.local` | must select production |
| `MARU_SECRET_KEY` | known development-only value | required, minimum strength |
| `MARU_DATABASE_URL` | local PostgreSQL | required PostgreSQL URL |
| `MARU_ALLOWED_HOSTS` | localhost addresses | required comma-separated hosts |
| `MARU_CSRF_TRUSTED_ORIGINS` | empty | explicit HTTPS origins if needed |
| `MARU_BUILD_VERSION` | `development` | immutable release identifier |
| `MARU_BUILD_COMMIT` | `unknown` | full source commit |
| `MARU_LOG_LEVEL` | `INFO` | reviewed level |

Boolean values accept only documented spellings and invalid configuration fails
startup.

## Test data

Tests and examples use synthetic data. Never copy a production database,
export, message, attachment, or personal identifier into local development.

## Troubleshooting

- If `python --version` is below 3.12, let uv provision/select a supported
  Python rather than changing the project constraint.
- If PostgreSQL tests fail to connect, inspect `docker compose ps` and the
  database URL before rerunning.
- If schema generation changes, inspect the OpenAPI diff and update the checked
  contract intentionally.
- If a migration is detected unexpectedly, review model changes; do not hide
  drift by generating an unexplained migration.
