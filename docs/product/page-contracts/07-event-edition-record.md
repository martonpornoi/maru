# Event edition record contract

- Status: Implemented and desktop/390-pixel smoke verified for platform
  oversight and scoped Executive Board visibility; accessibility, complete
  visual-state, and owner residuals remain
- Route: `/admin/platform/organizations/<organization-slug>/series/<series-slug>/editions/<edition-slug>/`
- API: `GET` and `PUT /api/v1/organizations/<organization-id>/editions/<edition-id>`
- Requirements: IDN-004, IDN-012, UX-009, UX-012, UX-013, UX-019, UX-020,
  UX-023, UX-024, INT-001, NFR-009
- Decisions: ADRs 0037–0041

## Purpose and primary user

Provide the stable record and landing page for one dated edition. It
establishes the visible scope beneath which people, registration,
applications, programme, timetable, venue operations, logistics, documents,
communications, reports, and settings will appear only after their complete
workflows are mounted.

The page permits an active Maru platform administrator.
ADR 0040's Board root carries organization-scoped `events.view_basic`, while a
profile change still requires exact `events.change_profile` authority at this
edition; the current backend matrix verifies that distinction. Route or selected
working context never grants convention access or participation.

## Placement, record, and navigation

The route must resolve one exact organization → series → edition chain. The
shared sidebar retains each selected scope and adds the edition name with
**Overview**, current exactly once. No placeholder destination is rendered for
an unmounted domain.

The record shows name, lifecycle, immutable slug and parents, official dates,
time zone, languages, currencies, aggregate version, timestamps, current
working-context state, and bounded recent activity. Draft and Preparing
records beneath a non-Closed organization expose the complete profile form;
Ready, Live, Closing, Archived, and Cancelled records are read-only here.
Lifecycle transitions remain a separate reasoned command.

## Explicit input contract

All persisted profile fields are non-null. The update is a complete
replacement, so API clients send every profile property even when only one
changes.

| Field | Type and format | Bounds; null/blank | Normalization | Classification and writer | Lifecycle and retention |
| --- | --- | --- | --- | --- | --- |
| `name` | Unicode text | 1–160 characters; null/blank forbidden | Trim ends and collapse internal whitespace | C1 edition setup; browser/API `events.change_profile` holder, including explicit platform policy | Editable only in Draft/Preparing beneath non-Closed organization; retained with edition |
| `starts_on` | ISO calendar date (`YYYY-MM-DD`) | Required; null/blank forbidden | Parse as date without time-zone conversion | C1 edition setup; same writer | On/before end; same edit boundary; retained with edition history |
| `ends_on` | ISO calendar date (`YYYY-MM-DD`) | Required; null/blank forbidden; at most 31 days after start | Parse as date without time-zone conversion | C1 edition setup; same writer | On/after start; same edit boundary; retained with edition history |
| `time_zone` | IANA time-zone identifier | Required; model max 63 characters; null/blank forbidden | Trim and validate installed IANA identifier | C1 locale setup; same writer | Same edit boundary; retained with edition and used for activity display |
| `language_codes` | Ordered list of language codes | 1–16 unique valid codes; each ≤35 characters; null/blank forbidden | Trim and lowercase | C1 locale setup; same writer | Same edit boundary; retained with edition |
| `currency_codes` | Ordered list of ISO 4217 codes | 1–8 unique valid codes; each 3 letters; null/blank forbidden | Trim and uppercase; browser accepts bounded comma/whitespace text | C1 finance-locale setup, not payment data; same writer | Same edit boundary; retained with edition |
| `expected_aggregate_version` | Positive integer concurrency token | Integer ≥1; null/blank forbidden | Strict integer parsing | C1 control metadata; browser hidden value or API caller | Compared under lock; stale value returns 409; not stored as profile content |

Organization, series, edition identifier, slug, lifecycle, lifecycle version,
actor, and timestamps are server-owned. HTML accepts only the six profile
fields, `expected_aggregate_version`, and CSRF. API accepts exactly the seven
JSON properties above. Unknown or forged fields are rejected instead of
ignored.

Field errors use the same actionable name/date/time-zone/language/currency
vocabulary as Create event edition. Unknown input uses `unknown_input_field`; concurrency
uses `stale_edition_version` with reload guidance; read-only state uses
`edition_profile_read_only`; a Closed parent uses `edition_parent_closed`.
Edition list/autocomplete GETs reject undeclared query parameters, and the
exact-detail GET accepts none. Path-like or unknown time-zone input is a bounded
`invalid_time_zone` response rather than a server error.

## Aggregate version, lifecycle, and mutation evidence

`aggregate_version` is the single optimistic version for every EventEdition
profile or lifecycle change. A profile update and a lifecycle transition are
separate commands, and each successful changed command advances it by exactly one.
`lifecycle_version` remains the transition-history sequence and is not the
profile concurrency token. PostgreSQL rejects combined profile/lifecycle
changes, ownership/slug mutation, version skips, and profile edits outside
Draft/Preparing.

The update service authorizes, locks organization, series, and edition, checks
the exact scope chain and expected aggregate version, normalizes and
model-validates the complete profile, then writes only changed fields. A real
change commits a minimized audit event,
`events.edition.details_updated.v1`, and its outbox delivery atomically. A
no-op advances no version and creates no evidence. Entered profile values do
not appear in audit or activity payloads.

## Working edition context

**Use as working edition** is an explicit POST to the scoped `/select/` route.
**Clear working edition** is a separate POST to `/clear/`. Both accept only the
CSRF transport field and reject every business or forged field. The session stores
only the edition identifier after the same exact route chain and current
`events.view_basic` authority are checked. Selection changes
navigation/display context only; it
does not write the edition, create audit/domain-event/outbox evidence, grant a
capability, replace an assignment, or create/change membership, participation,
or registration. This remains true when access comes from the canonical
organization-scoped Executive Board assignment. Edition creation does not
select automatically.

## Effective access and activity

The access header states that active platform administrators may view or,
where lifecycle allows, change the record under platform oversight. It also
distinguishes organization-scoped Board view from exact-edition
`events.change_profile`; the root Board assignment alone does not imply profile
edit. This is still not the final department/resource/field effective-access
explanation or **Manage access** workflow.

Recent activity projects only allowlisted domain facts for the exact edition:
creation, profile update, and lifecycle transition. It resolves a safe actor
display label and field names without entered values, emails, or raw UUIDs.
The security audit remains a separate restricted control-evidence boundary.

## Page and API states

- **Editable:** Draft or Preparing beneath a non-Closed organization.
- **Read-only:** Ready, Live, Closing, Archived, Cancelled, or Closed parent.
- **No change:** informational redirect with no version/evidence write.
- **Validation:** actionable field errors, safe values retained, no partial
  state.
- **Stale or lifecycle conflict:** 409 with reload/explanation.
- **Denied:** 403 before record disclosure.
- **Not found:** authorized caller receives 404 for a broken scope chain.
- **Dependency failure:** generic 503/retry behavior and atomic rollback.

## Verification required for completion

- exact-scope, authorization, lifecycle, validation, no-op, stale, unknown
  field, and rollback tests;
- database trigger tests for stable scope/slug, aggregate monotonicity,
  separate profile/lifecycle writes, and editable lifecycle;
- API field-ceiling/OpenAPI/error-shape tests;
- value-minimized audit/event/activity and platform non-participation tests;
- explicit select/clear POST, strict no-business-field input, session
  corruption, and no-authority/domain/evidence-side-effect tests for platform,
  direct-grant, and canonical Executive Board authority; and
- keyboard, focus, desktop, 390-pixel, read-only, error, and current-navigation
  evidence. Desktop/390-pixel current-navigation smoke passes; keyboard,
  automated accessibility, the full state matrix, and owner rehearsal remain.

## Explicit non-goals

- Lifecycle controls, representation, access assignment, or participation.
- Placeholder links for registration, programme, venue, timetable, logistics,
  documents, communications, reports, or settings.
- Editing slug, ownership, archived facts, or historical evidence.
