# Page 5 contract: Convention-series record

- Status: Implemented and locally verified; owner rehearsal and recorded
  accessibility/visual-state residuals remain
- Route: `/admin/organizations/<organization-slug>/series/<series-slug>/`
- API: `GET` and `PUT /api/v1/organizations/<organization-id>/series/<series-id>`
- Requirements: UX-013, UX-019, UX-020, UX-021, INT-001, NFR-009
- Decisions: ADRs 0037–0038

## Purpose and primary user

Let an active Maru platform administrator revisit and maintain one recurring
convention brand, inspect its dated editions, and continue to edition creation
without changing tenant ownership or stable identity.

The page is a series record, not a convention workspace. Platform attribution
does not create organization membership, representation, edition
participation, registration, a department position, or a convention role.

## Placement and navigation

The organization record links every listed series name to Page 5. The shared
sidebar retains **Organizations** and the selected organization section, then
adds a section named for the selected series with:

- **Series record**, current on Page 5; and
- **Convention editions** with an adjacent **+ Add** action when the
  organization is not Closed and the series is Active.

The editions destination anchors the edition inventory on Page 5. It is not a
global cross-tenant collection. A series or edition route must resolve beneath
the exact organization in its URL or return 404.

## Record, editions, and activity

The record shows the series name, immutable slug, parent organization,
availability, profile version, timestamps, and complete editable brand
profile. The edition inventory shows only editions belonging to the selected
series, including name, lifecycle, dates, and a link to Page 7. Empty and
populated states use the same section.

Recent activity is a bounded, value-minimized projection of allowlisted domain
facts for this exact aggregate. It shows a safe actor display label, plain
operation wording, changed field labels, and organization-local time. It does
not query the security audit as a user timeline, expose entered values, or
display raw actor identifiers. M2 still owns a cross-domain, access-aware
activity workspace.

## Explicit input contract

All fields are non-null at storage. “Blank” below means the empty string, not
SQL `NULL`. Retention is with the organization-owned recurring-brand record;
closure and data exit must preserve required audit and historical-edition
links.

| Field | Type and format | Bounds; null/blank | Normalization | Classification and writer | Lifecycle and retention |
| --- | --- | --- | --- | --- | --- |
| `name` | Unicode text | 1–160 characters; null/blank forbidden | Trim ends and collapse internal whitespace | C1 setup data; current browser/API: active platform administrator | Editable unless parent organization is Closed; retained with series |
| `description` | Unicode long text | 0–2,000 characters; null forbidden, blank allowed | Preserve meaningful text; form trims transport whitespace | C1 until an explicit publication workflow; same writer | Same edit boundary; retained with series |
| `website_url` | HTTP(S) URL | At most 200 stored characters; null forbidden, blank allowed | Trim; assume `https://` when the scheme is omitted; validate final URL | C1 until publication; same writer | Same edit boundary; retained with series |
| `contact_email` | Email address | At most 254 characters; null forbidden, blank allowed | Trim and validate address syntax; no account lookup implied | C1 public-contact setup; same writer | Same edit boundary; retained with series/contact record |
| `is_active` / browser `availability` | Boolean / Active or Inactive choice | Required in API replacement; browser defaults Active | Map exactly between boolean and named choice | C1 operational setup; same writer | Editable unless parent Closed; Inactive blocks new editions but deletes nothing |
| `expected_profile_version` | Positive integer concurrency token | Integer ≥1; null/blank forbidden on update | No coercion beyond strict integer parsing | C1 control metadata; browser hidden field or API caller | Compared under row lock; stale value returns 409; never stored as a profile field |

Organization identifier, series identifier, slug, timestamps, actor, and
edition relationships are trusted route/server state and are never accepted as
profile input. The HTML form accepts only the five profile fields,
`expected_profile_version`, and CSRF. The `PUT` body accepts exactly the six
JSON properties in the table. Any undeclared field is rejected; Maru does not
silently ignore forged ownership or lifecycle input.

Validation identifies the affected field: missing/blank or overlong name,
overlong description, invalid website/email, non-boolean availability, and
non-positive version each receive actionable field errors. Unknown fields use
`unknown_input_field`; a version mismatch uses `stale_series_profile` with
reload guidance; a Closed parent uses `series_parent_closed`.

## Authorization and effective-access summary

The controlled HTML and series API adapters require an authenticated, active
platform administrator and authorize before scoped lookup. The service repeats
the platform boundary and locks the exact organization-owned series. Future
organizer access needs an explicit capability contract; navigation, Django
staff status, or Django Groups must never provide it implicitly.

The current header truthfully says that active platform administrators may
view or change the record under platform oversight and that this is not
convention participation. This is a provisional/static UX-020 implementation:
it does not yet compute organization representation, departments, named
people, or a **Manage access** action. Those claims wait for M2 authorization
scope v2.

## Mutation, concurrency, and evidence

The update service locks the organization and series, verifies exact ownership
and expected profile version, normalizes and model-validates the complete
record, and writes only actual changes. A changed update advances
`profile_version` by exactly one and commits a value-minimized audit event plus
`organizations.convention_series.updated.v1` and its outbox delivery in the
same transaction. An unchanged save advances nothing and creates no evidence.

Organization, slug, timestamps, editions, and relationships cannot be changed
by this command. Transfer, delete, publication, and lifecycle/closure workflows
are not mounted.

## Page and API states

- **Normal:** zero or several editions, populated profile, current navigation,
  and bounded recent activity.
- **Validation:** field-local/actionable errors retain safe input; no write.
- **No change:** redirect with an informational message and no version/audit/
  event increment.
- **Stale:** 409 with reload guidance and no partial write.
- **Inactive or parent Closed:** the edition-add action is disabled/omitted;
  Closed also makes the profile read-only.
- **Denied:** 403 before scoped record disclosure.
- **Not found:** an authorized caller receives 404 for a broken route chain.
- **Dependency failure:** generic 503/retry behavior; canonical profile, audit,
  event, and outbox state roll back together.

API list queries reject undeclared parameters and use bounded page/page-size
values. The exact-detail GET accepts no query parameters. API errors use the
shared `application/problem+json` boundary with stable codes and optional
request/error detail members.

## Verification required for completion

- service and HTTP success, validation, stale, no-op, authorization, and
  dependency-rollback tests;
- cross-organization slug, identifier, and forged-field non-disclosure tests;
- database trigger tests for stable ownership/slug and exact version movement;
- value-minimized audit/event/activity assertions and no relationship side
  effects;
- OpenAPI/projection checks; and
- keyboard, focus, desktop, 390-pixel, empty, blocked, error, and current-menu
  browser evidence.

## Explicit non-goals

- Series transfer, destructive deletion, publication, or closure.
- Edition lifecycle changes.
- Organization representation, access assignment, participation,
  registration, programme, venue, or workforce creation.
