# Development setup

Status: Production-consolidation M1 development environment
Last updated: 2026-08-01

## Prerequisites

- Python 3.12, 3.13, or 3.14
- [uv](https://docs.astral.sh/uv/)
- Docker with Compose for the PostgreSQL development service
- Git
- Node 22.12 or newer and pnpm for embedded Convention work development

The system `python` on some Windows machines may be older. Verify the selected
interpreter with `uv python find` and do not run Maru on Python 3.9.

## First setup

```powershell
uv sync --all-groups
docker compose up -d postgres
$env:MARU_DATABASE_URL = "postgresql://maru:maru@127.0.0.1:5432/maru_rebuild_empty"
uv run python src/manage.py migrate
uv run python src/manage.py runserver
```

The controlled rebuild uses the separately named
`maru_rebuild_empty` database. Local defaults still connect to
`postgresql://maru:maru@127.0.0.1:5432/maru` when the environment variable is
omitted, so keep `MARU_DATABASE_URL` set in the server terminal.
Override settings with environment variables described in `.env.example`.
Maru does not automatically read `.env`; a shell or supervised runtime supplies
configuration.

## Bootstrap login

An empty database has no predefined account. Create a single Django bootstrap
administrator when a minimal setup is enough:

```powershell
uv run python src/manage.py createsuperuser
```

The account uses its email address or optional unique login handle to sign in
at <http://127.0.0.1:8000/admin/>. A superuser is explicitly classified as a
non-participating platform administrator. The current default browser
experience contains one progressive menu and Pages 1–7 from organization
inventory through edition record/working context. The preserved setup guide,
specialist records, public registration, and volunteer pages remain unmounted.
Local password authentication is not the production identity system.

The verified local baseline contains only:

```text
Database: maru_rebuild_empty
Username: admin
Email: admin@maru.local
Password: M4rucon-Rehearsal-2031!
```

See the
[empty-experience runbook](../operations/empty-experience-baseline.md). Do not
assume the named database is still empty or delete owner-created records. The
[hands-on tutorial](../operations/maru-hands-on-tutorial.md) uses clearly
synthetic records.

### M1 migration boundary

Organizations `0005`–`0007` and events `0006`–`0009` add series profile
versions, edition aggregate versions, creation receipts, span/digest
constraints, database triggers, and fail-closed downgrade fences for populated
workspaces. Stop old application writers before applying them in a shared
environment. Do not downgrade populated M1 data to old code or bypass the
fences; use a reviewed forward fix or approved backup/PITR recovery. See the
[edition workspace migration and recovery runbook](../operations/edition-workspace-migration-and-recovery.md).

### Preserved pre-reset workflows

The domain services, APIs, fixtures, and former browser implementation remain
in the repository as tested evidence during the rebuild. The following
commands are operator/recovery references; their old HTML pages are not mounted
by default.

In the preserved pre-reset URL configuration, an operator could create an
Organization, Convention Series, Event Edition, and separate Chair through
specialist record pages, then complete **Establish convention leadership** in
Convention work. Those pages are not mounted in the current baseline.

The equivalent command remains available for recovery and automation:

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

### Admin-first Marucon rehearsal

Use a new, separately named empty database. The command refuses a database
whose first account is not its deterministic administrator, never resets an
existing database, and imports only public handles, department descriptions,
and role labels. Images and contact data are excluded.

```powershell
$env:MARU_DATABASE_URL = "postgresql://maru:maru@127.0.0.1:5432/marucon_rehearsal"
uv run python src/manage.py migrate
uv run python src/manage.py seed_marucon_rehearsal --accept-public-roster
```

The output reports the `admin` login, Chair handle, counts, registration URL,
and shared local-only password `M4rucon-Rehearsal-2031!`. The external source
must be acknowledged explicitly on every network import. To rehearse without
public personal data, pass `--roster-file` with synthetic semantic HTML.
Automated tests use only such a synthetic miniature.

The former public registration pages are intentionally unmounted during
production consolidation. Registration APIs and services remain preserved.

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

Those persona accounts and records remain useful for backend permission tests,
but the former cockpit, reports, Front Desk, and attendee pages are not current
browser routes.

## Preserved Convention work frontend

The bundle is checked into Django's app static directory but is not mounted by
the ADR 0030 baseline. To verify the preserved source while it remains:

```powershell
cd frontends/staff-console
pnpm install --frozen-lockfile
pnpm run generate:api
pnpm run typecheck
pnpm run test
pnpm run build
cd ../..
```

Run `pnpm dev` for the Vite loop; it proxies API, account, administration, and
static routes to Django on port 8000. Restart a Django development process that
was already running before the Convention work static directory was first
created.

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

The edition-creation API requires a UUID `Idempotency-Key` HTTP header; its JSON
body must not contain `idempotency_key`. HTML Page 6 manages its own hidden
retry UUID. Both adapters call the same service and receipt boundary.

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
- If Django reports a missing identity, series-version, aggregate-version, or
  creation-receipt column, confirm the exact database URL, stop the server, run
  current migrations, and restart. Do not use `--fake` to suppress drift.
- If a migration is detected unexpectedly, review model changes; do not hide
  drift by generating an unexplained migration.
