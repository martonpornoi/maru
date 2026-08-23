# Platform administration home

Status: Platform administration home backend and responsive-smoke verified in the unified shell;
accessibility/state-matrix/owner rehearsal pending
Last updated: 2026-08-01

ADR 0031 replaces the accepted empty `/admin/` state with a read-only
organization inventory. ADR 0032 subsequently adds a separate Create organization creation
route; the inventory remains free of inline editing and convention-owned work.
ADR 0039 moves the inventory to `/admin/platform/organizations/` inside the
one administration shell.

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

This block records the historical controlled-rebuild login, not a promise about
the database's current contents. Inspect the selected database before use and
never delete owner-created records. For a deterministic populated tour, use
`seed_demo_data`; for an isolated empty journey, follow the hands-on tutorial's
separate-database procedure. Never reset `maru` or any other existing database.

## Start Platform administration home

From the repository root in PowerShell:

```powershell
$env:MARU_DATABASE_URL = "postgresql://maru:maru@127.0.0.1:5432/maru_rebuild_empty"
uv run python src/manage.py migrate
uv run python src/manage.py runserver
```

Open <http://127.0.0.1:8000/admin/>, sign in as `admin`, and select
**Platform administration → Organizations**. The direct route is
<http://127.0.0.1:8000/admin/platform/organizations/>.

## Expected behavior

- anonymous `/admin/platform/organizations/` redirects to Sign in;
- the active platform administrator sees **Organizations**;
- the page shows one **Organizations** row with a compact adjacent **+ Add**
  action;
- an empty database shows **No organizations yet** and zero organizations;
- the page explains **Platform access, not participation**;
- **+ Add** opens `/admin/platform/organizations/new/`;
- each organization name opens its
  `/admin/platform/organizations/<slug>/` record;
- an ordinary account, including ordinary staff, receives `403`;
- the same shell exposes only independently authorized Convention work and
  specialist records, without another global menu; and
- health and versioned JSON APIs remain available.

Local desktop and 390-pixel smoke passed without horizontal overflow or
console warnings. The complete empty/error/denied visual matrix, keyboard and
automated accessibility checks, and owner-led tutorial remain release gates.

The platform administrator may receive explicit platform-policy decisions and
may be an attributed actor. It must have no organization membership,
convention capability or role grant, participation, registration, volunteer
application, onboarding request, or workforce assignment. Future restricted
case capabilities must require break-glass and cannot follow merely from this
account kind.

## Failure and recovery

If the organization query fails, `/admin/platform/organizations/` returns a
read-only `503` page. The
HTML does not contain the database exception and no convention data changes.
Check PostgreSQL and `/health/ready`, then retry.

The accepted baseline is commit `db5af58` and Platform administration home's review landmark is
`codex/page-01-platform-home`. Both are ancestors of the consolidation line.
Inspect them with `git show`; do not switch or merge them into active work to
change current routing.

## Next page

Create organization is documented in
[`page-02-create-organization.md`](page-02-create-organization.md). It creates a
complete optional Draft organization profile and returns to this inventory.
