# Page 1 platform administration home

Status: Executable local Page 1
Last updated: 2026-07-31

ADR 0031 replaces the accepted empty `/admin/` state with a read-only
organization inventory. ADR 0032 subsequently adds a separate Page 2 creation
route; the inventory remains free of inline editing and convention-owned work.

## Current local environment

```text
Database: maru_rebuild_empty
Username: admin
Email: admin@maru.local
Password: M4rucon-Rehearsal-2031!
Account kind: platform_administrator
```

The password is local test data. Never reuse it in a deployment or real
account.

The database contains the platform administrator and the owner-created Draft
organization `MaruCon`. It contains no convention series, editions,
memberships, participation, registrations, volunteer applications, or
workforce assignments. The `maru` and `marucon_rehearsal` databases are not the
controlled rebuild database and must not be reset.

## Start Page 1

From the repository root in PowerShell:

```powershell
$env:MARU_DATABASE_URL = "postgresql://maru:maru@127.0.0.1:5432/maru_rebuild_empty"
uv run python src/manage.py migrate
uv run python src/manage.py runserver
```

Open <http://127.0.0.1:8000/admin/> and sign in as `admin`.

## Expected behavior

- anonymous `/admin/` redirects to Sign in;
- the active platform administrator sees **Organizations**;
- the page shows the persistent **Organizations** and **+ Add** side navigation;
- an empty database shows **No organizations yet** and zero organizations;
- the page explains **Platform access, not participation**;
- **+ Add** opens `/admin/organizations/new/`;
- an ordinary account, including ordinary staff, receives `403`;
- the old administration and Convention work HTML routes remain `404`; and
- health and versioned JSON APIs remain available.

The platform administrator may receive explicit platform-policy decisions and
may be an attributed actor. It must have no organization membership,
convention capability or role grant, participation, registration, volunteer
application, onboarding request, or workforce assignment. Future restricted
case capabilities must require break-glass and cannot follow merely from this
account kind.

## Failure and recovery

If the organization query fails, `/admin/` returns a read-only `503` page. The
HTML does not contain the database exception and no convention data changes.
Check PostgreSQL and `/health/ready`, then retry.

The accepted baseline is commit `db5af58` on
`codex/page-by-page-rebuild`. Page 1 is developed on
`codex/page-01-platform-home`. Switch back to the baseline branch if Page 1
must be removed without disturbing the preserved backend.

## Next page

Page 2 is documented in
[`page-02-create-organization.md`](page-02-create-organization.md). It creates a
complete optional Draft organization profile and returns to this inventory.
