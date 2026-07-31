# Page 4 create convention series

Status: Executable local Page 4
Last updated: 2026-07-31

ADR 0035 and UX-018 add a purpose-built recurring-brand command beneath one
organization without restoring generic Django model administration.

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
<http://127.0.0.1:8000/admin/organizations/marucon/series/new/>.

## Expected behavior

- Page 3 shows only the selected organization's series and contextual add
  action before the complete profile;
- the sidebar remains one **Organizations**/**+ Add** organization row;
- Page 4 displays the parent but accepts no organization or slug field;
- only Convention series name is required;
- description, website, public contact email, and availability are optional;
- availability starts Active and does not publish or create an edition;
- Maru normalizes the name and generates a bounded slug unique within MaruCon;
- success returns to Page 3 with the created row and one-time confirmation;
- creation and its value-minimized audit event are atomic; and
- this platform account remains outside every convention relationship.

Do not use Page 4 to create an edition. Page 5 will own the existing series
record and Page 6 will define the dated event edition after their contracts are
accepted.

## Failure and recovery

Invalid values stay local to the form and create nothing. A Closed parent
returns `409`; an authorized unknown slug returns `404`; other accounts are
denied before organization lookup. A database or audit failure returns a
generic `503` and transaction rollback removes the partial series.

Page 4 adds no migration. If it cannot load, check PostgreSQL and
`/health/ready`, then retry. Do not diagnose against or modify the preserved
`maru` or `marucon_rehearsal` databases.

## Next page gate

The owner should inspect and accept Page 4 before Page 5 defines the
Convention-series record.
