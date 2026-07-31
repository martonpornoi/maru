# Page 3 organization record

Status: Executable local Page 3
Last updated: 2026-07-31

ADR 0034 and UX-017 add purpose-built editing and protected empty-Draft
deletion without restoring generic model administration.

## Current local environment

```text
Database: maru_rebuild_empty
Username: admin
Email: admin@maru.local
Password: M4rucon-Rehearsal-2031!
Account kind: platform_administrator
```

The password is local test data. Never reuse it in a deployment or real
account. The controlled database contains the owner-created Draft `MaruCon`
with slug `marucon`, blank optional profile values, zero series/editions, and
its original creation audit event. Browser QA did not submit either Page 3
form. The `maru` and `marucon_rehearsal` databases remain out of scope.

## Start Page 3

From the repository root in PowerShell:

```powershell
$env:MARU_DATABASE_URL = "postgresql://maru:maru@127.0.0.1:5432/maru_rebuild_empty"
uv run python src/manage.py migrate
uv run python src/manage.py runserver
```

Open <http://127.0.0.1:8000/admin/>, sign in as `admin`, and select an
organization name. MaruCon's direct route is
<http://127.0.0.1:8000/admin/organizations/marucon/>.

## Expected behavior

- one sidebar row shows **Organizations** with adjacent **+ Add**;
- the record prepopulates the same complete profile used by Page 2;
- only organization name is required;
- **Save changes** updates changed fields and returns to the stable slug URL;
- posted slug and lifecycle values are ignored;
- an unchanged save produces no write or audit event;
- successful changed updates are atomic with an audit event containing field
  names but no entered profile values;
- the danger zone requires the current name exactly and explicit
  acknowledgement;
- deletion succeeds only for a Draft with no protected related records and is
  atomic with its audit event; and
- this platform account remains outside all convention relationships.

Never use the delete action as closure. A series, edition, member, authority,
participant, registration, workforce record, communication, restriction, or
other protected relationship refuses deletion. Lifecycle closure and data exit
remain a future reviewed workflow.

## Failure and recovery

Invalid fields and confirmation errors remain on the form and change nothing.
A database or audit failure returns a generic `503`; transaction rollback keeps
the prior organization. An authorized unknown slug returns `404`; authorization
runs before lookup for other accounts.

No migration is introduced by Page 3. If the page cannot load, check PostgreSQL
and `/health/ready`, then retry. Do not modify the preserved databases while
diagnosing the controlled rebuild.

## Next page gate

The owner should inspect and accept Page 3 before Page 4 defines the creation
of a Convention Series.
