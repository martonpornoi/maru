# Empty-experience baseline

Status: Historical accepted baseline; ADR 0039 unified shell is current
Last updated: 2026-08-01

ADR 0030 deliberately exposed only Sign in and one empty administration home.
The owner accepted that baseline. Pages 1–8 superseded its executable surface,
and ADR 0039 moved them into the unified `/admin/` shell. Keep this
document for the isolated database and original reset boundary. Use the
[hands-on tutorial](maru-hands-on-tutorial.md) for current routes. Backend
verification passes; live migration/browser/coverage gates remain.

## Current local environment

```text
Database: maru_rebuild_empty
Username: admin
Email: admin@maru.local
Password: M4rucon-Rehearsal-2031!
```

The password is local test data. Never reuse it in a deployment or real
account.

The database began with one account and no domain records. It may now contain
the owner's Draft MaruCon organization and M1 rehearsal records. Do not infer a
known-empty state from the database name or delete those records. After
identity migration `0010`, the first account is explicitly an active
`platform_administrator` as described by the Page 1 runbook.

## Start the current controlled shell

From the repository root in PowerShell:

```powershell
$env:MARU_DATABASE_URL = "postgresql://maru:maru@127.0.0.1:5432/maru_rebuild_empty"
uv run python src/manage.py migrate
uv run python src/manage.py runserver
```

Open <http://127.0.0.1:8000/admin/> and sign in as `admin`.

The current surface mounts organization inventory/creation/record, convention-
series creation/record, event-edition creation/record, Page 8 representation,
governance invitations, and explicit edition working context. Apply all
current migrations before starting; a missing
`login_handle`, series profile version, edition aggregate version, or creation
receipt column means the selected database is behind the running code.

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

## Current continuation

The baseline gate is complete and `RESET_REBUILD.md` is historical. Continue
from M1/M2 in `docs/project/PRODUCTION_CONSOLIDATION.md`; do not restore the old
shell or use this historical runbook as the current UI contract.
