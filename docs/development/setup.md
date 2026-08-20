# Development setup

Status: Production-consolidation M1.1/M2.1 locally migrated and smoke-verified
Last updated: 2026-08-19

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

## API contract and interactive documentation

After signing in as an active platform administrator, use:

- <http://127.0.0.1:8000/api/v1/docs/> for the searchable Swagger reference;
- <http://127.0.0.1:8000/api/v1/redoc/> for the reading-focused ReDoc reference;
  and
- <http://127.0.0.1:8000/api/v1/schema> for the authoritative machine-readable
  OpenAPI 3.1 contract.

Swagger and ReDoc render that same schema; they do not define another contract.
Swagger submit methods are disabled, and neither view grants credentials or
bypasses API authentication, tenant/edition scope, capabilities, CSRF,
step-up, strict-input, or idempotency controls. The schema and both references
are private to a freshly resolved active platform administrator and are not
exposed through registration-client CORS.

The browser assets are supplied locally by the locked
`drf-spectacular-sidecar` package. Generate and validate the drift-controlled
artifact with:

```powershell
uv run python src/manage.py spectacular --file openapi.yaml --validate
```

The checked-in `openapi.yaml` and generated TypeScript definitions remain the
build artifacts consumed by clients. Production builds must run
`collectstatic` and serve the bundled documentation assets from the same
immutable release.

## Contributor documentation

Python production and tooling callables use NumPy-style docstrings and are
rendered together with the maintained Markdown guides. Validate argument,
type, default, return/yield, assertion, and exact-raise agreement; semantic
prose quality; and the warning-clean HTML site with:

```powershell
uv run pydoclint src scripts
uv run python scripts/validate_python_docstrings.py src scripts
uv run sphinx-build -W --keep-going --fresh-env -j auto -b html docs docs/_build/html
```

Open `docs/_build/html/index.html` locally after the build. Local certification
and the GitHub-hosted acceptance workflow run the same commands; GitHub retains
the generated site as the `contributor-documentation` artifact. See
[`documentation-standards.md`](../quality/documentation-standards.md) for the
section and exclusion policy.

## Exact-commit acceptance

Activate the repository-managed push guard once per clone and run the complete
local certification before requesting review:

```powershell
./scripts/install_git_hooks.ps1
./scripts/certify.ps1
```

The certifier requires a clean tree and Docker Desktop. It preserves the
database-isolation contract by running one unit process and eight measured
integration shards against nine separate local PostgreSQL containers, then
combines branch coverage at the existing 90-percent floor. The public
repository does not trust a local receipt: its stable `PR gate` independently
runs the fail-closed selected acceptance path on isolated GitHub-hosted Linux
runners. See [local exact-commit certification](local-certification.md) for
local evidence and the public trust boundary.

## Bootstrap login

An empty database has no predefined account. Create a single Django bootstrap
administrator when a minimal setup is enough:

```powershell
uv run python src/manage.py createsuperuser
```

The account uses its email address or optional unique login handle to sign in
at <http://127.0.0.1:8000/admin/>. A superuser is explicitly classified as a
non-participating platform administrator. ADR 0039 makes one `/admin/` shell
the default, with Convention work, permission-filtered specialist records, and
Pages 1–8 below `/admin/platform/`. Backend route and authorization
verification passes. Active scoped accounts do not need Django `is_staff`
merely to enter the Maru shell or use their allowed organization workflows;
specialist records still require independent staff/model permissions. Local password
authentication is not the production identity system.

ADR 0040 adds a Page 8 representation handoff to that selected-organization
route space. Its schema, service, HTML, authorization, synthetic-fixture,
populated/fresh migration, local restore, and responsive browser checks pass.
Do not exercise it against an important database or infer Board members from
existing accounts; use the isolated synthetic hands-on tutorial after applying
all current migrations. The final consolidated suite, representative
deployment/PITR rehearsal, accessibility, and owner tutorial remain open.

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

### M2.1 governance and convention-subject boundary

Organizations `0008` adds the representation records. Organizations `0009`
through `0011` enforce immutable Executive Board provenance, exact active
authority, eligible principals, and global emergency controller containment.
Organizations `0012`, participation `0004`, registration `0031`, and workforce
`0003` install IDN-011 database guards so a platform administrator cannot be a
convention subject even through bulk or direct-SQL writes or concurrent account
reclassification.

These migrations require stopped writers. Run the privacy-minimized readiness
check before and after applying them:

```powershell
uv run python src/manage.py check_representation_readiness
uv run python src/manage.py migrate
uv run python src/manage.py check_representation_readiness
```

Do not use `--fake`, disable the triggers, or roll old writers over the new
guards. Follow the [Executive Board recovery runbook](../operations/executive-board-migration-and-recovery.md)
and [IDN-011 subject-boundary runbook](../operations/idn011-convention-subject-migration-and-recovery.md).

### Page 9 write-integrity and readiness boundary

Workforce `0006_edition_structure_schema`, authorization
`0010_retired_department_authority_guards`, and workforce
`0007_structure_write_integrity` form one migration-first, stopped-writer
sequence. The last migration scans only aggregate blocker counts, preserves
legacy Department identity/tree/order, creates legacy structure controls
without invented receipts, and installs the final control/receipt/Department
write boundary.

Production readiness requires the `0007` recorder row, definition fingerprints
for all 14 Page 9 `SECURITY DEFINER` helpers, and the exact catalog shape of all
28 trigger attachments. Those helpers stay outside
`RUNTIME_DATABASE_FUNCTION_EXECUTE_ALLOWLIST_V2`; direct `PUBLIC` and runtime
execution remains revoked. Do not use table presence, a successful ORM save,
or a manually recreated trigger as readiness evidence. Follow the
[exact authority-provenance runbook](../operations/authority-provenance-migration-and-recovery.md)
for the combined catalog/runtime-role proof.

### Unified shell and preserved workflows

The domain services, APIs, fixtures, and former browser implementation remain
in the repository as tested evidence. ADR 0039 is reusing their record-oriented
grammar without replacing current service or policy boundaries. The following
commands remain operator/recovery references; a mounted screen does not make a
direct model write the supported workflow.

In the pre-reset workflow, an operator could create an Organization,
Convention Series, Event Edition, and separate Chair through specialist record
pages, then complete **Establish convention leadership** in Convention work.
That web ceremony and its `/api/v1/management/convention-bootstrap` endpoint
are not mounted now. They remain historical behavior evidence only.

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

ADR 0040 supersedes this broad bootstrap as the normal first-authority path.
The command and underlying service remain operator/recovery evidence, not a
browser or public API workflow. Do not use them for a new Draft organization or
as an alternative to Page 8. They may be considered only by an approved legacy-
reconciliation procedure because they also create edition, workforce, and
participation relationships.

See the
[clean convention onboarding walkthrough](../operations/clean-convention-onboarding-walkthrough.md)
for the complete no-demo-database rehearsal.

### Retired public-roster rehearsal

`seed_marucon_rehearsal` is retired. It remains registered only so old scripts
fail with one explanatory `CommandError`; every former option is rejected
before password validation, file access, network access, or database writes.
Maru does not import live volunteer handles into rehearsal accounts.

Use the deterministic synthetic fixture instead:

```powershell
uv run python src/manage.py seed_demo_data
```

The synthetic fixture exercises the real Page 8 Executive Board provision,
invitation, self-response, and two-controller activation services while
keeping the platform administrator outside convention relationships. Continue
the hands-on journey through **Representation & access** under the selected
organization in `/admin/`.

ADR 0039's intended URL set can make the preserved public registration pages
reachable again. Registration APIs and services remain authoritative, and the
browser journey stays partial/deployment-gated until its current integration
and release evidence pass.

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
- versioned Page 9 structure controls and immutable retry receipts for the
  synthetic workforce Departments, created before lifecycle progression;
- memberships, overlapping participation capacities, historical snapshots,
  versioned role bundles, and scoped role assignments;
- convention-specific registration sections, questions, and products,
  published templates, inherited draft provenance, registrations, complete
  synthetic attendee profiles, entitlements, and operational timelines; and
- lifecycle transitions through the authorized command, with their audit,
  domain-event, and pending outbox records.

The fixture deliberately leaves invitation-scheduler liveness evidence empty.
Only an actual delivery, expiry, or retention scheduler run may write that
heartbeat; synthetic data must not make readiness report a live worker.

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

The current schema now includes an active two-controller Executive Board for
each synthetic organization, established through the real representation
services, plus initial workforce departments, positions,
volunteer opportunities, applications, onboarding agreements, and position
assignments. Shifts, programme, dealer-table, accommodation, and case records
remain future modules. Registration is a real vertical with a local/test-only
payment adapter. See
[`demo-data.md`](../modules/demo-data.md) for the exact boundary.

Those persona accounts and records remain useful for backend permission tests.
The former cockpit, reports, Front Desk, and attendee pages are preserved
workflows; route reachability during ADR 0039 does not make them accepted or
production-ready current journeys.

## Convention work frontend

The bundle is checked into Django's app static directory and mounted at
`/admin/workspace/` inside the shared shell. The route requires an active
platform administrator or current organization/edition authority. To verify
its source independently of browser rehearsal:

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
uv run pydoclint src scripts
uv run python scripts/validate_python_docstrings.py src scripts
uv run pytest
```

Complete local gate:

```powershell
./scripts/check.ps1
./scripts/verify-production-settings.ps1
```

The current dependency audit evidence is clean: `pip-audit` reports no known
Python package vulnerability and `pnpm audit` reports no known frontend package
vulnerability. Rerun both for a release because advisory data changes over
time; a clean dependency scan does not replace application security testing.

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

All Page 10 platform-invitation API mutations likewise require a canonical
lower-case UUID `Idempotency-Key` header and reject `retry_key` in JSON. Public
acceptance is JSON-only at `/api/v1/public/account-invitations/accept`; submit
the invitation code in the body, never in a path or query string. The exact-
origin CORS response permits `Idempotency-Key` for approved seasonal clients.
Page 10 Registration definition mutations use the same header-only retry
contract on the canonical configuration-command and profile-extension-field
endpoints. Their JSON bodies must not contain `retry_key`; configuration
commands additionally require one documented closed `operation` value and the
current positive `expected_version`.

See the [effect worker runbook](../operations/effects-worker-runbook.md) before
quarantine replay or queue recovery.

## Configuration

| Variable | Local default | Production |
| --- | --- | --- |
| `MARU_SETTINGS_MODULE` | `maru.settings.local` | must select production |
| `MARU_SECRET_KEY` | known development-only value | required, minimum strength |
| `MARU_DATABASE_URL` | local PostgreSQL | required PostgreSQL URL |
| `MARU_RUNTIME_DATABASE_ROLE` | empty | required dedicated non-owner login role name |
| `MARU_ALLOWED_HOSTS` | localhost addresses | required comma-separated hosts |
| `MARU_CSRF_TRUSTED_ORIGINS` | empty | explicit HTTPS origins if needed |
| `MARU_BUILD_VERSION` | `development` | immutable release identifier |
| `MARU_BUILD_COMMIT` | `unknown` | full source commit |
| `MARU_LOG_LEVEL` | `INFO` | reviewed level |

Boolean values accept only documented spellings and invalid configuration fails
startup.
`MARU_DATABASE_URL` may include ordinary libpq parameters such as `sslmode`,
but not `options`: Maru owns the fixed `search_path=public,pg_temp` connection
boundary so temporary or per-user schemas cannot shadow application tables.
`MARU_RUNTIME_DATABASE_ROLE` contains only a PostgreSQL role name, never its
password or connection URL. Production rejects a missing, non-printable, or
overlength name. Provision and rehearse the least-privilege role separately by
adapting
[`postgresql-runtime-role-provisioning.sql.example`](../operations/postgresql-runtime-role-provisioning.sql.example);
deliver its credential only through the deployment secret manager. Production
health accepts only a fresh connection genuinely authenticated as that login;
`SET ROLE` is not equivalent. The runtime role has four-operation DML on
ordinary application tables, `SELECT`/`INSERT` on Page 9 structure receipts,
and `SELECT`/`INSERT`/`UPDATE` on Page 9 structure controls, but only SELECT on
provenance marker/latch controls. It has no structure-table `REFERENCES`,
sequence update, parameter-control ACL, persistent trigger-disable setting,
membership admin option, or database-object grant option. Department remains
ordinary DML because its stopped-writer trigger owns retirement integrity.
Activation remains a controlled migration/cutover-owner operation.

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
