# Page 3 organization record

Status: Page 3 backend and responsive-smoke verified for platform and scoped
Board access; accessibility/state-matrix/owner rehearsal pending
Last updated: 2026-08-01

ADR 0034 and UX-017 add purpose-built editing and protected empty-Draft
deletion without using generic model saves for the audited workflow. ADR 0039
moves it into the unified shell's reserved platform route space.

## Current local environment

```text
Database: maru_rebuild_empty
Username: admin
Email: admin@maru.local
Password: M4rucon-Rehearsal-2031!
Account kind: platform_administrator
```

The password is local test data. Never reuse it in a deployment or real
account. These credentials and the `MaruCon` slug record the historical
controlled-rebuild exercise, not the selected database's guaranteed current
state. Inspect before use and do not modify or delete owner-created records.
The current responsive smoke loaded Page 3 without submitting either mutation
form. Use the tutorial's separate database for mutation rehearsal.

## Start Page 3

From the repository root in PowerShell:

```powershell
$env:MARU_DATABASE_URL = "postgresql://maru:maru@127.0.0.1:5432/maru_rebuild_empty"
uv run python src/manage.py migrate
uv run python src/manage.py runserver
```

Open <http://127.0.0.1:8000/admin/>, sign in as `admin`, and select an
organization name. MaruCon's direct route is
<http://127.0.0.1:8000/admin/platform/organizations/marucon/>.

## Expected behavior

- one sidebar row shows **Organizations** with adjacent **+ Add**;
- the record prepopulates the same complete profile used by Page 2;
- only organization name is required;
- **Save changes** updates changed fields and returns to the stable slug URL;
- posted slug, lifecycle, scope, actor, and other undeclared values are rejected
  before mutation;
- an unchanged save produces no write or audit event;
- successful changed updates are atomic with an audit event containing field
  names but no entered profile values;
- the danger zone requires the current name exactly and explicit
  acknowledgement;
- deletion succeeds only for a Draft with no protected related records and is
  atomic with its audit event; and
- this platform account remains outside all convention relationships.

The local desktop and 390-pixel journey passed without horizontal overflow or
console warnings. Complete keyboard/automated accessibility, mutation failure
states, and owner-led form rehearsal remain open.

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

## Next page

Page 3 is accepted. Its organization-scoped Convention series section and Page
4 creation action are documented in
[`page-04-create-convention-series.md`](page-04-create-convention-series.md).
