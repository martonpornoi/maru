# Page 2 create organization

Status: Executable local Page 2
Last updated: 2026-07-31

ADRs 0032 and 0033 define the first platform mutation in the controlled
rebuild. Page 2 creates one Draft organization from one required name, accepts
the complete optional organization profile, and deliberately creates no
convention, governance, membership, or participation records.

## Current local environment

```text
Database: maru_rebuild_empty
Username: admin
Email: admin@maru.local
Password: M4rucon-Rehearsal-2031!
Account kind: platform_administrator
```

The password is local test data. Never reuse it in a deployment or real
account. The controlled database currently contains the owner-created Draft
organization `MaruCon`. The `maru` and `marucon_rehearsal` databases are not
the controlled rebuild database and must not be reset or migrated for this
page.

## Start Page 2

From the repository root in PowerShell:

```powershell
$env:MARU_DATABASE_URL = "postgresql://maru:maru@127.0.0.1:5432/maru_rebuild_empty"
uv run python src/manage.py migrate
uv run python src/manage.py runserver
```

Open <http://127.0.0.1:8000/admin/>, sign in as `admin`, and select
**+ Add**. The direct route is
<http://127.0.0.1:8000/admin/organizations/new/>.

## Expected behavior

- the side navigation shows **Organizations** and **+ Add** on both pages;
- only **Organization name** is required;
- optional sections accept public identity, legal address and imprint,
  representative and registry references, website/email/telephone, primary
  country, default languages, and default time zone;
- Maru normalizes whitespace and generates a stable, collision-safe slug;
- the resulting organization has Draft lifecycle, English and UTC defaults,
  and blank omitted properties;
- success returns to `/admin/`, shows the Draft row, and shows a one-time
  confirmation;
- the platform administrator is recorded as audit actor only;
- no membership, Executive Board, authority, convention series, event edition,
  participation, registration, or workforce record is created; and
- anonymous users are sent to Sign in while ordinary and Django-staff-only
  accounts receive `403`.

This temporary Draft state is intentional. Lifecycle and slug are not form
fields and cannot be overridden by crafted POST data. Page 3 will edit an
existing organization such as MaruCon. A later governance workflow must
provision or backfill the Executive Board before activation and enforce the
editing rule in IDN-012.

## Failure and recovery

Invalid input remains on Page 2 with a field-local message and creates no
record. A database or audit write failure returns a generic `503` message; the
organization and successful audit event share one transaction, so neither can
survive alone. Check PostgreSQL and `/health/ready`, then retry.

Migration `organizations.0003_organization_draft_lifecycle` changes the default
for newly constructed organizations to Draft. Migration
`organizations.0004_organization_complete_profile` adds blank optional profile
columns. Neither migration rewrites existing organization values; the existing
MaruCon Draft remains intact. Demo and rehearsal builders continue to request
Active explicitly.

## Next page gate

The owner should inspect and accept Page 2 before Page 3, the Organization
record, receives a contract or implementation.
