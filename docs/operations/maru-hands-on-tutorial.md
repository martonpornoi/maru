# Maru hands-on tutorial: organization authority to edition

Status: M1.1/M2.1 locally migrated and responsive-smoke verified journey;
final suite, accessibility/state-matrix, and owner rehearsal pending
Last updated: 2026-08-01

This tutorial follows the intended first coherent Maru journey: a
non-participating platform administrator creates an organization, hands
authority to an Executive Board of at least two exact people, then creates a
recurring convention series and dated edition and explicitly selects working
context. It uses synthetic/local data. Do not use these credentials, names, or
procedures as production approval.

Backend route, permission, service, Page 8 integration, sensitive-read/denial,
and database-subject tests cover this journey. Local populated/fresh migration,
restore-drill, and desktop/390-pixel shell smoke evidence pass, but the exact
owner-led exercise below has not yet been recorded end to end. Apply every
current migration first. Never create authority with raw model edits.

For broader synthetic exploration, `seed_demo_data` now establishes an active
two-controller Executive Board for each demo organization by calling the same
provision, invite, self-response, and activation services. It does not infer a
real volunteer roster.

## What you will build

```text
Synthetic Awoostria Organizers (organization)
├── Executive Board (representation)
│   ├── Synthetic Alex (controller)
│   └── Synthetic Blake (controller)
└── Awoostria (convention series)
    └── Awoostria 2031 (event edition)
```

The platform administrator is recorded as the provisioning/activation operator
but remains outside that tree: no membership, Executive Board appointment or
role assignment, participation, registration, department position, shift, or
public convention identity is created for that account.

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

The permission-filtered administration home and one collapsible left
navigation appear. Open **Platform administration → Organizations**; its direct
route is <http://127.0.0.1:8000/admin/platform/organizations/>. Page 1 lists
organizations and keeps an adjacent **+ Add** action. The access summary
explains that your authority is platform oversight, not convention
participation.

The same sidebar may expose Convention work and specialist records according
to their independent policies. Their presence does not grant convention access
and does not make every preserved workflow a completed current journey. No
embedded page should render a second global menu or workspace selector.

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
tutorial: once Page 8 provisions the protected representation, deletion must
refuse rather than erase governance history.

## 5. Create and verify two synthetic person accounts

Page 8 never creates or guesses an account. Prepare two distinct ordinary
`person` accounts with verified emails before inviting them. Do not create
superusers or platform administrators, and do not copy a real volunteer roster.

For this isolated local database, the supported public identity flow is the
most faithful setup. In a second PowerShell terminal with the same
`MARU_DATABASE_URL`, submit two synthetic accounts:

```powershell
$tutorialBoardPassword = "M2!Board-Rehearsal-2031"
$tutorialBoardAccounts = @(
    @{
        email = "alex.board@example.invalid"
        display_name = "Synthetic Alex"
        password = $tutorialBoardPassword
    },
    @{
        email = "blake.board@example.invalid"
        display_name = "Synthetic Blake"
        password = $tutorialBoardPassword
    }
)

foreach ($tutorialBoardAccount in $tutorialBoardAccounts) {
    Invoke-RestMethod `
        -Method Post `
        -Uri "http://127.0.0.1:8000/api/v1/public/accounts" `
        -ContentType "application/json" `
        -Body ($tutorialBoardAccount | ConvertTo-Json)
}
```

The local settings use Django's console email backend. Each request prints a
single-use verification URL in the server terminal. Open each URL within 30
minutes, complete verification, then sign out. Repeating the public account
request for an existing unverified synthetic address creates a new challenge;
it still returns an enumeration-resistant generic response.

The shared password is only for this disposable tutorial. Never reuse it or
the `.invalid` identities in a shared or production environment. Do not mark
`email_verified_at` through the specialist record or database shell: the
verification challenge is part of the identity evidence this exercise is meant
to preserve.

## 6. Provision and invite the Executive Board (Page 8)

Sign back in as the platform administrator. On Page 3, select
**Representation & access**. The direct route is the organization's displayed
stable slug followed by `/representation/`, for example:

```text
http://127.0.0.1:8000/admin/platform/organizations/synthetic-awoostria-organizers/representation/
```

Use the real generated slug if a collision added a suffix.

In **Step 1**, enter a bounded synthetic reason such as
`Establish accountable controllers for the local tutorial.` and select
**Create Executive Board**. Confirm that the representation is Provisioning,
the organization remains Draft, and no controller exists automatically.

In **Step 2**, invite these exact verified emails one at a time, each with a
reason:

```text
alex.board@example.invalid
blake.board@example.invalid
```

The lookup is exact and enumeration-resistant. Missing, inactive, unverified,
and platform accounts must not become candidates. For these new accounts, an
invitation creates an Invited appointment and narrowly labelled Invited
organization membership, but no capability or convention participation. An
eligible pre-existing active membership may be reused. Inviting the same
account again must fail without creating a duplicate.

## 7. Let each controller answer their own invitation

Sign out, sign in as `alex.board@example.invalid` using the tutorial Board
password, and open **My governance invitations** at
`/admin/invitations/`. Follow the organization link. The account must see only
its own invitation, not Blake's email or row.
Choose **Accept invitation** and record the decision.

Sign out and repeat as `blake.board@example.invalid`. Each acceptance advances
its invitation version and the representation aggregate version but grants no
authority yet. A second response from an old page must fail as stale or already
answered instead of overwriting the first decision.

For an optional decline rehearsal, use a third synthetic verified account.
Declining ends only that account's Invited Executive Board relationship. Do not
decline either of the two required controllers in the main path.

The scoped in-product invitation list is implemented. Canonical inbox/email
delivery and reminders remain later work.

## 8. Activate organization governance

Sign back in as the platform administrator and return to Page 8. Before
activation, confirm:

- at least two distinct appointments say Accepted;
- no invitation remains Invited;
- both accounts remain active, verified person accounts; and
- the organization still says Draft.

In **Step 3**, enter the organization name exactly, including capitalization,
and a reason such as `Activate the accepted two-person tutorial Board.` Select
**Activate Executive Board** once.

The atomic result is:

- the organization becomes Active;
- the representation becomes Active;
- both appointments and memberships become Active;
- the fixed immutable `Executive Board` role version is created;
- each controller receives an organization-scoped assignment approved by the
  other controller; and
- the platform administrator is present only in actor evidence.

If activation reports a stale version, pending invitation, ineligible account,
suspended membership, or reserved-role conflict, reload and resolve that fact.
Do not edit role, membership, representation, or lifecycle records directly.
A dependency failure must keep the entire organization/authority state as it
was before the attempt.

## 9. Create the convention series (Page 4)

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

## 10. Review and edit the series (Page 5)

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

## 11. Create the dated edition (Page 6)

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

## 12. Review, edit, and select the edition (Page 7)

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

## 13. Inspect the API contract

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
Page 8 deliberately has no declared API in M2.1. Its browser adapters must use
the same module commands a future strict, versioned API would call; do not post
to model-admin endpoints or invent an undocumented representation API.

## 14. What to test as different users

Pages 1–2 remain platform-administrator setup. Backend tests verify Pages 3–7
for platform oversight and active Board-capability paths. Page 8 is
narrower and relationship-aware: an exact invitee may see only their own
open invitation; a representation manager may see the bounded directory for
their organization; an unrelated ordinary account or Django staff account must
learn nothing. Django model permission and selected-edition context are not
convention authority.

After activation, each controller should have one organization membership,
one active representation appointment, and one organization-scoped root role
assignment, but no edition participation, registration, department position,
or workforce assignment. The platform administrator must still have zero rows
as a subject in all of those convention-owned tables.

Pages 1–7 show a truthful principal-specific authority summary. Page 8 adds the
root representation/invitation explanation. Awoostria-shaped departments,
department/resource/field capabilities, and the complete computed access
header remain later M2 work.

## Troubleshooting

| Symptom | Safe response |
| --- | --- |
| `column ... does not exist` | Stop the server, confirm the intended database URL, run `migrate`, and restart the current build; do not fake migrations |
| 403 after sign-in | Pages 1–2 require an active platform administrator. On Pages 3–8, confirm exact current organization/edition authority or an own open invitation; staff status alone is insufficient |
| 404 under a nested URL | Return through the inventory; the organization, series, and edition route chain must match exactly |
| Exact Board email is rejected | Confirm the account already exists, is active, is a person rather than platform administrator, and completed email verification; the UI must not reveal which test failed |
| Activation says invitations are pending | Every invited controller must accept or decline before activation; do not bypass the pending row |
| Activation says the version is stale | Reload Page 8 and re-evaluate the current appointments; never replace the hidden aggregate version manually |
| Reserved Executive Board role conflict | Stop and reconcile the existing authority record; do not overwrite or rename it through model admin |
| 409 on edition creation | Check for Closed organization, Inactive series, or changed-payload reuse of a retry key |
| 409 while saving | Another write advanced the profile/aggregate version or the lifecycle is read-only; reload before deciding |
| 503 | Keep the submitted values, restore the named dependency, and retry; do not create a parallel record through raw model saves |
| Outbox remains pending | Follow the effects worker runbook; do not edit domain-event or receipt rows |

## Current stopping point

You have followed the implemented organization → representation → series →
edition journey. Local migration, restore, frontend, sensitive-read/denial, and
responsive smoke gates pass, but this tutorial is not release acceptance
evidence until the final consolidated full-suite/coverage rerun, representative
deployment/PITR recovery, keyboard/automated accessibility, complete visual
states, and owner rehearsal pass. Ongoing Board term
management, department hierarchy editing, typed applications, venues,
timetable planning, shifts, storage/logistics, governed documents, and on-site
communications remain ordered milestones in
`docs/project/PRODUCTION_CONSOLIDATION.md`. Reachable preserved screens or APIs
do not change their honest capability-ledger state.
