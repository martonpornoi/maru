# Page 4 create convention series

Status: Page 4 backend-verified for platform and scoped Board access; browser
rehearsal pending
Last updated: 2026-08-01

ADRs 0035 and 0036 plus UX-018 and UX-019 add a purpose-built recurring-brand
command and progressive scoped navigation beneath one organization without
using generic Django model saves for the audited workflow. ADR 0039 mounts it
in the unified shell's reserved platform route space.

## Current local environment

```text
Database: maru_rebuild_empty
Username: admin
Email: admin@maru.local
Password: M4rucon-Rehearsal-2031!
Account kind: platform_administrator
```

The password is local test data. Never reuse it in a deployment or real
account. The database contains the owner-created Draft `MaruCon` with slug
`marucon`, zero series/editions/relationships, and its original creation audit
event. Browser QA opened Page 4 but did not submit it.

## Start and open Page 4

From the repository root in PowerShell:

```powershell
$env:MARU_DATABASE_URL = "postgresql://maru:maru@127.0.0.1:5432/maru_rebuild_empty"
uv run python src/manage.py migrate
uv run python src/manage.py runserver
```

Open <http://127.0.0.1:8000/admin/>, select `MaruCon`, then use **+ Add
series**. Its direct route is
<http://127.0.0.1:8000/admin/platform/organizations/marucon/series/new/>.

## Expected behavior

- Page 3 shows only the selected organization's series and contextual add
  action before the complete profile;
- the sidebar keeps the global **Organizations**/**+ Add** row and, while
  MaruCon is selected, adds **Organization record** and **Convention series**
  with the scoped series **+ Add** action beside it;
- the sidebar begins at ordinary viewport padding on desktop and stacks above
  content without horizontal overflow at narrow widths;
- Page 4 displays the parent but accepts no organization or slug field;
- only Convention series name is required;
- description, website, public contact email, and availability are optional;
- availability starts Active and does not publish or create an edition;
- Maru normalizes the name and generates a bounded slug unique within MaruCon;
- success returns to Page 3 with the created row and one-time confirmation;
- creation, value-minimized audit,
  `organizations.convention_series.created.v1`, and outbox delivery are atomic;
  and
- this platform account remains outside every convention relationship.

Do not use Page 4 to create an edition. Page 5 now owns the existing series
record and Page 6 owns the dated event-edition command.

## Failure and recovery

Invalid values stay local to the form and create nothing. A Closed parent
returns `409`; an authorized unknown slug returns `404`; other accounts are
denied before organization lookup. A database, audit, event-publication, or
outbox failure returns a generic non-disclosing `503`; transaction rollback
removes the partial series and every correlated evidence row.

Page 4 adds no migration. If it cannot load, check PostgreSQL and
`/health/ready`, then retry. Do not diagnose against or modify the preserved
`maru` or `marucon_rehearsal` databases.

## Continue the current journey

Continue with the
[organization-to-edition hands-on tutorial](maru-hands-on-tutorial.md), which
covers Pages 5–7 and the explicit working-edition context. The original
per-page owner pause was superseded by ADR 0037's executable milestone cadence.
