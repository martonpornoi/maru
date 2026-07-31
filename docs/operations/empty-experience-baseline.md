# Empty-experience baseline

Status: Historical accepted baseline; superseded by Page 1
Last updated: 2026-07-31

ADR 0030 deliberately exposed only Sign in and one empty administration home.
The owner accepted that baseline. ADR 0031 and the
[Page 1 runbook](page-01-platform-home.md) now describe the executable home.

## Current local environment

```text
Database: maru_rebuild_empty
Username: admin
Email: admin@maru.local
Password: M4rucon-Rehearsal-2031!
```

The password is local test data. Never reuse it in a deployment or real
account.

The database contains one account and no organizations, convention series,
editions, registration configurations, registrations, departments, or
positions. After identity migration `0010`, the first account is explicitly an
active `platform_administrator` as described by the Page 1 runbook.

## Start the baseline

From the repository root in PowerShell:

```powershell
$env:MARU_DATABASE_URL = "postgresql://maru:maru@127.0.0.1:5432/maru_rebuild_empty"
uv run python src/manage.py migrate
uv run python src/manage.py runserver
```

Open <http://127.0.0.1:8000/admin/> and sign in as `admin`.

Historical baseline behavior before Page 1:

- `/` redirects to `/admin/`;
- an anonymous `/admin/` request redirects to `/accounts/login/`;
- Sign in contains only account credentials and submit;
- the authenticated home contains Maru identity, the signed-in name,
  POST-only Sign out, and the `Nothing here yet` message;
- non-staff accounts receive 403 at `/admin/`;
- old administration, Convention work, registration, guardian, account
  recovery, attendee, and volunteer pages return 404; and
- health and JSON `/api/v1/` endpoints remain available for backend work.

## Data safety

Do not point this baseline at `maru` or `marucon_rehearsal`. Do not flush or
drop those databases. `maru_rebuild_empty` is the only database for the
page-by-page rebuild until a later checkpoint explicitly changes that.

## Next page gate

The baseline gate is complete. Continue with the per-page gates in
`docs/project/RESET_REBUILD.md`; do not restore the old shell or use this
historical runbook as the current UI contract.
