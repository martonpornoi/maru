# Page 2 create organization

Status: Page 2 backend-verified in the unified shell; browser rehearsal pending
Last updated: 2026-08-01

ADRs 0032 and 0033 define the first platform mutation in the controlled
rebuild. Page 2 creates one Draft organization from one required name, accepts
the complete optional organization profile, and deliberately creates no
convention, governance, membership, or participation records. ADR 0034 places
its **+ Add** action beside **Organizations** on one navigation row.
ADR 0039 moves that row and page into the reserved `/admin/platform/` route
space inside the shared shell.

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
<http://127.0.0.1:8000/admin/platform/organizations/new/>.

## Expected behavior

- one navigation row shows **Organizations** and adjacent **+ Add** on Pages
  1–3;
- only **Organization name** is required;
- optional sections accept public identity, legal address and imprint,
  representative and registry references, website/email/telephone, primary
  country, default languages, and default time zone;
- Maru normalizes whitespace and generates a stable, collision-safe slug;
- the resulting organization has Draft lifecycle, English and UTC defaults,
  and blank omitted properties;
- success returns to `/admin/platform/organizations/`, shows the Draft row,
  and shows a one-time confirmation; the row name opens its Page 3 record;
- the platform administrator is recorded as audit actor only;
- no membership, Executive Board, authority, convention series, event edition,
  participation, registration, or workforce record is created; and
- anonymous users are sent to Sign in while ordinary and Django-staff-only
  accounts receive `403`.

This temporary Draft state is intentional. Lifecycle and slug are not form
fields and cannot be overridden by crafted POST data. Page 3 now edits an
existing organization such as MaruCon. ADR 0040/Page 8 now defines explicit
Executive Board provisioning, exact invitation, self-acceptance, and
two-controller activation; its schema and backend verification pass while live
migration/browser evidence remains. Existing non-Draft organizations require explicit reconciliation,
never an inferred person backfill.

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
Active only through their own explicit compatible lifecycle; `seed_demo_data`
now exercises the real two-controller representation handoff.

## Next page

Page 3 is documented in
[`page-03-organization-record.md`](page-03-organization-record.md). It maintains
the complete profile and can delete only a confirmed empty Draft.
