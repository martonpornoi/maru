# Maru hands-on tutorial: organization to edition

Status: M1 edition-workspace tutorial; implementation locally verified, owner
rehearsal pending
Last updated: 2026-08-01

This tutorial follows the first coherent Maru journey: a non-participating
platform administrator creates an organization, recurring convention series,
and dated edition, then revisits each record and explicitly selects working
context. It uses synthetic/local data. Do not use these credentials, names, or
procedures as production approval.

## What you will build

```text
Synthetic Awoostria Organizers (organization)
└── Awoostria (convention series)
    └── Awoostria 2031 (event edition)
```

The platform administrator is recorded as the operator but remains outside
that tree: no membership, Executive Board appointment, participation,
registration, department position, shift, or public convention identity is
created.

## 1. Start an isolated local environment

From the repository root in PowerShell:

The commands deliberately stop if the tutorial database name already exists;
they never migrate, empty, or drop an unknown database. If that happens, first
verify whether it is your disposable prepared baseline. Otherwise choose a new
name in the existence query, `createdb` command, and database URL.

```powershell
docker compose up -d --wait postgres
$tutorialDatabaseExists = (
    docker compose exec -T postgres psql -U maru -d maru -tAc `
        "SELECT 1 FROM pg_database WHERE datname = 'maru_rebuild_empty'" |
        Out-String
).Trim()
if ($tutorialDatabaseExists -eq "1") {
    throw "The tutorial database already exists; verify it or choose a new name."
}
docker compose exec -T postgres createdb -U maru maru_rebuild_empty
$env:MARU_DATABASE_URL = "postgresql://maru:maru@127.0.0.1:5432/maru_rebuild_empty"
uv run python src/manage.py migrate
uv run python src/manage.py check
uv run python src/manage.py runserver
```

Compose creates only its configured `maru` database. The guarded commands above
create one new separate tutorial database and refuse to touch an existing one.

Keep `MARU_DATABASE_URL` set in every server/management-command terminal. Do
not point this exercise at an important database. The M1 migration is
write-incompatible with old application nodes; follow the
[edition workspace migration runbook](edition-workspace-migration-and-recovery.md)
for any shared or production-shaped environment.

For a fresh empty database, stop the server briefly or use another terminal to
create exactly one bootstrap administrator:

```powershell
uv run python src/manage.py createsuperuser
```

A superuser is explicitly classified as `platform_administrator`. It may use
the management spine without becoming part of a convention.

The repository-prepared local baseline, when present, uses:

```text
Login handle: admin
Email: admin@maru.local
Password: M4rucon-Rehearsal-2031!
```

These credentials are local test data. Change them for any shared environment
and never reuse the password for a real account.

## 2. Sign in and understand the shell

Open <http://127.0.0.1:8000/admin/>. Sign in with the email or login handle.

Page 1 lists organizations. The left navigation has one global
**Organizations** destination with an adjacent **+ Add** action. It does not
show unavailable registration, timetable, logistics, document, or workforce
links. The access summary explains that your authority is platform oversight,
not convention participation.

Expected empty state: no invented setup record and no convention context. If
the prepared MaruCon Draft already exists, leave it intact and use a clearly
synthetic organization for this tutorial.

## 3. Create the organization (Page 2)

Select **+ Add** beside Organizations. Only **Organization name** is required.
For a useful rehearsal, enter:

| Section | Suggested synthetic value |
| --- | --- |
| Organization name | `Synthetic Awoostria Organizers` |
| Description | `Synthetic organizer used to rehearse Maru.` |
| Website | `example.invalid` |
| Contact email | `office@example.invalid` |
| Primary operating country | Austria |
| Default languages | German and English |
| Default time zone | `Europe/Vienna` |

Leave legal/imprint fields blank unless you specifically want to inspect their
validation. Never paste real addresses, tax identifiers, personal names, or
private documents into test data.

Select **Create organization**. Maru:

- normalizes the visible name;
- creates a bounded collision-safe slug;
- starts the organization in Draft;
- records a value-minimized audit event; and
- creates no board, membership, series, edition, or participant.

All browser forms use a closed input contract. Extra crafted fields such as
`slug` or `lifecycle` are rejected rather than silently accepted or ignored.

## 4. Review the organization (Page 3)

Select the organization name in the inventory. Page 3 shows its stable slug,
Draft state, convention-series section, complete profile, and protected danger
zone.

Try a small profile correction, such as changing the description, and select
**Save organization**. A changed save records only changed field names in
audit; an unchanged save reports that nothing changed and writes nothing.

Deletion is deliberately narrow. It requires the current name exactly and an
acknowledgement, and succeeds only for an empty Draft. Do not use it in this
tutorial: once the next step creates a protected series, deletion must refuse
rather than erase convention history.

## 5. Create the convention series (Page 4)

In the selected-organization navigation, select **+ Add** beside
**Convention series**. Enter:

| Field | Suggested value |
| --- | --- |
| Convention series name | `Awoostria` |
| Public description | `Synthetic recurring furry-convention brand.` |
| Website | `awoostria.example.invalid` |
| Public contact email | `convention@example.invalid` |
| Availability | Active |

Select **Create convention series**. Active means that the series may own a
future edition; it does not publish a website or create one. The organization
is trusted from the route, not an editable form field.

## 6. Review and edit the series (Page 5)

Select the series name on Page 3. Page 5 shows the stable series record,
profile version, recent activity, and an initially empty **Convention
editions** section.

Edit the public description and save. A real change increments the series
profile version exactly once and produces correlated audit/domain-event/outbox
evidence. Reloading an old form and trying to save after another change returns
a stale-write conflict instead of overwriting it. Saving identical values
advances nothing.

The activity block uses safe domain facts, not the security audit. It shows the
operation and changed field labels without showing the entered description,
email, UUID, or other hidden values.

## 7. Create the dated edition (Page 6)

Select **+ Add** beside **Convention editions**. Suggested values:

| Field | Suggested value |
| --- | --- |
| Edition name | `Awoostria 2031` |
| Starts on | `2031-06-05` |
| Ends on | `2031-06-08` |
| Time zone | inherited `Europe/Vienna` |
| Official languages | inherited German and English |
| Currencies | `EUR` |

The end may not precede the start or be more than 31 days later. Languages and
currencies are unique, bounded, code-backed values. Maru preserves a hidden
browser retry UUID through validation, so an accidental repeat reuses the
first edition rather than creating a duplicate.

Select **Create event edition**. The result is one Draft edition with aggregate
version 1. Creation redirects to Page 7 but deliberately does not select the
edition as working context. It also creates no registration configuration,
application type, venue, programme item, department, or shift.

## 8. Review, edit, and select the edition (Page 7)

Page 7 is the stable edition landing record. Confirm:

- the organization → series → edition chain is visible;
- lifecycle is Draft;
- dates, time zone, languages, currencies, slug, and aggregate version are
  visible;
- recent activity says that the edition was created without exposing input
  values; and
- no unimplemented domain appears as a placeholder menu item.

Change one editable value, such as the end date, and save. Draft and Preparing
profiles are editable; Ready, Live, Closing, Archived, and Cancelled are
read-only on this page. A changed profile save advances the single edition
aggregate version. Lifecycle transitions use a separate command but advance
the same aggregate version, which prevents one type of change from overwriting
the other.

Select **Use as working edition**. The POST stores display/query context in
your session and returns to the record. It does not grant access or create a
relationship. Select **Clear working edition** to remove that context.

## 9. Inspect the API contract

The supported schema is available at
<http://127.0.0.1:8000/api/v1/schema>. The M1 endpoints are:

```text
GET  /api/v1/organizations/{organization_id}/series
GET  /api/v1/organizations/{organization_id}/series/{series_id}
PUT  /api/v1/organizations/{organization_id}/series/{series_id}
GET  /api/v1/organizations/{organization_id}/editions
POST /api/v1/organizations/{organization_id}/editions
GET  /api/v1/organizations/{organization_id}/editions/{edition_id}
PUT  /api/v1/organizations/{organization_id}/editions/{edition_id}
```

Edition creation requires a UUID `Idempotency-Key` HTTP header; the JSON body
contains `series_id` and the six edition fields, not `idempotency_key`. Profile
updates are complete replacements and include the expected profile/aggregate
version. Unknown JSON properties are rejected. Scoped IDs are transport
identities; seasonal frontends should display human names and use only the
documented projection.

The repository does not yet ship a production third-party credential issuance
workflow. Use the OpenAPI schema and authenticated local test clients for
development; do not invent durable tokens or share a browser session cookie.

## 10. What to test as different users

The current HTML spine is intentionally platform-administrator-only. An active
ordinary account or Django staff account must receive 403; being able to sign
in or see a menu is not convention authority. The platform administrator must
still have zero rows in membership, participation, registration, authority,
and workforce subject tables.

M2 will add organization representation, Awoostria-shaped departments,
department/resource capabilities, and a computed access header. Until then,
the header is a truthful static statement about platform oversight only. It
does not mean that Executive Board or any department can use these pages yet.

## Troubleshooting

| Symptom | Safe response |
| --- | --- |
| `column ... does not exist` | Stop the server, confirm the intended database URL, run `migrate`, and restart the current build; do not fake migrations |
| 403 after sign-in | Confirm the account is active and explicitly classified as platform administrator; staff status alone is insufficient |
| 404 under a nested URL | Return through the inventory; the organization, series, and edition route chain must match exactly |
| 409 on edition creation | Check for Closed organization, Inactive series, or changed-payload reuse of a retry key |
| 409 while saving | Another write advanced the profile/aggregate version or the lifecycle is read-only; reload before deciding |
| 503 | Keep the submitted values, restore the named dependency, and retry; do not create a parallel record through raw model saves |
| Outbox remains pending | Follow the effects worker runbook; do not edit domain-event or receipt rows |

## Current stopping point

You have completed the M1 edition workspace spine. The current shell does
**not** yet
provide Executive Board representation, department hierarchy editing,
registration pages, application forms, venues, timetable planning, shifts,
storage/logistics, documents, or on-site communications. These remain ordered
milestones in `docs/project/PRODUCTION_CONSOLIDATION.md`, not hidden features.
