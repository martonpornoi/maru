# Empty-experience baseline

Status: Executable local baseline
Last updated: 2026-07-31

ADR 0030 deliberately exposes only Sign in and one empty administration home.
Use this environment to approve the shell before adding the first real page.

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
positions. The first account is an active staff superuser.

## Start the baseline

From the repository root in PowerShell:

```powershell
$env:MARU_DATABASE_URL = "postgresql://maru:maru@127.0.0.1:5432/maru_rebuild_empty"
uv run python src/manage.py migrate
uv run python src/manage.py runserver
```

Open <http://127.0.0.1:8000/admin/> and sign in as `admin`.

Expected behavior:

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

Do not add a menu or placeholder destinations. The next page starts only after
the product owner accepts this baseline and agrees its purpose, placement,
minimum information, actions, authorization, states, responsive behavior,
tests, and documentation in `docs/project/RESET_REBUILD.md`.
